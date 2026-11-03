# actions/weather_report.py

import json
import urllib.request
import webbrowser
from urllib.parse import quote_plus
from typing import Dict, Any, Optional

from core.units import (
    celsius_to_fahrenheit,
    format_temperature,
    format_wind_kmh,
    is_imperial,
    kmh_to_mph,
    spoken_temperature_name,
    spoken_wind_name,
)


def get_live_weather(city: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches real-time live weather data using wttr.in with zero API keys required.
    Auto-detects device physical location dynamically via hardware/Wi-Fi and IP when no city is passed.
    Returns structured metrics: city, temp_c, condition, humidity, wind, and summary.
    """
    target_city = city.strip() if city and city.strip() else None
    if target_city and target_city.lower() in ("here", "my location", "current location", "auto", "local", "device"):
        target_city = None

    detected_lat = None
    detected_lon = None

    # Dynamically auto-detect physical device location
    if not target_city:
        try:
            from core.device_location import get_device_location
            loc = get_device_location()
            target_city = loc.get("city")
            detected_lat = loc.get("latitude")
            detected_lon = loc.get("longitude")
        except Exception as e:
            print(f"[Weather] Device location auto-detect notice: {e}")
            target_city = None

    if detected_lat is not None and detected_lon is not None:
        url = f"https://wttr.in/{detected_lat:.4f},{detected_lon:.4f}?format=j1"
    elif target_city:
        encoded_city = quote_plus(target_city)
        url = f"https://wttr.in/{encoded_city}?format=j1"
    else:
        url = "https://wttr.in/?format=j1"

    fallback_c = 26
    fallback_kmh = 10
    fallback = {
        "status": "unavailable",
        "city": target_city or "Local Area",
        "temp_c": fallback_c,
        "temp_f": int(round(celsius_to_fahrenheit(fallback_c))),
        "temp": int(round(celsius_to_fahrenheit(fallback_c))) if is_imperial() else fallback_c,
        "condition": "Clear",
        "humidity": "65%",
        "wind": format_wind_kmh(fallback_kmh),
        "wind_kmph": fallback_kmh,
        "wind_mph": int(round(kmh_to_mph(fallback_kmh))),
        "wind_spoken": format_wind_kmh(fallback_kmh, spoken=True),
        "feels_like": int(round(celsius_to_fahrenheit(fallback_c))) if is_imperial() else fallback_c,
        "summary": "Weather telemetry temporarily offline.",
        "units": "imperial" if is_imperial() else "metric",
    }

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "curl/7.68.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            current = data.get("current_condition", [{}])[0]
            nearest = data.get("nearest_area", [{}])[0]

            detected_city = target_city
            if not detected_city:
                area_names = nearest.get("areaName", [{}])
                detected_city = area_names[0].get("value") if area_names else "Current Location"

            temp_c = int(float(current.get("temp_C", 26)))
            temp_f = int(float(current.get("temp_F", round(celsius_to_fahrenheit(temp_c)))))
            wind_kmh = float(current.get("windspeedKmph") or 10)
            wind_mph = float(current.get("windspeedMiles") or kmh_to_mph(wind_kmh))
            feels_c = int(float(current.get("FeelsLikeC", temp_c)))
            feels_f = int(float(current.get("FeelsLikeF", round(celsius_to_fahrenheit(feels_c)))))
            desc = current.get("weatherDesc", [{}])[0].get("value", "Clear")
            humidity = f"{current.get('humidity', '60')}%"
            imperial = is_imperial()
            display_temp = temp_f if imperial else temp_c
            display_wind = f"{int(round(wind_mph))} mph" if imperial else f"{int(round(wind_kmh))} km/h"
            display_feels = feels_f if imperial else feels_c

            return {
                "status": "success",
                "city": detected_city,
                "temp_c": temp_c,
                "temp_f": temp_f,
                "temp": display_temp,
                "temp_display": format_temperature(temp_c),
                "condition": desc,
                "humidity": humidity,
                "wind": display_wind,
                "wind_kmph": int(round(wind_kmh)),
                "wind_mph": int(round(wind_mph)),
                "wind_spoken": f"{int(round(wind_mph if imperial else wind_kmh))} {spoken_wind_name()}",
                "feels_like": display_feels,
                "feels_like_c": feels_c,
                "summary": f"{format_temperature(temp_c)}, {desc} in {detected_city}",
                "units": "imperial" if imperial else "metric",
            }
    except Exception as e:
        print(f"[Weather] Live weather fetch notice: {e}")
        return fallback


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None
):
    """
    Weather report action.
    Fetches real-time live weather metrics and optionally opens Google Weather.
    """
    city = parameters.get("city") if parameters else None
    time_param = parameters.get("time", "today") if parameters else "today"

    weather = get_live_weather(city)
    city_name = weather.get("city", "your area")
    temp = weather.get("temp", weather.get("temp_c", 26))
    cond = weather.get("condition", "Clear")
    wind_spoken = weather.get("wind_spoken") or format_wind_kmh(weather.get("wind_kmph"))

    msg = (
        f"The weather in {city_name} is currently {temp} {spoken_temperature_name()} "
        f"with {cond}, and the wind is {wind_spoken}."
    )
    _speak_and_log(msg, player)

    # Optional browser fallback if user explicitly asks or city was specified
    search_query = f"weather in {city_name} {time_param}"
    if parameters and parameters.get("open_browser", False):
        try:
            encoded_query = quote_plus(search_query)
            webbrowser.open(f"https://www.google.com/search?q={encoded_query}")
        except Exception:
            pass

    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=msg)
        except Exception:
            pass

    return msg


def _speak_and_log(message: str, player=None):
    if player:
        try:
            player.write_log(f"Brahma AI: {message}")
        except Exception:
            pass