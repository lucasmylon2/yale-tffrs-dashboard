"""Scrape Yale track & field results from TFRRS into tidy CSVs.

Usage:
    python scrape.py            # scrape both teams (uses cache)
    python scrape.py --refresh  # ignore cache, re-download everything
"""
import argparse
import os
import re
import sys
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from marks import parse_mark, event_kind

TEAM_PAGES = {
    "M": "https://www.tfrrs.org/teams/CT_college_m_Yale.html",
    "F": "https://www.tfrrs.org/teams/CT_college_f_Yale.html",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"}
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
REQUEST_DELAY = 1.5  # seconds between live requests, to be polite

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
DATE_RE = re.compile(rf"((?:{MONTHS})[A-Za-z]*\s+\d.*?\d{{4}})\s*$")


def fetch(url, cache_key, refresh=False):
    """Return HTML for url, caching to disk. Rate-limited on live fetch."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_key)
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    time.sleep(REQUEST_DELAY)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    with open(path, "w", encoding="utf-8") as f:
        f.write(resp.text)
    return resp.text


def get_roster(gender, refresh=False):
    """Return list of (athlete_id, name, url) for a team page."""
    html = fetch(TEAM_PAGES[gender], f"team_{gender}.html", refresh)
    soup = BeautifulSoup(html, "lxml")
    seen, roster = set(), []
    for a in soup.select('a[href*="/athletes/"]'):
        href = a.get("href", "")
        m = re.search(r"/athletes/(\d+)/([^/]+)/([^/?\"]+)", href)
        if not m:
            continue
        aid = m.group(1)
        if aid in seen:
            continue
        seen.add(aid)
        name = a.get_text(" ", strip=True) or m.group(3).replace("_", " ").strip()
        full = href if href.startswith("http") else "https://www.tfrrs.org" + href
        roster.append((aid, name, full))
    return roster


def parse_college_bests(soup):
    """Return list of (event, raw_mark) from the College Bests grid."""
    out = []
    label = soup.find(string=re.compile(r"College Bests", re.I))
    if not label:
        return out
    table = label.find_parent().find_next("table")
    if not table:
        return out
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        # grid is laid out as event, mark, event, mark
        for i in range(0, len(cells) - 1, 2):
            ev, mk = cells[i].strip(), cells[i + 1].strip()
            if ev and mk:
                out.append((ev, mk))
    return out


def infer_season(meet_name, date):
    """Indoor/Outdoor from the meet name, falling back to the month."""
    name = meet_name.lower()
    if "indoor" in name:
        return "Indoor"
    if "outdoor" in name:
        return "Outdoor"
    if date is not pd.NaT and date is not None and not pd.isna(date):
        # collegiate indoor season runs ~Dec-Mar, outdoor ~Apr-Aug
        return "Indoor" if date.month in (12, 1, 2, 3) else "Outdoor"
    return None


def parse_results(soup):
    """Walk meet tables, yielding result rows. Season/year derived per meet."""
    rows = []
    for el in soup.find_all("table"):
        # only meet tables have a date-bearing header th
        ths = el.find_all("th")
        if not ths:
            continue
        header = ths[0].get_text(" ", strip=True)
        dm = DATE_RE.search(header)
        if not dm:
            continue
        meet_date = dm.group(1).strip()
        meet_name = header[: dm.start()].strip()
        date = parse_meet_date(meet_date)
        year = int(date.year) if date is not pd.NaT and not pd.isna(date) else None
        season = infer_season(meet_name, date)
        for tr in el.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            event = tds[0].get_text(" ", strip=True)
            mark = tds[1].get_text(" ", strip=True)
            place = tds[2].get_text(" ", strip=True).split("\n")[0].strip() if len(tds) > 2 else ""
            if not event or not mark:
                continue
            rows.append({
                "event": event, "mark_raw": mark, "place": place,
                "meet": meet_name, "meet_date": meet_date, "date": date,
                "season": season, "year": year,
            })
    return rows


def parse_meet_date(date_str):
    """Best-effort parse of a TFRRS date string to a pandas Timestamp."""
    if not date_str:
        return pd.NaT
    # take the first date token, e.g. "May 16-17, 2026" -> "May 16, 2026"
    m = re.search(rf"({MONTHS})[a-z]*\s+(\d+).*?(\d{{4}})", date_str)
    if not m:
        return pd.NaT
    norm = f"{m.group(1)} {m.group(2)}, {m.group(3)}"
    return pd.to_datetime(norm, errors="coerce")


def scrape_athlete(aid, name, gender, url, refresh=False):
    html = fetch(url, f"athlete_{aid}.html", refresh)
    soup = BeautifulSoup(html, "lxml")

    pr_rows = []
    for ev, mk in parse_college_bests(soup):
        info = parse_mark(mk, ev)
        kind, higher = event_kind(ev)
        pr_rows.append({
            "athlete_id": aid, "athlete": name, "gender": gender,
            "event": ev, "mark": mk, "value": info["value"],
            "unit": info["unit"], "kind": kind, "higher_better": higher,
        })

    res_rows = []
    for r in parse_results(soup):
        info = parse_mark(r["mark_raw"], r["event"])
        kind, higher = event_kind(r["event"])
        res_rows.append({
            "athlete_id": aid, "athlete": name, "gender": gender,
            "event": r["event"], "mark": r["mark_raw"], "value": info["value"],
            "wind": info["wind"], "unit": info["unit"], "kind": kind,
            "higher_better": higher, "place": r["place"], "meet": r["meet"],
            "meet_date": r["meet_date"], "date": r["date"],
            "season": r["season"], "year": r["year"],
        })
    return pr_rows, res_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cache")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    all_prs, all_results = [], []

    for gender in ("M", "F"):
        roster = get_roster(gender, args.refresh)
        print(f"[{gender}] {len(roster)} athletes")
        for i, (aid, name, url) in enumerate(roster, 1):
            try:
                prs, results = scrape_athlete(aid, name, gender, url, args.refresh)
            except Exception as e:  # keep going on individual failures
                print(f"  ! {name} ({aid}) failed: {e}", file=sys.stderr)
                continue
            all_prs.extend(prs)
            all_results.extend(results)
            print(f"  [{gender} {i}/{len(roster)}] {name}: "
                  f"{len(prs)} PRs, {len(results)} results")

    prs_df = pd.DataFrame(all_prs)
    res_df = pd.DataFrame(all_results)
    prs_df.to_csv(os.path.join(DATA_DIR, "prs.csv"), index=False)
    res_df.to_csv(os.path.join(DATA_DIR, "results.csv"), index=False)
    print(f"\nWrote {len(prs_df)} PR rows -> data/prs.csv")
    print(f"Wrote {len(res_df)} result rows -> data/results.csv")


if __name__ == "__main__":
    main()
