"""Match-context factors derived from data we already have: rest days between
matches, and venue altitude. Both produce a small Elo adjustment per team.

Rest:    fewer days since a team's last match = fatigue. The differential (one
         side more rested than the other) is what moves the line — decisive in
         the knockouts where rest gaps open up.
Altitude: at the high Mexican venues (Mexico City ~2240 m, Guadalajara ~1566 m)
         non-acclimatised teams tire; sides that habitually play at altitude
         (Mexico) don't. Low US/Canada venues (<400 m) have no effect.

Everything is computed from live.results() (match dates) and the venue table, so
no external data is needed.
"""

from __future__ import annotations

from datetime import datetime

import live as live_mod

# Venue altitude in metres. Only the high ones matter; every US/Canada host is
# under ~400 m (negligible), so they're treated as sea level.
ALTITUDE_M = {
    "Mexico City": 2240,
    "Guadalajara": 1566,
    "Monterrey": 540,
}
ALT_THRESHOLD_M = 1200          # below this altitude has no meaningful effect
ALT_PENALTY = 18.0             # Elo penalty for a non-acclimatised team up high
ACCLIMATISED = {"Mexico"}     # nations that habitually play at altitude

REST_ELO_PER_DAY = 4.0        # Elo per day of rest advantage over the opponent
REST_DIFF_CAP_DAYS = 6        # ignore differentials beyond this many days
REST_MAX = 24.0               # cap on the rest Elo swing


def _team_match_dates(team: str) -> list[datetime]:
    out = []
    for r in live_mod.results():
        if team in (r.get("home"), r.get("away")):
            try:
                out.append(datetime.fromisoformat(r["ts"]))
            except (ValueError, TypeError, KeyError):
                pass
    return sorted(out)


def rest_days(team: str, as_of: datetime) -> int | None:
    """Days since the team's most recent match strictly before `as_of`."""
    prior = [d for d in _team_match_dates(team) if d < as_of]
    if not prior:
        return None
    return (as_of - prior[-1]).days


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%b %d %Y", "%b %d"):
        try:
            d = datetime.strptime(date_str, fmt)
            if d.year == 1900:                   # "Jun 20" with no year
                d = d.replace(year=2026)
            return d
        except ValueError:
            continue
    return None


def context_delta(home: str, away: str, venue: str | None = None,
                  match_date=None) -> dict:
    """Return rest/altitude Elo deltas plus a human-readable breakdown.

    {'home': float, 'away': float, 'restHome': int|None, 'restAway': int|None,
     'altitude': int, 'notes': [...]}
    """
    md = match_date if isinstance(match_date, datetime) else _parse_date(match_date)
    dh = da = 0.0
    notes: list[str] = []
    rh = ra = None

    if md is not None:
        rh, ra = rest_days(home, md), rest_days(away, md)
        if rh is not None and ra is not None:
            diff = max(-REST_DIFF_CAP_DAYS, min(REST_DIFF_CAP_DAYS, rh - ra))
            swing = max(-REST_MAX, min(REST_MAX, REST_ELO_PER_DAY * diff))
            dh += swing / 2.0
            da -= swing / 2.0
            if abs(swing) >= 4:
                more, less = (home, away) if rh > ra else (away, home)
                notes.append(f"{more} {abs(rh-ra)}d more rest than {less}")

    alt = ALTITUDE_M.get(venue or "", 0)
    if alt >= ALT_THRESHOLD_M:
        if home not in ACCLIMATISED:
            dh -= ALT_PENALTY
        if away not in ACCLIMATISED:
            da -= ALT_PENALTY
        notes.append(f"altitude {alt} m at {venue}")

    return {"home": round(dh, 1), "away": round(da, 1),
            "restHome": rh, "restAway": ra, "altitude": alt, "notes": notes}
