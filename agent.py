"""
ADK Agent for NYC 311 Vision Reporter — Live API streaming version.
Uses Gemini Live API for real-time bidirectional audio streaming.
Tools in tools/ are unchanged.
"""

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from tools.analyze import analyze_image
from tools.query_311 import query_311_data
from tools.geocode import reverse_geocode
from tools.draft import draft_complaint

load_dotenv()

SYSTEM_PROMPT = """You are the NYC 311 Vision Reporter assistant — an AI that helps New York City residents report infrastructure issues.

When a user shares a photo and GPS coordinates, follow this exact workflow:

1. **Analyze the photo** using the analyze_image tool to classify the infrastructure issue.
2. **Geocode the location** using the reverse_geocode tool with the provided latitude/longitude.
3. **Check existing complaints** using the query_311_data tool to find similar open 311 complaints nearby.
4. **Summarize your findings** to the user in a clear, friendly way:
   - What issue you detected and its severity
   - The address you resolved from their GPS
   - Whether similar complaints already exist nearby
5. **Ask 1-2 brief follow-up questions** to improve the report, such as:
   - How long has this issue been present?
   - Is it causing an immediate safety hazard?
   - Any other details they'd like to add?

6. After the user responds to your questions, use the draft_complaint tool to generate the final Open311-compatible complaint report. Present the draft clearly.

Keep responses concise and conversational. You're helping someone file a civic complaint, not writing an essay. Use plain language."""

APP_NAME = "nyc_311_vision_reporter"

session_service = InMemorySessionService()

agent = Agent(
    name="nyc_311_agent",
    model="gemini-live-2.5-flash-native-audio",
    instruction=SYSTEM_PROMPT,
    tools=[analyze_image, reverse_geocode, query_311_data, draft_complaint],
)

runner = Runner(
    app_name=APP_NAME,
    agent=agent,
    session_service=session_service,
)

run_config = RunConfig(
    response_modalities=["AUDIO"],
    streaming_mode=StreamingMode.BIDI,
    output_audio_transcription=types.AudioTranscriptionConfig(),
    input_audio_transcription=types.AudioTranscriptionConfig(),
)
