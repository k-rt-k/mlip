import json
import sqlite3
import sys

import numpy as np
import pytest

from evaluation_app.app import create_app
from evaluation_app.backends import Backends, OPENROUTER_MODEL, OPENROUTER_URL, RehearsalBackends, timed_recommend
from evaluation_app.__main__ import main
from evaluation_app.retrieval_service import Catalog, build_lookup
from evaluation_app.study import Study
from retrieval import EmbeddingCatalog, IndexConfig, RetrievalIndex


def start(client, arm=None):
    response = client.post("/api/session", json={"consent": True, "arm": arm})
    assert response.status_code == 200
    return response.get_json()


def suggest(client, prompt=""):
    response = client.post("/api/recommend", json={"prompt": prompt})
    assert response.status_code == 200
    return response.get_json()


def test_public_preview_uses_retrieval_and_a_secure_cookie(tmp_path):
    client = create_app(tmp_path / "preview.sqlite", preview=True, backends=RehearsalBackends()).test_client()
    page = client.get("/")
    assert b"Public retrieval preview" in page.data
    assert b"LLM baseline" not in page.data
    assert client.post("/api/session", json={"consent": True, "arm": "llm"}).status_code == 400
    response = client.post("/api/session", json={"consent": True, "arm": "retrieval"})
    assert response.status_code == 200
    assert "; Secure;" in response.headers["Set-Cookie"]
    panels = suggest(client, "jazz")["round"]["panels"]
    assert len(panels) == 1
    assert panels[0]["status"] == "ok"


def test_public_study_is_paired_and_uses_a_secure_cookie(tmp_path):
    client = create_app(tmp_path / "study.sqlite", public_study=True,
                        backends=RehearsalBackends()).test_client()
    page = client.get("/")
    assert b"Public retrieval preview" not in page.data
    assert b"Recommender for this test" not in page.data
    response = client.post("/api/session", json={"consent": True})
    assert response.status_code == 200
    assert "; Secure;" in response.headers["Set-Cookie"]
    assert len(suggest(client, "jazz")["round"]["panels"]) == 2


def test_paired_session_with_three_modes_and_mirrored_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr("evaluation_app.study.choice", lambda options: options[0])
    db = tmp_path / "pilot.sqlite"
    client = create_app(db, rehearsal=True).test_client()
    assert client.post("/api/search", json={"query": "Daft Punk"}).status_code == 409
    assert client.post("/api/session", json={"consent": False}).status_code == 400
    assert start(client)["playlist"] == []
    assert client.post("/api/playlist", json={"action": "add"}).status_code == 409

    state = suggest(client, "synthetic private prompt")
    assert state["round"]["mode"] == "text_only"
    panels = state["round"]["panels"]
    left, right = ({track["video_id"] for track in panel["offers"]} for panel in panels)
    assert len(panels) == 2 and left & right
    assert all("arm" not in panel and len(panel["offers"]) == 5 for panel in panels)
    shared_track = sorted(left & right)[0]
    assert client.post("/api/action", json={
        "action": "play", "round_id": state["round"]["id"], "position": 0, "video_id": shared_track,
    }).status_code == 200
    action = {"action": "keep", "round_id": state["round"]["id"], "position": 1, "video_id": shared_track}
    kept = client.post("/api/action", json=action).get_json()
    assert [track["video_id"] for track in kept["playlist"]] == [shared_track]
    assert [track["decision"] for panel in kept["round"]["panels"]
            for track in panel["offers"] if track["video_id"] == shared_track] == ["keep", "keep"]
    assert client.post("/api/action", json=action).status_code == 200
    assert client.post("/api/action", json={**action, "action": "reject"}).status_code == 409

    results = client.post("/api/search", json={"query": "Adele"}).get_json()["tracks"]
    assert results and results[0]["seed_eligible"]
    added = client.post("/api/playlist", json={"action": "add", "selection": results[0]["selection"]})
    assert len(added.get_json()["playlist"]) == 2
    refined = suggest(client, "a different synthetic request")
    assert refined["round"]["mode"] == "text_and_playlist"
    assert all(track["video_id"] not in {shared_track, results[0]["video_id"]}
               for panel in refined["round"]["panels"] for track in panel["offers"])
    assert suggest(client)["round"]["mode"] == "playlist_only"
    assert client.post("/api/finish", json={"rating": 4, "comments": "Helpful covers"}).status_code == 200
    assert client.get("/api/session").get_json()["finished"]
    assert b"synthetic private prompt" not in db.read_bytes()
    assert b"Helpful covers" in db.read_bytes()

    export = tmp_path / "export.json"
    monkeypatch.setattr(sys, "argv", ["evaluation_app", "--db", str(db), "--export", str(export)])
    main()
    comparison = json.loads(export.read_text())["participant_arm_summary"]
    assert len(comparison) == 2
    assert all(row["shown"] == 15 and row["kept"] == 1 for row in comparison)
    assert all(row["empty_slots"] == 0 and row["failed_panels"] == 0 for row in comparison)


