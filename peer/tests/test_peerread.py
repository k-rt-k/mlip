"""Tests for the PeerRead downloader helpers (no network, no git)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from peerread import (  # noqa: E402
    SECTIONS,
    UnknownSectionError,
    sparse_patterns,
    summarize,
    validate_sections,
)


class TestValidateSections:
    def test_known_sections_pass_through(self):
        assert validate_sections(["iclr_2017", "acl_2017"]) == ["iclr_2017", "acl_2017"]

    def test_unknown_section_raises_with_choices(self):
        with pytest.raises(UnknownSectionError) as exc:
            validate_sections(["iclr_2018"])
        assert "iclr_2018" in str(exc.value)
        assert "iclr_2017" in str(exc.value)

    def test_all_known_sections_are_valid(self):
        assert validate_sections(list(SECTIONS)) == list(SECTIONS)


class TestSparsePatterns:
    def test_default_excludes_raw_pdfs(self):
        pats = sparse_patterns(["iclr_2017"], ["train"], include_pdfs=False)
        assert "/data/iclr_2017/train/reviews/" in pats
        assert "/data/iclr_2017/train/parsed_pdfs/" in pats
        assert "/data/iclr_2017/train/reviews_raw/" in pats
        assert not any(p.endswith("/pdfs/") for p in pats)

    def test_include_pdfs_adds_pdf_dir(self):
        pats = sparse_patterns(["iclr_2017"], ["train"], include_pdfs=True)
        assert "/data/iclr_2017/train/pdfs/" in pats

    def test_section_level_files_always_included(self):
        pats = sparse_patterns(["acl_2017"], ["dev"], include_pdfs=False)
        # LICENSE.txt / README.md live directly under the section dir.
        assert "/data/acl_2017/*.txt" in pats
        assert "/data/acl_2017/*.md" in pats

    def test_no_pattern_matches_a_whole_directory_tree(self):
        # In non-cone mode "/x/*" matches subdirectories too, which pulls in pdfs/.
        pats = sparse_patterns(SECTIONS, ["train", "dev", "test"], include_pdfs=False)
        assert not any(p.endswith("/*") for p in pats)

    def test_cartesian_over_sections_and_splits(self):
        pats = sparse_patterns(["iclr_2017", "conll_2016"], ["train", "test"], False)
        assert "/data/conll_2016/test/reviews/" in pats
        assert "/data/iclr_2017/test/parsed_pdfs/" in pats

    def test_patterns_are_unique_and_ordered(self):
        pats = sparse_patterns(["iclr_2017", "iclr_2017"], ["train", "train"], False)
        assert len(pats) == len(set(pats))


class TestSummarize:
    def test_counts_json_files_per_split_and_kind(self, tmp_path):
        base = tmp_path / "data" / "iclr_2017"
        for split, n in [("train", 3), ("dev", 1)]:
            for kind in ("reviews", "parsed_pdfs"):
                d = base / split / kind
                d.mkdir(parents=True)
                for i in range(n):
                    (d / f"{i}.json").write_text("{}")
        (base / "train" / "reviews" / "notes.txt").write_text("ignored")

        summary = summarize(tmp_path, ["iclr_2017"])

        assert summary["iclr_2017"]["train"]["reviews"] == 3
        assert summary["iclr_2017"]["train"]["parsed_pdfs"] == 3
        assert summary["iclr_2017"]["dev"]["reviews"] == 1
        assert "test" not in summary["iclr_2017"]

    def test_missing_section_yields_empty(self, tmp_path):
        assert summarize(tmp_path, ["acl_2017"]) == {"acl_2017": {}}
