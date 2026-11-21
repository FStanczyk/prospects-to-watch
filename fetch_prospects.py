#!/usr/bin/env python3
"""Buduje data/prospects.js z list EliteProspects + numerów ze składów lig.

1. Zapisz listy z EP Draft Center jako data/<rok>prospects.html (sam fragment tabeli wystarczy).
2. python3 fetch_prospects.py
3. Otwórz index.html.

Numery:
  - OHL / WHL / QMJHL / USHL - automatycznie z oficjalnych składów (HockeyTech),
  - pozostałe ligi - ręcznie w kolumnie "numer" w data/manual_numbers.csv
    (wpis ręczny ma pierwszeństwo przed automatem). Skrypt sam dopisuje do CSV
    nowych zawodników bez numeru i nie rusza istniejących wierszy.

Terminarz (data/schedule.js): mecze lig HockeyTech na SCHEDULE_DAYS dni naprzód,
w których gra choć jeden prospekt.
"""
import csv
import difflib
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ep_parse import load_all

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "prospects.js"
SCHEDULE_OUT = DATA / "schedule.js"
SCHEDULE_DAYS = 60
MANUAL = DATA / "manual_numbers.csv"
CSV_COLS = ["zawodnik", "liga", "druzyna", "draft", "eliteprospects", "numer"]

# Publiczne klucze, których używają oficjalne strony lig. Klucz = nazwa ligi jak na EP.
HOCKEYTECH = {
    "OHL":   {"client_code": "ohl",   "key": "f1aa699db3d81487"},
    "WHL":   {"client_code": "whl",   "key": "41b145a848f4bd67"},
    "QMJHL": {"client_code": "lhjmq", "key": "f322673b6bcae299"},
    "USHL":  {"client_code": "ushl",  "key": "e828f89b243dc43f"},
}
# Ligi z EP, których zawodnicy są też w składach innej ligi HockeyTech.
ROSTER_ALIAS = {"NTDP": "USHL"}  # U.S. National U18/U17 = "USA Hockey NTDP" w USHL
API = "https://lscluster.hockeytech.com/feed/"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def api(league: dict, **params):
    q = {"feed": "modulekit", "fmt": "json", "key": league["key"],
         "client_code": league["client_code"], **params}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": "prospects-to-watch/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["SiteKit"]


def fetch_league(league: dict) -> dict:
    """Bieżący sezon zasadniczy: drużyny, składy [{name, team, team_id, number, ...}] i terminarz."""
    today = date.today().isoformat()
    seasons = [s for s in api(league, view="seasons")["Seasons"]
               if s["career"] == "1" and s["playoff"] == "0" and s["start_date"] <= today]
    sid = max(seasons, key=lambda s: s["start_date"])["season_id"]
    teams = api(league, view="teamsbyseason", season_id=sid)["Teamsbyseason"]

    def roster(t):
        return api(league, view="roster", season_id=sid, team_id=t["id"]).get("Roster", [])

    with ThreadPoolExecutor(max_workers=6) as pool:
        rosters = list(pool.map(roster, teams))
    players = [{"name": f'{p["first_name"]} {p["last_name"]}', "team": p.get("team_name", ""),
                "team_id": t["id"], "number": p.get("tp_jersey_number") or "",
                "birthdate": p.get("birthdate") or ""}
               for t, r in zip(teams, rosters) for p in r if isinstance(p, dict) and p.get("position")]
    try:
        games = api(league, view="schedule", season_id=sid).get("Schedule", [])
    except Exception as e:
        print(f'{league["client_code"]}: błąd pobierania terminarza: {e}', file=sys.stderr)
        games = []
    return {"teams": teams, "roster": players, "games": games}


def team_ids(prospects: list[dict], ht_league: str, teams: list[dict]) -> dict:
    """(liga EP, drużyna EP) -> id drużyny HockeyTech: z dopasowanych składów, potem po nazwie."""
    votes = {}
    for p in prospects:
        if p.get("_ht") == ht_league and p.get("_team_id"):
            votes.setdefault((p["league"], p["team"]), Counter())[p["_team_id"]] += 1
    out = {k: c.most_common(1)[0][0] for k, c in votes.items()}
    by_name = {norm(t["name"]): t["id"] for t in teams}
    for p in prospects:
        key = (p["league"], p["team"])
        if p.get("_ht") != ht_league or key in out:
            continue
        close = difflib.get_close_matches(norm(p["team"]), by_name, n=1, cutoff=0.75)
        if close:
            out[key] = by_name[close[0]]
        else:
            print(f"{ht_league}: nie znaleziono drużyny {p['team']} w terminarzu", file=sys.stderr)
    return out


def team_label(name: str) -> str:
    """QMJHL podaje "Saint John, Sea Dogs" - ujednolicamy do "Saint John Sea Dogs"."""
    return re.sub(r",\s*", " ", name).strip()