def test_youtube_music_skips_combined_rounds_and_pair_metrics_exclude_them(tmp_path, monkeypatch):
    monkeypatch.setattr("evaluation_app.study.choice", lambda options: options[-1])
    db = tmp_path / "paired.sqlite"
    client = create_app(db, rehearsal=True).test_client()
    start(client)
    opening = suggest(client, "jazz")["round"]
    assert all(panel["status"] == "ok" for panel in opening["panels"])
    offer = opening["panels"][0]["offers"][0]
    assert client.post("/api/action", json={
        "round_id": opening["id"], "position": 0, "action": "keep", "video_id": offer["video_id"],
    }).status_code == 200

    refined = suggest(client, "something faster")["round"]
    assert refined["panels"][0] == {"position": 0, "status": "not_applicable", "offers": []}
    assert len(refined["panels"][1]["offers"]) == 5
    assert all(panel["status"] == "ok" for panel in suggest(client)["round"]["panels"])

    export = tmp_path / "paired.json"
    monkeypatch.setattr(sys, "argv", ["evaluation_app", "--db", str(db), "--export", str(export)])
    main()
    rows = {row["arm"]: row for row in json.loads(export.read_text())["participant_arm_summary"]}
    youtube = rows["playlist_search"]
    assert youtube["not_applicable_panels"] == 1
    assert youtube["failed_panels"] == youtube["empty_slots"] == 0
    assert rows["retrieval"]["shown"] == 15
    assert youtube["paired_shown"] == rows["retrieval"]["paired_shown"] == 10


def test_paired_keep_rate_requires_offers_on_both_sides(tmp_path, monkeypatch):
    class PartiallyFilledBackends(RehearsalBackends):
        def recommend(self, arm, prompt, seeds, exclusions):
            tracks = super().recommend(arm, prompt, seeds, exclusions)
            if arm == "llm":
                return [] if prompt == "empty baseline" else tracks[:2]
            return tracks

    monkeypatch.setattr("evaluation_app.study.choice", lambda options: options[0])
    db = tmp_path / "study.sqlite"
    client = create_app(db, rehearsal=True, backends=PartiallyFilledBackends()).test_client()
    start(client)

    first = suggest(client, "empty baseline")["round"]
    assert first["panels"][1]["status"] == "ok" and first["panels"][1]["offers"] == []
    assert client.post("/api/action", json={
        "round_id": first["id"], "position": 0, "action": "keep",
        "video_id": first["panels"][0]["offers"][0]["video_id"],
    }).status_code == 200
    paired = suggest(client, "partially filled baseline")["round"]
    assert len(paired["panels"][1]["offers"]) == 2

    export = tmp_path / "export.json"
    monkeypatch.setattr(sys, "argv", ["evaluation_app", "--db", str(db), "--export", str(export)])
    main()
    rows = {row["arm"]: row for row in json.loads(export.read_text())["participant_arm_summary"]}
    retrieval, llm = rows["retrieval"], rows["llm"]
    assert (retrieval["shown"], retrieval["kept"]) == (10, 1)
    assert (retrieval["paired_shown"], retrieval["paired_kept"]) == (5, 0)
    assert llm["paired_shown"] == 2
    assert llm["empty_slots"] == 8
    assert llm["failed_panels"] == 0


