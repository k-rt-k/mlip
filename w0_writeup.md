## Spotify Recommendation + Playlist builder

- Spotify recommendations are typically repetitive, and in our personal experience, and don’t feel very personalised
- It also does not really take into account how exploratory we feel at the moment.

**Deliverable:** recommender + playlist builder with more control. A possible avenue, we could be able to chat with the recommender to build the playlist.

The recommender pipeline would have - representation generator, + some playlist constructor that balances exploration/exploitation.

**Challenges:** we will be working with the features given by spotify itself, and we do not have user data that we can learn additional features/similarities from.

## ML research paper draft reviewer

- Current Conference review process is very slow, with authors often having to wait months for an initial review of their draft. After which they submit rebuttals and directly hear back an accept/reject another few months down the line.
- The feedback loop can be made faster by using historical peer review data (<https://github.com/allenai/PeerRead>) and building a ML system which goes through your draft and gives relevant feedback.

**Deliverable:** a LLM finetuned on historical peer review data, which takes in a research paper draft and gives actionable insights about strengths and weaknesses.

**Challenges:** Evaluating this system is hard, since data of (research paper draft, feedback) is not common.

**Target audience:** CMU grad students, who would find such a tool very useful

**For an initial MVP:** we can build this pipeline for just abstract review instead of the entire paper, this will help with dealing with similar challenges, while keeping compute/token cost low. More importantly, most paper readers first read the abstract to see if a paper is worth reading or not. Having a tool for abstract draft review would be equally as important and would ensure that the abstract is a faithful summary of the entire paper.
