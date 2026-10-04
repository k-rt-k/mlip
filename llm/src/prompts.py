"""Versioned zero-shot prompts for the LLM baseline; bump PROMPT_VERSION on any wording change."""

PROMPT_VERSION = "v1"

SYSTEM = (
    "You are an expert music curator who builds playlists for listeners. "
    "Recommend only real, commercially released songs that are available on major "
    "streaming services such as YouTube Music. Never invent songs or artists; if you "
    "are unsure a song exists, choose a different one. Give each song's exact title "
    "and its primary credited artist. Respond only with JSON matching the requested schema."
)


def song_schema():
    """OpenRouter structured-output format: {"songs": [{"title", "artist"}]}, best first."""
    song = {"type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "artist": {"type": "string"}},
            "required": ["title", "artist"]}
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"songs": {"type": "array", "items": song}}, "required": ["songs"]}
    return {"type": "json_schema", "json_schema": {"name": "songs", "strict": True, "schema": schema}}


def format_track(track):
    return f'{track["title"]} — {", ".join(track["artists"])}'


def _messages(user):
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def prompt_only(request, n):
    """Playlist from a text request alone."""
    return _messages(
        f'Playlist request: "{request}"\n\n'
        f"Recommend {n} different songs that best fit this request, ordered from best "
        "fit to weakest fit. Match the requested mood, activity, genre, era, and "
        'language where stated. Return JSON: {"songs": [{"title": ..., "artist": ...}]}.'
    )


def seeds_only(seed_tracks, n):
    """Continuation from playlist songs alone, mirroring the platform's seed-only input."""
    listing = "\n".join(f"{i}. {format_track(t)}" for i, t in enumerate(seed_tracks, 1))
    return _messages(
        f"These songs are already in a playlist:\n{listing}\n\n"
        f"Recommend {n} different songs to add next, ordered from best fit to weakest "
        "fit. Match the playlist's genre, mood, era, language, and energy. Do not repeat "
        'any listed song. Return JSON: {"songs": [{"title": ..., "artist": ...}]}.'
    )