@pytest.mark.parametrize("suggestions_fail", [False, True])
@pytest.mark.parametrize("cleanup_dict", [False, True])
def test_seed_only_youtube_uses_a_private_temporary_playlist(tmp_path, monkeypatch,
                                                               suggestions_fail, cleanup_dict):
    browser = tmp_path / "browser.json"
    browser.touch()
    seed_ids = ["seedvideo01", "seedvideo02"]
    events = []

    def track(video_id):
        return {"videoId": video_id, "title": "A song", "artists": [{"name": "An artist"}]}

    class Client:
        def create_playlist(self, *, title, description, privacy_status, video_ids):
            assert title.startswith("Playlist Lab temporary ") and description == ""
            assert privacy_status == "PRIVATE" and video_ids == seed_ids
            events.append("create")
            return "PLtemporary"

        def get_playlist(self, playlist_id, *, limit, suggestions_limit=0):
            assert playlist_id == "PLtemporary" and limit is None
            events.append("suggest" if suggestions_limit else "verify")
            if suggestions_limit and suggestions_fail:
                raise RuntimeError("platform error")
            return {"owned": True, "privacy": "PRIVATE", "tracks": [track(vid) for vid in seed_ids],
                    "suggestions": [track(seed_ids[0]), track("suggestion1")]}

        def delete_playlist(self, playlist_id):
            assert playlist_id == "PLtemporary"
            events.append("delete")
            return {} if cleanup_dict else "STATUS_SUCCEEDED"

        def get_library_playlists(self, *, limit):
            assert limit is None
            events.append("list")
            return []

    def client_for(auth):
        assert auth == browser
        return Client()

    backends = Backends("http://127.0.0.1:8061", ytm_auth=browser)
    monkeypatch.setattr("evaluation_app.backends.make_client", client_for)
    monkeypatch.setattr(backends, "annotate", lambda tracks: tracks)
    seeds = [{"video_id": video_id} for video_id in seed_ids]
    assert timed_recommend(backends, "playlist_search", "faster", seeds, set())["status"] == "not_applicable"
    assert not events
    panel = timed_recommend(backends, "playlist_search", "", seeds, set())
    assert events == ["create", "verify", "suggest", "delete"] + (["list"] if cleanup_dict else [])
    if suggestions_fail:
        assert panel["status"] == "unavailable" and panel["tracks"] == []
    else:
        assert panel["status"] == "ok"
        assert [track["video_id"] for track in panel["tracks"]] == ["suggestion1"]


def test_youtube_music_text_lookup_is_public_without_browser_headers(monkeypatch):
    backends = Backends("http://127.0.0.1:8061")

    class Client:
        def search(self, query, *, filter, limit):
            assert query == "fast jazz" and filter == "community_playlists"
            assert limit == 20
            return []

    monkeypatch.setattr("evaluation_app.backends.make_client", lambda: Client())
    assert timed_recommend(backends, "playlist_search", "fast jazz", [], set())["status"] == "ok"
    assert timed_recommend(backends, "playlist_search", "", [{"video_id": "seedvideo01"}], set())["status"] == "unavailable"


def test_fifth_round_rating_is_optional_and_separate(tmp_path):
    db = tmp_path / "checkpoint.sqlite"
    client = create_app(db, rehearsal=True).test_client()
    start(client)
    for number in range(1, 6):
        result = suggest(client, "some music")
        assert result["round"]["number"] == number
        data = {"round_id": result["round"]["id"], "rating": 4}
        if number < 5:
            assert client.post("/api/checkpoint", json=data).status_code == 409
    saved = client.post("/api/checkpoint", json=data)
    assert saved.get_json()["round_five_rating"] == 4
    assert suggest(client, "something else")["round"]["number"] == 6
    assert client.post("/api/checkpoint", json=data).status_code == 409
    assert client.post("/api/finish", json={"rating": 2}).status_code == 200
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT rating FROM checkpoints").fetchone()[0] == 4
        assert conn.execute("SELECT rating FROM sessions").fetchone()[0] == 2


def test_manual_testing_and_balanced_pairs(tmp_path):
    app = create_app(tmp_path / "manual.sqlite", setup="manual", rehearsal=True)
    client = app.test_client()
    assert client.post("/api/session", json={"consent": True}).status_code == 400
    start(client, "llm")
    assert len(suggest(client, "synth pop")["round"]["panels"]) == 1

    study = Study(tmp_path / "paired.sqlite")
    ids = [study.create(False, "paired") for _ in range(4)]
    arms = [set(json.loads(study.session(session_id)["arms"])) for session_id in ids]
    assert arms.count({"retrieval", "llm"}) == 2
    assert arms.count({"retrieval", "playlist_search"}) == 2


def test_live_session_stops_when_arm_is_missing(tmp_path):
    class MissingBackend(RehearsalBackends):
        def ready(self, arms):
            assert set(arms) == {"llm", "playlist_search", "retrieval"}
            return ["LLM endpoint and model"]

    client = create_app(tmp_path / "missing.sqlite", backends=MissingBackend()).test_client()
    response = client.post("/api/session", json={"consent": True})
    assert response.status_code == 503
    assert "LLM" in response.get_json()["error"]
    assert not client.get("/api/session").get_json()["started"]


