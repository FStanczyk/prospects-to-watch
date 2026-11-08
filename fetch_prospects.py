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
"""
import csv
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

from ep_parse import load_all

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "prospects.js"
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


def fetch_rosters(league: dict) -> list[dict]:
    """Wszyscy zawodnicy bieżącego sezonu zasadniczego: [{name, team, number, ...}]."""
    today = date.today().isoformat()
    seasons = [s for s in api(league, view="seasons")["Seasons"]
               if s["career"] == "1" and s["playoff"] == "0" and s["start_date"] <= today]
    sid = max(seasons, key=lambda s: s["start_date"])["season_id"]
    teams = api(league, view="teamsbyseason", season_id=sid)["Teamsbyseason"]

    def roster(t):
        return api(league, view="roster", season_id=sid, team_id=t["id"]).get("Roster", [])

    with ThreadPoolExecutor(max_workers=6) as pool:
        rosters = pool.map(roster, teams)
    return [{"name": f'{p["first_name"]} {p["last_name"]}', "team": p.get("team_name", ""),
             "number": p.get("tp_jersey_number") or "", "birthdate": p.get("birthdate") or ""}
            for r in rosters for p in r if isinstance(p, dict) and p.get("position")]


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
    rosters = {}
    for lg in sorted(needed):
        try:
            rosters[lg] = fetch_rosters(HOCKEYTECH[lg])
        except Exception as e:
            print(f"{lg}: błąd pobierania składów: {e}", file=sys.stderr)

    unmatched = []
    for p in prospects:
        p["number"], p["birthdate"], p["number_src"] = "", "", ""
        hit = match(p, rosters[src(p["league"])]) if src(p["league"]) in rosters else None
        if hit:
            p["number"], p["birthdate"], p["number_src"] = hit["number"], hit["birthdate"], "auto"
        if manual.get(p["ep_id"]):
            p["number"], p["number_src"] = str(manual[p["ep_id"]]), "manual"
        if not p["number"]:
            unmatched.append(p)

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
    print(f"\nZapisano {OUT}")


if __name__ == "__main__":
    main()
