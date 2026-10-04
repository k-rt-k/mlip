# Initial Spotify Recommendation + Playlist Builder Idea

Historical week-0 notes. See [docs/SCOPE.md](docs/SCOPE.md) for the current
project scope and [docs/STATUS.md](docs/STATUS.md) for progress.

- Spotify recommendations are typically repetitive, and in our personal experience, and don’t feel very personalised
- It also does not really take into account how exploratory we feel at the moment.

**Deliverable:** recommender + playlist builder with more control. A possible avenue, we could be able to chat with the recommender to build the playlist.

The recommender pipeline would have - representation generator, + some playlist constructor that balances exploration/exploitation.

**Challenges:** we will be working with the features given by spotify itself, and we do not have user data that we can learn additional features/similarities from.
