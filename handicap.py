"""Asian Handicap cover probabilities from a scoreline grid.

Given the model's full scoreline distribution, compute — for each standard
handicap line (including quarter lines) — the probability the home side covers,
pushes, or loses, plus the *fair* (zero-vig) decimal odds for backing each side.
Pure math on the grid; no model internals exposed.
"""

from __future__ import annotations

# Home-team handicap lines to report.
LINES = [-2.5, -2.25, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0,
         0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]


def _simple_units(margin: float, h: float):
    """(win, loss) units for a home backer on a whole/half line."""
    adj = margin + h
    if adj > 0:
        return 1.0, 0.0
    if adj < 0:
        return 0.0, 1.0
    return 0.0, 0.0  # push (only on whole lines)


def _units(margin: int, h: float):
    """(win, loss) units for any line; quarter lines split into two halves."""
    if abs((h * 2) - round(h * 2)) > 1e-9:   # quarter line (…25/.75)
        w1, l1 = _simple_units(margin, h - 0.25)
        w2, l2 = _simple_units(margin, h + 0.25)
        return (w1 + w2) / 2, (l1 + l2) / 2
    return _simple_units(margin, h)


def cover_table(grid: dict) -> dict:
    """Per-line home/away cover probabilities + fair odds, plus the fair line."""
    supremacy = sum(p * (i - j) for (i, j), p in grid.items())
    rows = []
    even_line = None
    for h in LINES:
        A = B = push = 0.0           # A = home win-units, B = home loss-units
        win_any = 0.0
        for (i, j), p in grid.items():
            w, l = _units(i - j, h)
            A += p * w; B += p * l; push += p * (1 - w - l)
            if w > 0:
                win_any += p
        fair_home = round(1 + B / A, 2) if A > 1e-9 else None
        fair_away = round(1 + A / B, 2) if B > 1e-9 else None
        rows.append({"line": h, "homeCover": round(A, 3), "push": round(push, 3),
                     "awayCover": round(B, 3), "fairHome": fair_home,
                     "fairAway": fair_away, "homeWinAny": round(win_any, 3)})
        if even_line is None and A <= 0.5:
            even_line = h
    return {"supremacy": round(supremacy, 2),
            "fairLine": round(-supremacy * 2) / 2,   # ~pick'em line for the home team
            "lines": rows}
