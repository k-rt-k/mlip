# Final Project Topic

**Submitted:** November 20, 2026.

Each team names the course topic it will implement in the final project (Causal
Inference, Interpretability, Fairness, Distribution and Temporal Shift, or
Uncertainty Quantification), the question it answers, and how to evaluate
whether it helped over the existing ML solution. One line per answer.

## Submitted answers

1. Distribution and Temporal Shift. We'll test for temporal shift by labelling
   catalog and evaluation songs with release dates, then evaluating the deployed
   retrieval separately for each release era. We are interested in finding out
   shifts in songs (musical trends), and shifts in word usage. We expect
   seasonal variations (seasons/holidays) to already be well covered in the data.

2. Does recommendation quality drop for music newer than the catalog? If so, is
   the cause that those songs are missing from the catalog, or that the CLAP
   embeddings represent newer music poorly? Slicing results by era separates the
   two, so we know whether the catalog or the encoder needs updating.

3. Using our existing evaluation harness, we'll compare hit rate, recall and
   catalog coverage across release eras of our reference songs. The study is
   useful if the newer eras show lower quality that we can trace to missing
   catalog songs or to weaker embedding matches.
