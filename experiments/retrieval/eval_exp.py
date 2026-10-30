import argparse
import pandas as pd

def analyze_results(csv_path, top_n=10, metric="ndcg@5"):
    df = pd.read_csv(csv_path)

    metrics = [
        "hit_rate@5",
        "map@5",
        "ndcg@5",
        "precision@5",
        "recall@5",
    ]

    df["model"] = (
        df["prediction_file"]
        .str.replace(r"^.*[/\\]", "", regex=True)
        .str.replace(".json", "", regex=False)
    )

    for seed_count in sorted(df["seed_count"].unique()):
        subset = df[df["seed_count"] == seed_count]

        print(f"\n{'=' * 80}")
        print(f"BEST MODELS — {seed_count} SEEDS")
        print(f"{'=' * 80}")

        best = subset.sort_values(metric, ascending=False).head(top_n)
        print(best[["model"] + metrics].to_string(index=False))

    avg = (
        df.groupby("model", as_index=False)[metrics]
        .mean()
        .sort_values(metric, ascending=False)
    )

    print(f"\n{'=' * 80}")
    print("BEST MODELS — AVERAGE ACROSS SEED COUNTS")
    print(f"{'=' * 80}")
    print(avg.head(top_n).to_string(index=False))

    print(f"\n{'=' * 80}")
    print("BEST CONFIGURATION FOR EACH METRIC")
    print(f"{'=' * 80}")

    for m in metrics:
        best = avg.loc[avg[m].idxmax()]
        print(f"{m:15s}: {best['model']} ({best[m]:.6f})")

    avg.to_csv("ranked_results.csv", index=False)
    print("\nSaved all ranked configurations to ranked_results.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--metric", default="ndcg@5")
    args = parser.parse_args()

    analyze_results(args.csv_path, args.top_n, args.metric)