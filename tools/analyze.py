"""
Image analysis tool using Gemini Pro Vision via Vertex AI.
Sends a photo to Gemini, receives a structured classification of the infrastructure issue.
"""

import base64
import json
import os
import re

from google import genai
from google.genai import types


ANALYSIS_PROMPT = """Analyze this photo of a potential NYC infrastructure issue.
Classify the issue and respond ONLY with a valid JSON object (no markdown, no code fences, no extra text) with these exact fields:

{
  "issue_type": "one of: Pothole, Broken Streetlight, Graffiti, Overflowing Trash, Damaged Sidewalk, Fallen Tree, Broken Fire Hydrant, Missing Signage, Water Leak, Abandoned Vehicle, Other",
  "severity": "integer 1-5 where 1=minor cosmetic issue and 5=immediate safety hazard",
  "description": "2-3 sentence description of what you observe in the photo",
  "category_311": "the matching NYC 311 complaint category name (e.g., Street Condition, Street Light Condition, Dirty Conditions, etc.)"
}

If the photo does not show a clear infrastructure issue, return:
{
  "issue_type": "Unknown",
  "severity": 0,
  "description": "Description of what you see instead",
  "category_311": "Unknown"
}"""


def _parse_gemini_json(text: str) -> dict:
    """Extract and parse JSON from Gemini's response, handling code fences."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    # Fallback
    return {
        "issue_type": "Unknown",
        "severity": 0,
        "description": f"Could not parse Gemini response: {text[:200]}",
        "category_311": "Unknown",
    }


async def analyze_image(image_base64: str) -> dict:
    """Analyze a photo of an infrastructure issue using Gemini Vision.

    Args:
        image_base64: Base64-encoded image string (PNG or JPEG).

    Returns:
        Dict with issue_type, severity, description, category_311.
    """
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() in ("TRUE", "1")

    try:
        if use_vertex:
            client = genai.Client(
                vertexai=True,
                project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-east1"),
            )
        else:
            client = genai.Client(
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

        # Decode base64 to bytes for inline image
        image_bytes = base64.b64decode(image_base64)

        # Determine mime type (default to JPEG, detect PNG by magic bytes)
        mime_type = "image/jpeg"
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            mime_type = "image/png"

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[image_part, ANALYSIS_PROMPT],
        )

        result = _parse_gemini_json(response.text)

        # Ensure severity is an int
        if isinstance(result.get("severity"), str):
            try:
                result["severity"] = int(result["severity"])
            except ValueError:
                result["severity"] = 0

        return result

    except Exception as e:
        return {
            "issue_type": "Unknown",
            "severity": 0,
            "description": f"Error analyzing image: {str(e)}",
            "category_311": "Unknown",
        }


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()

    # Test with a tiny 1x1 red pixel PNG
    test_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

    result = asyncio.run(analyze_image(test_image))
    print("analyze_image result:")
    print(json.dumps(result, indent=2))
