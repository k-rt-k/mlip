"""Plot initial-ML-solution figures from saved predictions and result tables.

Run with an interpreter providing matplotlib (plotting is not a project dependency):
    python scripts/plot_initial_ml_results.py --output <overleaf>/figures/initial_ml

Needs the extracted v3 partial dataset for per-input hits. Writes PDF figures:
sweep.pdf (prompt + playlist configurations vs. references), seed_count.pdf
(5 vs. 20 seeds per method), per_input.pdf (hits per source playlist) and
factors.pdf (mean Precision@5 per sweep-factor level).
"""

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation'))
from metrics import calculate_all_metrics  # noqa: E402

DATASET = ROOT / 'data/youtube_music/partial_examples/v3/dataset.json'
SWEEP = ROOT / 'results/prompt_playlist_matrix/evaluation/combined.csv'
# Categorical slots in fixed order (validated: CVD and normal-vision separation pass).
COLORS = {'YouTube Music': '#2a78d6', 'Co-occurrence': '#eb6834', 'Seed-only CLAP': '#1baf7a',
          'Prompt + playlist CLAP': '#eda100', 'Zero-shot LLM (Qwen3.8 27B)': '#e87ba4'}
MARKERS = {'YouTube Music': 'o', 'Co-occurrence': 's', 'Seed-only CLAP': 'D',
           'Prompt + playlist CLAP': '^', 'Zero-shot LLM (Qwen3.8 27B)': 'v'}
PREDICTIONS = {'YouTube Music': 'ytm_native', 'Co-occurrence': 'cooccurrence',
               'Seed-only CLAP': 'seed_only_clap_v1',
               'Prompt + playlist CLAP': 'prompt_playlist_configured',  # hp.yaml default
               'Zero-shot LLM (Qwen3.8 27B)': 'llm_qwen'}
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#e4e3df'


def per_input_scores(examples):
    """{method: {example_id: metrics}} using the shared metric functions."""
    scores = {}
    for label, name in PREDICTIONS.items():
        predictions = json.loads((ROOT / 'predictions' / f'{name}.json').read_text())
        scores[label] = {e['example_id']: calculate_all_metrics(
            predictions.get(str(e['example_id']), [])[:5],
            [t['video_id'] for t in e['held_out_tracks']], k=[5]) for e in examples}
    return scores


def mean(scores, examples, seeds, key):
    rows = [scores[e['example_id']][key] for e in examples if e['seed_count'] == seeds]
    return sum(rows) / len(rows)


def style(plt):
    # Report style: body serif, recessive axes, no in-figure titles (captions carry them).
    plt.rcParams.update({
        'font.family': 'serif', 'font.serif': ['Charter', 'DejaVu Serif'], 'font.size': 8.5,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.linewidth': .6,
        'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED,
        'ytick.color': MUTED, 'xtick.major.width': .6, 'ytick.major.width': .6,
        'legend.frameon': False, 'pdf.fonttype': 42})


def plot_sweep(plt, scores, examples, path):
    """One dot per configuration; reference methods as labelled ticks."""
    rows = list(csv.DictReader(SWEEP.open()))
    fig, axes = plt.subplots(1, 2, figsize=(6.7, 2.0), sharey=True)
    for ax, key, title in zip(axes, ('precision@5', 'hit_rate@5'), ('P@5', 'Hit@5')):
        for y, seeds in enumerate((5, 20)):
            values = sorted(float(r[key]) for r in rows if r['seed_count'] == str(seeds))
            # Stack tied values vertically so all 108 configurations stay visible.
            seen = {}
            for v in values:
                seen[v] = seen.get(v, 0) + 1
                ax.scatter(v, y - .28 + seen[v] * .0055, s=6, color='#9a9994', lw=0, zorder=2)
            # Offset each reference method vertically so tied values stay visible.
            for dy, label in ((.08, 'YouTube Music'), (.2, 'Co-occurrence'), (.32, 'Seed-only CLAP')):
                v = mean(scores[label], examples, seeds, key)
                ax.scatter(v, y + dy, s=30, marker=MARKERS[label], color=COLORS[label], edgecolor='white',
                           lw=.8, zorder=3, label=label if y == 0 and ax is axes[0] else None)
        ax.set_yticks([0, 1], ['5 seeds', '20 seeds'])
        ax.set_ylim(-.45, 1.45)
        ax.invert_yaxis()
        ax.set_xlabel(title)
        ax.grid(axis='x', color=GRID, lw=.5)
        ax.set_axisbelow(True)
        ax.set_xlim(left=0)
    axes[0].scatter([], [], s=6, color='#9a9994', label='Prompt + playlist configurations (108)')
    fig.legend(loc='lower center', ncol=4, bbox_to_anchor=(.5, -.08), fontsize=7.5,
               handletextpad=.3, columnspacing=1.2)
    fig.tight_layout(rect=(0, .1, 1, 1))
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


FACTORS = (('agg', 'Seed query', {'mean': 'Mean', 'prompt_weighted_mean': 'Prompt-weighted mean',
                                        'top_k_mean': 'Top-5 mean'}),
           ('ret', 'Retrieval', {'text_only': 'Text', 'seed_only': 'Seeds',
                                 'early_fusion': 'Early fusion', 'multi_query': 'Multi-query'}),
           ('rank', 'Ranking', {'cosine': 'Cosine', 'weighted_score': 'Weighted score', 'rrf': 'RRF'}),
           ('seed', 'Seed coherence', {'mean': 'Mean', 'max': 'Max', 'top_k_mean': 'Top-3 mean'}))


