"""Local evaluation app for natural-language playlist curation."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from secrets import token_bytes
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from itsdangerous import BadData, URLSafeTimedSerializer

from .backends import Backends, OPENROUTER_MODEL, OPENROUTER_URL, RehearsalBackends, VIDEO_ID, timed_recommend
from .study import ARMS, SETUPS, Study, StudyConflict


COOKIE = "mlip_study_session"
ARM_LABELS = {
    "retrieval": "Team retrieval",
    "llm": "LLM baseline",
    "playlist_search": "YouTube Music baseline",
}


def endpoint(value):
    if not value:
        return None
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("Service endpoints must be HTTP(S) URLs without credentials or URL parameters.")
    return value.rstrip("/")


def create_app(db_path=None, *, setup="paired", rehearsal=False, backends=None):
    if setup not in SETUPS:
        raise ValueError("Unknown study setup")
    default_env = Path(__file__).resolve().parents[1] / "llm" / ".env"
    load_dotenv(os.getenv("MLIP_LLM_ENV_FILE") or default_env)
    site = Flask(__name__)
    site.config.update(MAX_CONTENT_LENGTH=32 * 1024)
    study = Study(db_path or os.getenv("MLIP_STUDY_DB", "data/evaluation_app/study.sqlite"))
    signer = URLSafeTimedSerializer(os.getenv("MLIP_STUDY_SIGNING_KEY") or token_bytes(32))
    if backends is None:
        llm_url = endpoint(os.getenv("MLIP_LLM_URL") or OPENROUTER_URL)
        llm_model = os.getenv("MLIP_LLM_MODEL")
        llm_key = os.getenv("MLIP_LLM_KEY")
        if llm_url == OPENROUTER_URL:
            llm_model = llm_model or OPENROUTER_MODEL
            llm_key = llm_key or os.getenv("OPENROUTER_API_KEY")
        ytm_auth = Path(os.getenv("MLIP_YTM_AUTH_FILE") or "data/youtube_music/browser.json").expanduser()
        backends = RehearsalBackends() if rehearsal else Backends(
            endpoint(os.getenv("MLIP_RETRIEVAL_URL", "http://127.0.0.1:8061")),
            llm_url, llm_model, llm_key, ytm_auth=ytm_auth,
        )
    secure_cookie = os.getenv("MLIP_SECURE_COOKIE") == "1"

    def error(message, code=400):
        return jsonify(error=message), code

    def payload():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        return value

    def session():
        session_id = request.cookies.get(COOKIE, "")
        row = study.session(session_id) if 0 < len(session_id) <= 64 else None
        if row and bool(row["rehearsal"]) == rehearsal and row["setup"] == setup:
            return row
        return None

    def active():
        row = session()
        if row is None or row["finished_at"]:
            raise StudyConflict("Start a session to continue.")
        return row

    @site.errorhandler(ValueError)
    def bad_request(exc):
        return error("That request is invalid.")

    @site.errorhandler(StudyConflict)
    def conflict(exc):
        return error(str(exc), 409)

    @site.errorhandler(413)
    def too_large(exc):
        return error("That request is too large.", 413)

    @site.after_request
    def protect(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https://i.ytimg.com; media-src https://*.dzcdn.net; "
            "frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @site.get("/")
    def index():
        return render_template("index.html", setup=setup, rehearsal=rehearsal, arms=ARM_LABELS,
                               openrouter=getattr(backends, "llm_url", None) == OPENROUTER_URL)

    @site.get("/api/session")
    def session_state():
        row = session()
        if row is None:
            return {"started": False}
        return {"started": True, "finished": bool(row["finished_at"]), **study.state(row["id"])}

    @site.post("/api/session")
    def start():
        data = payload()
        if data.get("consent") is not True:
            return error("Confirm that you agree to start the session.")
        old_session = session()
        if old_session and not old_session["finished_at"]:
            return error("A session is already in progress in this browser.", 409)
        arm = data.get("arm")
        if setup == "manual" and arm not in ARMS:
            return error("Choose a recommender.")
        available = list(ARMS) if setup == "paired" else [arm]
        missing = backends.ready(available)
        if missing:
            return error("The facilitator needs to configure " + " and ".join(missing) + ".", 503)
        session_id = study.create(rehearsal, setup, arm)
        result = jsonify(started=True, finished=False, playlist=[], round=None, round_five_rating=None)
        result.set_cookie(COOKIE, session_id, httponly=True, samesite="Strict", secure=secure_cookie,
                          max_age=8 * 60 * 60)
        return result

    @site.post("/api/search")
    def search():
        active()
        data = payload()
        query = data.get("query")
        if not isinstance(query, str) or not 0 < len(query.strip()) <= 160:
            return error("Enter a song or artist to search for.")
        try:
            tracks = backends.search(query.strip())
        except Exception:
            return error("YouTube Music search is temporarily unavailable.", 503)
        return {"tracks": [{**track, "selection": signer.dumps(track)} for track in tracks]}

    @site.post("/api/playlist")
    def edit_playlist():
        row = active()
        data = payload()
        action = data.get("action")
        if action == "add":
            if setup == "paired" and study.state(row["id"])["round"] is None:
                return error("Start with a text request, then add songs to your playlist.", 409)
            selection = data.get("selection")
            if not isinstance(selection, str):
                return error("Choose a song from search.")
            try:
                track = signer.loads(selection, max_age=60 * 60)
            except BadData:
                return error("Run the song search again to refresh that result.", 409)
        elif action == "remove":
            track = next((track for track in study.state(row["id"])["playlist"]
                          if track["video_id"] == data.get("video_id")), None)
            if track is None:
                return error("That song is already out of the playlist.", 409)
        else:
            return error("Choose Add or Remove.")
        study.edit_playlist(row["id"], action, track)
        return study.state(row["id"])

    @site.post("/api/preview")
    def preview():
        row = active()
        data = payload()
        selection = data.get("selection")
        if isinstance(selection, str):
            try:
                track = signer.loads(selection, max_age=60 * 60)
            except BadData:
                return error("Run the song search again to refresh that result.", 409)
        else:
            current = study.state(row["id"])
            tracks = current["playlist"] + [offer for panel in (current["round"] or {}).get("panels", [])
                                             for offer in panel["offers"]]
            track = next((item for item in tracks if item["video_id"] == data.get("video_id")), None)
            if track is None:
                return error("That song is no longer visible in this session.", 404)
        try:
            link = backends.preview(track)
        except Exception:
            return error("Deezer preview is temporarily unavailable.", 503)
        return {"url": link} if link else error("Deezer has no preview for this recording.", 404)

    @site.post("/api/recommend")
    def recommend():
        row = active()
        data = payload()
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or len(prompt) > 1000:
            return error("Enter a request of up to 1,000 characters.")
        prompt = prompt.strip()
        round_id, seeds, exclusions = study.start_round(row["id"], bool(prompt))
        seeds = backends.annotate(seeds)
        known = [track.get("seed_eligible") for track in seeds]
        eligible = sum(value is True for value in known) if all(value is not None for value in known) else None
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [executor.submit(timed_recommend, backends, arm, prompt, seeds, exclusions)
                       for arm in json.loads(row["arms"])]
            panels = [future.result() for future in pending]
        study.finalize_round(round_id, eligible, panels)
        return study.state(row["id"])

    @site.post("/api/action")
    def action():
        row = active()
        data = payload()
        round_id = data.get("round_id")
        position = data.get("position")
        video_id = data.get("video_id")
        selected = data.get("action")
        if (type(round_id) is not int or type(position) is not int
                or not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id)
                or selected not in ("keep", "reject", "play")):
            return error("Choose an action on a suggestion.")
        study.action(row["id"], round_id, position, video_id, selected)
        return {"recorded": True} if selected == "play" else study.state(row["id"])

    @site.post("/api/finish")
    def finish():
        row = active()
        data = payload()
        rating, comments = data.get("rating"), data.get("comments", "")
        if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
            return error("Choose a rating from 1 to 5 or leave it blank.")
        if not isinstance(comments, str) or len(comments) > 500:
            return error("Keep comments to 500 characters.")
        study.finish(row["id"], rating, comments.strip())
        return {"finished": True}

    @site.post("/api/checkpoint")
    def checkpoint():
        row = active()
        data = payload()
        rating, round_id = data.get("rating"), data.get("round_id")
        if type(round_id) is not int or type(rating) is not int or not 1 <= rating <= 5:
            return error("Choose a rating from 1 to 5.")
        study.save_checkpoint(row["id"], round_id, rating)
        return study.state(row["id"])

    return site
