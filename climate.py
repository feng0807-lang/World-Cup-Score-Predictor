"""Weather / acclimatization factor for World Cup 2026.

Idea: the 2026 host venues range from cool (Vancouver, Seattle) to very hot
(Monterrey, Dallas, Houston). A team acclimatized to conditions close to the
match-day weather has a small edge; a cool-climate team baking in 35 C heat is
at a disadvantage. We turn the climate mismatch into a small Elo-point delta
that feeds the existing prediction path (no model change needed).

Live weather comes from Open-Meteo (https://open-meteo.com) — free, no API key.
The effect is deliberately modest and tunable; weather is a minor signal.
"""

from __future__ import annotations

import json
import time
import urllib.request

# Elo points per 1 C of *relative* climate mismatch advantage. Small on purpose.
WEATHER_ELO_PER_DEG = 1.3
WEATHER_CAP = 35.0          # max |delta| from weather, in Elo points
CACHE_TTL = 1800            # cache live weather 30 min

# 2026 host cities: (latitude, longitude, typical June/July match temp C).
VENUES: dict[str, tuple[float, float, float]] = {
    "Atlanta":            (33.76, -84.40, 31),
    "Boston (Foxborough)":(42.09, -71.26, 26),
    "Dallas (Arlington)": (32.75, -97.08, 35),
    "Houston":            (29.68, -95.41, 34),
    "Kansas City":        (39.05, -94.48, 31),
    "Los Angeles":        (33.95, -118.34, 28),
    "Miami":              (25.96, -80.24, 32),
    "New York/New Jersey":(40.81, -74.07, 29),
    "Philadelphia":       (39.90, -75.17, 30),
    "San Francisco Bay":  (37.40, -121.97, 26),
    "Seattle":            (47.59, -122.33, 23),
    "Guadalajara":        (20.68, -103.46, 26),
    "Mexico City":        (19.30, -99.15, 24),
    "Monterrey":          (25.67, -100.24, 35),
    "Toronto":            (43.64, -79.39, 26),
    "Vancouver":          (49.28, -123.12, 22),
}

# Representative climate each team is acclimatized to (warm-season temp, C).
ORIGIN_TEMP: dict[str, float] = {
    "Argentina": 24, "Algeria": 33, "Australia": 28, "Austria": 24,
    "Belgium": 22, "Bosnia and Herzegovina": 27, "Brazil": 30, "Canada": 23,
    "Cape Verde": 27, "Colombia": 28, "Croatia": 28, "Curacao": 31,
    "Czechia": 23, "DR Congo": 30, "Ecuador": 24, "Egypt": 35, "England": 21,
    "France": 24, "Germany": 23, "Ghana": 31, "Haiti": 32, "Iran": 35,
    "Iraq": 42, "Ivory Coast": 31, "Japan": 30, "Jordan": 35, "Mexico": 28,
    "Morocco": 30, "Netherlands": 21, "New Zealand": 18, "Norway": 18,
    "Panama": 32, "Paraguay": 28, "Portugal": 30, "Qatar": 41, "Saudi Arabia": 40,
    "Scotland": 17, "Senegal": 31, "South Africa": 23, "South Korea": 29,
    "Spain": 32, "Sweden": 21, "Switzerland": 24, "Tunisia": 33, "Turkey": 31,
    "United States": 30, "Uruguay": 22, "Uzbekistan": 36,
}

_weather_cache: dict[str, tuple[float, dict]] = {}


def list_venues() -> list[str]:
    return list(VENUES.keys())


def live_weather(venue: str) -> dict:
    """Current temperature/humidity at a venue from Open-Meteo (cached)."""
    if venue not in VENUES:
        return {"available": False, "reason": "unknown_venue"}
    lat, lon, typical = VENUES[venue]
    now = time.time()
    if venue in _weather_cache and now - _weather_cache[venue][0] < CACHE_TTL:
        return _weather_cache[venue][1]
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&current=temperature_2m,relative_humidity_2m,apparent_temperature")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wc-predictor"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        cur = data.get("current", {})
        out = {"available": True, "venue": venue,
               "temp": cur.get("temperature_2m"),
               "feelsLike": cur.get("apparent_temperature"),
               "humidity": cur.get("relative_humidity_2m"),
               "typical": typical, "live": True}
    except Exception as e:
        out = {"available": True, "venue": venue, "temp": typical,
               "feelsLike": typical, "humidity": None, "typical": typical,
               "live": False, "note": f"live fetch failed ({e}); using typical"}
    _weather_cache[venue] = (now, out)
    return out


def _eff_temp(weather: dict) -> float:
    """Use 'feels like' if available (captures humidity), else temperature."""
    return weather.get("feelsLike") or weather.get("temp") or weather.get("typical")


def climate_assessment(home: str, away: str, weather: dict) -> dict:
    """Climate-mismatch edge for a match at given weather.

    Returns each team's mismatch vs the conditions and the resulting Elo-point
    deltas (the team closer to the match temperature is favoured).
    """
    venue_temp = _eff_temp(weather)
    oh = ORIGIN_TEMP.get(home)
    oa = ORIGIN_TEMP.get(away)
    if oh is None or oa is None or venue_temp is None:
        return {"venueTemp": venue_temp, "deltaHome": 0.0, "deltaAway": 0.0,
                "homeOrigin": oh, "awayOrigin": oa,
                "homeMismatch": None, "awayMismatch": None}
    mh = abs(venue_temp - oh)
    ma = abs(venue_temp - oa)
    # Team with the smaller mismatch gains; opponent's larger mismatch helps you.
    dh = max(-WEATHER_CAP, min(WEATHER_CAP, WEATHER_ELO_PER_DEG * (ma - mh)))
    da = -dh
    return {"venueTemp": round(venue_temp, 1),
            "homeOrigin": oh, "awayOrigin": oa,
            "homeMismatch": round(mh, 1), "awayMismatch": round(ma, 1),
            "deltaHome": round(dh, 1), "deltaAway": round(da, 1)}
