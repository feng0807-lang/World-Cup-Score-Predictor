"""Update each team's starting XI in squads.json from their most recent ESPN
match roster, so predictions for upcoming matches use the real lineups (and the
form delta, which averages over starters, reflects who actually plays).

- Walks every WC date up to today, keeping the most recent completed match per team.
- Matches ESPN starters to existing squad players by fuzzy name; sets starter flags.
- Adds ESPN starters not already in the squad (neutral rating = team starter avg,
  so effective Elo isn't distorted), updates jersey numbers and positions.
- Preserves existing player ratings and the squad's base_avg reference.

Run:  python update_lineups.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import form
import squads as squads_mod

NAME_SIM_THRESHOLD = 0.60


def _espn_pos_to_squad(pos: str | None) -> str:
    """Map an ESPN position abbreviation (G, CD, CM, CF, ...) to GK/DEF/MID/FWD."""
    if not pos:
        return "MID"
    p = pos.upper()
    if p.startswith("G"):
        return "GK"
    # Forwards: CF, ST, SS, LW, RW, F
    if p in ("F", "CF", "ST", "SS") or p.startswith(("LW", "RW", "FW")):
        return "FWD"
    # Defenders: CD, LB, RB, LWB, RWB, SW, D
    if p.startswith(("CD", "LB", "RB", "LWB", "RWB", "SW", "D")):
        return "DEF"
    # Midfield: CM, AM, DM, LM, RM, M
    if p.startswith(("CM", "AM", "DM", "LM", "RM", "M")):
        return "MID"
    return "MID"


def _collect_latest_rosters() -> dict[str, dict]:
    """team -> {'starters': [...], 'event': id} from each team's most recent match."""
    sess = form._session()
    today = datetime.utcnow()
    current = form.WC_START
    latest: dict[str, dict] = {}

    while current.date() <= today.date():
        date_str = current.strftime("%Y%m%d")
        try:
            events = form._events_for_date(sess, date_str)
        except Exception as e:
            print(f"  ! date {date_str}: {e}")
            current += timedelta(days=1)
            continue
        for ev in events:
            if ev["status"] != "STATUS_FULL_TIME":
                continue
            try:
                r = sess.get(f"{form.ESPN_SUMMARY}?event={ev['id']}", timeout=12)
                r.raise_for_status()
                rosters = r.json().get("rosters", [])
            except Exception as e:
                print(f"  ! event {ev['id']}: {e}")
                continue
            for rt in rosters:
                team = form._canonical_team(rt.get("team", {}).get("displayName", ""))
                starters = []
                for entry in rt.get("roster", []):
                    if not entry.get("starter"):
                        continue
                    ath = entry.get("athlete", {})
                    name = ath.get("displayName", "")
                    if not name:
                        continue
                    pos = entry.get("position") or {}
                    pos_abbr = pos.get("abbreviation") if isinstance(pos, dict) else pos
                    starters.append({
                        "name": name,
                        "number": int(entry.get("jersey") or 0),
                        "pos": _espn_pos_to_squad(pos_abbr),
                    })
                if len(starters) >= 7:  # sanity: a real XI
                    latest[team] = {"starters": starters, "event": ev["id"],
                                    "date": date_str}
        current += timedelta(days=1)
    return latest


def update_squads(squads=None, verbose=True):
    """Update every team's starting XI from its latest ESPN roster.

    If `squads` is passed (e.g. the server's in-memory dict) it is mutated in
    place so existing references stay valid. Returns a summary dict.
    """
    if squads is None:
        squads = squads_mod.load_squads()
    latest = _collect_latest_rosters()
    if verbose:
        print(f"\nFound recent rosters for {len(latest)} teams.\n")

    total_updated = 0
    unmatched_report = []

    incomplete = []
    for team, info in sorted(latest.items()):
        if team not in squads:
            if verbose:
                print(f"  ?? {team}: in ESPN but not in squads.json — skipped")
            continue
        squad = squads[team]
        players = squad["players"]
        starter_avg = (sum(p["rating"] for p in players if p.get("starter"))
                       / max(1, sum(1 for p in players if p.get("starter"))))
        neutral_rating = round(starter_avg)

        # Reset all to bench first
        for p in players:
            p["starter"] = False

        matched_ids = set()
        added = 0
        for st in info["starters"]:
            # Fuzzy match to an unused squad player
            best, best_sim = None, 0.0
            for p in players:
                if p["id"] in matched_ids:
                    continue
                sim = form._name_sim(st["name"], p["name"])
                if sim > best_sim:
                    best, best_sim = p, sim
            if best is not None and best_sim >= NAME_SIM_THRESHOLD:
                best["starter"] = True
                best["available"] = True
                if st["number"]:
                    best["number"] = st["number"]
                best["pos"] = st["pos"]
                matched_ids.add(best["id"])
            else:
                # New player not in squad — add at neutral rating
                new_id = max((p["id"] for p in players), default=-1) + 1
                players.append({
                    "id": new_id,
                    "number": st["number"],
                    "name": st["name"],
                    "pos": st["pos"],
                    "rating": neutral_rating,
                    "starter": True,
                    "available": True,
                })
                matched_ids.add(new_id)
                added += 1
                unmatched_report.append(f"{team}: +{st['name']} ({st['pos']}, best {best_sim:.2f})")

        n_start = sum(1 for p in players if p.get("starter"))
        eff = squads_mod.effective_elo(squad)
        if n_start != 11:
            incomplete.append(f"{team} ({n_start})")
        if verbose:
            flag = "" if n_start == 11 else f"  <-- {n_start} starters!"
            print(f"  {team:<24} XI set ({n_start}), +{added} new, eff Elo {eff}{flag}")
        total_updated += 1

    squads_mod.save_squads(squads)
    if verbose:
        print(f"\nUpdated {total_updated} teams. Saved squads.json.")
        if unmatched_report:
            print(f"\nNew players added ({len(unmatched_report)}):")
            for r in unmatched_report:
                print("  ", r)
    return {
        "teamsUpdated": total_updated,
        "rostersFound": len(latest),
        "newPlayers": unmatched_report,
        "incomplete": incomplete,
    }


