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

# Club-based acclimatization: the average climate of where a squad's players
# actually play their club football (derived from each squad's club-country mix),
# NOT their nationality. A Senegalese or Brazilian star at a European club is
# acclimatized to temperate Europe (~20 C); only squads built on domestic/Gulf
# leagues stay hot (Qatar, Saudi Arabia, Egypt, Iran, Iraq, Jordan...).
CLUB_TEMP: dict[str, float] = {
    # mostly Europe-based -> temperate
    "England": 20, "Scotland": 19, "Germany": 20, "France": 21, "Spain": 24,
    "Portugal": 22, "Netherlands": 20, "Belgium": 21, "Croatia": 22,
    "Switzerland": 20, "Austria": 20, "Czechia": 20, "Norway": 19, "Sweden": 20,
    "Bosnia and Herzegovina": 21, "Cape Verde": 21, "DR Congo": 21, "Ghana": 21,
    "Senegal": 21, "Ivory Coast": 21, "Algeria": 22, "Morocco": 23, "Japan": 21,
    "South Korea": 23, "Curacao": 20, "Canada": 21, "Australia": 23,
    "New Zealand": 21, "Haiti": 22,
    # South / Central America (Europe + regional leagues) -> mild-warm
    "Brazil": 23, "Argentina": 22, "Uruguay": 23, "Colombia": 24, "Ecuador": 24,
    "Paraguay": 25, "Panama": 26, "Mexico": 24, "United States": 22,
    # domestic / Gulf-league heavy -> hot-acclimatized
    "Qatar": 38, "Saudi Arabia": 38, "Egypt": 30, "Iran": 31, "Iraq": 33,
    "Jordan": 34, "Uzbekistan": 28, "Tunisia": 25, "Turkey": 24,
    "South Africa": 22,
}
# Backwards-compatible alias.
ORIGIN_TEMP = CLUB_TEMP

# Real stadium name per host venue (FIFA uses generic names during the event).
STADIUM: dict[str, str] = {
    "Atlanta": "Mercedes-Benz Stadium",
    "Boston (Foxborough)": "Gillette Stadium",
    "Dallas (Arlington)": "AT&T Stadium",
    "Houston": "NRG Stadium",
    "Kansas City": "Arrowhead Stadium",
    "Los Angeles": "SoFi Stadium",
    "Miami": "Hard Rock Stadium",
    "New York/New Jersey": "MetLife Stadium",
    "Philadelphia": "Lincoln Financial Field",
    "San Francisco Bay": "Levi's Stadium",
    "Seattle": "Lumen Field",
    "Guadalajara": "Estadio Akron",
    "Mexico City": "Estadio Banorte",  # formerly Estadio Azteca, renamed for WC2026
    "Monterrey": "Estadio BBVA",
    "Toronto": "BMO Field",
    "Vancouver": "BC Place",
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
        out = {"available": True, "venue": venue, "stadium": STADIUM.get(venue),
               "temp": cur.get("temperature_2m"),
               "feelsLike": cur.get("apparent_temperature"),
               "humidity": cur.get("relative_humidity_2m"),
               "typical": typical, "live": True}
    except Exception as e:
        out = {"available": True, "venue": venue, "stadium": STADIUM.get(venue),
               "temp": typical, "feelsLike": typical, "humidity": None,
               "typical": typical, "live": False,
               "note": f"live fetch failed ({e}); using typical"}
    _weather_cache[venue] = (now, out)
    return out


def _eff_temp(weather: dict) -> float:
    """Use 'feels like' if available (captures humidity), else temperature."""
    return weather.get("feelsLike") or weather.get("temp") or weather.get("typical")


def climate_assessment(home: str, away: str, weather: dict) -> dict:
    """Club-acclimatization edge for a match at given weather.

    Compares each team's squad-club climate to the match conditions; the team
    whose players are acclimatized closer to the match temperature is favoured.
    """
    venue_temp = _eff_temp(weather)
    oh = CLUB_TEMP.get(home)
    oa = CLUB_TEMP.get(away)
    if oh is None or oa is None or venue_temp is None:
        return {"venueTemp": venue_temp, "deltaHome": 0.0, "deltaAway": 0.0,
                "homeClubTemp": oh, "awayClubTemp": oa,
                "homeMismatch": None, "awayMismatch": None}
    mh = abs(venue_temp - oh)
    ma = abs(venue_temp - oa)
    # Team with the smaller mismatch gains; opponent's larger mismatch helps you.
    dh = max(-WEATHER_CAP, min(WEATHER_CAP, WEATHER_ELO_PER_DEG * (ma - mh)))
    da = -dh
    return {"venueTemp": round(venue_temp, 1),
            "homeClubTemp": oh, "awayClubTemp": oa,
            "homeMismatch": round(mh, 1), "awayMismatch": round(ma, 1),
            "deltaHome": round(dh, 1), "deltaAway": round(da, 1)}
