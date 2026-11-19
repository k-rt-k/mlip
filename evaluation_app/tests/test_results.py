"""Field-study results use participants, not offers, as comparison units."""

import pytest

from evaluation_app.results import analyze


def export_fixture():
    return {
        "sessions": [
            {"id": "live", "rehearsal": 0, "setup": "paired", "arms": ["retrieval", "llm"],
             "started_at": "2026-11-19T00:00:00+00:00", "finished_at": "2026-11-19T00:05:00+00:00",
             "rating": 4, "comments": None},
            {"id": "practice", "rehearsal": 1, "setup": "paired", "arms": ["retrieval", "playlist_search"],
             "started_at": "2026-11-19T00:00:00+00:00", "finished_at": "2026-11-19T00:01:00+00:00",
             "rating": None, "comments": None},
            {"id": "unfinished", "rehearsal": 0, "setup": "paired", "arms": ["llm", "retrieval"],
             "started_at": "2026-11-19T00:00:00+00:00", "finished_at": None,
             "rating": None, "comments": None},
        ],
        "playlist": [
            {"session_id": "live", "recording": "same"},
            {"session_id": "live", "recording": "r3"},
        ],
        "rounds": [
            {"id": 1, "session_id": "live", "status": "complete", "mode": "text_only", "seed_count": 0},
            {"id": 2, "session_id": "live", "status": "complete", "mode": "text_and_playlist", "seed_count": 1},
            {"id": 3, "session_id": "practice", "status": "complete", "mode": "text_only", "seed_count": 0},
        ],
        "panels": [
            {"round_id": 1, "position": 0, "arm": "retrieval", "status": "ok", "elapsed_ms": 100},
            {"round_id": 1, "position": 1, "arm": "llm", "status": "ok", "elapsed_ms": 200},
            {"round_id": 2, "position": 0, "arm": "retrieval", "status": "ok", "elapsed_ms": 110},
            {"round_id": 2, "position": 1, "arm": "llm", "status": "unavailable", "elapsed_ms": 45000},
            {"round_id": 3, "position": 0, "arm": "retrieval", "status": "ok", "elapsed_ms": 100},
            {"round_id": 3, "position": 1, "arm": "playlist_search", "status": "ok", "elapsed_ms": 200},
        ],
        "offers": [
            {"round_id": 1, "position": 0, "rank": 1, "recording": "same", "decision": "keep", "play_clicks": 1},
            {"round_id": 1, "position": 0, "rank": 2, "recording": "r2", "decision": None, "play_clicks": 0},
            {"round_id": 1, "position": 1, "rank": 1, "recording": "same", "decision": "keep", "play_clicks": 0},
            {"round_id": 1, "position": 1, "rank": 2, "recording": "b2", "decision": "reject", "play_clicks": 1},
            {"round_id": 2, "position": 0, "rank": 1, "recording": "r3", "decision": "keep", "play_clicks": 0},
            {"round_id": 3, "position": 0, "rank": 1, "recording": "r4", "decision": None, "play_clicks": 0},
            {"round_id": 3, "position": 1, "rank": 1, "recording": "b4", "decision": None, "play_clicks": 0},
        ],
        "checkpoints": [{"session_id": "live", "round_id": 1, "rating": 3}],
        "participant_arm_summary": [],
    }


def test_paired_metric_uses_only_shared_eligible_rounds():
    result = analyze(export_fixture())
    assert result["screening"] == {"sessions": 3, "included": 1, "other_cohort": 1,
                                    "manual": 0, "incomplete": 1, "no_paired_rounds": 0}
    row = result["participants"][0]
    assert row["paired_rounds"] == 1
    assert row["retrieval"]["shown"] == row["baseline_stats"]["shown"] == 2
    assert row["retrieval"]["kept"] == row["baseline_stats"]["kept"] == 1
    assert row["retrieval"]["undecided"] == row["baseline_stats"]["rejected"] == 1
    assert row["delta_keep_rate"] == 0
    assert row["overlap_recordings"] == 1
    assert row["all_rounds"]["retrieval"]["shown"] == 3
    assert row["all_rounds"]["llm"]["unavailable_panels"] == 1
    assert row["round_five_rating"] == 3
    assert row["duration_seconds"] == 300
    assert row["final_playlist_size"] == 2
    assert row["mode_results"]["text_only"]["retrieval"]["shown"] == 2
    assert row["mode_results"]["text_and_playlist"]["paired_rounds"] == 0
    assert result["by_baseline"]["llm"]["participants"] == 1
    assert result["by_baseline"]["llm"]["mean_retrieval_keep_rate"] == 0.5
    assert result["by_baseline"]["llm"]["mean_baseline_keep_rate"] == 0.5


def test_rehearsal_is_explicit_cohort():
    result = analyze(export_fixture(), cohort="rehearsal")
    assert [row["session_id"] for row in result["participants"]] == ["practice"]
    assert result["by_baseline"]["playlist_search"]["participants"] == 1


def test_session_with_no_eligible_comparison_is_screened_out():
    data = export_fixture()
    data["offers"] = [row for row in data["offers"] if row["round_id"] != 1]
    result = analyze(data)
    assert result["screening"]["included"] == 0
    assert result["screening"]["no_paired_rounds"] == 1
    assert result["by_baseline"]["llm"]["mean_participant_delta"] is None


def test_invalid_panel_arm_is_rejected():
    data = export_fixture()
    data["panels"][0]["arm"] = "playlist_search"
    with pytest.raises(ValueError, match="panel arm"):
        analyze(data)


def test_pair_without_retrieval_is_rejected():
    data = export_fixture()
    data["sessions"][0]["arms"] = ["llm", "playlist_search"]
    with pytest.raises(ValueError, match="Invalid arms"):
        analyze(data)


def test_mirrored_decisions_must_agree():
    data = export_fixture()
    data["offers"][2]["decision"] = "reject"
    with pytest.raises(ValueError, match="Mirrored decision"):
        analyze(data)
