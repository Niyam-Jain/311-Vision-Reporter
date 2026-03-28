"""
API Verification Script for NYC 311 Vision Reporter.
Tests all three external APIs to confirm they work before building real logic.

Usage: python test_apis.py
"""

import os
import asyncio

from dotenv import load_dotenv

load_dotenv()

results = {}


async def test_vertex_ai():
    """Test Vertex AI / Gemini connection with a simple text prompt."""
    print("\n--- Testing Vertex AI / Gemini ---")
    try:
        from google import genai

        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-east1")

        if not project:
            print("ERROR: GOOGLE_CLOUD_PROJECT not set in .env")
            results["Vertex AI / Gemini"] = False
            return

        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Say hello in one sentence.",
        )

        print(f"Response: {response.text}")
        print("✅ Vertex AI / Gemini: PASS")
        results["Vertex AI / Gemini"] = True

    except Exception as e:
        print(f"❌ FAILED: Vertex AI — check your project ID and authentication")
        print(f"   Error: {e}")
        results["Vertex AI / Gemini"] = False


async def test_socrata_311():
    """Test NYC 311 Socrata API with a simple query."""
    print("\n--- Testing NYC 311 Socrata API ---")
    try:
        import httpx

        url = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
        params = {
            "$limit": 3,
            "$select": "unique_key,complaint_type,created_date,status",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        print(f"Received {len(data)} complaints:")
        for complaint in data:
            print(f"  - {complaint.get('complaint_type', 'N/A')} | {complaint.get('status', 'N/A')} | {complaint.get('created_date', 'N/A')}")

        print("✅ Socrata 311 API: PASS")
        results["Socrata 311 API"] = True

    except Exception as e:
        print(f"❌ FAILED: Socrata API — check network connectivity")
        print(f"   Error: {e}")
        results["Socrata 311 API"] = False


async def test_geocoding():
    """Test Google Maps Geocoding API with NYU Tandon coordinates."""
    print("\n--- Testing Google Maps Geocoding API ---")
    try:
        import httpx

        api_key = os.getenv("MAPS_API_KEY")
        if not api_key:
            print("ERROR: MAPS_API_KEY not set in .env")
            results["Google Maps Geocode"] = False
            return

        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "latlng": "40.6942,-73.9866",
            "key": api_key,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "OK" and data.get("results"):
            address = data["results"][0].get("formatted_address", "No address found")
            print(f"Address: {address}")
            print("✅ Google Maps Geocode: PASS")
            results["Google Maps Geocode"] = True
        else:
            print(f"API returned status: {data.get('status')}")
            print(f"Error message: {data.get('error_message', 'None')}")
            print("❌ FAILED: Geocoding API — check your MAPS_API_KEY")
            results["Google Maps Geocode"] = False

    except Exception as e:
        print(f"❌ FAILED: Geocoding API — check your MAPS_API_KEY")
        print(f"   Error: {e}")
        results["Google Maps Geocode"] = False


async def main():
    print("=" * 50)
    print("NYC 311 Vision Reporter — API Verification")
    print("=" * 50)

    await test_vertex_ai()
    await test_socrata_311()
    await test_geocoding()

    print("\n" + "=" * 50)
    print("=== API Verification Results ===")
    print("=" * 50)

    for api_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {api_name:.<30} {status}")

    print()

    if all(results.values()):
        print("All APIs working! Ready for Phase 2. 🚀")
    else:
        print("⚠️  Some APIs failed. Fix the issues above before proceeding.")


if __name__ == "__main__":
    asyncio.run(main())
