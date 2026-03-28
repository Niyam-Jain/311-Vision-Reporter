"""
FastAPI backend for NYC 311 Vision Reporter — Live API streaming version.
Single WebSocket endpoint replaces the three REST endpoints.
Static file serving and health check are unchanged.
"""

import asyncio
import json
import traceback
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

from agent import runner, session_service, run_config, APP_NAME
from tools.analyze import analyze_image

load_dotenv()

# Patch the websockets open_timeout used by google-genai Live API.
# The default 10 s is too short when Vertex AI needs to refresh credentials.
try:
    import google.genai.live as _genai_live
    _orig_ws_connect = _genai_live.ws_connect

    def _patched_ws_connect(uri, **kwargs):
        print(f"[patch] ws_connect uri={uri}", flush=True)
        kwargs.setdefault("open_timeout", 60)
        kwargs.setdefault("ping_interval", 30)
        kwargs.setdefault("ping_timeout", 60)
        return _orig_ws_connect(uri, **kwargs)

    _genai_live.ws_connect = _patched_ws_connect
    print("[patch] websockets open_timeout patched to 60s", flush=True)
except Exception as _e:
    print(f"[patch] could not patch open_timeout: {_e}", flush=True)

app = FastAPI(title="NYC 311 Vision Reporter")


@app.on_event("startup")
async def warmup_credentials():
    """Pre-warm Vertex AI credentials (token fetch only — no Live API session)."""
    import os
    from google import genai as _genai
    try:
        client = _genai.Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-east4"),
        )
        await asyncio.to_thread(lambda: next(iter(client.models.list()), None))
        print("[startup] credentials warmed up", flush=True)
    except Exception as e:
        print(f"[startup] credential warmup failed (non-fatal): {e}", flush=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    import os
    return {"maps_api_key": os.getenv("MAPS_API_KEY", "")}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    user_id = f"user_{uuid.uuid4().hex[:8]}"
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    live_queue = LiveRequestQueue()

    async def run_agent():
        """Consume events from run_live and forward to the browser.
        Retries up to 4 times on transient Vertex AI connection errors."""
        agent_transcript = []
        user_transcript = []

        for attempt in range(4):
            if attempt > 0:
                delay = 2 ** (attempt - 1)   # 1s, 2s, 4s
                print(f"[agent] retry {attempt}/3 in {delay}s...", flush=True)
                await asyncio.sleep(delay)

            try:
                # Fresh session for each attempt so the ADK has clean state
                attempt_session_id = session_id if attempt == 0 else f"session_{uuid.uuid4().hex[:8]}"
                if attempt > 0:
                    await session_service.create_session(
                        app_name=APP_NAME, user_id=user_id, session_id=attempt_session_id
                    )
                print(f"[agent] run_live starting (attempt {attempt+1}, session={attempt_session_id})", flush=True)
                async for event in runner.run_live(
                    user_id=user_id,
                    session_id=attempt_session_id,
                    live_request_queue=live_queue,
                    run_config=run_config,
                ):
                    # ── Audio output → send raw bytes immediately ──────────
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                                await ws.send_bytes(part.inline_data.data)

                    # ── Output transcription — accumulate, flush on turn end
                    ot = getattr(event, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        agent_transcript.append(ot.text)
                    if getattr(event, "turn_complete", False) and agent_transcript:
                        await ws.send_text(json.dumps({
                            "type": "transcript",
                            "role": "agent",
                            "content": "".join(agent_transcript),
                        }))
                        agent_transcript.clear()

                    # ── Input transcription — accumulate, flush on turn end ─
                    it = getattr(event, "input_transcription", None)
                    if it and getattr(it, "text", None):
                        user_transcript.append(it.text)
                    if getattr(event, "turn_complete", False) and user_transcript:
                        await ws.send_text(json.dumps({
                            "type": "transcript",
                            "role": "user",
                            "content": "".join(user_transcript).strip(),
                        }))
                        user_transcript.clear()

                    # ── Tool result: draft_complaint → send draft card ─────
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            fr = getattr(part, "function_response", None)
                            if fr and getattr(fr, "name", None) == "draft_complaint":
                                complaint = fr.response or {}
                                if isinstance(complaint, dict) and "result" in complaint:
                                    complaint = complaint["result"]
                                await ws.send_text(json.dumps({
                                    "type": "draft",
                                    "complaint": complaint,
                                }))
                break  # completed successfully — don't retry

            except Exception as exc:
                print(f"[agent] attempt {attempt+1} failed: {exc}", flush=True)
                if attempt == 3:
                    traceback.print_exc()

    agent_task = asyncio.create_task(run_agent())
    # LiveRequestQueue buffers all sends until run_live() establishes the
    # connection, so we can enter the receive loop immediately.
    await asyncio.sleep(0)  # yield once to let run_agent start connecting

    try:
        while True:
            message = await ws.receive()

            # ── Binary: raw PCM audio from the microphone ──────────────────
            if "bytes" in message and message["bytes"]:
                print(f"[ws] audio chunk received: {len(message['bytes'])} bytes", flush=True)
                live_queue.send_realtime(
                    types.Blob(
                        data=message["bytes"],
                        mime_type="audio/pcm;rate=16000",
                    )
                )

            # ── Text: JSON control messages ────────────────────────────────
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "image":
                    # Analyze image in a background task so the Live API
                    # WebSocket handshake isn't blocked by the HTTP call.
                    captured = dict(data)

                    async def analyze_and_send(d=captured):
                        print("[ws] analyze_image starting...", flush=True)
                        analysis = await analyze_image(d["image_base64"])
                        print(f"[ws] analyze_image done: {analysis.get('issue_type')}", flush=True)
                        live_queue.send_content(
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        text=(
                                            f"I found an infrastructure issue near me. "
                                            f"GPS coordinates: latitude={d.get('latitude')}, "
                                            f"longitude={d.get('longitude')}. "
                                            f"Photo analysis result: {analysis}. "
                                            f"Please use this analysis along with the GPS to help me "
                                            f"report it to NYC 311 — geocode the location, check for "
                                            f"existing complaints, and ask any follow-up questions."
                                        )
                                    ),
                                ],
                            )
                        )

                    asyncio.create_task(analyze_and_send())

                elif msg_type == "text":
                    # Text fallback from the input box
                    live_queue.send_content(
                        types.Content(
                            role="user",
                            parts=[types.Part(text=data.get("content", ""))],
                        )
                    )

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        traceback.print_exc()
    finally:
        live_queue.close()
        agent_task.cancel()


# Static files — must be last
app.mount("/", StaticFiles(directory="static", html=True), name="static")