def build_schedule(prospects: list[dict], data: dict) -> list[dict]:
    today = date.today()
    until = (today + timedelta(days=SCHEDULE_DAYS)).isoformat()
    since = (today - timedelta(days=1)).isoformat()
    games = []
    for lg, d in data.items():
        refs = {}  # team_id -> [[liga EP, drużyna EP], ...]
        for key, tid in team_ids(prospects, lg, d["teams"]).items():
            refs.setdefault(tid, []).append(list(key))
        for g in d["games"]:
            if not (since <= g["date_played"] <= until) or g.get("date_tbd") == "1":
                continue
            home, away = g["home_team"], g["visiting_team"]
            if home not in refs and away not in refs:
                continue
            games.append({
                "id": g["game_id"], "league": lg,
                "start": g["GameDateISO8601"], "tbd": g.get("time_tbd") == "1",
                "status": g.get("game_status", ""), "final": g.get("final") == "1",
                "venue": g.get("venue_location") or g.get("venue_name") or "",
                "home": {"name": team_label(g["home_team_name"]), "refs": refs.get(home, [])},
                "away": {"name": team_label(g["visiting_team_name"]), "refs": refs.get(away, [])},
            })
    games.sort(key=lambda g: (datetime.fromisoformat(g["start"]), g["league"]))
    return games


def match(prospect: dict, roster: list[dict]):
    name, team = norm(prospect["name"]), norm(prospect["team"])
    same = [r for r in roster if norm(r["name"]) == name]
    if len(same) > 1:
        same = [r for r in same if norm(r["team"]) == team] or same
    if not same:  # "Ben" vs "Benjamin": to samo nazwisko, jedno imię zaczyna się od drugiego
        first, last = name.split()[0], name.split()[-1]
        same = [r for r in roster
                if norm(r["name"]).split()[-1] == last
                and (norm(r["name"]).startswith(first) or first.startswith(norm(r["name"]).split()[0]))]
    if not same:  # inna transliteracja imienia (Artyom/Artem): nazwisko + drużyna
        same = [r for r in roster if norm(r["name"]).split()[-1] == last and norm(r["team"]) == team]
    if len(same) > 1:
        same = [r for r in same if norm(r["team"]) == team]
    return same[0] if len(same) == 1 else None


def ep_id_from_url(url: str):
    m = re.search(r"/player/(\d+)", url or "")
    return m.group(1) if m else None


def read_manual() -> list[dict]:
    if not MANUAL.exists():
        return []
    with MANUAL.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_manual(rows: list[dict]):
    with MANUAL.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main():
    prospects = load_all(DATA)
    if not prospects:
        sys.exit("Brak plików data/<rok>prospects.html")
    manual_rows = read_manual()
    manual = {ep_id_from_url(r.get("eliteprospects")): (r.get("numer") or "").strip().lstrip("#")
              for r in manual_rows}

    src = lambda lg: ROSTER_ALIAS.get(lg, lg)
    needed = {src(p["league"]) for p in prospects} & HOCKEYTECH.keys()
    ht_data = {}
    for lg in sorted(needed):
        try:
            ht_data[lg] = fetch_league(HOCKEYTECH[lg])
        except Exception as e:
            print(f"{lg}: błąd pobierania składów: {e}", file=sys.stderr)
    rosters = {lg: d["roster"] for lg, d in ht_data.items()}

    unmatched = []
    for p in prospects:
        p["number"], p["birthdate"], p["number_src"] = "", "", ""
        hit = match(p, rosters[src(p["league"])]) if src(p["league"]) in rosters else None
        p["_ht"] = src(p["league"]) if src(p["league"]) in ht_data else None
        if hit:
            p["number"], p["birthdate"], p["number_src"] = hit["number"], hit["birthdate"], "auto"
            p["_team_id"] = hit["team_id"]
        if manual.get(p["ep_id"]):
            p["number"], p["number_src"] = str(manual[p["ep_id"]]), "manual"
        if not p["number"]:
            unmatched.append(p)

    games = build_schedule(prospects, ht_data)
    for p in prospects:
        p.pop("_ht", None), p.pop("_team_id", None)

    leagues = {}
    for p in prospects:
        leagues.setdefault(p["league"], {}).setdefault(p["team"], []).append(p)

    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "leagues": leagues}
    OUT.write_text("window.PROSPECTS = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")

    new_rows = [{"zawodnik": p["name"], "liga": p["league"], "druzyna": p["team"], "draft": p["draft"],
                 "eliteprospects": p["ep_url"], "numer": ""}
                for p in sorted(unmatched, key=lambda x: (x["league"], x["team"], x["name"]))
                if p["ep_id"] not in manual]
    if new_rows or not MANUAL.exists():
        write_manual(manual_rows + new_rows)

    print(f"Prospektów: {len(prospects)}, z numerem: {len(prospects) - len(unmatched)}")
    if unmatched:
        print(f"Bez numeru: {len(unmatched)} (nowych w {MANUAL.name}: {len(new_rows)}) - uzupełnij kolumnę 'numer'")
    SCHEDULE_OUT.write_text("window.SCHEDULE = " + json.dumps(
        {"updated": data["updated"], "games": games}, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"Meczów z prospektami (najbliższe {SCHEDULE_DAYS} dni): {len(games)}")
    print(f"\nZapisano {OUT}, {SCHEDULE_OUT}")


if __name__ == "__main__":
    main()
