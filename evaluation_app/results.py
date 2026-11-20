"""Summarize exported study events at the participant level.

Run ``python -m evaluation_app.results --help``. The paired keep-rate difference
is retrieval minus its assigned baseline, using only rounds where both panels
were available and showed at least one song. Rehearsals are a separate cohort.
"""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
from random import Random
from statistics import mean, median

from .backends import TOP_K


TABLES = ("sessions", "playlist", "rounds", "panels", "offers", "checkpoints")
ARMS = {"retrieval", "llm", "playlist_search"}
MODES = {"text_only", "text_and_playlist", "playlist_only"}
STATUSES = {"ok", "unavailable", "not_applicable"}


def _unique(rows, key, label):
    result = {}
    for row in rows:
        value = key(row)
        if value in result:
            raise ValueError(f"Duplicate {label}: {value}")
        result[value] = row
    return result


def _index(data):
    """Validate references before producing any metrics."""
    if not isinstance(data, dict) or any(not isinstance(data.get(table), list) for table in TABLES):
        raise ValueError("Expected a study export with sessions, rounds, panels, offers, and checkpoints lists.")
    sessions = _unique(data["sessions"], lambda r: r["id"], "session")
    playlist = _unique(data["playlist"], lambda r: (r["session_id"], r["recording"]), "playlist song")
    rounds = _unique(data["rounds"], lambda r: r["id"], "round")
    panels = _unique(data["panels"], lambda r: (r["round_id"], r["position"]), "panel")
    offers = _unique(data["offers"], lambda r: (r["round_id"], r["position"], r["rank"]), "offer")
    checkpoints = _unique(data["checkpoints"], lambda r: r["session_id"], "checkpoint")
    for session in sessions.values():
        arms = session["arms"]
        if (not isinstance(arms, list) or len(arms) not in (1, 2) or len(set(arms)) != len(arms)
                or not set(arms) <= ARMS or (session["setup"] == "paired") != (len(arms) == 2)
                or (session["setup"] == "paired" and "retrieval" not in arms)):
            raise ValueError(f"Invalid arms for session {session['id']}")
    for session_id, _ in playlist:
        if session_id not in sessions:
            raise ValueError(f"Playlist song belongs to unknown session {session_id}")
    for row in rounds.values():
        if row["session_id"] not in sessions or row["mode"] not in MODES:
            raise ValueError(f"Invalid round {row['id']}")
    for key, panel in panels.items():
        round_row = rounds.get(panel["round_id"])
        if round_row is None or round_row["status"] != "complete":
            raise ValueError(f"Panel {key} has no complete round")
        arms = sessions[round_row["session_id"]]["arms"]
        if panel["position"] not in range(len(arms)) or panel["arm"] != arms[panel["position"]]:
            raise ValueError(f"Invalid panel arm or position for {key}")
        if panel["status"] not in STATUSES:
            raise ValueError(f"Invalid panel status for {key}")
    for key, offer in offers.items():
        panel = panels.get(key[:2])
        if panel is None or panel["status"] != "ok" or not 1 <= offer["rank"] <= TOP_K:
            raise ValueError(f"Invalid offer location or rank: {key}")
        if offer["decision"] not in (None, "keep", "reject") or offer["play_clicks"] < 0:
            raise ValueError(f"Invalid offer feedback: {key}")
    for session_id, checkpoint in checkpoints.items():
        if session_id not in sessions or checkpoint["round_id"] not in rounds:
            raise ValueError(f"Invalid checkpoint for {session_id}")
        if rounds[checkpoint["round_id"]]["session_id"] != session_id:
            raise ValueError(f"Checkpoint belongs to another session: {session_id}")
    by_round = {}
    for row in data["panels"]:
        by_round.setdefault(row["round_id"], []).append(row)
    by_panel = {}
    for row in data["offers"]:
        by_panel.setdefault((row["round_id"], row["position"]), []).append(row)
    for key, rows in by_panel.items():
        recordings = [row["recording"] for row in rows]
        if len(recordings) != len(set(recordings)):
            raise ValueError(f"Repeated recording in panel {key}")
    for round_id, panel_rows in by_round.items():
        decisions = {}
        for panel in panel_rows:
            for offer in by_panel.get((round_id, panel["position"]), []):
                old = decisions.setdefault(offer["recording"], offer["decision"])
                if old != offer["decision"]:
                    raise ValueError(f"Mirrored decision differs in round {round_id}")
    return sessions, playlist, rounds, by_round, by_panel, checkpoints


