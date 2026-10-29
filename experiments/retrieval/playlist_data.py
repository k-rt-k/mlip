"""Input and embedding loaders for prompt-conditioned playlist experiments."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from retrieval.catalog import normalized_vectors


@dataclass(frozen=True)
class PartialExample:
    example_id: str
    seed_video_ids: tuple[str, ...]
    prompt: str


def load_video_embeddings(path: Path) -> dict[str, np.ndarray]:
    """Load normalized CLAP vectors keyed by YouTube video ID."""
    with np.load(path, allow_pickle=False) as raw:
        if not {"ids", "vectors"}.issubset(raw.files):
            raise ValueError(f"{path}: expected ids and vectors arrays")
        ids = [str(value) for value in raw["ids"]]
        vectors = normalized_vectors(raw["vectors"])
    if len(ids) != len(vectors) or len(set(ids)) != len(ids):
        raise ValueError(f"{path}: invalid or duplicate video IDs")
    return dict(zip(ids, vectors))


def load_partial_examples(inputs_path: Path, prompts_path: Path) -> list[PartialExample]:
    """Join public seed inputs to frozen prompt labels by example ID."""
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    if any("held_out_tracks" in row for row in inputs.get("examples", [])):
        raise ValueError("inputs must not include held-out tracks")
    prompt_rows = json.loads(prompts_path.read_text(encoding="utf-8")).get("examples", [])
    prompts = {str(row["example_id"]): row["prompt"] for row in prompt_rows}
    examples = []
    for row in inputs.get("examples", []):
        example_id = str(row["example_id"])
        prompt = prompts.get(example_id)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"example {example_id}: missing frozen prompt")
        seed_ids = tuple(track["video_id"] for track in row.get("seed_tracks", []))
        if not seed_ids:
            raise ValueError(f"example {example_id}: no seed video IDs")
        examples.append(PartialExample(example_id, seed_ids, prompt))
    if set(prompts) != {example.example_id for example in examples}:
        raise ValueError("prompt labels and partial inputs have different example IDs")
    return examples


def load_reference_candidate_ids(path: Path) -> set[str]:
    """Return the public reference-pool tracks eligible for recommendation."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    candidates = {
        track["video_id"]
        for prompt in raw.get("prompts", [])
        for playlist in prompt.get("playlists", [])
        for track in playlist.get("tracks", [])
        if isinstance(track, dict) and track.get("video_id")
    }
    if not candidates:
        raise ValueError(f"{path}: no reference candidate IDs")
    return candidates


def candidate_matrix(embeddings: dict[str, np.ndarray], candidate_ids: set[str]) -> tuple[tuple[str, ...], np.ndarray]:
    """Select embedded public candidates in stable ID order."""
    ids = tuple(sorted(candidate_ids & set(embeddings)))
    if not ids:
        raise ValueError("none of the candidate IDs have embeddings")
    return ids, np.stack([embeddings[video_id] for video_id in ids])
