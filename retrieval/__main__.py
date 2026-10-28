"""Build, query or compare CPU indexes over precomputed embeddings.

Examples (from the repository root, using uv-managed Python 3.12):
  uv run python -m retrieval build --corpus /path/to/mpd-full/clap --method exact --output data/retrieval/exact
  uv run python -m retrieval build --corpus /path/to/clap.npz --method ivf --nlist 256 --nprobe 16 --training-sample-size 50000 --seed 0 --output data/retrieval/ivf
  uv run python -m retrieval build --corpus /path/to/clap.npz --method hnsw --m 32 --ef-construction 200 --ef-search 128 --output data/retrieval/hnsw
  uv run python -m retrieval search --index data/retrieval/hnsw --queries /path/to/text-queries.npz --k 100 --output data/retrieval/hits.json
  uv run python -m retrieval benchmark --corpus /path/to/clap.npz --queries /path/to/text-queries.npz --configs configs.json --k 100 --output data/retrieval/benchmark.json

configs.json is a list of IndexConfig dicts. Exact is included automatically.
Use --artifacts-dir /data/user_data/hpoonia/... to retain full-catalog indexes
and predictions; set TMPDIR on that storage too for files larger than 1 GB.
IVF nlist/training settings and HNSW m/ef_construction changes rebuild indexes;
nprobe or ef_search variations reuse a build. Use --threads consistently.
Input/output IDs retain their namespace; ranking, deduplication and YTM joins
are downstream. The CLI never downloads audio or model weights.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import faiss
import numpy as np

from . import IndexConfig, RetrievalIndex, load_embeddings
from .benchmark import compare


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument(
        "--limit", type=int, help="explicit prefix limit for smoke tests"
    )
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--method", choices=["exact", "ivf", "hnsw"], required=True)
    for name in [
        "nlist",
        "nprobe",
        "training-sample-size",
        "m",
        "ef-construction",
        "ef-search",
    ]:
        build.add_argument("--" + name, type=int)
    build.add_argument("--seed", type=int, default=0)
    search = commands.add_parser("search")
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--queries", type=Path, required=True)
    search.add_argument("--k", type=int, default=5)
    search.add_argument("--nprobe", type=int)
    search.add_argument("--ef-search", type=int)
    search.add_argument("--output", type=Path, required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--corpus", type=Path, required=True)
    benchmark.add_argument("--queries", type=Path, required=True)
    benchmark.add_argument("--configs", type=Path, required=True)
    benchmark.add_argument("--k", type=int, default=5)
    benchmark.add_argument("--repeats", type=int, default=3)
    benchmark.add_argument("--warmups", type=int, default=1)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--artifacts-dir", type=Path, help="new directory retaining indexes and predictions; use data storage")
    for command in (build, search, benchmark):
        command.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    if args.threads <= 0:
        parser.error("threads must be positive")
    faiss.omp_set_num_threads(args.threads)
    try:
        if args.command == "build":
            config = IndexConfig(
                **{
                    name: getattr(args, name)
                    for name in IndexConfig.__dataclass_fields__
                }
            )
            corpus = load_embeddings(args.corpus, limit=args.limit)
            index = RetrievalIndex.build(corpus, config)
            index.save(args.output)
            print(
                json.dumps(
                    {
                        "output": str(args.output),
                        "rows": len(index.ids),
                        "config": asdict(config),
                        "build_info": index.build_info,
                    },
                    indent=2,
                )
            )
            return
        if args.command == "search":
            index = RetrievalIndex.load(args.index)
            index.set_search_parameters(nprobe=args.nprobe, ef_search=args.ef_search)
            queries = load_embeddings(args.queries)
            result = index.search(queries.vectors, args.k)
            report = {
                "query_ids": queries.ids,
                "song_ids": result.song_ids,
                "scores": [
                    [float(x) if np.isfinite(x) else None for x in row]
                    for row in result.scores
                ],
                "rows": result.rows.tolist(),
                "config": asdict(index.config),
                "corpus_fingerprint": index.corpus_fingerprint,
                "queries_fingerprint": queries.fingerprint,
            }
        else:
            configs = [IndexConfig(**c) for c in json.loads(args.configs.read_text())]
            report = compare(
                args.corpus,
                args.queries,
                configs,
                k=args.k,
                repeats=args.repeats,
                warmups=args.warmups,
                threads=args.threads,
                artifacts_dir=args.artifacts_dir,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(f"Saved {args.output}")
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
