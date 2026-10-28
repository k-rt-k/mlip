# Initial ML Solution

**This is a team assignment.**

**Due:** Thursday, October 29, 2026, 11:59pm.

This project assignment builds on the baseline assignment and asks you to build
a more robust ML solution and find out whether it is better than the baseline(s)
(measured the same way, on the same data). Make sure to update anything flagged
in the previous assignment before starting this one.

## What to submit

A writeup (PDF), plus a **link to your code on GitHub (make sure we can access it)**.

### Part 1: Revision from your last assignment

Revise anything that was flagged in your previous assignment. State what changed
and why.

### Part 2: Current evaluation setup

1. The task metric, with its unit and population.
2. The model metric, and the capacity or cost constraint it comes from.
3. The validation setting you compute it in, and why that setting is what
   deployment looks like.
4. Why does a model that does best on (2) under (3) do well at (1)? What would
   have to be true for that to be wrong?

These must be the same ones you used for your baselines. If you have a good
reason to change either, say what changed, why, and re-run your baselines on the
new setup so the comparison is still fair.

### Part 3: Modeling methodology

How you got from raw data to a trained model: how the data was processed, what
features (if any) you built and why, how you handled missing values and outliers,
and anything you did to prevent leakage.

Be explicit about what is computed when. Every feature/context/data provided to
the model must be computable using only data available at the time of prediction.

### Part 4: Models and hyperparameters explored

Which model families did you try (including foundation models)? Which ones did
you consider but decided not to run?

List everything you ran, not just the ones that worked well.

For each model family: which hyperparameters you tuned, over what range, and how
many trials you ran. If you used any defaults for any hyperparameters, state
which ones, and why.

### Part 6: Model selection methodology

How did you choose the final model? What did you compare, on what data, using
what metric?

### Part 7: Results (and comparison to baselines)

A table with your baselines and your ML models, on the same split, using the
same metric.

- How much better is your model, and is that enough to deploy?
- Where does your model do worse than the baseline? Any subsets of the data
  where the baseline is better (by time, geography, or other attributes)?

## What we're looking for

1. Is the split and metric the same as your baselines, or properly re-run?
2. Did you explore a reasonable set of models and hyperparameters?
3. Did the model selection methodology match the deployment setting and was the
   final model chosen correctly?
4. Is the comparison to baselines fair?
5. Do you know what your results mean for the task you're tackling (not just the
   ML metric but the task)?

## Important

- If something didn't finish running, report what you have and say what's
  missing. That's a normal state for a project at this stage.

*Part numbering follows the supplied assignment; no Part 5 was provided.*
