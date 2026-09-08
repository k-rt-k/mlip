"""Official venue deadlines: parsing (pure) and merging across sources.

Milestones we care about, all stored as UTC epoch milliseconds:
  submission        paper submission deadline
  review_due        reviewer deadline (reviews exist after this)
  reviews_released  reviews visible to authors; rebuttal window opens
  rebuttal_end      author/reviewer discussion closes
  decision          decision notification

Sources, in merge priority: website (iclr.cc Dates page / 2017 archive prose),
invitations (OpenReview v2 per-paper invitation due dates), empirical (busiest
day of submissions/reviews/decisions). Network code lives in
peer/scripts/fetch_venue_dates.py; everything here is testable offline.
"""

import html as _html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

MILESTONES = ("submission", "review_due", "reviews_released", "rebuttal_end", "decision")
SOURCE_PRIORITY = ("website", "invitations", "empirical")

# Anywhere on Earth = deadline passes when the day ends at UTC-12.
AOE = timezone(timedelta(hours=-12))
TZ = {"UTC": timezone.utc, "GMT": timezone.utc,
      "PDT": timezone(timedelta(hours=-7)), "PST": timezone(timedelta(hours=-8)),
      "EDT": timezone(timedelta(hours=-4)), "EST": timezone(timedelta(hours=-5))}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Normalised-label substrings per milestone. Position in the list is the rank:
# a lower-ranked needle (e.g. "papersubmissiondeadline") beats a higher one
# ("submissiondeadline") anywhere on the page, so side-track dates lose.
LABEL_RULES = {
    "submission": ["papersubmissiondeadline", "submissiondeadline"],
    "reviews_released": ["reviewsreleased", "rebuttaldiscussionbegins", "rebuttalbegins",
                         "discussionperiodstarts", "discussionperiodbegins",
                         "discussionstarts", "discussionbegins"],
    "rebuttal_end": ["rebuttaldiscussionends", "rebuttalends", "authorscanrespond",
                     "authorresponseends", "discussionperiodends", "discussionends"],
    "decision": ["paperdecisionnotification", "decisionnotification", "authornotification",
                 "papernotification"],
    "review_due": ["reviewperiodends", "reviewdeadline", "reviewsdue", "reviewperiod"],
}
EXCLUDE_WORDS = ("workshop", "volunteer", "travel", "financial", "ethics", "abstract",
                 "supplementary", "registration", "sponsor", "expo", "camera", "video",
                 "reviewercomp", "tutorial", "socials", "blog", "tiny")
# Per-milestone vetoes on the normalised label.
VETO = {
    "review_due": ("opens", "begins", "starts", "meta", "final"),
    "reviews_released": ("meta",),
}


def _norm(label):
    return re.sub(r"[^a-z0-9]", "", label.lower())


def label_rank(label):
    """(milestone, rank) for a Dates-page label, or (None, None) if irrelevant."""
    n = _norm(label)
    if any(w in n for w in EXCLUDE_WORDS):
        return None, None
    for milestone, needles in LABEL_RULES.items():
        for rank, needle in enumerate(needles):
            if needle in n:
                if any(v in n for v in VETO.get(milestone, ())):
                    return None, None
                # "Reviewer/AC discussion ends" is not the author window closing.
                if milestone == "rebuttal_end" and "reviewer" in n and "author" not in n:
                    return None, None
                return milestone, rank
    return None, None


def milestone_for_label(label):
    """Map a Dates-page label to a milestone name, or None if irrelevant."""
    return label_rank(label)[0]


_TOKEN = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}) '(\d{2})(?: (\d{1,2}):(\d{2}) (AM|PM) ([A-Z]{3,4}))?")


def parse_date_token(token):
    """'Oct 27 '17 02:00 PM PDT' or 'Sep 28 '23 (Anywhere on Earth)' -> UTC epoch ms, else None."""
    m = _TOKEN.match(token.strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, day, year = MONTHS[m.group(1).lower()], int(m.group(2)), 2000 + int(m.group(3))
    if m.group(4):
        hour = int(m.group(4)) % 12 + (12 if m.group(6) == "PM" else 0)
        dt = datetime(year, month, day, hour, int(m.group(5)), tzinfo=TZ.get(m.group(7), timezone.utc))
    else:
        dt = datetime(year, month, day, 23, 59, 59, tzinfo=AOE)
    return int(dt.timestamp() * 1000)


def _text_lines(page_html):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page_html, flags=re.S)
    text = _html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def parse_dates_page(page_html):
    """iclr.cc/Conferences/<year>/Dates -> {milestone: epoch_ms}. Label precedes its date."""
    lines = _text_lines(page_html)
    best = {}  # milestone -> (rank, position, ts)
    for i in range(1, len(lines)):
        ts = parse_date_token(lines[i])
        if ts is None:
            continue
        milestone, rank = label_rank(lines[i - 1])
        if milestone and (milestone not in best or (rank, i) < best[milestone][:2]):
            best[milestone] = (rank, i, ts)
    return {m: v[2] for m, v in best.items()}


_ARCHIVE = {
    "submission": r"Submission Deadline:.*?([A-Z][a-z]+ [\d\w ,]+?\d{4})",
    "review_due": r"Review Period:?\s*until\s*([A-Z][a-z]+ \d+\w*,? \d{4})",
    "rebuttal": r"Rebuttal/discussion:\s*([A-Z][a-z]+ \d+\w*,? \d{4})\s*to\s*([A-Z][a-z]+ \d+\w*,? \d{4})",
    "decision": r"Decision Notification:\s*([A-Z][a-z]+ \d+\w*,? \d{4})",
}