def _counts():
    return {"shown": 0, "kept": 0, "rejected": 0, "undecided": 0,
            "play_clicks": 0, "empty_slots": 0, "ok_panels": 0,
            "unavailable_panels": 0, "not_applicable_panels": 0}


def _add(counts, panel, offers):
    status = panel["status"]
    counts[status + "_panels"] += 1
    counts["shown"] += len(offers)
    counts["kept"] += sum(row["decision"] == "keep" for row in offers)
    counts["rejected"] += sum(row["decision"] == "reject" for row in offers)
    counts["undecided"] += sum(row["decision"] is None for row in offers)
    counts["play_clicks"] += sum(row["play_clicks"] for row in offers)
    if status == "ok":
        counts["empty_slots"] += TOP_K - len(offers)


def _rates(counts):
    shown = counts["shown"]
    judged = counts["kept"] + counts["rejected"]
    return {**counts, "keep_rate": counts["kept"] / shown if shown else None,
            "judged_fraction": judged / shown if shown else None,
            "keep_among_judged": counts["kept"] / judged if judged else None}


def _interval(values):
    """Percentile bootstrap at participant level; suppress for a tiny pilot."""
    if len(values) < 10:
        return None
    rng = Random(718)
    draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(5000))
    return [draws[124], draws[4874]]


def analyze(data, *, cohort="live"):
    """Return privacy-conscious participant rows and baseline summaries."""
    if cohort not in ("live", "rehearsal"):
        raise ValueError("Cohort must be live or rehearsal.")
    sessions, playlist, rounds, by_round, by_panel, checkpoints = _index(data)
    screening = {"sessions": len(sessions), "included": 0, "other_cohort": 0,
                 "manual": 0, "incomplete": 0, "no_paired_rounds": 0}
    participants = []
    for session in sessions.values():
        if bool(session["rehearsal"]) != (cohort == "rehearsal"):
            screening["other_cohort"] += 1
            continue
        if session["setup"] != "paired":
            screening["manual"] += 1
            continue
        if not session["finished_at"]:
            screening["incomplete"] += 1
            continue
        arms = session["arms"]
        baseline = next(arm for arm in arms if arm != "retrieval")
        all_counts = {arm: _counts() for arm in arms}
        paired_counts = {arm: _counts() for arm in arms}
        modes = dict.fromkeys(sorted(MODES), 0)
        mode_counts = {mode: {arm: _counts() for arm in arms} for mode in MODES}
        overlap = paired_rounds = 0
        session_rounds = [r for r in rounds.values() if r["session_id"] == session["id"]
                          and r["status"] == "complete"]
        for round_row in session_rounds:
            round_id = round_row["id"]
            panels = sorted(by_round.get(round_id, []), key=lambda p: p["position"])
            if len(panels) != 2:
                raise ValueError(f"Completed paired round {round_id} lacks two panels")
            for panel in panels:
                _add(all_counts[panel["arm"]], panel, by_panel.get((round_id, panel["position"]), []))
            if all(panel["status"] == "ok" and by_panel.get((round_id, panel["position"]))
                   for panel in panels):
                paired_rounds += 1
                modes[round_row["mode"]] += 1
                recordings = []
                for panel in panels:
                    offers = by_panel[(round_id, panel["position"])]
                    _add(paired_counts[panel["arm"]], panel, offers)
                    _add(mode_counts[round_row["mode"]][panel["arm"]], panel, offers)
                    recordings.append({offer["recording"] for offer in offers})
                overlap += len(recordings[0] & recordings[1])
        if not paired_rounds:
            screening["no_paired_rounds"] += 1
            continue
        screening["included"] += 1
        paired = {arm: _rates(counts) for arm, counts in paired_counts.items()}
        duration = (datetime.fromisoformat(session["finished_at"])
                    - datetime.fromisoformat(session["started_at"])).total_seconds()
        participants.append({
            "session_id": session["id"], "baseline": baseline,
            "panel_a": arms[0], "panel_b": arms[1], "rounds": len(session_rounds),
            "paired_rounds": paired_rounds, "paired_modes": modes,
            "mode_results": {
                mode: {"paired_rounds": modes[mode],
                       "retrieval": _rates(counts["retrieval"]),
                       "baseline": _rates(counts[baseline])}
                for mode, counts in sorted(mode_counts.items())
            },
            "retrieval": paired["retrieval"], "baseline_stats": paired[baseline],
            "delta_keep_rate": paired["retrieval"]["keep_rate"] - paired[baseline]["keep_rate"],
            "overlap_recordings": overlap,
            "all_rounds": {arm: _rates(counts) for arm, counts in all_counts.items()},
            "duration_seconds": duration,
            "final_playlist_size": sum(key[0] == session["id"] for key in playlist),
            "final_rating": session["rating"],
            "round_five_rating": checkpoints.get(session["id"], {}).get("rating"),
        })
    by_baseline = {}
    for baseline in ("llm", "playlist_search"):
        rows = [row for row in participants if row["baseline"] == baseline]
        deltas = [row["delta_keep_rate"] for row in rows]
        by_baseline[baseline] = {
            "participants": len(rows), "mean_participant_delta": mean(deltas) if deltas else None,
            "median_participant_delta": median(deltas) if deltas else None,
            "participant_delta_ci95": _interval(deltas),
            "mean_retrieval_keep_rate": mean(row["retrieval"]["keep_rate"] for row in rows) if rows else None,
            "mean_baseline_keep_rate": mean(row["baseline_stats"]["keep_rate"] for row in rows) if rows else None,
            "paired_rounds": sum(row["paired_rounds"] for row in rows),
            "retrieval_shown": sum(row["retrieval"]["shown"] for row in rows),
            "retrieval_kept": sum(row["retrieval"]["kept"] for row in rows),
            "baseline_shown": sum(row["baseline_stats"]["shown"] for row in rows),
            "baseline_kept": sum(row["baseline_stats"]["kept"] for row in rows),
        }
    return {"schema_version": 1, "cohort": cohort, "primary_metric":
            "mean of participant (retrieval keep/shown minus assigned baseline keep/shown) "
            "over rounds with at least one offer in both panels",
            "screening": screening, "by_baseline": by_baseline, "participants": participants}