def test_live_study_requires_youtube_music_auth_file(tmp_path, monkeypatch):
    class Healthy:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ready": True}

    monkeypatch.setattr("evaluation_app.backends.requests.get", lambda *args, **kwargs: Healthy())
    backends = Backends("http://127.0.0.1:8061", OPENROUTER_URL, OPENROUTER_MODEL,
                        "configured-key", ytm_auth=tmp_path / "missing.json")
    assert backends.ready(["retrieval", "playlist_search"]) == ["YouTube Music browser credentials"]


def test_openrouter_combined_prompt_keeps_privacy_controls(monkeypatch):
    def complete(messages, model, **kwargs):
        assert "more energetic" in messages[-1]["content"]
        assert "Seed Song" in messages[-1]["content"]
        assert model == OPENROUTER_MODEL and kwargs["endpoint"] == OPENROUTER_URL
        assert kwargs["extra"]["provider"] == {
            "zdr": True, "data_collection": "deny", "require_parameters": True,
        }
        assert kwargs["extra"]["reasoning"] == {"enabled": False}
        return {"text": '{"songs":[{"title":"Followup","artist":"Artist"}]}'}

    monkeypatch.setattr("evaluation_app.backends.chat_client.complete", complete)
    backends = Backends("http://127.0.0.1:8061", OPENROUTER_URL, OPENROUTER_MODEL, "synthetic-key")
    assert backends.ready(["llm"]) == []
    assert backends.llm_candidates("more energetic", [{"title": "Seed Song", "artists": ["Band"]}]) == [
        {"title": "Followup", "artist": "Artist"},
    ]


def test_preview_uses_the_signed_search_result(tmp_path, monkeypatch):
    class PreviewBackend(RehearsalBackends):
        def search(self, query):
            return [{**self.tracks[0], "recording_key": "isrc:GBDUW0000053"}]

    def preview(session, recording_id):
        assert recording_id == "isrc:GBDUW0000053"
        return "https://cdnt-preview.dzcdn.net/clip"

    monkeypatch.setattr("evaluation_app.backends.fresh_preview", preview)
    monkeypatch.setattr(PreviewBackend, "preview", staticmethod(Backends.preview))
    client = create_app(tmp_path / "preview.sqlite", rehearsal=True, backends=PreviewBackend()).test_client()
    start(client)
    result = client.post("/api/search", json={"query": "Daft Punk"}).get_json()["tracks"][0]
    assert client.post("/api/preview", json={"selection": "forged"}).status_code == 409
    response = client.post("/api/preview", json={"selection": result["selection"]})
    assert response.get_json() == {"url": "https://cdnt-preview.dzcdn.net/clip"}


def test_cpu_catalog_uses_partial_coverage_and_excludes_seed_recording(tmp_path):
    source = tmp_path / "tracks.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE tracks (id, title, artist, duration, isrc)")
        db.executemany("INSERT INTO tracks VALUES (?,?,?,?,?)", [
            ("a", "Seed Song", "Band", 120, "AAAA"),
            ("b", "Followup", "Artist", 180, "BBBB"),
            ("c", "Something Different", "Someone", 200, "CCCC"),
        ])
    lookup = tmp_path / "lookup.sqlite"
    build_lookup(source, lookup)
    with pytest.raises(FileExistsError):
        build_lookup(source, lookup)
    vectors = np.array([[1, 0], [.8, .6], [0, 1]], dtype="float32")
    index = RetrievalIndex.build(EmbeddingCatalog(["a", "b", "c"], vectors), IndexConfig("exact"))
    catalog = Catalog(index, lookup)
    matched = {"video_id": "aaaaaaaaaaa", "title": "Seed Song", "artists": ["Band"], "duration_seconds": 122}
    missing = {"video_id": "bbbbbbbbbbb", "title": "Unmatched", "artists": ["Band"]}
    assert [info["seed_eligible"] for info in catalog.coverage([matched, missing]).values()] == [True, False]
    assert not catalog.coverage([{**matched, "title": "Seed Song (Live)"}])["aaaaaaaaaaa"]["seed_eligible"]
    assert not catalog.coverage([{**matched, "duration_seconds": 140}])["aaaaaaaaaaa"]["seed_eligible"]
    assert catalog.shortlist(None, [matched, missing], [], 3, 2)[0]["title"] == "Followup"
    assert catalog.shortlist([0, 1], [missing], [], 3, 2)[0]["title"] == "Something Different"
    assert catalog.shortlist(None, [missing], [], 3, 2) == []
