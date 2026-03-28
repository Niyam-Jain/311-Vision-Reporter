"""
Complaint draft generator following Open311 GeoReport v2 spec.
Assembles all gathered context into a structured, submission-ready complaint.
"""

from datetime import datetime, timezone


# Map issue types to NYC 311 service codes
ISSUE_TO_SERVICE_CODE = {
    "Pothole": "HPD-street-condition",
    "Broken Streetlight": "DOT-street-light",
    "Graffiti": "DSNY-graffiti",
    "Overflowing Trash": "DSNY-dirty-conditions",
    "Damaged Sidewalk": "DOT-sidewalk",
    "Fallen Tree": "DPR-damaged-tree",
    "Broken Fire Hydrant": "DEP-hydrant",
    "Missing Signage": "DOT-traffic-signal",
    "Water Leak": "DEP-water-system",
    "Abandoned Vehicle": "NYPD-derelict-vehicle",
    "Other": "OTHER-general",
    "Unknown": "OTHER-general",
}


def get_severity_label(severity: int) -> str:
    """Convert numeric severity to a human-readable label."""
    labels = {1: "Minor", 2: "Moderate", 3: "Significant", 4: "Severe", 5: "Critical"}
    return labels.get(severity, "Unknown")


async def draft_complaint(
    issue_type: str,
    severity: int,
    description: str,
    formatted_address: str,
    latitude: float,
    longitude: float,
    user_notes: str = "",
    existing_complaint_count: int = 0,
    borough: str = None,
    zip_code: str = None,
) -> dict:
    """Generate a structured 311 complaint draft following Open311 GeoReport v2 spec.

    Args:
        issue_type: Classified issue type (e.g. "Pothole").
        severity: Severity rating 1-5.
        description: AI-generated description of the issue.
        formatted_address: Full street address from geocoding.
        latitude: GPS latitude.
        longitude: GPS longitude.
        user_notes: Additional context from the user's responses.
        existing_complaint_count: Number of existing complaints found nearby.
        borough: NYC borough name.
        zip_code: Postal code.

    Returns:
        Dict structured as an Open311-compatible complaint.
    """
    # Build comprehensive description
    full_description = description.strip()
    if user_notes and user_notes.strip():
        full_description += f" Additional context from reporter: {user_notes.strip()}"

    return {
        "service_code": ISSUE_TO_SERVICE_CODE.get(issue_type, "OTHER-general"),
        "service_name": issue_type,
        "description": full_description,
        "lat": latitude,
        "long": longitude,
        "address_string": formatted_address,
        "zipcode": zip_code,
        "borough": borough,
        "severity": severity,
        "severity_label": get_severity_label(severity),
        "media_url": None,  # Would be photo URL in production
        "requested_datetime": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "metadata": {
            "existing_complaints_nearby": existing_complaint_count,
            "ai_classified": True,
            "open311_compatible": True,
            "spec_version": "GeoReport v2",
        },
    }


if __name__ == "__main__":
    import asyncio
    import json

    result = asyncio.run(
        draft_complaint(
            issue_type="Pothole",
            severity=3,
            description="Large pothole approximately 2 feet wide on the road surface near the intersection.",
            formatted_address="6 MetroTech Center, Brooklyn, NY 11201",
            latitude=40.6942,
            longitude=-73.9866,
            user_notes="It has been here for about 2 weeks and is getting worse after the rain.",
            existing_complaint_count=5,
            borough="Brooklyn",
            zip_code="11201",
        )
    )
    print("draft_complaint result:")
    print(json.dumps(result, indent=2))
