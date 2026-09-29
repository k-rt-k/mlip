"""Worker checkpoint alignment, failure recording, and SLURM submission."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("embed_worker", SCRIPTS / "embed.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@pytest.mark.parametrize("all_bad", [False, True])
def test_worker_records_failures_and_resumes(tmp_path, monkeypatch, all_bad):
    monkeypatch.setattr(sys, "argv", ["embed.py", "--user", "alice", "--model", "clap",
                                     "--out-dir", str(tmp_path)])
    monkeypatch.setattr(worker, "require_persistent_out", lambda path, *a, **kw: path)
    monkeypatch.setattr(worker, "track_isrcs", lambda user: {t: {} for t in "abc"})
    downloaded = []
    def download(chunk, *args, **kwargs):
        downloaded.append(list(chunk))
        return {t: tmp_path / f"{t}.mp3" for t in chunk}, []
    monkeypatch.setattr(worker, "download_previews", download)
    class FakeEmbedder:
        def embed_audio(self, paths, on_error):
            rows = []
            for path in paths:
                if all_bad or path.stem == "b":
                    on_error(path, "bad audio")
                else:
                    rows.append([1, 0] if path.stem == "a" else [0, 1])
            return np.array(rows)
    monkeypatch.setattr(worker, "get_embedder", lambda *a, **kw: FakeEmbedder())
    worker.main()
    output = tmp_path / "clap/shard-0-of-1.npz"
    if all_bad:
        assert not output.exists()
    else:
        data = np.load(output)
        assert data["ids"].tolist() == ["a", "c"]
        np.testing.assert_array_equal(data["vectors"], [[1, 0], [0, 1]])
    events = [json.loads(line) for line in next((tmp_path / "manifest").iterdir()).read_text().splitlines()]
    assert [e["track_id"] for e in events if e["event"] == "clip_failed"] == (list("abc") if all_bad else ["b"])
    worker.main()
    assert downloaded[-1] == (list("abc") if all_bad else ["b"])


def test_submit_wrapper_creates_logs_before_submission(tmp_path):
    repo = tmp_path / "repo with spaces"
    scripts = repo / "spotify/scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "submit_babel_embed.sh"
    wrapper.write_text((SCRIPTS / wrapper.name).read_text())
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sbatch = fake_bin / "sbatch"
    sbatch.write_text('#!/bin/bash\n[ -d logs ] || exit 9\nprintf "%s\\n" "$PWD" "$@"\n')
    sbatch.chmod(0o755)
    result = subprocess.run(["bash", str(wrapper), "--nodelist=node1"], cwd=tmp_path,
                            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                            capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(repo), "--nodelist=node1",
        f"--chdir={repo}", f"--output={repo}/logs/%x-%j.out", str(scripts / "babel_embed.sbatch")]
