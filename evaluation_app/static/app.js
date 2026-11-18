"use strict";

const element = (id) => document.getElementById(id);
const promptInput = element("request");
const searchInput = element("search");
const player = element("player");
const playerDialog = element("player-dialog");
const previewAudio = element("preview-audio");
const previewButton = element("preview-button");
const previewStatus = element("preview-status");
const feedbackDialog = element("feedback-dialog");
const paired = document.body.dataset.setup === "paired";

let state = { started: false, finished: false, playlist: [], round: null };
let searchResults = [];
let searching = false;
let working = false;
let recommending = false;
let seedTimer;
let playingTrack;

async function api(path, body) {
  const response = await fetch("/api/" + path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text) item.textContent = text;
  return item;
}

function button(text, action, className = "secondary", label) {
  const item = node("button", className, text);
  item.type = "button";
  if (label) item.setAttribute("aria-label", label);
  item.addEventListener("click", action);
  return item;
}

function showError(error) {
  const alert = element("error");
  alert.textContent = error ? error.message : "";
  alert.hidden = !error;
}

function key(track) {
  return track.recording_key || track.video_id;
}

function containsTrack(track) {
  return state.playlist.some((seed) => seed.video_id === track.video_id || key(seed) === key(track));
}

function trackRow(track, actions, showBadge = false) {
  const item = node("li", "track-row");
  const art = node("div", "art");
  const image = node("img");
  image.alt = "";
  image.loading = "lazy";
  image.src = "https://i.ytimg.com/vi/" + track.video_id + "/default.jpg";
  art.append(image);
  const details = node("div");
  const name = node("p", "track-title", track.title);
  details.append(name, node("p", "track-artist", track.artists.join(", ")));
  if (showBadge && track.seed_eligible) {
    details.append(node("span", "badge", "✦ Can guide recommendations"));
  }
  const choices = node("div", "track-actions");
  choices.append(...actions);
  details.append(choices);
  item.append(art, details);
  return item;
}

function play(track, panel) {
  playingTrack = track;
  previewButton.hidden = !key(track).startsWith("isrc:");
  previewButton.disabled = false;
  previewStatus.textContent = "";
  element("player-title").textContent = track.title;
  element("external-play").href = "https://music.youtube.com/watch?v=" + track.video_id;
  player.src = "https://www.youtube-nocookie.com/embed/" + track.video_id + "?autoplay=1";
  playerDialog.showModal();
  if (panel) {
    api("action", {
      action: "play", round_id: state.round.id, position: panel.position, video_id: track.video_id,
    }).catch(showError);
  }
}

function playButton(track, panel) {
  return button("▶ Play", () => play(track, panel), "secondary", "Play " + track.title);
}

function current(response) {
  state = { ...state, ...response };
  sync();
}

async function mutate(path, data) {
  if (working || recommending) return false;
  showError(null);
  working = true;
  sync();
  try {
    current(await api(path, data));
    return true;
  } catch (error) {
    showError(error);
    return false;
  } finally {
    working = false;
    sync();
  }
}

function decide(track, panel, action) {
  return mutate("action", {
    action, round_id: state.round.id, position: panel.position, video_id: track.video_id,
  });
}

async function add(track) {
  if (!await mutate("playlist", { action: "add", selection: track.selection })) return;
  clearTimeout(seedTimer);
  if (!promptInput.value.trim()) {
    seedTimer = setTimeout(() => {
      if (!promptInput.value.trim() && state.playlist.length) recommend();
    }, 500);
  }
}

function renderPlaylist() {
  const songs = state.playlist;
  const size = songs.length;
  const eligible = songs.filter((track) => track.seed_eligible === true).length;
  const unknown = songs.some((track) => track.seed_eligible == null);
  element("track-count").textContent = size + (size === 1 ? " song" : " songs");
  element("empty-playlist").hidden = size > 0;
  element("empty-playlist-copy").textContent = paired && !state.round
    ? "Keep a suggestion to start your playlist."
    : "Keep a suggestion or add a song to start your playlist.";
  const coverage = element("coverage");
  coverage.hidden = size === 0;
  coverage.textContent = unknown ? "Embedding availability is temporarily unknown for some songs."
    : eligible + " of " + size + " playlist songs can guide audio recommendations.";
  element("playlist").replaceChildren(...songs.map((track) => {
    const remove = button("Remove", () => mutate("playlist", { action: "remove", video_id: track.video_id }),
      "secondary", "Remove " + track.title);
    remove.disabled = working || recommending;
    return trackRow(track, [playButton(track), remove], true);
  }));
}

function renderSearch() {
  element("search-results").replaceChildren(...searchResults.map((track) => {
    const inPlaylist = containsTrack(track);
    const addButton = button(inPlaylist ? "Added" : "Add", () => add(track), "secondary", "Add " + track.title);
    addButton.disabled = inPlaylist || working || recommending;
    return trackRow(track, [playButton(track), addButton], true);
  }));
}

