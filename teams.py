"""2026 FIFA World Cup teams: Elo ratings and the 12-group draw.

48 teams, 12 groups of four (hosts USA, Canada, Mexico). Final draw held
5 Dec 2025; playoff winners (Bosnia, Sweden, Turkey, Czechia via UEFA;
DR Congo, Iraq via the intercontinental playoffs) slotted in March 2026.

Elo ratings are an approximate strength snapshot — edit freely, or load your
own via a JSON file using `load_teams_json`.
"""

from __future__ import annotations

import json

# Approximate Elo ratings (higher = stronger) for all 48 finalists.
ELO: dict[str, int] = {
    # Group A
    "Mexico": 1810, "South Africa": 1730, "South Korea": 1790, "Czechia": 1800,
    # Group B
    "Canada": 1730, "Bosnia and Herzegovina": 1770, "Qatar": 1650, "Switzerland": 1870,
    # Group C
    "Brazil": 2040, "Morocco": 1900, "Haiti": 1620, "Scotland": 1790,
    # Group D
    "United States": 1820, "Paraguay": 1740, "Australia": 1740, "Turkey": 1840,
    # Group E
    "Germany": 1960, "Curacao": 1610, "Ivory Coast": 1770, "Ecuador": 1800,
    # Group F
    "Netherlands": 2000, "Japan": 1850, "Sweden": 1820, "Tunisia": 1700,
    # Group G
    "Belgium": 1970, "Egypt": 1770, "Iran": 1760, "New Zealand": 1620,
    # Group H
    "Spain": 2080, "Cape Verde": 1670, "Saudi Arabia": 1660, "Uruguay": 1935,
    # Group I
    "France": 2070, "Senegal": 1840, "Iraq": 1660, "Norway": 1890,
    # Group J
    "Argentina": 2100, "Algeria": 1780, "Austria": 1820, "Jordan": 1650,
    # Group K
    "Portugal": 2010, "DR Congo": 1740, "Uzbekistan": 1700, "Colombia": 1930,
    # Group L
    "England": 2030, "Croatia": 1945, "Ghana": 1720, "Panama": 1690,
}

# The official 12-group draw (groups A-L).
GROUPS: dict[str, list[str]] = {
    "A": ["Mexico", "South Africa", "South Korea", "Czechia"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curacao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}


def load_teams_json(path: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Load {"elo": {...}, "groups": {...}} from a JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["elo"], data.get("groups", {})
