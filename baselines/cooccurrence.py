"""Item-item Co-occurrence baseline model for playlist continuation."""

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Dict, List, Set


class CooccurrenceRecommender:
    """Non-ML baseline that ranks candidate tracks based on co-occurrence frequencies

    with seed tracks across a reference corpus of playlists.
    """

    def __init__(self):
        self.co_matrix = defaultdict(Counter)
        self.track_counts = Counter()

    def fit(self, reference_pools_path: Path):
        """Builds co-occurrence index from reference_pools.json."""
        raw_data = json.loads(reference_pools_path.read_text(encoding="utf-8"))
        
        # Parse nested structure: raw_data["prompts"] -> prompt["playlists"] -> playlist["tracks"]
        playlists = []
        if isinstance(raw_data, dict):
            if "prompts" in raw_data:
                for prompt_obj in raw_data["prompts"]:
                    playlists.extend(prompt_obj.get("playlists", []))
            elif "playlists" in raw_data:
                playlists = raw_data["playlists"]
        elif isinstance(raw_data, list):
            playlists = raw_data

        print(f"[CooccurrenceModel] Indexing {len(playlists)} reference playlists...")

        for pl in playlists:
            tracks = pl.get("tracks", [])
            video_ids = [
                t["video_id"] if isinstance(t, dict) else t 
                for t in tracks if t and (isinstance(t, str) or "video_id" in t)
            ]
            unique_ids = list(set(video_ids))

            # Update global frequency / popularity count
            for vid in unique_ids:
                self.track_counts[vid] += 1

            # Update co-occurrence matrix
            for i, vid_a in enumerate(unique_ids):
                for j, vid_b in enumerate(unique_ids):
                    if i != j:
                        self.co_matrix[vid_a][vid_b] += 1

        print(f"[CooccurrenceModel] Indexed {len(self.co_matrix)} unique tracks with co-occurrence data.")

    def predict(self, seed_track_ids: List[str], top_k: int = 5) -> List[str]:
        """Predicts top K co-occurring tracks for a given list of seed tracks,

        excluding seeds from recommendations.
        """
        seeds_set: Set[str] = set(seed_track_ids)
        candidate_scores = Counter()

        # Score candidates by summing co-occurrence counts across all seeds
        for seed in seed_track_ids:
            if seed in self.co_matrix:
                for candidate, score in self.co_matrix[seed].items():
                    if candidate not in seeds_set:
                        candidate_scores[candidate] += score

        # Sort candidate recommendations by score descending, breaking ties with global popularity
        sorted_candidates = sorted(
            candidate_scores.keys(),
            key=lambda candidate: (candidate_scores[candidate], self.track_counts[candidate]),
            reverse=True,
        )

        # Fallback to globally popular tracks if co-occurrence pool yields fewer than top_k
        if len(sorted_candidates) < top_k:
            popular_fallback = [
                vid for vid, _ in self.track_counts.most_common()
                if vid not in seeds_set and vid not in sorted_candidates
            ]
            sorted_candidates.extend(popular_fallback)

        return sorted_candidates[:top_k]