function renderPanels() {
  const container = element("panels");
  const label = element("round-label");
  if (!state.round) {
    label.textContent = "";
    container.replaceChildren(node("div", "panel empty-panel",
      "Suggestions will appear here after your first request."));
    return;
  }

  const modes = {
    text_only: "Text request",
    text_and_playlist: "Text + playlist",
    playlist_only: "Playlist only",
  };
  label.textContent = modes[state.round.mode];
  container.replaceChildren(...state.round.panels.map((panel, index) => {
    const section = node("section", "panel");
    if (paired) {
      const heading = node("h3", "", index === 0 ? "Panel A" : "Panel B");
      section.append(heading);
    }
    if (!panel.offers.length) {
      const messages = {
        not_applicable: "This panel can suggest songs from a text request alone or from your playlist alone.",
        unavailable: "Suggestions are temporarily unavailable.",
        ok: "No suggestions for this round. Try another request or add a song that can guide recommendations.",
      };
      section.append(node("p", "small", messages[panel.status]));
      return section;
    }
    const list = node("ul", "track-list");
    for (const track of panel.offers) {
      const actions = [playButton(track, panel)];
      if (track.decision) {
        actions.push(node("span", "decision", track.decision === "keep" ? "Kept" : "Rejected"));
      } else {
        for (const [label, action] of [["Keep", "keep"], ["Reject", "reject"]]) {
          const control = button(label, () => decide(track, panel, action),
            "secondary " + action, label + " " + track.title);
          control.disabled = working || recommending;
          actions.push(control);
        }
      }
      list.append(trackRow(track, actions));
    }
    section.append(list);
    return section;
  }));
}

function sync() {
  element("intro").hidden = state.started;
  element("workspace").hidden = !state.started || state.finished;
  element("finished").hidden = !state.finished;
  element("end-session").hidden = !state.started || state.finished;
  element("end-session").disabled = working || recommending;
  if (!state.started || state.finished) return;
  element("suggest").disabled = working || recommending || (!promptInput.value.trim() && !state.playlist.length);
  element("request-help").textContent = !state.playlist.length
    ? "Start with a request in your own words."
    : "Refine your request, or leave it blank for playlist-based suggestions.";
  element("search-form").hidden = paired && !state.round;
  const checkpoint = state.round?.number === 5;
  element("checkpoint-form").hidden = !checkpoint || state.round_five_rating != null;
  element("checkpoint-status").hidden = !checkpoint || state.round_five_rating == null;
  renderPlaylist();
  renderSearch();
  renderPanels();
}

async function recommend() {
  clearTimeout(seedTimer);
  if (working || recommending) return;
  const prompt = promptInput.value;
  if (!prompt.trim() && !state.playlist.length) return;

  recommending = true;
  showError(null);
  element("suggestion-status").textContent = "Finding suggestions…";
  sync();
  try {
    const result = await api("recommend", { prompt });
    const offered = result.round.panels.reduce((sum, panel) => sum + panel.offers.length, 0);
    if (offered && promptInput.value === prompt) promptInput.value = "";
    current(result);
    element("suggestion-status").textContent = offered ? "New suggestions are ready." : "";
  } catch (error) {
    showError(error);
    element("suggestion-status").textContent = "";
  } finally {
    recommending = false;
    sync();
  }
}

element("start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const startButton = event.submitter;
  startButton.disabled = true;
  showError(null);
  try {
    const arm = element("arm");
    current(await api("session", { consent: element("consent").checked, arm: arm ? arm.value : null }));
    promptInput.focus();
  } catch (error) {
    showError(error);
  } finally {
    startButton.disabled = false;
  }
});

element("request-form").addEventListener("submit", (event) => {
  event.preventDefault();
  recommend();
});
promptInput.addEventListener("input", () => {
  if (promptInput.value.trim()) clearTimeout(seedTimer);
  element("suggest").disabled = working || recommending || (!promptInput.value.trim() && !state.playlist.length);
});

element("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query || searching) return;
  searching = true;
  const searchButton = event.submitter;
  searchButton.disabled = true;
  const status = element("search-status");
  status.textContent = "Searching…";
  try {
    searchResults = (await api("search", { query })).tracks;
    renderSearch();
    status.textContent = searchResults.length ? "" : "No songs found.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    searching = false;
    searchButton.disabled = false;
  }
});

element("close-player").addEventListener("click", () => playerDialog.close());
playerDialog.addEventListener("close", () => {
  playingTrack = undefined;
  player.hidden = false;
  player.removeAttribute("src");
  previewAudio.pause();
  previewAudio.removeAttribute("src");
  previewAudio.hidden = true;
});
previewButton.addEventListener("click", async () => {
  const track = playingTrack;
  if (!track) return;
  previewButton.disabled = true;
  previewStatus.textContent = "Finding a Deezer preview…";
  try {
    const result = await api("preview", { video_id: track.video_id, selection: track.selection });
    if (playingTrack !== track) return;
    player.removeAttribute("src");
    player.hidden = true;
    previewAudio.src = result.url;
    previewAudio.hidden = false;
    previewStatus.textContent = "30-second Deezer preview";
    previewAudio.play().catch(() => {});
  } catch (error) {
    if (playingTrack === track) previewStatus.textContent = error.message;
  } finally {
    if (playingTrack === track) previewButton.disabled = false;
  }
});
element("end-session").addEventListener("click", () => feedbackDialog.showModal());
element("close-feedback").addEventListener("click", () => feedbackDialog.close());
element("checkpoint-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const rating = Number(element("checkpoint-rating").value);
  mutate("checkpoint", { rating, round_id: state.round.id });
});
element("feedback-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  const errorMessage = element("feedback-error");
  submit.disabled = true;
  errorMessage.textContent = "";
  try {
    const rating = element("rating").value;
    current(await api("finish", { rating: rating ? Number(rating) : null, comments: element("comments").value }));
    feedbackDialog.close();
  } catch (error) {
    errorMessage.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
element("new-session").addEventListener("click", () => {
  element("consent").checked = false;
  element("rating").value = "";
  element("checkpoint-rating").value = "";
  element("comments").value = "";
  promptInput.value = "";
  searchInput.value = "";
  searchResults = [];
  element("search-status").textContent = "";
  element("suggestion-status").textContent = "";
  current({ started: false, finished: false, playlist: [], round: null });
});

api("session").then(current).catch((error) => {
  sync();
  showError(error);
});
