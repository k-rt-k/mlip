"""Collect official ICLR deadlines per year into peer/config/venue_dates.json.

Sources merged in priority order (see peer/src/venue_dates.py):
  website      iclr.cc/Conferences/<year>/Dates (2018+) or the 2017 archive page
  invitations  OpenReview v2 per-paper invitation due dates (2023+)
  empirical    busiest day of submissions / reviews / decisions on OpenReview

    ~/mamba/envs/claude/bin/python peer/scripts/fetch_venue_dates.py --years 2017-2025
"""

import argparse
import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openreview_auth import get_client  # noqa: E402
from revisions import fetch_submissions  # noqa: E402
from venue_dates import (  # noqa: E402
    AOE, MILESTONES, iso, merge_sources, parse_archive_2017, parse_cfp_page, parse_dates_page,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "venue_dates.json"
V2_FROM_YEAR = 2024  # ICLR 2024 is the first cycle on API v2 (2023 is still v1)
EMPIRICAL_SAMPLE = 150  # v2 papers to sample for empirical review/decision days


def venue_id(year):
    return f"ICLR.cc/{year}/Conference" if year >= 2018 else f"ICLR.cc/{year}/conference"


def api_version(year):
    return 2 if year >= V2_FROM_YEAR else 1


# ---- website ----

def website_dates(year):
    """Dates page (precise times) over Call-for-Papers prose (fills what Dates omits)."""
    if year == 2017:
        page = requests.get("https://iclr.cc/archive/www/2017.html", timeout=30).text
        text = re.sub(r"<[^>]+>", " ", page)
        return parse_archive_2017(text)
    dates = requests.get(f"https://iclr.cc/Conferences/{year}/Dates", timeout=30)
    cfp = requests.get(f"https://iclr.cc/Conferences/{year}/CallForPapers", timeout=30)
    out = parse_cfp_page(cfp.text, year) if cfp.ok else {}
    out.update(parse_dates_page(dates.text) if dates.ok else {})
    return out


# ---- invitations (v2 only) ----

INVITATION_MAP = {  # invitation name -> (attribute, milestone)
    "Official_Review": ("duedate", "review_due"),
    "Meta_Review": ("cdate", "rebuttal_end"),
    "Decision": ("duedate", "decision"),
}


def invitation_dates(client, venue, api):
    if api != 2:
        return {}
    out = {}
    venue_subs = client.get_all_invitations(id=f"{venue}/-/Submission", expired=True)
    if venue_subs and venue_subs[0].duedate:
        out["submission"] = venue_subs[0].duedate
    sample = fetch_submissions(client, venue, api, limit=1)
    if not sample:
        return out
    for inv in client.get_all_invitations(prefix=f"{venue}/Submission{sample[0].number}/-/", expired=True):
        name = inv.id.rsplit("/-/", 1)[-1]
        if name in INVITATION_MAP:
            attr, milestone = INVITATION_MAP[name]
            value = getattr(inv, attr, None)
            if value:
                out[milestone] = value
    return out


# ---- empirical ----

def _busiest_day_end(timestamps):
    """End (AoE) of the calendar day with the most events, as epoch ms."""
    if not timestamps:
        return None
    days = collections.Counter(datetime.fromtimestamp(t / 1000, tz=timezone.utc).date() for t in timestamps)
    day = max(days, key=days.get)
    return int(datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=AOE).timestamp() * 1000)


EMPIRICAL_CAN_FILL = ("submission", "review_due", "decision")


def empirical_dates(client, venue, api, needed):
    """Busiest-day estimates, fetching only what `needed` (subset of EMPIRICAL_CAN_FILL) requires."""
    needed = [m for m in needed if m in EMPIRICAL_CAN_FILL]
    out = {}
    if not needed:
        return out
    subs = fetch_submissions(client, venue, api, limit=None if "submission" in needed else EMPIRICAL_SAMPLE)
    if "submission" in needed:
        out["submission"] = _busiest_day_end([n.tcdate for n in subs])
    if not ({"review_due", "decision"} & set(needed)):
        return out
    reviews, decisions, metas = [], [], []
    if api == 1:
        # Per-paper invitation layout by year (v1 prefix regex is case-sensitive):
        #   2017: <venue>/-/paper<N>/...   2018-19: <venue>/-/Paper<N>/...   2020-23: <venue>/Paper<N>/-/...
        for pattern in (f"{venue}/Paper.*", f"{venue}/-/Paper.*", f"{venue}/-/paper.*"):
            notes = client.get_all_notes(invitation=pattern)
            if notes:
                break
        for n in notes:
            kind = n.invitation.rsplit("/", 1)[-1].lower()
            if kind in ("review", "official_review"):
                reviews.append(n.tcdate)
            elif kind in ("acceptance", "decision"):
                decisions.append(n.tcdate)
            elif kind == "meta_review":
                metas.append(n.tcdate)
        decisions = decisions or metas  # ICLR 2019: the meta-review carried the decision
    else:
        for note in subs[:EMPIRICAL_SAMPLE]:
            for r in client.get_all_notes(forum=note.id):
                kind = r.invitations[0].rsplit("/", 1)[-1].lower() if r.invitations else ""
                if kind == "official_review":
                    reviews.append(r.tcdate)
                elif kind == "decision":
                    decisions.append(r.tcdate)
    if "review_due" in needed:
        out["review_due"] = _busiest_day_end(reviews)
    if "decision" in needed:
        out["decision"] = _busiest_day_end(decisions)
    return out


# ---- main ----

def parse_years(spec):
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--years", default="2017-2025", help="e.g. 2017-2025 or 2024")
    p.add_argument("--no-openreview", action="store_true", help="Website only (no login needed)")
    p.add_argument("--config", type=Path, default=CONFIG_PATH)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = json.loads(args.config.read_text()) if args.config.exists() else {}
    clients = {}
    for year in parse_years(args.years):
        venue, api = venue_id(year), api_version(year)
        sources = {"website": website_dates(year)}
        if not args.no_openreview:
            client = clients.setdefault(api, get_client(api))
            sources["invitations"] = invitation_dates(client, venue, api)
            still_missing = [m for m, v in merge_sources(sources).items() if v["value"] is None]
            # Reuse empirical values from a previous run; they are expensive to recompute.
            cached = {m: config[venue][m]["value"] for m in still_missing
                      if venue in config and config[venue].get(m, {}).get("source") == "empirical"
                      and config[venue][m].get("value")}
            to_fetch = [m for m in still_missing if m not in cached and m in EMPIRICAL_CAN_FILL]
            if to_fetch:
                print(f"{venue}: empirical fallback for {to_fetch}", flush=True)
            sources["empirical"] = {**cached, **empirical_dates(client, venue, api, to_fetch)}
        merged = merge_sources(sources)
        manual = {m: config[venue][m] for m in MILESTONES
                  if venue in config and config[venue].get(m, {}).get("source") == "manual"}
        merged.update(manual)
        for m in MILESTONES:  # human-readable twin of the epoch-ms value
            merged[m]["iso"] = iso(merged[m]["value"])
        config[venue] = {**merged, "api": api, "year": year}
        print(f"\n{venue}")
        for m in MILESTONES:
            v = merged[m]
            flag = "" if v["source"] in ("website", "manual") else "   <-- check"
            print(f"  {m:<17} {iso(v['value']) or '-':<26} {v['source'] or 'MISSING'}{flag}")
    args.config.parent.mkdir(parents=True, exist_ok=True)
    args.config.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(f"\nWrote {args.config}")


if __name__ == "__main__":
    main()
