"""Tests for review/decision parsing and pre/post PDF selection (no network)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reviews import (  # noqa: E402
    classify_replies,
    parse_score,
    rating_history,
    review_record,
    select_pre_post,
)


def note(id, invitation, tcdate, forum="F", **content):
    return SimpleNamespace(id=id, invitation=invitation, tcdate=tcdate, forum=forum,
                           content=content, signatures=[f"~{id}"])


def row(rev_id, tcdate, pdf):
    return {"rev_id": rev_id, "tcdate": tcdate, "pdf": pdf, "iso_date": str(tcdate)}


class TestClassifyReplies:
    def test_v1_iclr2017_names(self):
        replies = [
            note("F", "ICLR.cc/2017/conference/-/submission", 1),
            note("r1", "ICLR.cc/2017/conference/-/paper1/official/review", 10, rating="7: Good"),
            note("c1", "ICLR.cc/2017/conference/-/paper1/public/comment", 11),
            note("d1", "ICLR.cc/2017/conference/-/paper1/acceptance", 20, decision="Reject"),
        ]
        out = classify_replies(replies, submission_id="F")
        assert [n.id for n in out["reviews"]] == ["r1"]
        assert out["decision"].id == "d1"

    def test_v2_names_and_meta_review_excluded(self):
        replies = [
            note("r1", "V/Submission1/-/Official_Review", 10),
            note("m1", "V/Submission1/-/Meta_Review", 15),
            note("d1", "V/Submission1/-/Decision", 20),
        ]
        out = classify_replies(replies, submission_id="F")
        assert [n.id for n in out["reviews"]] == ["r1"]
        assert out["decision"].id == "d1"

    def test_no_decision(self):
        out = classify_replies([note("r1", "V/-/review", 10)], submission_id="F")
        assert out["decision"] is None

    def test_iclr2019_meta_review_is_the_decision_when_no_decision_note(self):
        replies = [note("r1", "V/-/Paper1/Official_Review", 10),
                   note("m1", "V/-/Paper1/Meta_Review", 20, recommendation="Accept (Poster)")]
        out = classify_replies(replies, submission_id="F")
        assert out["decision"].id == "m1"
        assert [n.id for n in out["reviews"]] == ["r1"]

    def test_v2_notes_carry_invitations_list_not_invitation(self):
        v2 = lambda id, inv, t: SimpleNamespace(id=id, invitations=[inv, "V/-/Edit"], tcdate=t,
                                                forum="F", content={}, signatures=[])
        replies = [v2("r1", "V/Submission1/-/Official_Review", 10),
                   v2("d1", "V/Submission1/-/Decision", 20)]
        out = classify_replies(replies, submission_id="F")
        assert [n.id for n in out["reviews"]] == ["r1"]
        assert out["decision"].id == "d1"

    def test_iclr2020_layout_paper_group_before_dash(self):
        replies = [note("r1", "V/Paper7/-/Official_Review", 10),
                   note("m1", "V/Paper7/-/Meta_Review", 15),
                   note("d1", "V/Paper7/-/Decision", 20)]
        out = classify_replies(replies, submission_id="F")
        assert out["decision"].id == "d1"


class TestSelectPrePost:
    # window_start = reviews released (or review deadline); decision = notification.
    def test_pre_is_first_pdf_post_is_last_in_window(self):
        rows = [row("a", 1, "/a"), row("b", 5, "/b"), row("c", 15, "/c"), row("d", 30, "/d")]
        sel = select_pre_post(rows, window_start=10, decision=20)
        assert sel["pre"]["rev_id"] == "a"
        assert sel["post"]["rev_id"] == "c"
        assert sel["n_pdfs_before_decision"] == 3
        assert sel["n_in_window"] == 1
        assert sel["n_camera_ready"] == 1

    def test_none_when_only_pre_review_self_revisions(self):
        rows = [row("a", 1, "/a"), row("b", 5, "/b"), row("d", 30, "/d")]
        assert select_pre_post(rows, window_start=10, decision=20) is None

    def test_none_when_no_revision_before_decision(self):
        rows = [row("a", 1, "/a"), row("d", 30, "/d")]
        assert select_pre_post(rows, window_start=10, decision=20) is None

    def test_none_when_thresholds_missing(self):
        rows = [row("a", 1, "/a"), row("b", 15, "/b")]
        assert select_pre_post(rows, window_start=None, decision=20) is None
        assert select_pre_post(rows, window_start=10, decision=None) is None

    def test_rows_without_pdf_ignored(self):
        rows = [row("a", 1, "/a"), row("x", 12, None), row("b", 15, "/b")]
        sel = select_pre_post(rows, window_start=10, decision=20)
        assert sel["post"]["rev_id"] == "b"

    def test_same_pdf_path_is_not_a_revision(self):
        rows = [row("a", 1, "/a"), row("b", 15, "/a")]
        assert select_pre_post(rows, window_start=10, decision=20) is None

    def test_window_start_is_inclusive(self):
        rows = [row("a", 1, "/a"), row("b", 10, "/b")]
        assert select_pre_post(rows, window_start=10, decision=20)["post"]["rev_id"] == "b"


class TestScores:
    def test_parse_v1_string(self):
        assert parse_score("7: Good paper, accept") == 7

    def test_parse_v2_wrapped(self):
        assert parse_score({"value": 8}) == 8
        assert parse_score({"value": "3: reject"}) == 3

    def test_parse_missing(self):
        assert parse_score(None) is None
        assert parse_score("n/a") is None

    def test_rating_history_from_revision_rows(self):
        rows = [
            {"rev_id": "e1", "tcdate": 1, "iso_date": "d1", "rating": "5: ok", "confidence": "3: x"},
            {"rev_id": "e2", "tcdate": 2, "iso_date": "d2", "rating": "7: good", "confidence": "3: x"},
        ]
        hist = rating_history(rows)
        assert [h["rating"] for h in hist] == [5, 7]
        assert hist[0]["iso_date"] == "d1"

    def test_review_record_shape(self):
        r = note("r1", "V/-/review", 10, rating="6: ok", confidence="4: c")
        rec = review_record(r, history=[{"rating": 6, "iso_date": "d"}])
        assert rec["review_id"] == "r1"
        assert rec["rating"] == 6 and rec["confidence"] == 4
        assert rec["rating_first"] == 6 and rec["rating_last"] == 6
        assert rec["rating_changed"] is False
