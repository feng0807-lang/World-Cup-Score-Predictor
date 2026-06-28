"""Official 2026 World Cup knockout bracket (fetched from ESPN once the group
stage completed). The R32 matchups are the real draw; the *_MAP tables encode
how each round feeds the next (1-indexed slots into the previous round's
winners), taken from ESPN's bracket placeholders
("Round of 32 N Winner vs Round of 32 M Winner").

Team names are normalised to teams.py / squads.json.
"""

from __future__ import annotations

# Round of 32 in official slot order (ESPN match-number / event-id order).
R32 = [
    ("South Africa", "Canada"),                 # 1
    ("Brazil", "Japan"),                         # 2
    ("Netherlands", "Morocco"),                  # 3
    ("Germany", "Paraguay"),                     # 4
    ("Ivory Coast", "Norway"),                   # 5
    ("Mexico", "Ecuador"),                       # 6
    ("France", "Sweden"),                        # 7
    ("Belgium", "Senegal"),                      # 8
    ("United States", "Bosnia and Herzegovina"), # 9
    ("England", "DR Congo"),                     # 10
    ("Portugal", "Croatia"),                     # 11
    ("Spain", "Austria"),                        # 12
    ("Switzerland", "Algeria"),                  # 13
    ("Australia", "Egypt"),                      # 14
    ("Argentina", "Cape Verde"),                 # 15
    ("Colombia", "Ghana"),                       # 16
]

# Each later round: list of (slotA, slotB), 1-indexed into the previous round's
# winners. From ESPN's R16/QF/SF/Final placeholder fixtures.
R16_MAP = [(1, 3), (2, 5), (4, 6), (7, 8), (11, 12), (9, 10), (13, 15), (14, 16)]
QF_MAP = [(1, 2), (5, 6), (3, 4), (7, 8)]
SF_MAP = [(1, 2), (3, 4)]
FINAL_MAP = [(1, 2)]

ROUNDS = [
    ("Round of 16", R16_MAP),
    ("Quarter-finals", QF_MAP),
    ("Semi-finals", SF_MAP),
    ("Final", FINAL_MAP),
]
