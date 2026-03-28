# NYC 311 Vision Reporter

**GDG NYC Build With AI Hackathon @ NYU Tandon — March 28, 2026**

**Author:** Niyam Jain
**Email:** niyamjain2003@gmail.com

---

An AI-powered mobile web app that lets NYC residents report infrastructure issues by snapping a photo. The app uses Google's Gemini Live API for real-time voice conversation, automatically identifies the problem in the photo, reverse-geocodes the GPS location, checks for existing complaints nearby, and generates a structured Open311-compatible complaint — all through a natural voice dialogue.

---

## Table of Contents

- [Demo Flow](#demo-flow)
- [Architecture Overview](#architecture-overview)
- [System Architecture Diagram](#system-architecture-diagram)
- [Backend — FastAPI Server](#backend--fastapi-server)
- [AI Agent — Google ADK](#ai-agent--google-adk)
- [Tools](#tools)
  - [analyze\_image](#1-analyze_image)
  - [reverse\_geocode](#2-reverse_geocode)
  - [query\_311\_data](#3-query_311_data)
  - [draft\_complaint](#4-draft_complaint)
- [Frontend — Vanilla JS PWA](#frontend--vanilla-js-pwa)
- [WebSocket Protocol](#websocket-protocol)
- [Data Flow — Step by Step](#data-flow--step-by-step)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Local Development](#setup--local-development)
- [Environment Variables](#environment-variables)
- [Deployment — Google Cloud Run](#deployment--google-cloud-run)
- [Open311 GeoReport v2 Compatibility](#open311-georeport-v2-compatibility)
- [Known Limitations](#known-limitations)

---

## Demo Flow

1. User opens the app on their phone and points the camera at a pothole, broken streetlight, graffiti, etc.
2. The app captures the photo and acquires the GPS location.
3. Gemini Vision analyzes the photo and classifies the issue.
4. The AI agent speaks back to the user, confirming what it found, the resolved street address, and whether similar complaints are already open nearby.
5. The agent asks 1–2 follow-up questions (e.g., "How long has this been here?").
6. The user responds by voice or text.
7. The agent generates a complete complaint draft and displays a review card with a map thumbnail.
8. The user taps **Approve & Submit** — the app simulates submission through the Open311 API flow with step-by-step status updates.

---

## Architecture Overview

The system has three main layers:

```
Browser (Mobile PWA)
    │
    │  WebSocket (binary PCM audio + JSON control messages)
    ▼
FastAPI Server (Python)
    │
    ├── analyze_image ──► Gemini 2.5 Flash (Vertex AI) — Vision
    │
    └── Google ADK Runner ──► Gemini Live 2.5 Flash Native Audio (Vertex AI)
            │
            ├── reverse_geocode ──► Google Maps Geocoding API
            ├── query_311_data  ──► NYC Open Data / Socrata API
            └── draft_complaint ──► Open311 GeoReport v2 (local assembly)
```

The backend is the sole bridge between the browser and all AI/external services. The browser never calls Google APIs directly — it only sends audio bytes and JSON messages over a single WebSocket connection.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   Browser (Mobile PWA)                  │
│                                                         │
│  ┌──────────────┐   ┌────────────────┐                  │
│  │ Screen 1     │   │ Screen 2       │                  │
│  │ (Capture)    │──►│ (Chat / Voice) │                  │
│  │ Camera / GPS │   │ Audio + Text   │                  │
│  └──────────────┘   └───────┬────────┘                  │
└──────────────────────────────┼──────────────────────────┘
                               │ WebSocket /ws
              ┌────────────────┼────────────────────┐
              │     FastAPI Server (main.py)         │
              │                │                    │
              │  ┌─────────────▼──────────────────┐ │
              │  │  websocket_endpoint()           │ │
              │  │                                 │ │
              │  │  ┌──────────────────────────┐  │ │
              │  │  │  LiveRequestQueue        │  │ │
              │  │  │  (buffers audio/content) │  │ │
              │  │  └──────────┬───────────────┘  │ │
              │  │             │                   │ │
              │  │  ┌──────────▼───────────────┐  │ │
              │  │  │  ADK Runner.run_live()   │  │ │
              │  │  │  (async event stream)    │  │ │
              │  │  └──────────┬───────────────┘  │ │
              │  └─────────────┼───────────────── ┘ │
              │                │                    │
              │  ┌─────────────▼──────────────────┐ │
              │  │  Google ADK Agent               │ │
              │  │  gemini-live-2.5-flash-          │ │
              │  │  native-audio                   │ │
              │  │                                 │ │
              │  │  Tools:                         │ │
              │  │  • analyze_image ───────────────┼─┼──► Gemini 2.5 Flash
              │  │  • reverse_geocode ─────────────┼─┼──► Google Maps API
              │  │  • query_311_data ──────────────┼─┼──► NYC Open Data
              │  │  • draft_complaint (local)      │ │
              │  └─────────────────────────────────┘ │
              └─────────────────────────────────────-─┘
```

---

## Backend — FastAPI Server

**File:** `main.py`

The backend is a single FastAPI application serving both the static frontend and a WebSocket endpoint.

### Startup: Credential Warmup

On startup, the server pre-warms Google Cloud credentials by calling `client.models.list()` — a lightweight authenticated request. This avoids a cold-start credential refresh timeout when the first real WebSocket connection arrives.

```python
@app.on_event("startup")
async def warmup_credentials():
    client = genai.Client(vertexai=True, project=..., location=...)
    await asyncio.to_thread(lambda: next(iter(client.models.list()), None))
```

### WebSocket Patch

The default `websockets` library `open_timeout` of 10 seconds is too short for Vertex AI to refresh OAuth2 credentials. The server monkey-patches `google.genai.live.ws_connect` at module load time to extend timeouts:

```
open_timeout  : 10s → 60s
ping_interval : 20s → 30s
ping_timeout  : 20s → 60s
```

This is necessary because Vertex AI's Live API endpoint processes the system instruction and tool declarations before returning the initial HTTP upgrade response — which can take 15–30 seconds on first connection.

### WebSocket Endpoint `/ws`

Each browser connection gets:
- A unique `user_id` and `session_id`
- A `LiveRequestQueue` that safely buffers content before the Live API connection is established
- Two concurrent async tasks:
  1. `run_agent()` — drives the ADK runner and streams events back to the browser
  2. The receive loop — forwards browser messages into the `LiveRequestQueue`

**Retry logic:** `run_agent()` retries up to 4 times with exponential backoff (1s, 2s, 4s delays). Each retry creates a fresh ADK session to avoid state corruption from a partially-established connection.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |
| `GET` | `/api/config` | Returns Maps API key for the frontend |
| `WS` | `/ws` | Main bidirectional WebSocket connection |
| `GET` | `/*` | Static file serving (HTML/CSS/JS) |

---

## AI Agent — Google ADK

**File:** `agent.py`

The AI agent is built with **Google Agent Development Kit (ADK)**. It uses `gemini-live-2.5-flash-native-audio` — a model variant optimized for real-time bidirectional audio streaming.

### Model Configuration

```python
run_config = RunConfig(
    response_modalities=["AUDIO"],        # Agent speaks back
    streaming_mode=StreamingMode.BIDI,    # Full duplex audio
    output_audio_transcription=AudioTranscriptionConfig(),  # Transcribe agent speech
    input_audio_transcription=AudioTranscriptionConfig(),   # Transcribe user speech
)
```

The `BIDI` streaming mode means the agent can interrupt and be interrupted mid-sentence — a true real-time voice conversation, not a push-to-talk system.

### System Prompt Workflow

The agent follows a deterministic 6-step workflow enforced via its system prompt:

1. Call `analyze_image` to classify the photo
2. Call `reverse_geocode` to resolve the GPS to a street address
3. Call `query_311_data` to find nearby open complaints
4. Summarize findings to the user (verbally)
5. Ask 1–2 follow-up questions
6. Call `draft_complaint` to generate the final report

### Session Management

`InMemorySessionService` stores conversation state per WebSocket connection. Sessions are scoped to the connection lifetime — there is no persistence between page refreshes by design.

---

## Tools

### 1. `analyze_image`

**File:** `tools/analyze.py`

Sends a base64-encoded photo to **Gemini 2.5 Flash** (via Vertex AI) with a structured prompt. Returns a JSON classification:

| Field | Type | Description |
|-------|------|-------------|
| `issue_type` | string | One of 11 categories (Pothole, Broken Streetlight, Graffiti, etc.) |
| `severity` | int 1–5 | 1 = minor cosmetic, 5 = immediate safety hazard |
| `description` | string | 2–3 sentence description of what the model observes |
| `category_311` | string | Matching NYC 311 complaint category name |

Note: This tool uses the standard `generate_content` (REST) API, not the Live API — it's called in a background task so it doesn't block the WebSocket handshake.

### 2. `reverse_geocode`

**File:** `tools/geocode.py`

Calls the **Google Maps Geocoding API** with a `latlng` parameter. Parses `address_components` to extract:

- `formatted_address` — Full human-readable address
- `street_number`, `street_name`
- `neighborhood`
- `borough` — NYC borough (Brooklyn, Manhattan, Queens, etc.)
- `zip_code`

Falls back to `"Near (lat, lng)"` if the API key is missing or the request fails.

### 3. `query_311_data`

**File:** `tools/query_311.py`

Queries **NYC Open Data** (dataset `erm2-nwe9`) via the Socrata API. Uses a spatial `within_circle()` filter to find complaints within a configurable radius (default 200m) matching the classified issue type.

Returns:

| Field | Description |
|-------|-------------|
| `total_complaints` | Number of matching complaints found |
| `open_complaints` | Count with status: Open, In Progress, Pending, or Assigned |
| `most_recent_date` | Date of the most recently filed matching complaint |
| `resolution_rate` | Percentage of found complaints with status Closed |
| `common_descriptors` | Top 3 descriptor strings from the dataset |
| `sample_resolutions` | Up to 3 resolution descriptions from closed complaints |

No API key required — NYC Open Data is publicly accessible.

### 4. `draft_complaint`

**File:** `tools/draft.py`

Assembles all gathered context into a structured complaint following the **Open311 GeoReport v2** specification. This tool runs locally (no external API call) and produces:

```json
{
  "service_code": "HPD-street-condition",
  "service_name": "Pothole",
  "description": "Large pothole approximately 2 feet wide...",
  "lat": 40.6942,
  "long": -73.9866,
  "address_string": "6 MetroTech Center, Brooklyn, NY 11201",
  "zipcode": "11201",
  "borough": "Brooklyn",
  "severity": 3,
  "severity_label": "Significant",
  "requested_datetime": "2026-03-28T15:30:00+00:00",
  "status": "draft",
  "metadata": {
    "existing_complaints_nearby": 5,
    "ai_classified": true,
    "open311_compatible": true,
    "spec_version": "GeoReport v2"
  }
}
```

---

## Frontend — Vanilla JS PWA

**Files:** `static/index.html`, `static/app.js`, `static/style.css`, `static/audio-processor.js`

The frontend is a single-page app with two screens:

### Screen 1 — Capture

- **Camera access** via `getUserMedia` with `facingMode: environment` (rear camera on mobile)
- **File upload** fallback for devices without camera API support
- **GPS acquisition** via `navigator.geolocation.getCurrentPosition` with high accuracy enabled
- GPS status indicator updates in real time (acquiring → locked with coordinates)
- The Analyze button only activates when both a photo and a GPS fix are available

### Screen 2 — Chat / Voice

- **Audio capture:** Uses the Web Audio API with an `AudioWorkletProcessor` (`audio-processor.js`) to capture raw PCM audio at 16 kHz (the format Gemini Live expects). Audio is streamed continuously as binary WebSocket frames.
- **Audio playback:** Agent audio responses arrive as binary WebSocket frames and are played back using a Web Audio API buffer queue.
- **Transcript display:** Both agent and user speech are transcribed server-side and sent as JSON `transcript` messages, displayed in a chat bubble UI.
- **Text fallback:** A text input bar allows typing responses when voice isn't convenient.
- **Draft card:** When the agent calls `draft_complaint`, the server sends a `draft` message. The frontend renders a review card with:
  - Google Maps Static API thumbnail (400×200, zoom 17, red pin at the location)
  - Structured complaint details (issue, severity, address, borough, ZIP, description)
  - Approve & Submit button

### Submission Flow (Demo)

When the user taps Approve & Submit:
1. Button shows spinner: "Submitting to NYC 311..."
2. Status steps through: "Connecting to Open311 API..." → "Uploading photo evidence..." → "Submitting complaint #311-2026-XXXXX..." → "Confirmed ✓"
3. The draft card is replaced with a success card showing the complaint number and address

> This is a demo simulation. The Open311 API integration is architected and ready — production deployment would swap the fake steps for a real `POST` to the NYC Open311 endpoint.

---

## WebSocket Protocol

All communication between browser and server uses a single WebSocket connection at `/ws`.

### Browser → Server

| Format | Content | Description |
|--------|---------|-------------|
| Binary | Raw PCM bytes | 16 kHz, 16-bit, mono audio from microphone |
| JSON `{"type": "image", "image_base64": "...", "latitude": ..., "longitude": ...}` | Photo + GPS | Triggers image analysis + agent context injection |
| JSON `{"type": "text", "content": "..."}` | Text string | Text input fallback |

### Server → Browser

| Format | Content | Description |
|--------|---------|-------------|
| Binary | Raw PCM bytes | Agent voice response audio (16 kHz) |
| JSON `{"type": "transcript", "role": "agent", "content": "..."}` | Text | Agent speech transcription |
| JSON `{"type": "transcript", "role": "user", "content": "..."}` | Text | User speech transcription |
| JSON `{"type": "draft", "complaint": {...}}` | Object | Open311 complaint draft, triggers review card |

---

## Data Flow — Step by Step

```
1. User taps "Analyze Issue"
   Browser: captures JPEG → base64 encodes → sends JSON {type:"image", image_base64, lat, lng}

2. Server receives image message
   main.py: spawns background task → calls analyze_image(image_base64)
   analyze.py: POST to Gemini 2.5 Flash → receives JSON classification
   main.py: injects analysis + GPS into LiveRequestQueue as a text Content part

3. ADK runner receives the content
   agent.py: Gemini Live sees the analysis result and GPS coordinates
   Agent calls reverse_geocode(lat, lng)
   geocode.py: GET Google Maps Geocoding API → returns structured address

4. Agent calls query_311_data(issue_type, lat, lng)
   query_311.py: GET Socrata API with within_circle() spatial filter
   Returns complaint counts and statistics

5. Agent composes a voice summary and speaks to the user
   main.py: receives audio output events → sends binary PCM to browser
   main.py: receives output_transcription events → sends {type:"transcript", role:"agent"}
   Browser: plays audio through Web Audio API, displays transcript bubble

6. User responds by voice
   Browser: streams raw PCM via binary WebSocket frames
   main.py: forwards bytes → LiveRequestQueue.send_realtime()
   Gemini Live: transcribes user speech → sends input_transcription events
   main.py: accumulates fragments, flushes on turn_complete → {type:"transcript", role:"user"}

7. After follow-up Q&A, agent calls draft_complaint(...)
   draft.py: assembles Open311 GeoReport v2 object (local, no API call)
   main.py: detects function_response for "draft_complaint" in events
   main.py: sends {type:"draft", complaint:{...}} to browser

8. Browser renders draft card
   app.js: renderDraftCard() builds review UI with map thumbnail
   User reviews and taps Approve → runSubmissionFlow() animates submission steps
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Agent Framework | Google Agent Development Kit (ADK) |
| Live Voice AI | Gemini Live 2.5 Flash Native Audio (Vertex AI) |
| Vision AI | Gemini 2.5 Flash (Vertex AI) |
| Backend | FastAPI + Uvicorn (Python 3.11) |
| Real-time Transport | WebSockets (bidirectional, binary + JSON) |
| Geocoding | Google Maps Geocoding API |
| Map Thumbnails | Google Maps Static API |
| 311 Data | NYC Open Data — Socrata API (dataset erm2-nwe9) |
| Frontend | Vanilla JS + Web Audio API (no framework) |
| Audio Processing | AudioWorklet (custom PCM processor) |
| Containerization | Docker |
| Cloud Platform | Google Cloud Run |
| IDE | Antigravity IDE |

---

## Project Structure

```
311/
├── main.py                  # FastAPI app, WebSocket endpoint, ADK integration
├── agent.py                 # ADK Agent definition, RunConfig, session service
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container definition for Cloud Run
├── setup_gcloud.sh          # Helper script for Cloud Run deployment
├── check_env.py             # Environment variable validation utility
├── test_apis.py             # Integration tests for all external APIs
├── .gitignore
│
├── tools/
│   ├── __init__.py
│   ├── analyze.py           # Gemini Vision image classification
│   ├── geocode.py           # Google Maps reverse geocoding
│   ├── query_311.py         # NYC Open Data / Socrata spatial query
│   └── draft.py             # Open311 GeoReport v2 complaint assembler
│
└── static/
    ├── index.html           # Single-page app (two-screen layout)
    ├── app.js               # All frontend logic, WebSocket client, audio
    ├── style.css            # Dark-mode mobile-first UI
    └── audio-processor.js  # AudioWorklet: mic → raw PCM at 16 kHz
```

---

## Setup & Local Development

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI API enabled
- `gcloud` CLI authenticated (`gcloud auth application-default login`)
- Google Maps API key (Geocoding API + Static Maps API enabled)

### Install

```bash
git clone https://github.com/Niyam-Jain/311-Vision-Reporter.git
cd 311-Vision-Reporter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the project root:

```env
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-east4
MAPS_API_KEY=your-google-maps-api-key
```

### Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in a browser. For full camera/GPS/microphone access, use a browser over HTTPS or `localhost` (Chrome grants device permissions to localhost automatically).

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | Set to `TRUE` to use Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Yes | Vertex AI region (e.g. `us-east4`) |
| `MAPS_API_KEY` | Yes | Google Maps API key (Geocoding + Static Maps) |

---

## Deployment — Google Cloud Run

```bash
# Build and push container
gcloud builds submit --tag gcr.io/YOUR_PROJECT/311-vision-reporter

# Deploy
gcloud run deploy 311-vision-reporter \
  --image gcr.io/YOUR_PROJECT/311-vision-reporter \
  --platform managed \
  --region us-east4 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GOOGLE_CLOUD_LOCATION=us-east4,MAPS_API_KEY=YOUR_KEY
```

Cloud Run's HTTPS URL is required for mobile browsers to grant camera and microphone permissions.

---

## Open311 GeoReport v2 Compatibility

The `draft_complaint` tool produces a payload that maps directly to the Open311 GeoReport v2 spec fields:

| Open311 Field | Our Field | Notes |
|---------------|-----------|-------|
| `service_code` | `service_code` | NYC agency-prefixed code (e.g. `DOT-street-light`) |
| `service_name` | `service_name` | Human-readable issue type |
| `description` | `description` | AI description + user notes |
| `lat` | `lat` | GPS latitude |
| `long` | `long` | GPS longitude |
| `address_string` | `address_string` | Geocoded formatted address |
| `requested_datetime` | `requested_datetime` | ISO 8601 UTC timestamp |
| `status` | `status` | Always `"draft"` until submitted |

In production, submission would be a `POST` to `https://api.nyc.gov/open311/v2/requests.json`.

---

## Known Limitations

- **In-memory sessions only:** Conversation state is lost on server restart or page refresh. No database persistence.
- **No real Open311 submission:** The submission flow is a UI demo. The NYC Open311 API requires a registered service account for `POST` requests.
- **Vertex AI Live API latency:** The initial WebSocket connection to Vertex AI can take 10–30 seconds on a cold start while credentials are refreshed. The retry logic and credential warmup mitigate this but don't eliminate it.
- **Single user per session:** Each WebSocket connection is independent. There is no multi-user or shared session support.
- **Photo not uploaded:** The `media_url` field in the complaint draft is `null`. In production, the photo would be uploaded to GCS and the signed URL included in the submission.

---

*Built at the GDG NYC Build With AI Hackathon @ NYU Tandon, March 28, 2026.*
