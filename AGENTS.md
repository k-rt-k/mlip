# MLIP Course Project (CMU 10-718: Machine Learning In Practice)

## Project and Current State

Four-person team building a natural-language-guided music playlist recommender.
Input: a text request and optionally songs already in a playlist. Output: ranked
song suggestions that the user can accept or refine through further requests.
The current scope does not use personal listening history for recommendations.
The first baseline milestone covers prompt-only generation and partial-playlist
continuation using public **YouTube Music** playlists (reference dataset v2
assembled for twenty prompts; evaluation decisions belong to the baseline owners).
The LLM also takes prompt + partial inputs; evaluation for that mode remains TBD.

As of **2026-10-05**: the music proposal is documented; Spotify authentication,
inventory, and metadata-enrichment code exists from earlier feasibility work.
The **current stage is baseline comparison and remaining LLM evaluation**; the
four-part milestone checklist is in `docs/STATUS.md`. Harsh's datasets/pipelines
are ready. Spandan's evaluation pipeline, YouTube Music continuation, and
co-occurrence baseline have results on all 40 partial inputs. Ayush's zero-shot
LLM is scored on 20 prompts and all 40 partial inputs; prompt + partial generation
remains pending.
Public search/fetch, local seed/hidden splits, private seed-only creation, and
continuation suggestions have passed live pilot checks. Twenty prompts now have
three cached reference playlists each (60 playlists, 4,475 distinct video IDs),
with tracks, provenance, selection caveats, and available displayed view metadata.
Twenty source playlists have paired five- and twenty-song inputs (40 verified
private copies), with hidden songs saved separately from model inputs. Larger
inputs include the original five seeds; all other source songs are hidden for
each size. Copies are owned by `mlip.team0@gmail.com`. The current partial dataset
is under `data/youtube_music/partial_examples/v3/`; v2 is retained for compatibility.
A credential-free dataset handoff ZIP and checksum manifest are committed under `datasets/`;
extract the ZIP from the repository root as described in `README.md`.
The reported split and primary constrained metric still need agreement;
see `docs/STATUS.md` for artifacts and review caveats. Browser headers are the only
supported account-auth method. Radio Pool is also scored on all 40 inputs; its
399 cached public seed radios, frozen pools, and evaluation are shared in
`datasets/radio-pool-v1.zip`. LLM reranking is a separate deferred experiment.
No embedding pipeline has been completed. Read `docs/STATUS.md` for the latest
results, remaining evaluation work, and open issues.

## Read Before Working

1. `docs/SCOPE.md` — original submitted proposal, preserved verbatim, plus
   separately recorded durable scope amendments. Stable reference for project
   intent; never use it to track implementation progress.
2. `docs/STATUS.md` — concise present state, deliverables, ownership, and remaining
   milestone work. Completed-task summaries appear newest first.

Keep this file short. Put detailed plans and results in the linked documents.
Explicit user instructions take precedence; reconcile affected docs when the
team changes direction. Do not treat historical docs as current requirements.

## Repo Layout

- `spotify/` — existing music API/authentication and feasibility tooling
- `llm/` — zero-shot generation, catalog resolution, and tests
- `evaluation/` — partial-playlist metrics and evaluation runner
- `baselines/` — co-occurrence and Radio Pool baselines, candidate collection, and runners
- `predictions/` — saved co-occurrence, YouTube Music, Radio Pool, and LLM predictions for all 40 inputs (plus LLM prompt-only)
- `youtube_music/` — public playlist collection, seed-only copies, suggestions,
  browser-auth setup, and tests; script docstrings contain usage
