"""Location and Maps Tool for determining current location and searching Google Maps."""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Any

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.location_maps")

_GEO_TIMEOUT = 8.0


def get_current_approximate_location() -> dict[str, Any]:
    """Resolve current approximate location using public IP geolocation."""
    try:
        with httpx.Client(timeout=_GEO_TIMEOUT) as client:
            resp = client.get("http://ip-api.com/json")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return {
                        "city": data.get("city", "Unknown City"),
                        "region": data.get("regionName", "Unknown Region"),
                        "country": data.get("country", "Unknown Country"),
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "timezone": data.get("timezone", "UTC"),
                        "isp": data.get("isp", ""),
                    }
    except Exception as e:
        logger.warning(f"Failed to query IP geolocation: {e}")

    return {
        "city": "Unknown",
        "region": "Unknown",
        "country": "Unknown",
        "lat": None,
        "lon": None,
        "timezone": "UTC",
    }


class LocationMapsTool(BaseTool):
    """Query current location or open Google Maps for places and directions."""

    name = "location_and_maps"
    description = (
        "Find current geographic location, search Google Maps for places/businesses, "
        "or get driving directions between locations. "
        "Supports 'where am i', searching 'restaurants near me', or getting directions."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current_location", "search_maps", "directions"],
                "description": "Operation to perform: 'current_location' (Where am I?), 'search_maps' (Find places), 'directions' (Navigate).",
            },
            "query": {
                "type": "string",
                "description": "Place, restaurant, or business to search for (e.g. 'coffee shops near me', 'Eiffel Tower').",
            },
            "destination": {
                "type": "string",
                "description": "Destination address/name when requesting directions.",
            },
            "origin": {
                "type": "string",
                "description": "Optional starting point for directions (defaults to current location).",
            },
            "open_in_browser": {
                "type": "boolean",
                "description": "Whether to open the map directly in the browser (default: true).",
            },
        },
        "required": ["action"],
    }

    def execute(
        self,
        action: str,
        query: str = "",
        destination: str = "",
        origin: str = "",
        open_in_browser: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        act = (action or "current_location").lower().strip()

        if act == "current_location":
            loc = get_current_approximate_location()
            if loc.get("city") != "Unknown":
                summary = (
                    f"Current Approximate Location:\n"
                    f"City: {loc['city']}, {loc['region']}\n"
                    f"Country: {loc['country']}\n"
                    f"Coordinates: {loc.get('lat')}, {loc.get('lon')}\n"
                    f"Timezone: {loc.get('timezone')}"
                )
                if open_in_browser and loc.get("lat") and loc.get("lon"):
                    map_url = f"https://www.google.com/maps?q={loc['lat']},{loc['lon']}"
                    try:
                        webbrowser.open(map_url)
                    except Exception:
                        pass
                return ToolResult(
                    name=self.name,
                    content=summary,
                    is_error=False,
                    safety_level=self.safety_level,
                )
            else:
                return ToolResult(
                    name=self.name,
                    content="Could not determine approximate location via network IP.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        elif act == "search_maps":
            q = (query or "").strip()
            if not q:
                url = "https://maps.google.com"
                msg = "Opened Google Maps in your browser."
            else:
                encoded = urllib.parse.quote_plus(q)
                url = f"https://www.google.com/maps/search/{encoded}"
                msg = f"Searching Google Maps for '{q}' in your browser."

            if open_in_browser:
                try:
                    webbrowser.open(url)
                except Exception as e:
                    return ToolResult(
                        name=self.name,
                        content=f"Failed to open Google Maps: {e}",
                        is_error=True,
                        safety_level=self.safety_level,
                    )

            return ToolResult(
                name=self.name,
                content=f"{msg}\nMap URL: {url}",
                is_error=False,
                safety_level=self.safety_level,
            )

        elif act == "directions":
            dest = (destination or query or "").strip()
            if not dest:
                return ToolResult(
                    name=self.name,
                    content="Error: 'destination' is required to get directions.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            encoded_dest = urllib.parse.quote_plus(dest)
            if origin.strip():
                encoded_orig = urllib.parse.quote_plus(origin.strip())
                url = f"https://www.google.com/maps/dir/{encoded_orig}/{encoded_dest}"
                msg = f"Opened directions from '{origin}' to '{dest}' in Google Maps."
            else:
                url = f"https://www.google.com/maps/dir//{encoded_dest}"
                msg = f"Opened directions to '{dest}' in Google Maps."

            if open_in_browser:
                try:
                    webbrowser.open(url)
                except Exception as e:
                    return ToolResult(
                        name=self.name,
                        content=f"Failed to open directions: {e}",
                        is_error=True,
                        safety_level=self.safety_level,
                    )

            return ToolResult(
                name=self.name,
                content=f"{msg}\nRoute URL: {url}",
                is_error=False,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Unknown action '{action}'. Supported actions: current_location, search_maps, directions.",
            is_error=True,
            safety_level=self.safety_level,
        )
