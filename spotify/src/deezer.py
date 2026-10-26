"""Rate-limited Deezer API access shared by the MPD pipeline and eval-song mapping."""
import threading
import time

import requests

API = 'https://api.deezer.com'


class RateLimiter:
    """One process-wide request budget shared by all fetching threads."""
    def __init__(self, requests_per_second):
        if requests_per_second <= 0:
            raise ValueError('request rate must be positive')
        self.interval = 1 / requests_per_second
        self.lock = threading.Lock()
        self.next = 0

    def wait(self):
        with self.lock:
            delay = self.next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.next = time.monotonic() + self.interval

    def cool_down(self, seconds):
        with self.lock:
            self.next = max(self.next, time.monotonic() + seconds)


class LimitedSession(requests.Session):
    def __init__(self, limiter):
        super().__init__()
        self.limiter = limiter

    def get(self, *args, **kwargs):
        self.limiter.wait()
        response = super().get(*args, **kwargs)
        if response.status_code == 429:
            self.limiter.cool_down(30)
        elif response.status_code == 200:
            try:
                if response.json().get('error', {}).get('code') == 4:
                    self.limiter.cool_down(30)
            except ValueError:
                pass
        return response


def search_candidates(session, query, attempts=3):
    """Deezer search results (up to 25); transient and API errors are retried, then raised."""
    for attempt in range(attempts):
        try:
            response = session.get(f'{API}/search', params={'q': query, 'limit': 25}, timeout=30)
            response.raise_for_status()
            body = response.json()
            if 'error' in body:
                raise requests.RequestException(f'Deezer error: {body["error"]}')
            return body.get('data', [])
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * 2 ** attempt)


def fresh_preview(session, deezer_id):
    """Current preview URL for a track; signed CDN URLs expire about 15 minutes after issue."""
    response = session.get(f'{API}/track/{deezer_id}', timeout=30)
    response.raise_for_status()
    return response.json().get('preview') or None
