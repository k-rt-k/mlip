# Project Scope: Natural-Language Music Playlist Recommendation

This is the stable project reference: the original submitted proposal below is
preserved verbatim from the copy supplied by Harsh on **2026-10-04**. Its claims,
assumptions, and terminology describe the submission, not verified current facts.

Keep the submitted text unchanged. Add occasional, explicitly agreed changes to
project goals, boundaries, data strategy, or evaluation approach in the separate
scope amendments section. Implementation progress, dataset inventories, owners,
experiments, blockers, and remaining tasks belong in [STATUS.md](STATUS.md).
Do not update this document merely because work has been completed.

## Original Submitted Proposal

1. The problem: what problem are you solving, how big is it, and for whom? How many people or organizations does it affect? How much does it affect them?*
Who has this problem today, and what do they do about it right now? Make sure to name a person or a role (e.g. fraud auditors or home cooks or drivers ) (limit: 1500 characters)
A: 
Building/Curating a music playlist involves some combination of manual effort (by discovery or following trends) or by suggestions from a recommender based on listening history and what is generally trending. And there isn’t much control that the recommenders give you, in terms of mood or genre specification.
We want to build a system that can assist in this task. The user could obtain recommendations given natural language and optionally existing songs in a playlist, and receive suggestions. This can be envisioned as an iterative process, like a chatbot.
Potential profiles of users that might appreciate this would be - (1) users wanting to discover new songs/expand their taste, (2) people building playlists for personal events (house parties, etc.) (3) curating music for other media
A second possible benefit (which we won’t explicitly promise yet) could be for smaller artists, who might not rank high with traditional recommendation systems.
There are over 770million (300m paid) and 2billion (100m paid) users for spotify and youtube music respectively. The market that is actually interested in this feature would be much smaller and harder to quantify, but nonetheless huge given the scale of users.

2. The goal: what outcome are you trying to change if you're successful?*
Complete the sentence: "We are trying to change ______, measured by ______." It must be measurable by someone other than you. Be specific and concrete. (limit: 1500 characters)
A: We are trying to change the way users curate playlists. Instead of relying on the song suggested by the spotify recommendation algorithm, we propose a novel method where the user can interact with our system in plain english to curate the playlist matching what they want to listen to! The impact of our system can be measured by a user satisfaction survey, which would help validate the idea (and our execution for it) of building playlists using natural language, something which Spotify doesn’t currently support!
3. The action: what happens when your system produces an output?*
When the system flags or recommends something, WHO does WHAT? How often? (limit: 1500 characters)
A: 
The user accepts the song suggestions into their playlist, or they listen to it and refine their wants. 
4. Capacity — how many can they do?
This number determines your metric. If you cannot figure it out, you may not have scoped the project well. Your project may not have a capacity constraint, but that is unlikely — if you decide it does not apply, state that and be very thorough about why.


4a. They can act on X (a number) per Y (Day/week/month/session/cycle...)*
How many items can be acted on in one period? what is that period?
A: Roughly 1-5 song suggestions per min.
4b. What is the justification for that number*
Where does it come from? Staff time, budget, screen slots, review hours? (limit: 500 characters)
A: It depends on if the user is adding a couple songs to an already created playlist, in which case they might take ~ 30 seconds (or even longer) to listen to a portion of the song before approving. If they are creating a playlist from scratch with just english descriptions, they might only look at song titles to recognize ones they already know and quickly judge if they fit the theme, in which case they could review up to 5 songs in a minute. 


