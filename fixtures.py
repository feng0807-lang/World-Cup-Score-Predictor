"""Official 2026 FIFA World Cup group-stage schedule (72 matches).

Each fixture: group, date, home, away, and the host venue (a key into
climate.VENUES / climate.STADIUM, so weather + stadium resolve automatically).
Team names and venue keys are normalised to match teams.py and climate.py.
"""

from __future__ import annotations

import climate as climate_mod

# group, date, home, away, venue-key
FIXTURES: list[tuple[str, str, str, str, str]] = [
    # Group A
    ("A", "Jun 11", "Mexico", "South Africa", "Mexico City"),
    ("A", "Jun 11", "South Korea", "Czechia", "Guadalajara"),
    ("A", "Jun 18", "Czechia", "South Africa", "Atlanta"),
    ("A", "Jun 18", "Mexico", "South Korea", "Guadalajara"),
    ("A", "Jun 24", "Czechia", "Mexico", "Mexico City"),
    ("A", "Jun 24", "South Africa", "South Korea", "Monterrey"),
    # Group B
    ("B", "Jun 12", "Canada", "Bosnia and Herzegovina", "Toronto"),
    ("B", "Jun 12", "Qatar", "Switzerland", "San Francisco Bay"),
    ("B", "Jun 18", "Switzerland", "Bosnia and Herzegovina", "Los Angeles"),
    ("B", "Jun 18", "Canada", "Qatar", "Vancouver"),
    ("B", "Jun 24", "Switzerland", "Canada", "Vancouver"),
    ("B", "Jun 24", "Bosnia and Herzegovina", "Qatar", "Seattle"),
    # Group C
    ("C", "Jun 13", "Brazil", "Morocco", "New York/New Jersey"),
    ("C", "Jun 13", "Haiti", "Scotland", "Boston (Foxborough)"),
    ("C", "Jun 19", "Scotland", "Morocco", "Boston (Foxborough)"),
    ("C", "Jun 19", "Brazil", "Haiti", "Philadelphia"),
    ("C", "Jun 24", "Scotland", "Brazil", "Miami"),
    ("C", "Jun 24", "Morocco", "Haiti", "Atlanta"),
    # Group D
    ("D", "Jun 12", "United States", "Paraguay", "Los Angeles"),
    ("D", "Jun 13", "Australia", "Turkey", "Vancouver"),
    ("D", "Jun 19", "United States", "Australia", "Seattle"),
    ("D", "Jun 19", "Turkey", "Paraguay", "San Francisco Bay"),
    ("D", "Jun 25", "Turkey", "United States", "Los Angeles"),
    ("D", "Jun 25", "Paraguay", "Australia", "San Francisco Bay"),
    # Group E  (CUR-ECU / venue corrected from a source swap with Group F)
    ("E", "Jun 14", "Germany", "Curacao", "Houston"),
    ("E", "Jun 14", "Ivory Coast", "Ecuador", "Philadelphia"),
    ("E", "Jun 20", "Ecuador", "Curacao", "Houston"),
    ("E", "Jun 20", "Germany", "Ivory Coast", "Toronto"),
    ("E", "Jun 25", "Ecuador", "Germany", "New York/New Jersey"),
    ("E", "Jun 25", "Curacao", "Ivory Coast", "Philadelphia"),
    # Group F
    ("F", "Jun 14", "Netherlands", "Japan", "Dallas (Arlington)"),
    ("F", "Jun 14", "Sweden", "Tunisia", "Monterrey"),
    ("F", "Jun 20", "Netherlands", "Sweden", "Kansas City"),
    ("F", "Jun 20", "Tunisia", "Japan", "Monterrey"),
    ("F", "Jun 25", "Japan", "Sweden", "Dallas (Arlington)"),
    ("F", "Jun 25", "Tunisia", "Netherlands", "Kansas City"),
    # Group G
    ("G", "Jun 15", "Belgium", "Egypt", "Vancouver"),
    ("G", "Jun 15", "Iran", "New Zealand", "Los Angeles"),
    ("G", "Jun 21", "Belgium", "Iran", "Los Angeles"),
    ("G", "Jun 21", "New Zealand", "Egypt", "Vancouver"),
    ("G", "Jun 26", "Egypt", "Iran", "Seattle"),
    ("G", "Jun 26", "New Zealand", "Belgium", "Vancouver"),
    # Group H
    ("H", "Jun 15", "Spain", "Cape Verde", "Atlanta"),
    ("H", "Jun 15", "Saudi Arabia", "Uruguay", "Miami"),
    ("H", "Jun 21", "Spain", "Saudi Arabia", "Atlanta"),
    ("H", "Jun 21", "Uruguay", "Cape Verde", "Miami"),
    ("H", "Jun 26", "Cape Verde", "Saudi Arabia", "Houston"),
    ("H", "Jun 26", "Uruguay", "Spain", "Guadalajara"),
    # Group I
    ("I", "Jun 16", "France", "Senegal", "New York/New Jersey"),
    ("I", "Jun 16", "Iraq", "Norway", "Boston (Foxborough)"),
    ("I", "Jun 22", "France", "Iraq", "Philadelphia"),
    ("I", "Jun 22", "Norway", "Senegal", "New York/New Jersey"),
    ("I", "Jun 26", "Norway", "France", "Boston (Foxborough)"),
    ("I", "Jun 26", "Senegal", "Iraq", "Toronto"),
    # Group J
    ("J", "Jun 16", "Argentina", "Algeria", "Kansas City"),
    ("J", "Jun 16", "Austria", "Jordan", "San Francisco Bay"),
    ("J", "Jun 22", "Argentina", "Austria", "Dallas (Arlington)"),
    ("J", "Jun 22", "Jordan", "Algeria", "San Francisco Bay"),
    ("J", "Jun 27", "Algeria", "Austria", "Kansas City"),
    ("J", "Jun 27", "Jordan", "Argentina", "Dallas (Arlington)"),
    # Group K
    ("K", "Jun 17", "Portugal", "DR Congo", "Houston"),
    ("K", "Jun 17", "Uzbekistan", "Colombia", "Mexico City"),
    ("K", "Jun 23", "Portugal", "Uzbekistan", "Houston"),
    ("K", "Jun 23", "Colombia", "DR Congo", "Guadalajara"),
    ("K", "Jun 26", "Colombia", "Portugal", "Miami"),
    ("K", "Jun 27", "DR Congo", "Uzbekistan", "Atlanta"),
    # Group L
    ("L", "Jun 17", "England", "Croatia", "Dallas (Arlington)"),
    ("L", "Jun 17", "Ghana", "Panama", "Toronto"),
    ("L", "Jun 23", "England", "Ghana", "Boston (Foxborough)"),
    ("L", "Jun 23", "Panama", "Croatia", "Toronto"),
    ("L", "Jun 27", "Panama", "England", "New York/New Jersey"),
    ("L", "Jun 27", "Croatia", "Ghana", "Philadelphia"),
]


def all_fixtures() -> list[dict]:
    """Fixtures as dicts, with the resolved stadium name for each venue."""
    return [{"group": g, "date": d, "home": h, "away": a, "venue": v,
             "stadium": climate_mod.STADIUM.get(v, v)}
            for (g, d, h, a, v) in FIXTURES]
