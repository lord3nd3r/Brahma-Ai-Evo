"""Units preference: locale default, persistence, and weather formatting."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from core import units


def test_no_locale_defaults_to_imperial(monkeypatch):
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MEASUREMENT", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.setattr(units.locale, "getlocale", lambda: (None, None))
    assert units.locale_default_units() == "imperial"


def test_en_us_defaults_to_imperial(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(units.locale, "getlocale", lambda: ("en_US", "UTF-8"))
    assert units.locale_default_units() == "imperial"
    assert units.locale_default_units(["English_United States"]) == "imperial"


def test_non_us_locale_defaults_to_metric(monkeypatch):
    for key in ("LANG", "LC_ALL", "LC_MEASUREMENT", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    monkeypatch.setattr(units.locale, "getlocale", lambda: ("en_GB", "UTF-8"))
    assert units.locale_default_units() == "metric"
    assert units.locale_default_units(["de_DE"]) == "metric"


def test_saved_units_override_locale(monkeypatch):
    monkeypatch.setattr(units, "_read_saved_units", lambda: "metric")
    monkeypatch.setattr(units, "locale_default_units", lambda: "imperial")
    assert units.get_units() == "metric"

    monkeypatch.setattr(units, "_read_saved_units", lambda: None)
    assert units.get_units() == "imperial"


def test_set_units_persists(monkeypatch):
    stored = {}

    def _set(key, value):
        stored[key] = value

    monkeypatch.setattr("memory.config_manager.set_setting", _set)
    assert units.set_units("imperial") == "imperial"
    assert stored["units"] == "imperial"
    assert units.set_units("metric") == "metric"
    assert units.set_units("not-a-unit") == units.locale_default_units()


def test_conversions_and_spoken_labels():
    assert units.celsius_to_fahrenheit(0) == 32
    assert units.celsius_to_fahrenheit(100) == 212
    assert round(units.fahrenheit_to_celsius(32), 5) == 0
    assert units.format_temperature(26, units="imperial") == "79°F"
    assert units.format_temperature(26, units="metric") == "26°C"
    assert units.format_temperature(26, units="imperial", spoken=True) == "79 degrees Fahrenheit"
    assert units.format_temperature(26, units="metric", spoken=True) == "26 degrees Celsius"
    assert units.format_wind_kmh(16, units="imperial") == "10 mph"
    assert units.format_wind_kmh(16, units="imperial", spoken=True) == "10 miles per hour"
    assert units.format_wind_kmh(16, units="metric", spoken=True) == "16 kilometers per hour"
    assert units.format_distance_km(420, units="imperial") == "261 mi"
    assert "fahrenheit" in units.open_meteo_unit_query("imperial")
    assert "mph" in units.open_meteo_unit_query("imperial")
    assert "celsius" in units.open_meteo_unit_query("metric")
    assert "Fahrenheit" in units.prompt_clause("imperial")
    assert "Celsius" in units.prompt_clause("metric")


def test_weather_report_speaks_fahrenheit(monkeypatch):
    payload = {
        "current_condition": [{
            "temp_C": "26",
            "temp_F": "79",
            "weatherDesc": [{"value": "Sunny"}],
            "humidity": "55",
            "windspeedKmph": "16",
            "windspeedMiles": "10",
            "FeelsLikeC": "27",
            "FeelsLikeF": "81",
        }],
        "nearest_area": [{"areaName": [{"value": "Orlando"}]}],
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(units, "get_units", lambda: "imperial")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    from actions.weather_report import get_live_weather, weather_action

    weather = get_live_weather("Orlando")
    assert weather["temp"] == 79
    assert weather["temp_c"] == 26
    assert "°F" in weather["summary"]
    assert weather["wind"] == "10 mph"

    spoken = weather_action({"city": "Orlando"})
    assert "79 degrees Fahrenheit" in spoken
    assert "10 miles per hour" in spoken
    assert "Celsius" not in spoken


def test_daily_briefing_narrative_uses_saved_units(monkeypatch):
    monkeypatch.setattr(units, "get_units", lambda: "imperial")
    from actions import daily_briefing

    monkeypatch.setattr(daily_briefing, "_get_weather_intel", lambda city=None: {
        "status": "success",
        "city": "Orlando",
        "temp_c": 26,
        "temp": 79,
        "condition": "Sunny",
        "wind_spoken": "10 miles per hour",
    })
    monkeypatch.setattr(daily_briefing, "_get_calendar_intel", lambda: {"count": 0, "events": []})
    monkeypatch.setattr(daily_briefing, "_get_gmail_intel", lambda: {"configured": False, "count": 0})
    monkeypatch.setattr(daily_briefing, "_get_instagram_intel", lambda: {"configured": False, "count": 0})
    monkeypatch.setattr(daily_briefing, "_get_top_headlines", lambda **kwargs: [])

    _data, narrative = daily_briefing.compile_unified_briefing(city="Orlando")
    assert "79 degrees Fahrenheit" in narrative
    assert "Celsius" not in narrative


def test_open_meteo_requests_fahrenheit(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "current": {
                    "temperature_2m": 75.2,
                    "relative_humidity_2m": 40,
                    "wind_speed_10m": 8.4,
                    "weather_code": 0,
                }
            }).encode()

    def _urlopen(req, timeout=0):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(units, "get_units", lambda: "imperial")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    from actions.geospatial_globe import fetch_location_weather

    weather = fetch_location_weather(28.5, -81.3)
    assert "temperature_unit=fahrenheit" in captured["url"]
    assert "wind_speed_unit=mph" in captured["url"]
    assert weather["temperature"] == 75.2
    assert weather["temperature_unit"] == "F"
    assert weather["wind_unit"] == "mph"
    assert weather["temperature_c"] == pytest.approx(24.0, abs=0.2)
