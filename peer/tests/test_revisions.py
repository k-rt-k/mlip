"""Tests for OpenReview revision helpers (no network; clients are mocked)."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revisions import (  # noqa: E402
    download_revision_pdf,
    fetch_revisions,
    fetch_submissions,
    pick_initial_and_final,
    summarize_revisions,
    venue_slug,
)


def v2_edit(id, tcdate, invitation, title=None, abstract=None, pdf=None):
    """Mimic an openreview.api.Edit: field values live under content[k]['value']."""
    content = {}
    if title is not None:
        content["title"] = {"value": title}
    if abstract is not None:
        content["abstract"] = {"value": abstract}
    if pdf is not None:
        content["pdf"] = {"value": pdf}
    return SimpleNamespace(id=id, tcdate=tcdate, invitation=invitation,
                           note=SimpleNamespace(content=content))


def v1_ref(id, tcdate, invitation, title=None, abstract=None, pdf=None):
    """Mimic an API-v1 reference Note: flat content dict, no .note attribute."""
    content = {k: v for k, v in [("title", title), ("abstract", abstract), ("pdf", pdf)]
               if v is not None}
    return SimpleNamespace(id=id, tcdate=tcdate, invitation=invitation, content=content)


class TestSummarizeRevisions:
    def test_v2_edits_sorted_by_tcdate_with_fields(self):
        edits = [
            v2_edit("e2", 2000, "V/Sub1/-/Revision", title="B", pdf="/pdf/b.pdf"),
            v2_edit("e1", 1000, "V/-/Submission", title="A", abstract="x", pdf="/pdf/a.pdf"),
        ]
        rows = summarize_revisions(edits)
        assert [r["rev_id"] for r in rows] == ["e1", "e2"]
        assert rows[0] == {
            "rev_id": "e1", "tcdate": 1000, "iso_date": "1970-01-01T00:00:01+00:00",
            "invitation": "V/-/Submission", "title": "A", "abstract": "x", "pdf": "/pdf/a.pdf",
        }
        assert rows[1]["abstract"] is None

    def test_v1_references_flat_content(self):
        refs = [v1_ref("r1", 5000, "ICLR.cc/2017/conference/-/submission",
                       title="T", pdf="/pdf/x.pdf")]
        rows = summarize_revisions(refs)
        assert rows[0]["title"] == "T"
        assert rows[0]["pdf"] == "/pdf/x.pdf"
        assert rows[0]["abstract"] is None

    def test_edit_without_note_is_skipped(self):
        edits = [SimpleNamespace(id="e0", tcdate=1, invitation="V/-/Edit", note=None),
                 v2_edit("e1", 2, "V/-/Submission", title="A")]
        assert [r["rev_id"] for r in summarize_revisions(edits)] == ["e1"]


class TestPickInitialAndFinal:
    def rows(self, pdfs):
        return [{"rev_id": f"r{i}", "tcdate": i, "pdf": p} for i, p in enumerate(pdfs)]

    def test_returns_first_and_last_distinct_pdf(self):
        first, last = pick_initial_and_final(self.rows(["/a", None, "/b", "/c"]))
        assert first["rev_id"] == "r0"
        assert last["rev_id"] == "r3"

    def test_none_when_single_pdf(self):
        assert pick_initial_and_final(self.rows(["/a", None])) is None

    def test_none_when_same_pdf_repeated(self):
        assert pick_initial_and_final(self.rows(["/a", "/a"])) is None

    def test_none_when_no_pdfs(self):
        assert pick_initial_and_final(self.rows([None, None])) is None


class TestClientWrappers:
    def test_fetch_revisions_v2_uses_note_edits(self):
        client = MagicMock()
        client.get_note_edits.return_value = ["e"]
        assert fetch_revisions(client, "n1", api_version=2) == ["e"]
        client.get_note_edits.assert_called_once_with(note_id="n1", sort="tcdate:asc")

    def test_fetch_revisions_v1_uses_references(self):
        client = MagicMock()
        client.get_references.return_value = ["r"]
        assert fetch_revisions(client, "n1", api_version=1) == ["r"]
        client.get_references.assert_called_once_with(referent="n1", original=True)

    def test_fetch_submissions_v2_uses_submission_invitation_not_venueid(self):
        # content.venueid only returns accepted papers (2260 of 7404 for ICLR 2024).
        client = MagicMock()
        client.get_all_notes.return_value = ["n"]
        assert fetch_submissions(client, "ICLR.cc/2024/Conference", api_version=2) == ["n"]
        client.get_all_notes.assert_called_once_with(
            invitation="ICLR.cc/2024/Conference/-/Submission", sort="number:asc")

    def test_fetch_submissions_v1_tries_blind_submission_then_submission(self):
        client = MagicMock()
        client.get_all_notes.side_effect = [[], ["n"]]  # 2017 has no Blind_Submission
        assert fetch_submissions(client, "ICLR.cc/2017/conference", api_version=1) == ["n"]
        calls = [c.kwargs["invitation"] for c in client.get_all_notes.call_args_list]
        assert calls == ["ICLR.cc/2017/conference/-/Blind_Submission",
                         "ICLR.cc/2017/conference/-/submission"]

    def test_fetch_submissions_v1_blind_submission_short_circuits(self):
        client = MagicMock()
        client.get_all_notes.return_value = ["n"]
        fetch_submissions(client, "ICLR.cc/2020/Conference", api_version=1)
        client.get_all_notes.assert_called_once_with(
            invitation="ICLR.cc/2020/Conference/-/Blind_Submission", sort="number:asc")

    def test_fetch_submissions_limit_truncates(self):
        client = MagicMock()
        client.get_all_notes.return_value = list(range(10))
        assert fetch_submissions(client, "V", api_version=2, limit=3) == [0, 1, 2]

    def test_bad_api_version(self):
        with pytest.raises(ValueError):
            fetch_revisions(MagicMock(), "n", api_version=3)

    def test_download_pdf_v2_uses_attachment(self, tmp_path):
        client = MagicMock()
        client.get_attachment.return_value = b"%PDF"
        dest = tmp_path / "x.pdf"
        assert download_revision_pdf(client, "e1", 2, dest) == dest
        client.get_attachment.assert_called_once_with(field_name="pdf", id="e1")
        assert dest.read_bytes() == b"%PDF"

    def test_download_pdf_v1_uses_reference_pdf(self, tmp_path):
        client = MagicMock()
        client.get_pdf.return_value = b"%PDF"
        download_revision_pdf(client, "r1", 1, tmp_path / "y.pdf")
        client.get_pdf.assert_called_once_with("r1", is_reference=True)


class TestVenueSlug:
    def test_slug_is_filesystem_safe(self):
        assert venue_slug("ICLR.cc/2017/conference") == "ICLR.cc_2017_conference"
