"""
Reverse geocoding tool using Google Maps Geocoding API.
Converts GPS coordinates to a structured street address.
"""

import os

import httpx


GEOCODING_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"


def _extract_component(address_components: list, target_types: list[str]) -> str | None:
    """Extract a specific component from Google's address_components array."""
    for component in address_components:
        component_types = component.get("types", [])
        for target in target_types:
            if target in component_types:
                return component.get("long_name")
    return None


async def reverse_geocode(latitude: float, longitude: float) -> dict:
    """Convert GPS coordinates to a street address using Google Maps Geocoding API.

    Args:
        latitude: GPS latitude.
        longitude: GPS longitude.

    Returns:
        Dict with formatted_address, street_number, street_name,
        neighborhood, borough, zip_code.
    """
    fallback = {
        "formatted_address": f"Near ({latitude:.4f}, {longitude:.4f})",
        "street_number": None,
        "street_name": None,
        "neighborhood": None,
        "borough": None,
        "zip_code": None,
    }

    api_key = os.getenv("MAPS_API_KEY")
    if not api_key:
        print("[reverse_geocode] WARNING: MAPS_API_KEY not set")
        return fallback

    try:
        params = {
            "latlng": f"{latitude},{longitude}",
            "key": api_key,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(GEOCODING_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "OK" or not data.get("results"):
            print(f"[reverse_geocode] API status: {data.get('status')}")
            return fallback

        result = data["results"][0]
        components = result.get("address_components", [])

        return {
            "formatted_address": result.get("formatted_address", fallback["formatted_address"]),
            "street_number": _extract_component(components, ["street_number"]),
            "street_name": _extract_component(components, ["route"]),
            "neighborhood": _extract_component(components, ["neighborhood"]),
            "borough": _extract_component(
                components, ["sublocality_level_1", "administrative_area_level_2"]
            ),
            "zip_code": _extract_component(components, ["postal_code"]),
        }

    except Exception as e:
        print(f"[reverse_geocode] Error: {e}")
        return fallback


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()

    # Test with NYU Tandon coordinates
    result = asyncio.run(reverse_geocode(40.6942, -73.9866))
    print("reverse_geocode result:")
    for key, value in result.items():
        print(f"  {key}: {value}")
