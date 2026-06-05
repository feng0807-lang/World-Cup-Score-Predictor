"""World Cup score & tournament predictor — command line interface.

Examples
--------
    # Predict a single match
    python predict.py match Argentina France

    # Predict using custom Elo numbers
    python predict.py match Brazil Spain --elo-home 2055 --elo-away 2050

    # Simulate the whole tournament (10k runs) and rank title chances
    python predict.py simulate --runs 10000

    # Use your own data file
    python predict.py simulate --data data_sample.json
"""

from __future__ import annotations

import argparse
import sys

from model import predict_match
from tournament import run_simulation
import teams as teams_mod


def _pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def cmd_match(args: argparse.Namespace, elo: dict[str, int]) -> int:
    import secure
    eh = round(secure.trained_elo(args.home))
    ea = round(secure.trained_elo(args.away))
    p = predict_match(args.home, args.away)
    print(f"\n  {args.home}  (Elo {eh})   vs   {args.away}  (Elo {ea})")
    print("  " + "-" * 48)
    print(f"  Expected score : {p.expected_score[0]} - {p.expected_score[1]}")
    ml = p.most_likely_score
    print(f"  Most likely    : {ml[0]} - {ml[1]}")
    print()
    print(f"  {args.home} win : {_pct(p.p_home_win)}")
    print(f"  Draw          : {_pct(p.p_draw)}")
    print(f"  {args.away} win : {_pct(p.p_away_win)}")
    print("\n  Most probable scorelines:")
    for (i, j), prob in p.top_scorelines(6):
        print(f"     {i}-{j}   {_pct(prob)}")
    print()
    return 0


def cmd_simulate(args: argparse.Namespace, elo: dict[str, int],
                 groups: dict[str, list[str]]) -> int:
    if not groups:
        print("No group structure available. Provide one via --data (see data_sample.json).")
        return 1
    print(f"\n  Simulating {args.runs:,} tournaments...\n")
    results = run_simulation(groups, None, n=args.runs, seed=args.seed)
    ranked = sorted(results.items(), key=lambda kv: kv[1]["champion"], reverse=True)

    print(f"  {'Team':<18}{'R32':>8}{'R16':>8}{'QF':>8}{'SF':>8}{'Final':>8}{'WINNER':>9}")
    print("  " + "-" * 67)
    for team, probs in ranked:
        print(f"  {team:<18}{_pct(probs['round32'])}{_pct(probs['round16'])}{_pct(probs['quarter'])}"
              f"{_pct(probs['semi'])}{_pct(probs['final'])}{_pct(probs['champion'])}")
    print(f"\n  Predicted champion: {ranked[0][0]} "
          f"({_pct(ranked[0][1]['champion'])} of simulations)\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="World Cup football score predictor")
    parser.add_argument("--data", help="JSON file with custom 'elo' and 'groups'")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("match", help="predict a single match")
    m.add_argument("home")
    m.add_argument("away")

    s = sub.add_parser("simulate", help="Monte-Carlo simulate the tournament")
    s.add_argument("--runs", type=int, default=10000)
    s.add_argument("--seed", type=int, default=None)

    args = parser.parse_args(argv)

    if args.data:
        elo, groups = teams_mod.load_teams_json(args.data)
    else:
        elo, groups = teams_mod.ELO, teams_mod.GROUPS

    if args.command == "match":
        return cmd_match(args, elo)
    if args.command == "simulate":
        return cmd_simulate(args, elo, groups)
    return 1


if __name__ == "__main__":
    sys.exit(main())