def _prose_date(s, hour=23, minute=59, tz=AOE):
    """'November 4th 5th, 2016' -> last day mentioned, as epoch ms."""
    m = re.match(r"([A-Za-z]+)\s+(.*?),?\s*(\d{4})$", s.strip())
    month = MONTHS[m.group(1).lower()[:3]]
    day = int(re.findall(r"\d+", m.group(2))[-1])
    return int(datetime(int(m.group(3)), month, day, hour, minute, tzinfo=tz).timestamp() * 1000)


def parse_archive_2017(text):
    """ICLR 2017 archive page prose (conference track section only)."""
    text = re.sub(r"\s+", " ", text)
    text = text.split("Workshop Track Submission Deadline")[0]
    out = {}
    m = re.search(_ARCHIVE["submission"], text)
    if m:
        out["submission"] = _prose_date(m.group(1), hour=17, minute=0, tz=TZ["EDT"])
    m = re.search(_ARCHIVE["review_due"], text)
    if m:
        out["review_due"] = _prose_date(m.group(1))
    m = re.search(_ARCHIVE["rebuttal"], text)
    if m:
        out["reviews_released"] = _prose_date(m.group(1), hour=0, minute=0)
        out["rebuttal_end"] = _prose_date(m.group(2))
    m = re.search(_ARCHIVE["decision"], text)
    if m:
        out["decision"] = _prose_date(m.group(1))
    return out


_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def parse_prose_date(s, cycle_year, end_of_day=True):
    """Free-text date ('4 November 2019.', 'Nov 09, 2021', 'Nov 4', 'Nov 10-22') -> epoch ms.

    A missing year is inferred from the conference cycle: Sep-Dec fall in the
    year before `cycle_year`, Jan-Aug in `cycle_year`. Ranges take the end.
    Deadlines resolve to end of day AoE; `end_of_day=False` gives start of day.
    """
    s = s.strip()
    m = re.search(_MONTH_RE, s, re.I)
    if not m:
        return None
    month = MONTHS[m.group(1).lower()]
    after, before = s[m.end():], s[:m.start()]
    # Day must sit next to the month: 'Nov 10-22' -> 22, 'Nov 09, 2021' -> 9, '4 November' -> 4.
    m_after = re.match(r"\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\b", after)
    m_before = re.search(r"(\d{1,2})\s*$", before)
    if m_after:
        day = int(m_after.group(2) or m_after.group(1))
    elif m_before:
        day = int(m_before.group(1))
    else:
        return None
    if not 1 <= day <= 31:
        return None
    year_m = re.search(r"\b(20\d{2})\b", s)
    year = int(year_m.group(1)) if year_m else (cycle_year - 1 if month >= 9 else cycle_year)
    hour, minute, second = (23, 59, 59) if end_of_day else (0, 0, 0)
    return int(datetime(year, month, day, hour, minute, second, tzinfo=AOE).timestamp() * 1000)


# CFP line regexes: milestone -> [(pattern, end_of_day)]; first line that matches wins.
CFP_RULES = {
    "submission": [(r"^Submission date:\s*(.+)$", True),
                   (r"paper submission deadline is\s+(.+?)(?:\.\s|$)", True)],
    "reviews_released": [(r"^Reviews released:\s*(.+)$", False)],
    "rebuttal_end": [(r"^Author discussion period ends:\s*(.+)$", True),
                     (r"^Author/Reviewer Discussion:\s*(.+)$", True)],
    "decision": [(r"^Final decisions?:\s*(.+)$", True),
                 (r"^On (.+?), authors will be notified", True)],
}


def parse_cfp_page(page_html, cycle_year):
    """iclr.cc/Conferences/<year>/CallForPapers -> {milestone: epoch_ms}."""
    lines = [re.sub(r"\s+", " ", ln) for ln in _text_lines(page_html)]
    out = {}
    for milestone, rules in CFP_RULES.items():
        for pattern, end_of_day in rules:
            for ln in lines:
                m = re.search(pattern, ln, re.I)
                if m:
                    ts = parse_prose_date(m.group(1), cycle_year, end_of_day)
                    if ts:
                        out[milestone] = ts
                        break
            if milestone in out:
                break
    return out


def merge_sources(by_source):
    """{source: {milestone: ms}} -> {milestone: {value, source}} using SOURCE_PRIORITY."""
    merged = {}
    for milestone in MILESTONES:
        merged[milestone] = {"value": None, "source": None}
        for source in SOURCE_PRIORITY:
            value = (by_source.get(source) or {}).get(milestone)
            if value is not None:
                merged[milestone] = {"value": value, "source": source}
                break
    return merged


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "venue_dates.json"


def load_thresholds(venue, config_path=CONFIG_PATH):
    """Selection thresholds for a venue from the config, or None if not recorded.

    Returns {'window_start', 'decision', 'window_start_source', 'decision_source'};
    window_start prefers reviews_released, then review_due.
    """
    path = Path(config_path)
    if not path.exists():
        return None
    entry = json.loads(path.read_text()).get(venue)
    if not entry:
        return None
    start = next((entry[m] for m in ("reviews_released", "review_due") if entry.get(m, {}).get("value")), None)
    decision = entry.get("decision", {})
    if not start or not decision.get("value"):
        return None
    return {"window_start": start["value"], "window_start_source": start["source"],
            "decision": decision["value"], "decision_source": decision["source"]}
