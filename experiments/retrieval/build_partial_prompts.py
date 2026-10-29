"""Freeze prompt labels for the v3 partial-playlist inputs.

The labels are authored from the visible seed-song listings, not from hidden
tracks or source-playlist metadata.  One source-level label is applied to its
paired five- and twenty-seed examples.

    uv run python -m experiments.retrieval.build_partial_prompts \
        --output data/youtube_music/partial_examples/v3/prompt_inputs.json
"""

import argparse
import hashlib
import json
from pathlib import Path


# These descriptions were written after inspecting only model_inputs.json's
# seed tracks.  Keep them fixed while evaluating this task.
PROMPTS_BY_SOURCE = {
    1: "Expressive solo classical piano, from lyrical nocturnes to dramatic virtuoso Romantic-era pieces.",
    2: "Warm vintage jazz, swing, and classic vocal standards for an elegant Italian dinner.",
    3: "Soulful R&B heartbreak ballads by powerful women vocalists, for sitting with a breakup.",
    4: "Current high-energy pop, dance, and club tracks with a glossy, viral-party feel.",
    5: "Warm, wistful indie folk and alternative songs with acoustic textures for an open-road escape.",
    6: "Sophisticated mellow jazz: intimate vocals, piano trios, and relaxed late-night swing.",
    7: "Golden-era 1990s East Coast hip-hop with jazzy samples, sharp flows, and streetwise grooves.",
    8: "Feel-good Spanish-language pop and rock singalongs for a nostalgic night with friends.",
    9: "Atmospheric indie, synth-pop, and alternative tracks for a neon-lit late-night drive.",
    10: "Timeless 1970s and 1980s singer-songwriter, soft-rock, and classic-rock favorites to sing along with.",
    11: "Immersive dark ambient, downtempo electronic, and cinematic soundscapes for a solitary night walk.",
    12: "Gentle classic bossa nova and Brazilian jazz with acoustic guitars, soft vocals, and seaside warmth.",
    13: "Emotional mid-2000s emo, pop-punk, and alternative rock for dramatic teenage nostalgia.",
    14: "Tender 1970s slow-jam soul and R&B love songs with smooth harmonies and a romantic mood.",
    15: "Upbeat early-1980s funk, boogie, and disco-soul for a joyful old-school dance floor.",
    16: "Tender contemporary Hindi indie-pop and acoustic love songs for a reflective, romantic evening.",
    17: "Fast, raw early hardcore punk with confrontational energy and short, urgent songs.",
    18: "Uplifting contemporary Black gospel and praise music with powerful lead vocals and encouragement.",
    19: "Epic cinematic orchestral and choral music for a heroic fantasy battle or movie-trailer moment.",
    20: "Roots reggae and dub from the 1970s and 1980s with deep bass, conscious lyrics, and a laid-back sound-system feel.",
}


def load_examples(path: Path) -> list[dict]:
    """Read the public model inputs; reject anything resembling hidden answers."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    examples = raw.get("examples")
    if not isinstance(examples, list):
        raise ValueError("expected an object with an examples list")
    if any("held_out_tracks" in example for example in examples):
        raise ValueError("prompt construction must use model inputs, never hidden tracks")
    return examples


def build_prompt_inputs(examples: list[dict], prompts: dict[int, str]) -> list[dict]:
    """Attach one nonempty frozen prompt to every paired partial-playlist input."""
    source_ids = {int(example["source_example_id"]) for example in examples}
    if source_ids != set(prompts):
        raise ValueError("source prompt IDs must exactly match source_example_id values")
    by_source: dict[int, list[dict]] = {}
    for example in examples:
        source_id = int(example["source_example_id"])
        by_source.setdefault(source_id, []).append(example)
    for source_id, group in by_source.items():
        if {int(example["seed_count"]) for example in group} != {5, 20}:
            raise ValueError(f"source {source_id} must have exactly 5- and 20-seed inputs")
    return [
        {
            "example_id": int(example["example_id"]),
            "source_example_id": int(example["source_example_id"]),
            "seed_count": int(example["seed_count"]),
            "prompt": prompts[int(example["source_example_id"])],
        }
        for example in examples
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path,
        default=Path("data/youtube_music/partial_examples/v3/model_inputs.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite {args.output}")
    examples = load_examples(args.inputs)
    prompt_inputs = build_prompt_inputs(examples, PROMPTS_BY_SOURCE)
    payload = {
        "schema_version": 1,
        "input_file": str(args.inputs),
        "input_sha256": hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
        "label_policy": "manually authored from visible seed tracks only; one prompt per source example",
        "examples": prompt_inputs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(prompt_inputs)} frozen prompt labels to {args.output}")


if __name__ == "__main__":
    main()