def plot_factors(plt, path):
    """Mean Precision@5 per level of each sweep factor, averaged over the other factors."""
    rows = list(csv.DictReader(SWEEP.open()))
    for row in rows:
        name = Path(row['prediction_file']).stem
        row.update(dict(part.split('-', 1) for part in name.split('__')))
    fig, axes = plt.subplots(1, 4, figsize=(6.7, 1.9), sharex=True)
    for ax, (key, title, levels) in zip(axes, FACTORS):
        for seeds, face in (('5', INK), ('20', 'white')):
            for y, level in enumerate(levels):
                values = [float(r['precision@5']) for r in rows
                          if r[key] == level and r['seed_count'] == seeds]
                ax.scatter(sum(values) / len(values), y, s=26, facecolor=face, edgecolor=INK,
                           lw=.9, zorder=3, label=f'{seeds} seeds' if y == 0 else None)
        ax.set_yticks(range(len(levels)), list(levels.values()), fontsize=7.5)
        ax.set_ylim(-.6, len(levels) - .4)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=8.5)
        ax.grid(axis='x', color=GRID, lw=.5)
        ax.set_axisbelow(True)
        ax.set_xlim(0, .12)
        ax.set_xticks([0, .05, .1])
    fig.supxlabel('Mean P@5, averaged over the other three factors', fontsize=8.5, y=.14)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, bbox_to_anchor=(.5, -.1), fontsize=7.5)
    fig.tight_layout(rect=(0, .12, 1, 1), w_pad=.6)
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def plot_seed_count(plt, scores, examples, path):
    """Slope chart: each method's metric at five and twenty seeds."""
    fig, axes = plt.subplots(1, 2, figsize=(6.7, 2.4))
    for ax, key, title in zip(axes, ('precision@5', 'hit_rate@5'), ('P@5', 'Hit@5')):
        for label in PREDICTIONS:
            values = [mean(scores[label], examples, seeds, key) for seeds in (5, 20)]
            ax.plot([0, 1], values, color=COLORS[label], lw=2, marker=MARKERS[label],
                    ms=6, mec='white', mew=.8, label=label)
        ax.set_xticks([0, 1], ['5 seeds', '20 seeds'])
        ax.set_xlim(-.2, 1.2)
        ax.set_ylim(bottom=0)
        ax.set_ylabel(title)
        top = max(ax.get_ylim()[1], .01)
        step = .02 if key == 'precision@5' else .1  # tick values exact at two decimals
        ax.set_yticks([round(i * step, 2) for i in range(int(top / step) + 1)])
        ax.yaxis.set_major_formatter(lambda v, _: f'{v:.2f}')
        ax.grid(axis='y', color=GRID, lw=.5)
        ax.set_axisbelow(True)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=5, bbox_to_anchor=(.5, -.06),
               fontsize=7.5, handletextpad=.3, columnspacing=1.0)
    fig.tight_layout(rect=(0, .1, 1, 1))
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


# Short genre labels from the hand-written per-source prompts (build_partial_prompts.py).
SOURCE_LABELS = {1: 'Classical piano', 2: 'Vintage jazz', 3: 'R&B ballads', 4: 'Dance pop',
                 5: 'Indie folk', 6: 'Mellow jazz', 7: '1990s hip-hop', 8: 'Spanish pop',
                 9: 'Synth-pop', 10: '1970s-80s soft rock', 11: 'Dark ambient', 12: 'Bossa nova',
                 13: 'Emo / pop-punk', 14: '1970s soul', 15: '1980s funk', 16: 'Hindi indie-pop',
                 17: 'Hardcore punk', 18: 'Gospel', 19: 'Cinematic orchestral', 20: 'Roots reggae'}


def plot_per_input(plt, scores, examples, path):
    """Hidden songs in the top five per source playlist: seed-only CLAP vs. YouTube Music."""
    fig, axes = plt.subplots(1, 2, figsize=(6.7, 3.6), sharey=True)
    for ax, seeds in zip(axes, (5, 20)):
        group = sorted((e for e in examples if e['seed_count'] == seeds),
                       key=lambda e: e['source_example_id'])
        ys = [e['source_example_id'] for e in group]
        for offset, label in ((-.2, 'YouTube Music'), (.2, 'Seed-only CLAP')):
            hits = [round(scores[label][e['example_id']]['precision@5'] * 5) for e in group]
            ax.barh([y + offset for y in ys], hits, height=.38, color=COLORS[label],
                    label=label, lw=0)
        ax.set_yticks(ys, [SOURCE_LABELS[y] for y in ys], fontsize=7)
        ax.set_xlim(0, 5)
        ax.set_xticks(range(6))
        ax.set_xlabel(f'Hidden songs in top 5 ({seeds} seeds)')
        ax.grid(axis='x', color=GRID, lw=.5)
        ax.set_axisbelow(True)
    axes[0].invert_yaxis()  # shared y-axis: invert once so source 1 is on top
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, bbox_to_anchor=(.55, -.04),
               fontsize=7.5)
    fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    args.output.mkdir(parents=True, exist_ok=True)
    examples = json.loads(DATASET.read_text())['examples']
    scores = per_input_scores(examples)
    style(plt)
    plot_sweep(plt, scores, examples, args.output / 'sweep.pdf')
    plot_seed_count(plt, scores, examples, args.output / 'seed_count.pdf')
    plot_per_input(plt, scores, examples, args.output / 'per_input.pdf')
    plot_factors(plt, args.output / 'factors.pdf')
    for label in PREDICTIONS:  # Printed so the figures can be checked against the result tables.
        print(label, [round(mean(scores[label], examples, s, k), 4)
                      for s in (5, 20) for k in ('precision@5', 'hit_rate@5')])


if __name__ == '__main__':
    main()