- `youtube_music/scripts/setup_auth.py` — paste Copy as fetch (Node.js) input from `mlip.team0@gmail.com` to refresh browser credentials and test authentication; usage is in the file.
- `prompts.txt` — twenty synthetic prompts explicitly requested by the user
- `datasets/` — approved, credential-free baseline and Radio Pool ZIPs with checksum manifests
- `data/` — extracted datasets/local artifacts (gitignored), plus explicitly committed LLM run outputs
- `docs/` — `SCOPE.md`, `STATUS.md`, and existing API/feasibility references
- `milestones/` — descriptions of project milestone deliverables; see `milestones/baselines.md`.
- `scripts/git-hooks/` — secret guards; setup instructions in `README.md`
- `w0_writeup.md` — initial Spotify project idea; current scope is in `docs/SCOPE.md`
- `CLAUDE.md` — existing symlink to this file, sharing the same agent guidance

## Code Conventions

- Flag missing credentials, access, inputs, or unfinished requirements immediately; stop dependent work and ask for what is needed rather than substitute assumptions or present incomplete work as ready.
- **Reuse first.** When writing experiments, use existing code functions. Before
  writing any new function, search the codebase for an existing implementation
  and call that instead.
- **Design for future callers.** If the code doesn't exist yet, reason about
  whether the snippet should be callable in this manner by future work, and
  shape its interface accordingly (vs. keeping it local to the experiment).
- **Modularity and maintainability are priorities** — prefer small, composable
  functions over monolithic scripts.
- **Inline documentation**: short and sweet. Brief docstrings/comments that say
  what and why, nothing verbose.
- **Tests-first applies to shared/library code**, not one-off experiment scripts.

## Shared Documentation

- Maintain just `docs/SCOPE.md` and `docs/STATUS.md` for project coordination.
  Keep task-specific usage and interface details in the relevant source files;
  do not create separate task READMEs or decision logs unless requested.
- Treat `STATUS.md` as a shared present-state board, not an implementation or
  single-session log. Consolidate a teammate's completed task into one concise, dated
  outcome summary: ready deliverables, owner, essential artifact pointers,
  material limitations/blockers, and remaining work. Update the milestone
  checklist to match; do not add entries for intermediate steps (e.g. 10 prompts
  followed by 10 more when the present result is 20).
- Assume teammates share/push updates when a task is complete. Publish one
  completed-task summary, not incremental entries for work within that task.
  Report the final supported setup (e.g. browser authentication), not discarded
  alternatives, failed attempts, debugging milestones, or historical decision
  explanations. Include an unresolved blocker only if it still affects current work.
- New teammates may prepend their own completed-task summaries.
  Revise or merge overlapping entries rather than repeat the same facts. Remove
  superseded or stale summaries as the board grows; preserving every historical
  entry is not a goal. Keep it information-dense and easy to scan. Commands,
  debugging history, and detailed results belong in source docstrings or artifacts.
- Write `STATUS.md` for all teammates, not as an agent memory log. Record project
  facts and ownership neutrally; exclude chat narration, personal agent reminders,
  and instructions restricting the current agent's task. Agent guidance belongs
  here, and usage details belong in source files.
- Keep the submitted proposal in `SCOPE.md` unchanged. Update only its separate
  amendments when the team intentionally changes goals, boundaries, data
  strategy, or evaluation approach (e.g. interim proxies before participant
  ratings). Never put stages, completion counts, test results, owners, blockers,
  or task checklists there. Those belong in `STATUS.md`; keep this overview
  current. Distinguish proposed plans from implementation and verified results.
- Share context through synchronized Git changes, following the user's
  commit/push instructions. Commit only explicitly approved dataset bundles;
  keep extracted data ignored. Never commit secrets, personal histories,
  identifiable feedback, or raw user prompts. The explicitly requested synthetic
  pilot prompts in `prompts.txt` are shared experiment inputs.

## Branch & Worktree Workflow

- **Small features**: commit directly to the current branch.
- **Large features** (multi-file / multi-session work that warrants an
  implementation plan): develop in a git worktree. When writing the
  implementation plan for a large feature, name the worktree in it.
- **When in doubt, ask.** Unless the branch-vs-worktree call is totally obvious,
  ask the user before deciding.
