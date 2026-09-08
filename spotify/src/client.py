"""Thin wrapper over spotipy exposing only the dev-mode-supported API surface.

Spotify removed/deprecated large parts of the Web API for new apps
(Nov 2024 + Feb 2026); spotipy still exposes those methods and they 403 at
runtime. This layer blocks them with a clear error and wraps the surviving
endpoints with uniform pagination. See docs/spotify_api.md for the full table.
"""


class DeprecatedEndpointError(RuntimeError):
    """Raised when calling an endpoint Spotify no longer serves to new apps."""


# spotipy method -> why it's blocked. Kept in sync with docs/spotify_api.md.
BLOCKED_METHODS = {
    # Deprecated for new apps, Nov 2024 (returns 403).
    "audio_features": "deprecated Nov 2024 — no audio-feature vectors for new apps",
    "audio_analysis": "deprecated Nov 2024",
    "recommendations": "deprecated Nov 2024 — Spotify's recommender is unavailable",
    "recommendation_genre_seeds": "deprecated Nov 2024",
    "artist_related_artists": "deprecated Nov 2024",
    "featured_playlists": "deprecated Nov 2024",
    "category_playlists": "deprecated Nov 2024",
    # Removed from Development Mode, Feb 2026.
    "tracks": "bulk lookup removed from dev mode Feb 2026 — use track() per id",
    "artists": "bulk lookup removed from dev mode Feb 2026 — use artist() per id",
    "albums": "bulk lookup removed from dev mode Feb 2026 — use album() per id",
    "categories": "browse endpoints removed from dev mode Feb 2026",
    "new_releases": "browse endpoints removed from dev mode Feb 2026",
    "user": "public user data removed from dev mode Feb 2026",
    "user_playlists": "public user data removed from dev mode Feb 2026",
    "available_markets": "removed from dev mode Feb 2026",
}


def unwrap_item(entry):
    """Return the track/episode dict from a wrapped API entry, or None.

    Playlist items wrap it under 'item' (Feb 2026 rename), saved/recent
    entries under 'track'; bare track dicts pass through unchanged.
    """
    if "item" in entry or "track" in entry:
        return entry.get("item") or entry.get("track")
    return entry


class SpotifyClient:
    """Dev-mode-safe Spotify API client. Wraps an authenticated spotipy.Spotify."""

    def __init__(self, sp):
        self._sp = sp

    def __getattr__(self, name):
        if name in BLOCKED_METHODS:
            raise DeprecatedEndpointError(f"{name}: {BLOCKED_METHODS[name]}")
        raise AttributeError(f"SpotifyClient has no method {name!r}")

    def _paginate(self, first_page, max_items=None):
        """Collect items across pages by following 'next' links."""
        items, current_page = list(first_page["items"]), first_page
        while current_page.get("next") and (max_items is None or len(items) < max_items):
            current_page = self._sp.next(current_page)
            items.extend(current_page["items"])
        return items if max_items is None else items[:max_items]

    # ---- current user ----

    def profile(self):
        return self._sp.current_user()

    def top_tracks(self, time_range="medium_term", max_items=50):
        """time_range: short_term (~4wk) | medium_term (~6mo) | long_term (years)."""
        return self._paginate(
            self._sp.current_user_top_tracks(limit=50, time_range=time_range),
            max_items,
        )

    def top_artists(self, time_range="medium_term", max_items=50):
        return self._paginate(
            self._sp.current_user_top_artists(limit=50, time_range=time_range),
            max_items,
        )

    def playlists(self, max_items=None):
        return self._paginate(self._sp.current_user_playlists(limit=50), max_items)

    def playlist_tracks(self, playlist_id, max_items=None):
        return self._paginate(self._sp.playlist_items(playlist_id, limit=50), max_items)

    def saved_tracks(self, max_items=None):
        return self._paginate(self._sp.current_user_saved_tracks(limit=50), max_items)

    def recently_played(self, max_items=50):
        return self._paginate(self._sp.current_user_recently_played(limit=50), max_items)

    def followed_artists(self, max_items=None):
        first_page = self._sp.current_user_followed_artists(limit=50)["artists"]
        return self._paginate(first_page, max_items)

    # ---- catalog (single-item lookups + search only in dev mode) ----

    def search(self, query, type="track", max_items=10):
        """type: track | artist | album | playlist | show | episode | audiobook."""
        first_page = self._sp.search(q=query, type=type, limit=min(max_items, 50))[f"{type}s"]
        return self._paginate(first_page, max_items)

    def track(self, track_id):
        return self._sp.track(track_id)

    def artist(self, artist_id):
        return self._sp.artist(artist_id)

    def album(self, album_id):
        return self._sp.album(album_id)

    def album_tracks(self, album_id, max_items=None):
        return self._paginate(self._sp.album_tracks(album_id, limit=50), max_items)

    def artist_albums(self, artist_id, max_items=None):
        return self._paginate(self._sp.artist_albums(artist_id, limit=50), max_items)
