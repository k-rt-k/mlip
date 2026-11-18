# Field Evaluation Design and Model Revision

**Due:** Thursday, November 19, 2026, 11:30pm.

Connect model evaluation to task evaluation. How would we know that the model
helps people achieve the goals of the task?

## Part 1: Revise previous submissions

Revise the Initial ML Solution and Baselines based on course feedback.

1. Specify one model metric to rank models by. If it combines multiple
   components, explain how they produce one number. Specify one task metric.
2. Use a model selection methodology that matches deployment. State what is
   held out and what the system should generalize to.
3. Explore a sufficiently large model and hyperparameter space.

## Part 2: Field evaluation design (5 points)

In two pages, design the randomized controlled experiment you would run to test
whether the system works for its intended task in deployment.

1. **Causal question.** Does the system improve a specified outcome for a
   specified population compared with what happens today?
2. **Unit of randomization.** Specify the unit (person, group, or other) and
   justify the choice.
3. **Trial arms.** Specify the number of variations, what they are, and the
   control arm.
4. **Primary outcome.** Define the main outcome.
5. **Secondary outcomes.** Describe any additional outcomes to measure and report.
6. **Power.** Give the minimum detectable effect at the realistically available
   sample size and the required sample size for the expected effect. State
   explicitly: “To detect an **X** effect on **[primary outcome]** at 80% power,
   we need **N** units per arm, which at our rate of **U** units per
   [day/week/month] is **W** weeks.”
7. **Risks.** Identify threats to validity specific to the design and give a
   concrete mitigation for each.

## Part 3: Pilot field evaluation (5 points)

Run the smallest version of the design that works end to end. Report what
happened for each component of Part 2, including the observed results. Explain
why the full-scale evaluation could not be run.
