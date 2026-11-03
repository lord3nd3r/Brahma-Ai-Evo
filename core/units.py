"""User-facing temperature, wind, and distance units.

``app_settings.json`` stores ``units`` as ``"imperial"`` or ``"metric"``.
A saved value always wins. When the key is absent, ``en_US`` / any ``*_US``
locale (and a missing or C/POSIX locale) defaults to imperial. Every other
locale defaults to metric.
"""

from __future__ import annotations

import locale
import os
from typing import Any

IMPERIAL = "imperial"
METRIC = "metric"

_KMH_TO_MPH = 0.621371192
_KM_TO_MILES = 0.621371192


def normalize_units(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {IMPERIAL, "us", "fahrenheit", "f"}:
        return IMPERIAL
    if text in {METRIC, "si", "celsius", "c"}:
        return METRIC
    return None


def _locale_tags() -> list[str]:
    tags: list[str] = []
    for key in ("LC_ALL", "LC_MEASUREMENT", "LANG", "LANGUAGE"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        # LANGUAGE can be a colon-separated preference list.
        for part in raw.split(":"):
            token = part.split(".")[0].strip()
            if token:
                tags.append(token)
    try:
        language, _encoding = locale.getlocale()
    except Exception:
        language = None
    if language:
        tags.append(language)
    return tags


def _is_us_locale(tag: str) -> bool:
    compact = tag.strip().lower().replace(" ", "").replace("-", "_")
    if not compact or compact in {"c", "posix"}:
        return False
    if compact == "en_us" or compact.startswith("en_us"):
        return True
    if compact.endswith("_us") or "unitedstates" in compact:
        return True
    return False


def locale_default_units(tags: list[str] | None = None) -> str:
    """Imperial for a US locale or no locale; metric for everything else."""
    found = tags if tags is not None else _locale_tags()
    meaningful = [
        tag for tag in found
        if tag and tag.strip().lower().split(".")[0] not in {"c", "posix"}
    ]
    if not meaningful:
        return IMPERIAL
    for tag in meaningful:
        if _is_us_locale(tag):
            return IMPERIAL
    return METRIC


def _read_saved_units() -> str | None:
    try:
        from memory.config_manager import get_setting
        return normalize_units(get_setting("units", None))
    except Exception:
        return None


def get_units() -> str:
    saved = _read_saved_units()
    if saved:
        return saved
    return locale_default_units()


def set_units(value: Any) -> str:
    """Persist a user override. Invalid values fall back to the locale default."""
    chosen = normalize_units(value) or locale_default_units()
    from memory.config_manager import set_setting
    set_setting("units", chosen)
    return chosen


def is_imperial(units: str | None = None) -> bool:
    mode = normalize_units(units) if units is not None else get_units()
    return mode == IMPERIAL


def celsius_to_fahrenheit(celsius: float) -> float:
    return float(celsius) * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (float(fahrenheit) - 32.0) * 5.0 / 9.0


def kmh_to_mph(kmh: float) -> float:
    return float(kmh) * _KMH_TO_MPH


def mph_to_kmh(mph: float) -> float:
    return float(mph) / _KMH_TO_MPH


def km_to_miles(km: float) -> float:
    return float(km) * _KM_TO_MILES


def miles_to_km(miles: float) -> float:
    return float(miles) / _KM_TO_MILES


def temperature_symbol(units: str | None = None) -> str:
    return "°F" if is_imperial(units) else "°C"


def spoken_temperature_name(units: str | None = None) -> str:
    return "degrees Fahrenheit" if is_imperial(units) else "degrees Celsius"


def spoken_wind_name(units: str | None = None) -> str:
    return "miles per hour" if is_imperial(units) else "kilometers per hour"


def wind_symbol(units: str | None = None) -> str:
    return "mph" if is_imperial(units) else "km/h"


def distance_symbol(units: str | None = None) -> str:
    return "mi" if is_imperial(units) else "km"


def display_temperature(celsius: float, units: str | None = None, digits: int = 0) -> float:
    value = celsius_to_fahrenheit(celsius) if is_imperial(units) else float(celsius)
    return round(value, digits)


def format_temperature(
    celsius: float | None,
    *,
    units: str | None = None,
    spoken: bool = False,
    digits: int = 0,
) -> str:
    if celsius is None:
        return f"--{temperature_symbol(units)}"
    number = display_temperature(celsius, units, digits)
    rendered = f"{number:.{digits}f}" if digits else f"{int(number)}"
    if spoken:
        return f"{rendered} {spoken_temperature_name(units)}"
    return f"{rendered}{temperature_symbol(units)}"


def format_wind_kmh(
    kmh: float | None,
    *,
    units: str | None = None,
    spoken: bool = False,
    digits: int = 0,
) -> str:
    if kmh is None:
        return f"-- {wind_symbol(units)}"
    value = kmh_to_mph(kmh) if is_imperial(units) else float(kmh)
    rendered = f"{round(value, digits):.{digits}f}" if digits else f"{int(round(value))}"
    if spoken:
        return f"{rendered} {spoken_wind_name(units)}"
    return f"{rendered} {wind_symbol(units)}"


def format_distance_km(
    km: float | None,
    *,
    units: str | None = None,
    spoken: bool = False,
    digits: int = 0,
) -> str:
    if km is None:
        return f"-- {distance_symbol(units)}"
    value = km_to_miles(km) if is_imperial(units) else float(km)
    rendered = f"{round(value, digits):.{digits}f}" if digits else f"{int(round(value))}"
    if spoken:
        word = "miles" if is_imperial(units) else "kilometers"
        return f"{rendered} {word}"
    return f"{rendered} {distance_symbol(units)}"


def open_meteo_unit_query(units: str | None = None) -> str:
    if is_imperial(units):
        return "temperature_unit=fahrenheit&wind_speed_unit=mph"
    return "temperature_unit=celsius&wind_speed_unit=kmh"


def prompt_clause(units: str | None = None) -> str:
    if is_imperial(units):
        return (
            "MEASUREMENT UNITS: The user prefers imperial units. "
            "State temperatures as degrees Fahrenheit, wind as miles per hour, "
            "and distances as miles. Do not use Celsius or kilometers unless the user asks."
        )
    return (
        "MEASUREMENT UNITS: The user prefers metric units. "
        "State temperatures as degrees Celsius, wind as kilometers per hour, "
        "and distances as kilometers."
    )
