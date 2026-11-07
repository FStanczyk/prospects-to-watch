"""Parser tabel z EliteProspects Draft Center zapisanych ręcznie do data/<rok>prospects.html."""
import re
from html.parser import HTMLParser
from pathlib import Path


class _DraftTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.section = [], ""
        self._row = self._cell = None
        self._in_section = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"text": "", "href": None, "img": None}
        elif tag == "a" and self._cell is not None and self._cell["href"] is None:
            self._cell["href"] = a.get("href")
        elif tag == "img" and self._cell is not None and self._cell["img"] is None:
            self._cell["img"] = a.get("title")
        elif tag == "span" and "QSvhfG_section" in (a.get("class") or ""):
            self._in_section, self.section = True, ""

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self._cell["text"] = self._cell["text"].strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 10:
                self.rows.append((self.section, self._row))
            self._row = None
        elif tag == "span":
            self._in_section = False

    def handle_data(self, data):
        if self._in_section:
            self.section += data.strip()
        elif self._cell is not None:
            self._cell["text"] += data


def parse_file(path: Path, draft_year: int) -> list[dict]:
    p = _DraftTable()
    p.feed(path.read_text(encoding="utf-8"))
    out = []
    for section, c in p.rows:
        rank, nat, player, team, league = c[:5]
        m = re.match(r"(.*?)\s*\(([^)]+)\)$", player["text"])
        name, pos = (m.group(1), m.group(2)) if m else (player["text"], "")
        ep_id = re.search(r"/player/(\d+)/", player["href"] or "")
        out.append({
            "ep_id": ep_id.group(1) if ep_id else None,
            "ep_url": "https://www.eliteprospects.com" + (player["href"] or ""),
            "name": name,
            "pos": pos,
            "nation": nat["img"] or "",
            "rank": int(rank["text"]) if rank["text"].isdigit() else None,
            "tier": section.title(),
            "team": team["text"],
            "league": league["text"],
            "draft": draft_year,
        })
    return out


def load_all(data_dir: Path) -> list[dict]:
    players = []
    for f in sorted(data_dir.glob("*prospects.html")):
        year = int(re.match(r"(\d{4})", f.name).group(1))
        players += parse_file(f, year)
    return players