def _collect_start_counts():
    """team -> {player_name: starts} across every completed match, plus the most
    recent number/pos seen for each player."""
    from collections import defaultdict
    sess = form._session()
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    meta: dict[str, dict[str, dict]] = defaultdict(dict)
    today = datetime.utcnow()
    cur = form.WC_START
    while cur.date() <= today.date():
        ds = cur.strftime("%Y%m%d")
        try:
            events = form._events_for_date(sess, ds)
        except Exception:
            cur += timedelta(days=1); continue
        for ev in events:
            if ev["status"] != "STATUS_FULL_TIME":
                continue
            try:
                rosters = sess.get(f"{form.ESPN_SUMMARY}?event={ev['id']}",
                                   timeout=12).json().get("rosters", [])
            except Exception:
                continue
            for rt in rosters:
                team = form._canonical_team(rt.get("team", {}).get("displayName", ""))
                for entry in rt.get("roster", []):
                    if not entry.get("starter"):
                        continue
                    nm = entry.get("athlete", {}).get("displayName", "")
                    if not nm:
                        continue
                    counts[team][nm] += 1
                    pos = entry.get("position") or {}
                    meta[team][nm] = {"number": int(entry.get("jersey") or 0),
                                      "pos": _espn_pos_to_squad(pos.get("abbreviation", ""))}
        cur += timedelta(days=1)
    return counts, meta


def set_first_xi(squads=None, verbose=True):
    """Set every team's starting XI to its FIRST-CHOICE eleven — the 11 players
    who started the most across the tournament — and reset base_avg so that XI
    reads as full strength (lineup delta 0). Run after group play to undo any
    dead-rubber rotation in the latest-match lineups."""
    if squads is None:
        squads = squads_mod.load_squads()
    counts, meta = _collect_start_counts()
    updated, added_rep = 0, []
    for team, sq in squads.items():
        cnt = counts.get(team)
        if not cnt:
            continue
        players = sq["players"]
        # the most-started 11 (tie-break: keep ESPN order stable)
        top11 = [nm for nm, _ in sorted(cnt.items(), key=lambda x: -x[1])[:11]]
        for p in players:
            p["starter"] = False
        starter_avg = (sum(p["rating"] for p in players) / max(1, len(players)))
        matched = set()
        for nm in top11:
            best, sim = None, 0.0
            for p in players:
                if p["id"] in matched:
                    continue
                s = form._name_sim(nm, p["name"])
                if s > sim:
                    best, sim = p, s
            m = meta[team].get(nm, {})
            if best is not None and sim >= NAME_SIM_THRESHOLD:
                best["starter"] = True
                best["available"] = True
                if m.get("number"):
                    best["number"] = m["number"]
                if m.get("pos"):
                    best["pos"] = m["pos"]
                matched.add(best["id"])
            else:
                nid = max((p["id"] for p in players), default=-1) + 1
                players.append({"id": nid, "number": m.get("number", 0), "name": nm,
                                "pos": m.get("pos", "MID"), "rating": round(starter_avg),
                                "starter": True, "available": True})
                matched.add(nid)
                added_rep.append(f"{team}: +{nm}")
        # rebaseline: the first XI is now full strength -> lineup delta 0
        starters = [p for p in players if p["starter"]]
        if starters:
            sq["base_avg"] = round(sum(p["rating"] for p in starters) / len(starters), 2)
        n = len(starters)
        if verbose:
            print(f"  {team:<24} first XI ({n}), eff Elo {squads_mod.effective_elo(sq)}"
                  + ("" if n == 11 else f"  <-- {n}!"))
        updated += 1
    squads_mod.save_squads(squads)
    if verbose:
        print(f"\nSet first XI for {updated} teams; new players: {len(added_rep)}")
    return {"teamsUpdated": updated, "newPlayers": added_rep}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "firstxi":
        set_first_xi()
    else:
        update_squads()
