### What this is for

Before you build a model, you need to know what it has to beat. This assignment asks you to implement simple, reasonable approaches to your problem and measure their performance. The baselines you implement here are not strawman approaches - they're often the approach that turns out to be hard to beat in practice, And they're what your later ML results will be compared with.

### What to submit

A **short writeup (PDF), plus a link to your code on GitHub.&#xA0;**&#x4D;ake sure the TAs and Instructor can access your GitHub repository.

#### Part 1 · Revised proposal

Update your proposal submission (just the ones that were given a 1) based on our feedback, especially your baselines (questions 8 and 9).\
\
For each revised answer, include the original, your revision, and a sentence on what changed. As the grading policy states, revised answers are re-scored: a 1 you fix becomes at least a 2, and a strong revision can earn a 3.

#### Part 2 · Evaluation setup

**Your split.** How did you divide the data into training and test sets, and why that split matches how the model would actually be used. If you don't have or plan to use training data, you still need to explain what your validation or test sets are. 

**Your metric, with its constraints.** "Precision" alone isn't enough since it's trivial to maximize without a constraint. You should list  the metric and the constraint: *"precision at the top 200 postings per week."*

This split and metric are what you'll evaluate your ML models on later in the semester, so it's important to get them right.

#### Part 3 · Your baselines

**A · A non-ML baseline (required).** What happens today or is easily available, or the simplest rule or heuristic someone could apply without a model. If current practice exists, you should implement that.

**B · A zero-shot LLM baseline (required where appropriate).** How does an off-the-shelf LLM perforn? This is increasingly the baseline many people actually compare against, so it's worth knowing whether your problem needs anything more.

If it's not appropriate, say why in one or two sentences, and (optionally) implement a simple ML baseline instead (logistic regression or a shallow decision tree on a handful of features). You don't need to do a simple ML baseline now - you can do it as part of the next assignment.

For each baseline, describe it in a sentence or two: what it does, and why it's a good baseline.

**If your metric needs a ranking** (precision@k and similar), a baseline or LLM that answers yes/no won't give you one. You'll need to produce a score or ranking and explain how you did it.

**For the LLM baseline, record the model, its version, and the prompt you used.** 

#### Part 4 · First-pass results

Report each baseline's performance on your split, using your metric from Part 2.

This is a first pass. We're not grading how good the results are, but whether it's the right metric and it's measured correctly.

#### Part 5 · What this tells you

A short paragraph:

- How hard will your baselines be to beat?
- How much better does your model need to be for it to be worth deploying?

### What we're looking for

- Is the non-ML baseline appropriate - something someone might actually do, rather than a strawman?
- Does the split match how the model would be used?
- Is the metric derived from the decision, with a constraint and a number?
- Are all baselines measured on the same test split, with that metric?
- For the LLM baseline: is it done well? If you didn't run one, is the reason convincing?
- Did you take the proposal feedback and update your approach?

### Things not to do

**"Random" as your only baseline.** Random is a sanity check, not a baseline. Organizations deploying ML don't otherwise make random decisions. They compare against what they already do, or could do easily and cheaply.

**A strawman.** If your baseline is deliberately weak, your model will look artificially good. Make it the strongest simple approach you can (including writing a reasonable prompt for the LLM).

**Evaluating baselines differently from your model.** Use the same data, split, and metrics.

**Ignoring ties.** A rule like "recommend something they've liked before" produces binary outcomes or ties. Decide how you break them; otherwise, your metric depends on an arbitrary ordering
