"""Tests for venue deadline parsing and merging (no network; HTML snippets inline)."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venue_dates import (  # noqa: E402
    MILESTONES,
    iso,
    load_thresholds,
    merge_sources,
    milestone_for_label,
    parse_archive_2017,
    parse_cfp_page,
    parse_date_token,
    parse_dates_page,
    parse_prose_date,
)


def utc(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


class TestMilestoneForLabel:
    def test_submission(self):
        assert milestone_for_label("Paper Submission deadline") == "submission"
        assert milestone_for_label("Paper Submission Deadline") == "submission"

    def test_abstract_and_workshop_excluded(self):
        assert milestone_for_label("Abstract Submission Deadline") is None
        assert milestone_for_label("Workshop Submission Deadline") is None
        assert milestone_for_label("Supplementary Material Submission Deadline") is None

    def test_reviews_released_variants(self):
        assert milestone_for_label("Paper Reviews Released") == "reviews_released"
        assert milestone_for_label("Paper Rebuttal/discussion begins") == "reviews_released"
        assert milestone_for_label("Public/ Author/ Reviewer/ A C- Discussion  Starts") == "reviews_released"

    def test_rebuttal_end_requires_author_or_rebuttal(self):
        assert milestone_for_label("Paper Rebuttal/discussion ends") == "rebuttal_end"
        assert milestone_for_label("Author/ Reviewer/ A C- Discussion Period Ends") == "rebuttal_end"
        assert milestone_for_label("Reviewer/ A C- Discussion Period Ends") is None

    def test_decision(self):
        assert milestone_for_label("Paper Decision Notification") == "decision"
        assert milestone_for_label("Workshop Decision Notification") is None
        assert milestone_for_label("Volunteer Application Notification") is None

    def test_review_due(self):
        assert milestone_for_label("Review Period Ends") == "review_due"
        assert milestone_for_label("Paper Review Period") == "review_due"
        assert milestone_for_label("Review Deadline") == "review_due"
        assert milestone_for_label("Reviews  Due") == "review_due"

    def test_review_period_opens_and_meta_final_are_not_review_due(self):
        assert milestone_for_label("Review Period Opens") is None
        assert milestone_for_label("Review  Period  Begins") is None
        assert milestone_for_label("Meta  Reviews  Due") is None
        assert milestone_for_label("Final  Reviews  Due") is None

    def test_2025_labels(self):
        assert milestone_for_label("Full  Paper  Submission  Deadline") == "submission"
        assert milestone_for_label("Discussion  Period  Starts") == "reviews_released"
        assert milestone_for_label("Discussion  Period  Ends") == "rebuttal_end"
        assert milestone_for_label("Last  Day  Authors  Can  Respond") == "rebuttal_end"

    def test_tiny_papers_excluded(self):
        assert milestone_for_label("Tiny Papers Submission Deadline") is None
        assert milestone_for_label("Tiny Paper Notification") is None


class TestRanking:
    # ICLR 2023 lists a bare "Submission Deadline" (a side track) before the real one.
    HTML = """
    <span>Submission Deadline</span><span>Feb 02 '23 (Anywhere on Earth)</span>
    <span>Decision notification</span><span>Mar 31 '23 (Anywhere on Earth)</span>
    <span>Paper Submission deadline</span><span>Sep 28 '22 (Anywhere on Earth)</span>
    <span>Paper Decision Notification</span><span>Jan 21 '23 02:00 AM UTC</span>
    """

    def test_paper_prefixed_label_beats_bare_label_regardless_of_order(self):
        out = parse_dates_page(self.HTML)
        assert iso(out["submission"]).startswith("2022-09-29")
        assert iso(out["decision"]).startswith("2023-01-21")

    def test_bare_label_used_when_no_paper_label(self):
        html = "<span>Decision notification</span><span>Mar 31 '23 (Anywhere on Earth)</span>"
        assert iso(parse_dates_page(html)["decision"]).startswith("2023-04-01")


class TestParseDateToken:
    def test_explicit_timezone(self):
        assert parse_date_token("Oct 27 '17 02:00 PM PDT") == utc(2017, 10, 27, 21, 0)
        assert parse_date_token("Mar 20 '24 11:00 AM UTC") == utc(2024, 3, 20, 11, 0)

    def test_anywhere_on_earth_is_end_of_day_utc_minus_12(self):
        assert parse_date_token("Sep 28 '23 (Anywhere on Earth)") == utc(2023, 9, 29, 11, 59, 59)

    def test_garbage_is_none(self):
        assert parse_date_token("Successful Page Load") is None


class TestParseDatesPage:
    HTML = """
    <div><span>Paper Submission deadline</span><span>Oct 27 '17 02:00 PM PDT</span>
    <span>Paper Review Period</span><span>Nov 27 '17 02:00 PM PST</span>
    <span>Paper Rebuttal/discussion begins</span><span>Nov 27 '17 02:00 PM PST</span>
    <span>Paper Rebuttal/discussion ends</span><span>Jan 05 '18 02:00 PM PST</span>
    <span>Paper Decision Notification</span><span>Jan 29 '18 02:00 PM PST</span>
    <span>Workshop Submission Deadline</span><span>Feb 12 '18 02:00 PM PST</span></div>
    """

    def test_extracts_all_conference_milestones(self):
        out = parse_dates_page(self.HTML)
        assert out["submission"] == utc(2017, 10, 27, 21, 0)
        assert out["review_due"] == utc(2017, 11, 27, 22, 0)
        assert out["reviews_released"] == utc(2017, 11, 27, 22, 0)
        assert out["rebuttal_end"] == utc(2018, 1, 5, 22, 0)
        assert out["decision"] == utc(2018, 1, 29, 22, 0)

    def test_first_match_wins(self):
        html = self.HTML + "<span>Paper Decision Notification</span><span>Mar 01 '18 02:00 PM PST</span>"
        assert parse_dates_page(html)["decision"] == utc(2018, 1, 29, 22, 0)


class TestParseArchive2017:
    TEXT = ("Conference Track Submission Deadline: 5:00pm Eastern Daylight Time (EDT), "
            "November 4th 5th, 2016 Review Period: until December 16nd, 2016 "
            "Rebuttal/discussion: December 17th, 2016 to January 20th, 2017 "
            "Decision Notification: February 6th, 2017 Workshop Track Submission Deadline: "
            "5:00pm Eastern Daylight Time (EDT), February 17th, 2017")

    def test_conference_track_only(self):
        out = parse_archive_2017(self.TEXT)
        # Submission: 5pm EDT on the last listed day. Others: Anywhere-on-Earth
        # end of day (UTC-12), so the UTC instant is 11:59 the next morning.
        assert iso(out["submission"]) == "2016-11-05T21:00:00+00:00"
        assert iso(out["review_due"]) == "2016-12-17T11:59:00+00:00"
        assert iso(out["reviews_released"]) == "2016-12-17T12:00:00+00:00"
        assert iso(out["rebuttal_end"]) == "2017-01-21T11:59:00+00:00"
        assert iso(out["decision"]) == "2017-02-07T11:59:00+00:00"
        assert "workshop" not in str(out)


class TestParseProseDate:
    def test_formats_with_year(self):
        assert iso(parse_prose_date("4 November 2019.", 2020)).startswith("2019-11-05T11:59:59")
        assert iso(parse_prose_date("Nov 09, 2021", 2022)).startswith("2021-11-10T11:59:59")
        assert iso(parse_prose_date("Jan 15 2024", 2024)).startswith("2024-01-16T11:59:59")
        assert iso(parse_prose_date("December 22, 2018", 2019)).startswith("2018-12-23T11:59:59")

    def test_missing_year_inferred_from_cycle(self):
        # Sep-Dec belong to the year before the conference, Jan-Aug to the conference year.
        assert iso(parse_prose_date("Nov 4", 2023)).startswith("2022-11-05")
        assert iso(parse_prose_date("Jan 20", 2023)).startswith("2023-01-21")

    def test_range_takes_the_end(self):
        assert iso(parse_prose_date("Nov 10-22", 2024)).startswith("2023-11-23")

    def test_start_of_day_option(self):
        assert iso(parse_prose_date("Nov 10", 2024, end_of_day=False)) == "2023-11-10T12:00:00+00:00"

    def test_garbage(self):
        assert parse_prose_date("the submission system", 2024) is None


class TestParseCfpPage:
    def test_2020_style(self):
        html = """<p>Submission date: 25 September 2019, 6pm EAT (East Africa Time, UTC+3).</p>
        <p>Reviews released: 4 November 2019.</p><p>Author discussion period ends: 15 November 2019</p>
        <p>Final decisions: 19 December 2019</p>"""
        out = parse_cfp_page(html, 2020)
        assert iso(out["submission"]).startswith("2019-09-26")
        assert iso(out["reviews_released"]).startswith("2019-11-04T12:00")
        assert iso(out["rebuttal_end"]).startswith("2019-11-16")
        assert iso(out["decision"]).startswith("2019-12-20")

    def test_2024_style_range_and_no_year(self):
        html = """<li>Submission date: 11:59pm, Sept 28</li><li>Reviews released: Nov 10</li>
        <li>Author/Reviewer Discussion: Nov 10-22</li><li>Final decisions: Jan 15 2024</li>"""
        out = parse_cfp_page(html, 2024)
        assert iso(out["submission"]).startswith("2023-09-29")
        assert iso(out["reviews_released"]).startswith("2023-11-10T12:00")
        assert iso(out["rebuttal_end"]).startswith("2023-11-23")
        assert iso(out["decision"]).startswith("2024-01-16")

    def test_2019_prose(self):
        html = """<p>The paper submission deadline is September 27, 2018 - 6:00 pm EDT.</p>
        <p>On December 22, 2018, authors will be notified about the acceptance or rejection of their paper.</p>"""
        out = parse_cfp_page(html, 2019)
        assert iso(out["submission"]).startswith("2018-09-28")
        assert iso(out["decision"]).startswith("2018-12-23")
        assert "rebuttal_end" not in out


class TestMergeSources:
    def test_priority_and_provenance(self):
        merged = merge_sources({
            "website": {"submission": 1, "decision": 2},
            "invitations": {"submission": 10, "review_due": 11, "decision": 12},
            "empirical": {"submission": 100, "reviews_released": 101, "decision": 102},
        })
        assert merged["submission"] == {"value": 1, "source": "website"}
        assert merged["review_due"] == {"value": 11, "source": "invitations"}
        assert merged["reviews_released"] == {"value": 101, "source": "empirical"}
        assert merged["decision"] == {"value": 2, "source": "website"}
        assert merged["rebuttal_end"] == {"value": None, "source": None}

    def test_all_milestones_present(self):
        assert set(merge_sources({})) == set(MILESTONES)


class TestLoadThresholds:
    def write(self, tmp_path, entry):
        import json
        p = tmp_path / "venue_dates.json"
        p.write_text(json.dumps({"V": entry}))
        return p

    def test_prefers_reviews_released(self, tmp_path):
        p = self.write(tmp_path, {"reviews_released": {"value": 5, "source": "website"},
                                  "review_due": {"value": 3, "source": "website"},
                                  "decision": {"value": 9, "source": "invitations"}})
        t = load_thresholds("V", p)
        assert (t["window_start"], t["decision"]) == (5, 9)
        assert (t["window_start_source"], t["decision_source"]) == ("website", "invitations")

    def test_falls_back_to_review_due(self, tmp_path):
        p = self.write(tmp_path, {"reviews_released": {"value": None, "source": None},
                                  "review_due": {"value": 3, "source": "empirical"},
                                  "decision": {"value": 9, "source": "website"}})
        assert load_thresholds("V", p)["window_start"] == 3

    def test_none_when_missing(self, tmp_path):
        p = self.write(tmp_path, {"decision": {"value": None, "source": None}})
        assert load_thresholds("V", p) is None
        assert load_thresholds("other", p) is None
        assert load_thresholds("V", tmp_path / "nope.json") is None
