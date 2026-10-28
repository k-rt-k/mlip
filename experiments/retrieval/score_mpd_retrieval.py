"""Score saved MPD prompt retrieval trials and export actual recommendations.

  uv run python -m experiments.retrieval.score_mpd_retrieval --runs-dir /data/user_data/hpoonia/mlip/retrieval/mpd-v1/indexes --tracks /data/user_data/hpoonia/mlip/retrieval/mpd-v1/snapshot/tracks.sqlite --output data/retrieval/mpd-v1

Uses all 20 existing prompt references, with upstream Deezer-match ISRC equality
instead of cross-namespace video-ID equality. Unmatched gold remains in the
denominator. Deduplicate recordings in the raw top 100, then score top 1/5/10.
No candidate is added or filtered using relevance. These are development proxy
scores, not held-out estimates or directly comparable to old video-ID scores.
The saved LLM prompt-only baseline is rescored under the same identity policy.
"""

import argparse
import csv
import html
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.recordings import recording_key, score_recordings


def mean_metrics(records):
    """Macro-average existing metric outputs over equally weighted prompts."""
    return {key: sum(r[key] for r in records) / len(records) for key in records[0]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-dir', type=Path, required=True)
    parser.add_argument('--tracks', type=Path, required=True)
    parser.add_argument('--references', type=Path, default=Path('data/youtube_music/references/v2/reference_pools.json'))
    parser.add_argument('--eval-map', type=Path, default=Path('/data/user_data/ksnair/mlip/embeddings/ytm-eval/deezer_map.json'))
    parser.add_argument('--query-manifest', type=Path, default=Path('data/retrieval/real-run/verified-text-queries.json'))
    parser.add_argument('--llm', type=Path, default=Path('predictions/llm_qwen_prompt_only.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prompts = json.loads(args.references.read_text())['prompts']
    evidence = json.loads(args.eval_map.read_text())
    queries = json.loads(args.query_manifest.read_text())
    texts = dict(zip(queries['query_ids'], queries['texts']))
    prompt_by_text = {p['prompt']: p for p in prompts}
    if set(texts.values()) != set(prompt_by_text) or len(texts) != len(prompts):
        raise ValueError('query texts do not exactly match the frozen prompt set')
    gold = {str(p['prompt_id']): {recording_key(evidence.get(v, {}), f'yt:{v}')
                                for v in p['song_support']} for p in prompts}
    reports = []
    for file in sorted(args.runs_dir.glob('build-*/results.json')):
        reports.extend(json.loads(file.read_text()))
    if not reports:
        raise ValueError('no completed benchmark builds found')
    predictions = [json.loads(Path(r['predictions_path']).read_text()) for r in reports]
    wanted = {tid for p in predictions for row in p['song_ids'] for tid in row if tid}
    db = sqlite3.connect(f'file:{args.tracks.resolve()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    metadata = {}
    wanted = sorted(wanted)
    for start in range(0, len(wanted), 800):
        batch = wanted[start:start+800]
        for row in db.execute(f"SELECT * FROM tracks WHERE id IN ({','.join('?' for _ in batch)})", batch):
            metadata[row['id']] = dict(row)
    if set(wanted) != set(metadata):
        raise ValueError('recommendations missing MPD recording provenance')
    gold_isrcs = sorted({k.removeprefix('isrc:') for g in gold.values() for k in g if k.startswith('isrc:')})
    available = set()
    for start in range(0, len(gold_isrcs), 800):
        batch = gold_isrcs[start:start+800]
        available.update('isrc:' + r[0] for r in db.execute(
            f"SELECT DISTINCT isrc FROM tracks WHERE isrc IN ({','.join('?' for _ in batch)})", batch))
    coverage = {pid: dict(reference_recordings=len(g), covered_recordings=len(g & available),
                          fraction=len(g & available)/len(g),
                          ceilings=score_recordings(sorted(g & available), g))
                for pid, g in gold.items()}
    trials = []
    for number, (report, prediction) in enumerate(zip(reports, predictions)):
        per_prompt = {}
        for qid, tids, scores in zip(prediction['query_ids'], prediction['song_ids'], prediction['scores']):
            prompt = prompt_by_text[texts[qid]]
            pid = str(prompt['prompt_id'])
            unique = {}
            for tid, score in zip(tids, scores):
                if tid is None:
                    continue
                info = metadata[tid]
                key = recording_key(info, f'mpd:{tid}')
                unique.setdefault(key, dict(spotify_id=tid, artist=info['artist'], title=info['title'],
                                           isrc=info['isrc'], deezer_id=info['deezer_id'],
                                           cosine_score=score, reference_hit=key in gold[pid]))
            per_prompt[pid] = dict(prompt=prompt['prompt'], metrics=score_recordings(unique, gold[pid]),
                                   recommendations=list(unique.values())[:10])
        if set(per_prompt) != set(gold):
            raise ValueError('trial does not cover every prompt')
        trials.append(dict(trial=number, benchmark=report,
                           mean_cosine_at_5=sum(sum(row[:5])/5 for row in prediction['scores'])/len(prompts),
                           mean_metrics=mean_metrics([p['metrics'] for p in per_prompt.values()]),
                           per_prompt=per_prompt))
    llm = json.loads(args.llm.read_text())
    llm_per_prompt = {pid: score_recordings(
        [recording_key(evidence.get(v, {}), f'yt:{v}') for v in llm.get(pid, [])], g)
        for pid, g in gold.items()}
    result = dict(
        interpretation='20 development prompts; recording-level reference overlap; unmatched gold retained',
        identity_policy='valid ISRC from upstream metadata match, otherwise namespaced ID; duplicates collapsed',
        ranking_policy='first 10 unique recordings from raw top 100; no reference-based filtering',
        coverage=coverage, trials=trials,
        llm_same_policy=dict(mean_metrics=mean_metrics(list(llm_per_prompt.values())), per_prompt=llm_per_prompt),
    )
    eligible = [t for t in trials if t['benchmark']['ann_recall_at_cutoffs']['5'] >= .95
                and t['benchmark']['ann_recall_at_cutoffs']['100'] >= .95]
    result['fastest_at_95pct_ann_recall'] = min(
        eligible, key=lambda t: t['benchmark']['latency_ms']['p95'])['trial'] if eligible else None
    result['best_development_ndcg_at_5'] = max(t['mean_metrics']['ndcg@5'] for t in trials)
    result['quality_ties'] = [t['trial'] for t in trials
                              if t['mean_metrics']['ndcg@5'] == result['best_development_ndcg_at_5']]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'scored-trials.json').write_text(json.dumps(result, indent=2) + '\n')
    with (args.output / 'per-prompt.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['trial', 'prompt_id', 'prompt', 'precision@5', 'hit_rate@5', 'ndcg@5'])
        writer.writeheader()
        for t in trials:
            for pid, p in t['per_prompt'].items():
                writer.writerow(dict(trial=t['trial'], prompt_id=pid, prompt=p['prompt'],
                                     **{k: p['metrics'][k] for k in ['precision@5', 'hit_rate@5', 'ndcg@5']}))
    rows = ['| Trial | Method | nlist / M | nprobe / efSearch | ANN recall@5 / @100 | Mean cosine@5 | P@5 | HR@5 | NDCG@5 | p95 ms | Build s | Index GiB | Peak GiB |',
            '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for t in trials:
        b, m = t['benchmark'], t['mean_metrics']
        c = b['config']
        rows.append(f"| {t['trial']} | {c['method']} | {c['nlist'] or c['m'] or '—'} | {c['nprobe'] or c['ef_search'] or '—'} | {b['ann_recall_at_cutoffs']['5']:.3f} / {b['ann_recall_at_cutoffs']['100']:.3f} | {t['mean_cosine_at_5']:.4f} | {m['precision@5']:.3f} | {m['hit_rate@5']:.3f} | {m['ndcg@5']:.4f} | {b['latency_ms']['p95']:.3f} | {b['construction_seconds']:.1f} | {b['index_file_bytes']/2**30:.3f} | {b['process_peak_rss_bytes']/2**30:.3f} |")
    rows.extend(['', 'LLM prompt-only, rescored under the same recording policy: ' +
                 json.dumps(result['llm_same_policy']['mean_metrics']), '',
                 'All results are development proxy scores. Index memory is serialized size; peak RSS includes loading/training.'])
    (args.output / 'comparison.md').write_text('\n'.join(rows) + '\n')
    body = ['<!doctype html><meta charset="utf-8"><title>MPD prompt recommendations</title>',
            '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}summary{cursor:pointer;padding:12px;background:#eee}li{padding:4px}small{color:#555}</style>',
            '<h1>MPD prompt recommendations</h1><p>Development set · 1,025,994 candidates · ISRC reference-overlap proxy. Cosine similarity is not a probability.</p>']
    for t in trials:
        body.append('<details><summary>Trial ' + str(t['trial']) + ': ' + html.escape(json.dumps(t['benchmark']['config'])) +
                    f" · NDCG@5 {t['mean_metrics']['ndcg@5']:.4f}</summary>")
        for pid, p in t['per_prompt'].items():
            body.append('<h3>' + html.escape(pid + '. ' + p['prompt']) + '</h3><ol>')
            for rec in p['recommendations'][:5]:
                body.append(f'<li><a href="https://open.spotify.com/track/{rec["spotify_id"]}">' +
                            html.escape(rec['artist'] + ' — ' + rec['title']) +
                            f'</a> <small>cosine {rec["cosine_score"]:.4f}' +
                            (' · reference match' if rec['reference_hit'] else '') + '</small></li>')
            body.append('</ol>')
        body.append('</details>')
    (args.output / 'recommendations.html').write_text('\n'.join(body))
    print('\n'.join(rows))
