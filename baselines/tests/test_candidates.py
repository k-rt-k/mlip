import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from baselines.candidates import build_pool, radio_candidates


def track(vid):
    return {"video_id": vid, "title": vid, "artists": ["Artist"]}


def test_union_order_excludes_seeds_and_counts_each_radio_once():
    radios = {"s": [track("s"), track("b"), track("b"), track("a")],
              "t": [track("a"), track("b"), track("c")]}
    pool = build_pool([track("s")], radios, [track("z"), track("d"), track("b")])
    assert [t["video_id"] for t in pool] == ["b", "a", "c", "d", "z"]
    assert [t["radio_seed_count"] for t in pool] == [2, 2, 1, 0, 0]
    assert len(build_pool(["s"], radios, [], max_size=2)) == 2


def test_radio_pacing_errors_and_unique_seeds(monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr("baselines.candidates.time.sleep", sleeps.append)

    class Client:
        def get_watch_playlist(self, **kwargs):
            calls.append(kwargs)
            if kwargs["videoId"] == "bad":
                raise RuntimeError("sensitive message")
            return {"tracks": [{"videoId": "a", "title": "A", "artists": [{"name": "Artist"}]}]}

    result = radio_candidates(Client(), ["s", "s", "bad"], delay=0.5)
    assert len(calls) == 2
    assert calls[0] == {"videoId": "s", "radio": True, "limit": 50}
    assert sleeps == [0.5]
    assert result["errors"] == [{"seed_id": "bad", "error": "RuntimeError"}]
    assert result["radios"]["s"][0]["video_id"] == "a"


def test_pool_is_independent_of_cooccurrence_input_order():
    left = build_pool([], {}, [track("z"), track("a")])
    right = build_pool([], {}, [track("a"), track("z")])
    assert left == right


def test_builder_keeps_hidden_tracks_out_of_collection(tmp_path, monkeypatch, capsys):
    import json
    from baselines import build_candidate_pools as runner

    inputs = tmp_path / "inputs.json"
    dataset = tmp_path / "dataset.json"
    references = tmp_path / "references.json"
    output = tmp_path / "pools.json"
    inputs.write_text(json.dumps({"examples": [{"example_id": 1, "seed_tracks": [track("s")]}]}))
    dataset.write_text(json.dumps({"examples": [{"example_id": 1, "held_out_tracks": [track("hidden")]}]}))
    references.write_text(json.dumps({"prompts": [{"playlists": [{"tracks": [track("s"), track("co")]}]}]}))
    calls = []

    class Client:
        def get_watch_playlist(self, **kwargs):
            calls.append(kwargs["videoId"])
            return {"tracks": [{"videoId": "radio", "title": "Radio", "artists": [{"name": "Artist"}]}]}

    monkeypatch.setattr(runner, "make_client", Client)
    monkeypatch.setattr(sys, "argv", ["builder", "--inputs", str(inputs), "--dataset", str(dataset),
                                     "--references", str(references), "--output", str(output), "--delay", "0"])
    runner.main()
    result = json.loads(output.read_text())
    assert calls == ["s"]
    assert [t["video_id"] for t in result["examples"]["1"]["candidates"]] == ["radio", "co"]
    assert result["ceiling"]["1"]["ceiling"] == 0
    import pytest
    with pytest.raises(SystemExit):
        runner.main()
    assert calls == ["s"]


def test_load_pools_rejects_seed_leaks_duplicates_and_shortlists(tmp_path):
    import json
    import pytest
    from baselines.candidates import load_pools
    path = tmp_path / 'pools.json'
    for candidates in [[track('s'), track('a')], [track('a'), track('a')], [track('a')]]:
        path.write_text(json.dumps({'examples': {'1': {'seed_tracks': [track('s')], 'seed_count': 1,
                                                     'candidates': candidates}}}))
        with pytest.raises(ValueError):
            load_pools(path, k=2)
    path.write_text(json.dumps({'examples': {'1': {'seed_tracks': [track('s')], 'seed_count': 1,
                                                 'candidates': [track('a'), track('b')]}}}))
    assert len(load_pools(path, k=2)['1']['candidates']) == 2
