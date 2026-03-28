import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
print(f"API key (first 10): {api_key[:10]}...")

client = genai.Client(api_key=api_key)

# Try listing models first
print("\n--- Listing available models ---")
try:
    for model in client.models.list():
        if "flash" in model.name.lower():
            print(f"  {model.name}")
except Exception as e:
    print(f"  Error listing models: {e}")

# Try gemini-1.5-flash (different quota bucket)
print("\n--- Testing gemini-1.5-flash ---")
try:
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents="Say hello in one sentence.",
    )
    print(f"  Response: {response.text}")
    print("  ✅ PASS")
except Exception as e:
    print(f"  ❌ Error: {e}")

# Try gemini-2.0-flash
print("\n--- Testing gemini-2.0-flash ---")
try:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Say hello in one sentence.",
    )
    print(f"  Response: {response.text}")
    print("  ✅ PASS")
except Exception as e:
    print(f"  ❌ Error: {e}")
