# MLIP Course Project (CMU 10-718: Machine Learning In Practice)

## Project Overview

Course project for CMU's Machine Learning In Practice. **Current status: deciding
between two project topics** — a final choice has not been made yet (update this
section once the topic is chosen):

1. **Spotify Recommendation System** (`spotify/`) — a recommender + playlist
   builder giving users more control over exploration vs. exploitation.
2. **Peer Reviewer for Academic Papers** (`peer/`) — an LLM-based reviewer
   trained on historical peer-review data (PeerRead), MVP scoped to abstract
   review.

The initial week-0 writeup for both options is in `w0_writeup.md`.

## Repo Layout

- `w0_writeup.md` — w0 writeup covering both candidate topics
- `spotify/` — Spotify recommender work (placeholder until topic is chosen)
- `peer/` — paper-reviewer work (placeholder until topic is chosen)
- `data/` — datasets (gitignored; never commit data)
- `docs/` — headline experiment writeup (created once experiments begin)

## Code Conventions

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

## Documentation (`docs/`)

Maintain a `docs/` folder containing:
- the **headline experiment** writeup, and
- **pointers to relevant code sections and commits** (file paths + commit hashes).

Update `docs/` whenever experiments or interfaces change so it never goes stale.
Creating and updating `docs/` is required project work — it overrides the global
"never proactively create documentation files" rule.

## Branch & Worktree Workflow

- **Small features**: commit directly to the current branch.
- **Large features** (multi-file / multi-session work that warrants an
  implementation plan): develop in a git worktree. When writing the
  implementation plan for a large feature, name the worktree in it.
- **When in doubt, ask.** Unless the branch-vs-worktree call is totally obvious,
  ask the user before deciding.