def _participant_csv(path, rows):
    fields = ("session_id", "baseline", "panel_a", "panel_b", "rounds", "paired_rounds",
              "retrieval_shown", "retrieval_kept", "retrieval_keep_rate", "baseline_shown",
              "baseline_kept", "baseline_keep_rate", "delta_keep_rate", "overlap_recordings",
              "duration_seconds", "final_playlist_size", "final_rating", "round_five_rating")
    with path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{key: row.get(key) for key in fields},
                             "retrieval_shown": row["retrieval"]["shown"],
                             "retrieval_kept": row["retrieval"]["kept"],
                             "retrieval_keep_rate": row["retrieval"]["keep_rate"],
                             "baseline_shown": row["baseline_stats"]["shown"],
                             "baseline_kept": row["baseline_stats"]["kept"],
                             "baseline_keep_rate": row["baseline_stats"]["keep_rate"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON from evaluation_app --export")
    parser.add_argument("--output", type=Path, required=True, help="New metrics JSON; never overwrites")
    parser.add_argument("--participants-csv", type=Path, help="Optional participant-level CSV")
    parser.add_argument("--cohort", choices=("live", "rehearsal"), default="live")
    args = parser.parse_args()
    if args.participants_csv and args.output.resolve() == args.participants_csv.resolve():
        parser.error("Metrics JSON and participant CSV need different paths.")
    for path in (args.output, args.participants_csv):
        if path and path.exists():
            parser.error(f"Output already exists: {path}")
    try:
        result = analyze(json.loads(args.input.read_text(encoding="utf-8")), cohort=args.cohort)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(f"Invalid study export: {exc}")
    if not result["screening"]["sessions"]:
        parser.error("The export has no sessions. Check that --export used the same --db as the app.")
    for path in (args.output, args.participants_csv):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, ensure_ascii=False)
        output.write("\n")
    if args.participants_csv:
        _participant_csv(args.participants_csv, result["participants"])
    print(f"Included {result['screening']['included']} completed {args.cohort} paired sessions.")
    for arm, summary in result["by_baseline"].items():
        print(f"{arm}: n={summary['participants']}, mean paired keep-rate difference="
              f"{summary['mean_participant_delta']}")


if __name__ == "__main__":
    main()
