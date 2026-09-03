"""Weather Tool using the Open-Meteo free API for real-time weather and forecasts."""

from __future__ import annotations

from typing import Any

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.builtin.location_maps import get_current_approximate_location

logger = get_logger("tools.weather")

_TIMEOUT = 10.0

# WMO Weather interpretation codes (WW)
WMO_CODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def geocode_city(city_name: str) -> tuple[float, float, str] | None:
    """Resolve city name to (lat, lon, resolved_name) using Open-Meteo geocoding."""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_name.strip()}&count=1&language=en&format=json"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results")
                if results and len(results) > 0:
                    r = results[0]
                    name = f"{r.get('name')}, {r.get('country', '')}".strip(", ")
                    return float(r["latitude"]), float(r["longitude"]), name
    except Exception as e:
        logger.warning(f"Geocoding failed for '{city_name}': {e}")
    return None


class WeatherTool(BaseTool):
    """Query current weather, temperature, rain chance, and forecast for any city or current location."""

    name = "get_weather"
    description = (
        "Get current weather conditions, temperature, humidity, wind speed, "
        "and precipitation forecast for any city, or the user's current location."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name (e.g. 'Hyderabad', 'London', 'New York'). If omitted, uses current location.",
            },
        },
        "required": [],
    }

    def execute(self, city: str | None = None, **kwargs: Any) -> ToolResult:
        location_name = ""
        lat: float | None = None
        lon: float | None = None

        if city and city.strip():
            geo = geocode_city(city.strip())
            if geo:
                lat, lon, location_name = geo
            else:
                return ToolResult(
                    name=self.name,
                    content=f"Could not find coordinates for city '{city}'. Please verify spelling.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
        else:
            # Current location fallback
            approx = get_current_approximate_location()
            if approx.get("lat") and approx.get("lon"):
                lat = float(approx["lat"])
                lon = float(approx["lon"])
                location_name = f"{approx.get('city')}, {approx.get('region')}"
            else:
                # Default fallback if offline / unknown: Hyderabad
                lat, lon = 17.3850, 78.4867
                location_name = "Hyderabad (Default)"

        # Fetch from Open-Meteo
        api_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&"
            f"daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&"
            f"timezone=auto"
        )

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
                data = resp.json()

            current = data.get("current", {})
            daily = data.get("daily", {})

            temp_c = current.get("temperature_2m", 0.0)
            temp_f = round((temp_c * 9 / 5) + 32, 1)
            feels_c = current.get("apparent_temperature", temp_c)
            humidity = current.get("relative_humidity_2m", 0)
            wind_kmh = current.get("wind_speed_10m", 0.0)
            wmo_code = current.get("weather_code", 0)
            condition = WMO_CODE_MAP.get(wmo_code, "Partly Cloudy")

            # Daily rain chance & high/low
            rain_chance = 0
            if daily.get("precipitation_probability_max"):
                rain_chance = daily["precipitation_probability_max"][0] or 0
            max_c = daily.get("temperature_2m_max", [temp_c])[0]
            min_c = daily.get("temperature_2m_min", [temp_c])[0]

            rain_summary = "Rain is unlikely today." if rain_chance < 25 else f"Chance of rain today: {rain_chance}%."

            report = (
                f"Weather for {location_name}:\n"
                f"• Condition: {condition}\n"
                f"• Temperature: {temp_c}°C ({temp_f}°F) — Feels like {feels_c}°C\n"
                f"• High / Low: {max_c}°C / {min_c}°C\n"
                f"• Humidity: {humidity}%\n"
                f"• Wind Speed: {wind_kmh} km/h\n"
                f"• Precipitation: {rain_summary}"
            )

            return ToolResult(
                name=self.name,
                content=report,
                is_error=False,
                safety_level=self.safety_level,
            )

        except Exception as e:
            logger.error(f"Weather lookup failed: {e}")
            return ToolResult(
                name=self.name,
                content=f"Unable to retrieve weather forecast at this time: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