Data and analysis
5. The data: what will you use, and do you have it now? What evidence do you have that it is sufficient and reliable?*
What is/are the data source(s)? Do you have it today, or can you get it by when? What is your fallback if you cannot? (limit: 1500 characters)
A: 
Music Features:
Spotify used to give songs features (danceability/valence/energy/mood/etc.) via its API, which was deprecated a few years ago. There are other api services that provide these features, but they have limited coverage, especially for new songs.
We instead focus on a different source – we can obtain preview snippets for free (via Deezer or Soundcloud), and can use music embedding models to generate meaningful representations. 
We plan on using (with finetuning) existing open source joint music-text embedding models (see below), but we also have datasets as fallback (see MusicSem below) should we have to do more training ourselves.
For learning associations among songs for the playlist, we could also rely on community mirrors for the million playlist dataset from Spotify. This helps us incorporate information from existing songs present in the playlist before making a recommendation.
MusicSem dataset: For a song, contains descriptive, atmospheric, situational, metadata-related, and contextual text about the song. This is helpful for getting a correlation between song and its textual description
User Data: We do not have, and will not use user data for recommendations because of availability and privacy issues. The spotify API does allow us to see exact playback data for songs with authorisation. We may explore that as a way for better evaluation/feedback, but we would not be able to get enough users to sign up, so we will only take explicit feedback for eval.
6a. The ML analysis: which do you need?*
A: We need the Spotify Million Playlist dataset mirror for sure as that is the core substance used for recommendation. In order to get song feature embeddings, using Deezer or Soundcloud is necessary. 
6b. Why those, and why not the others?*
Given the goal, action and data — explain why the ones you selected fit, and why the others do not. (limit: 1500 characters)
A: Spotify API for giving music embeddings would have been really helpful but as it is depreciated we cannot use it. Another dataset MusicCaps contains captions written by musicians. However the dataset is small and captions differ from what actual users would write. We also plan on using large scale pretrained foundation models such as CLaMP (https://ai-muzic.github.io/clamp/) which is pre-trained on WebMusicText (WebMT), a dataset of 1.4 million music-text pairs. By utilizing such foundation models directly we avoid having to interface with large scale datasets such as WebMT. We also avoid datasets like LAION-Audio-630K which contain general audio-text pairs instead of specific music-text pairs, since our downstream use case is to recommend music directly and general audio pretraining might be detrimental.
Predict is the choice that fits best here. Given an input of a set of songs already present in the playlist and a plain English description of what kind of songs the user wants and the model will predict the top K songs that would be best to add to the playlist. The others don't really apply. We are not describing the contents of the song, nor are we detecting anything. We're also not generating new songs based on the description, and nor are we trying to change the outcome through an intervention.


Evaluation, baseline, and the non-ML version
7. How would you know it worked?*
How would you know the model worked? And beyond the model: what would you observe in the world 3 / 6 / 9 / 12 months after launch? Who would you test with (prospectively), and how many? (limit: 1500 characters)
A: We would know if the model worked if we see regular user traffic and positive feedback on song recommendations during our evaluation studies. We do not expect any divergence from real world data a few months after the launch except that our model would not recognize new songs unless we update our retrieval index periodically. For testing, we plan to create a website or app and share it with fellow students and ask them to create playlists and test out our tool! We could collect feedback/rating, or track usage if we are building them a public playlist. We are aiming for feedback from at least 40 participants.
8. The non-ML baseline*
What is the simplest rule, sort, filter, checklist, or current practice that partly solves this? What does ML add over it? (limit: 1500 characters)
A: Currently, a user would have to find existing playlists naively that would match the vibe/prompt they have in mind. Streaming platforms currently do not expose any search or retrieval functionality that allow you to create playlists from text input.
9. A simple ML baseline — what is it, and by how much should you beat it?*
What simple ML model could you use as an additional baseline? How much better than it do you need to be for this to be worth deploying? (limit: 1500 characters)
A: A simple ML baseline would be computing keyword overlap between the words present in the instruction and song metadata. This is really easy to deploy, so our more complex strategy of using embedding based recommendation, would have to outperform this approach by a significant margin (over 20%).
10. Biggest risk*
In one or two sentences: what is most likely to make this fail? Use the failure modes from week 1. (limit: 500 characters)
A: Metric mismatch is most likely. The end factor we want to improve is user satisfaction. However the only evaluation approaches available to us are about  which might not directly correlate with users liking the suggestion. Another failure mode is data (in our case more like reliance on an embedding model upstream). If the embedding model is not good with certain kinds of music or cannot properly work with song snippets and casually typed descriptions, our retrieval would be off.
11. Ethical Considerations: What are some of the ethical considerations that need to be taken into account within your project? Think about privacy issues, data security, bias/discrimination, accountability, and transparency.. What will you do about those issues? (limit: 1500 characters)


A:
Two main ethical considerations that arise in this project are user privacy and bias. To protect privacy, the recommender should not collect, store, or require personally identifiable user data. Prompts should only be used to generate recommendations and not be used in any other manner. 

Another major concern is bias in the recommended playlist. Recommendation systems can unintentionally favor certain genres, artists, or cultures based on the data they are trained on. To address this, we can test the recommender using a diverse range of prompts and evaluate whether it consistently favors certain types of music. 

## Agreed Scope Amendments After Submission

These decisions supplement the submission; they do not rewrite it.

- **Initial baseline evaluation:** use offline playlist-based proxies before
  participant ratings are available. Explicit user satisfaction and feedback
  remain the intended product evaluation; playlist overlap or co-occurrence
  provides supporting evidence, not proof that users like recommendations.
  Specific proxy formulas remain to be agreed by the evaluation owners.
- **Baseline data source:** use public playlists discovered through YouTube
  Music for the initial milestone, rather than requiring Spotify MPD access for
  this stage. MPD and audio-preview/music-text embedding approaches remain part
  of the proposed longer-term modeling direction. Music discovery can return
  playlists also accessible on YouTube; it is not general YouTube search.
- **Baseline input modes:** cover prompt-only generation and partial-playlist
  continuation; also consider an LLM with prompt + partial inputs. A suitable
  evaluation approach for the combined mode remains an open design decision.
- **Partial-playlist evidence:** provide only retained seed songs to a
  partial-only recommender and keep removed songs as hidden reference positives.
  Platform continuation uses seed-only copies with neutral titles/descriptions,
  so the full source playlist is not supplied as task context.
