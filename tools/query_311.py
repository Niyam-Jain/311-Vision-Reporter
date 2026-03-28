"""
NYC 311 Open Data query tool using Socrata API.
Queries existing complaints near a given location and computes summary statistics.
"""

from collections import Counter

import httpx


# Map our issue_type values to NYC 311 complaint_type strings
ISSUE_TO_311_TYPE = {
    "Pothole": "Street Condition",
    "Broken Streetlight": "Street Light Condition",
    "Graffiti": "Graffiti",
    "Overflowing Trash": "Dirty Conditions",
    "Damaged Sidewalk": "Sidewalk Condition",
    "Fallen Tree": "Damaged Tree",
    "Broken Fire Hydrant": "Broken Fire Hydrant",
    "Missing Signage": "Traffic Signal Condition",
    "Water Leak": "Water System",
    "Abandoned Vehicle": "Derelict Vehicle",
    "Other": "Other",
    "Unknown": "Other",
}

SOCRATA_ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

OPEN_STATUSES = {"Open", "In Progress", "Pending", "Assigned"}


async def query_311_data(
    complaint_type: str,
    latitude: float,
    longitude: float,
    radius_meters: int = 200,
) -> dict:
    """Query NYC 311 Open Data for existing complaints near a location.

    Args:
        complaint_type: The complaint type to search for (our issue_type value or NYC 311 category).
        latitude: GPS latitude.
        longitude: GPS longitude.
        radius_meters: Search radius in meters (default 200).

    Returns:
        Dict with total_complaints, open_complaints, most_recent_date,
        resolution_rate, common_descriptors, sample_resolutions.
    """
    empty_result = {
        "total_complaints": 0,
        "open_complaints": 0,
        "most_recent_date": None,
        "resolution_rate": 0,
        "common_descriptors": [],
        "sample_resolutions": [],
    }

    try:
        # Map to 311 complaint type if needed
        mapped_type = ISSUE_TO_311_TYPE.get(complaint_type, complaint_type)

        # Build the spatial query
        where_clause = f"within_circle(location, {latitude}, {longitude}, {radius_meters})"

        # For Unknown/Other, skip complaint_type filter to show all nearby activity
        if mapped_type not in ("Other", "Unknown"):
            where_clause += f" AND complaint_type='{mapped_type}'"

        params = {
            "$where": where_clause,
            "$order": "created_date DESC",
            "$limit": "20",
            "$select": "unique_key,created_date,status,resolution_description,descriptor,agency",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(SOCRATA_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()

        if not data or not isinstance(data, list):
            return empty_result

        total = len(data)

        # Count open complaints
        open_count = sum(1 for r in data if r.get("status") in OPEN_STATUSES)

        # Most recent date (already sorted DESC)
        most_recent = data[0].get("created_date")
        if most_recent:
            # Format nicely: "2024-03-15" from ISO timestamp
            most_recent = most_recent[:10]

        # Resolution rate
        closed_count = sum(1 for r in data if r.get("status") == "Closed")
        resolution_rate = int((closed_count / total) * 100) if total > 0 else 0

        # Common descriptors (top 3)
        descriptors = [r.get("descriptor") for r in data if r.get("descriptor")]
        common_descriptors = [desc for desc, _ in Counter(descriptors).most_common(3)]

        # Sample resolutions from closed complaints
        sample_resolutions = [
            r["resolution_description"]
            for r in data
            if r.get("status") == "Closed"
            and r.get("resolution_description")
            and r["resolution_description"].strip()
        ][:3]

        return {
            "total_complaints": total,
            "open_complaints": open_count,
            "most_recent_date": most_recent,
            "resolution_rate": resolution_rate,
            "common_descriptors": common_descriptors,
            "sample_resolutions": sample_resolutions,
        }

    except Exception as e:
        print(f"[query_311_data] Error querying Socrata API: {e}")
        return empty_result


if __name__ == "__main__":
    import asyncio

    # Test with real coordinates near NYU Tandon
    result = asyncio.run(
        query_311_data(
            complaint_type="Street Condition",
            latitude=40.6942,
            longitude=-73.9866,
            radius_meters=500,
        )
    )
    print("query_311_data result:")
    print(f"  Total complaints: {result['total_complaints']}")
    print(f"  Open: {result['open_complaints']}")
    print(f"  Most recent: {result['most_recent_date']}")
    print(f"  Resolution rate: {result['resolution_rate']}%")
    print(f"  Common descriptors: {result['common_descriptors']}")
    print(f"  Sample resolutions: {result['sample_resolutions']}")
