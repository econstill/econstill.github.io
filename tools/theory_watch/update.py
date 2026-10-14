"""Build a static economic-theory discovery feed from Crossref's SSRN records."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from string import Template
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
BASE_URL = "https://econstill.github.io/theory-watch/"
CROSSREF = "https://api.crossref.org/prefixes/10.2139/works"
FIELDS = "DOI,title,author,abstract,created,posted,deposited,resource,type,subject"
RULES = json.loads((ROOT / "rules.json").read_text())
DOI_PATTERN = re.compile(r"10\.2139/ssrn\.(\d+)", re.I)
FORMAL = re.compile(
    r"\b((?:we|i) (?:prove|show|establish|derive|characteri[sz]e)|theorem|lemma|"
    r"necessary and sufficient|if and only if|axiom|analytical|theoretical model|"
    r"closed.form|existence|uniqueness|impossibility|equilibrium exists|equilibria exist)\b", re.I
)
ECONOMIC = re.compile(
    r"\b(economic|economics|economy|economies|market|markets|auction|auctions|"
    r"bidders?|buyers?|sellers?|firms?|consumers?|voters?|preferences?|"
    r"incentives?|contracts?|bargaining|welfare|mechanism|game|games)\b", re.I
)
OUTSIDE_SCOPE = re.compile(
    r"\b(video games?|pok[eé]mon|game (?:engine|level|development)|scrabble|"
    r"autonomous vehicles?|vehicular|uavs?|unmanned|wireless|antenna|"
    r"image (?:classification|segmentation)|quantum|protein|genomic|"
    r"drug discovery|microarchitectur\w*|warfare|time.series momentum)\b", re.I
)
EMPIRICAL_TITLE = re.compile(r"\b(evidence from|empirical (?:analysis|study)|bibliometric)\b", re.I)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "div", "br", "li", "jats:p"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "li", "jats:p"):
            self.parts.append(" ")

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def plain(value):
    text = str(value or "")
    for _ in range(3):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    parser = PlainText()
    parser.feed(text)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def classify(title, abstract, doi):
    doi = doi.lower()
    if doi in RULES["exclude_dois"]:
        return []
    if doi in RULES["include_dois"]:
        return ["Editor inclusion"]
    if OUTSIDE_SCOPE.search(title):
        return []
    title_lower, abstract_lower = title.lower(), abstract.lower()
    matched = []
    title_hits = abstract_hits = 0
    for topic, phrases in RULES["topics"].items():
        in_title = sum(phrase in title_lower for phrase in phrases)
        in_abstract = sum(phrase in abstract_lower for phrase in phrases)
        if in_title or in_abstract:
            matched.append((4 * in_title + in_abstract, topic))
            title_hits += in_title
            abstract_hits += sum(
                phrase in abstract_lower for phrase in phrases
                if phrase not in ("risk aversion", "risk preference", "optimal policy")
            )
    formal = bool(FORMAL.search(abstract))
    economic = bool(ECONOMIC.search(title + " " + abstract))
    if EMPIRICAL_TITLE.search(title) and not re.search(
        r"\b(we prove|we derive|theorem|necessary and sufficient)\b", abstract, re.I
    ):
        return []
    core_title = any(phrase in title_lower for phrase in (
        "game theory", "decision theory", "mechanism design", "social choice",
        "revealed preference", "network games", "bayesian persuasion", "market design",
    ))
    eligible = (title_hits and economic and (formal or not abstract or core_title)) or (
        abstract_hits >= 2 and formal and economic
    )
    return [topic for _, topic in sorted(matched, reverse=True)[:3]] if eligible else []


def request_json(url):
    contact = os.environ.get("CROSSREF_MAILTO", "stillwang@bjtu.edu.cn")
    req = urllib.request.Request(url, headers={
        "User-Agent": f"TheoryWatch/1.0 (+{BASE_URL}; mailto:{contact})",
        "Accept": "application/json",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            delay = min(30, int(exc.headers.get("Retry-After", "0") or 0))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            delay = 0
        time.sleep(max(delay, 2 ** (attempt + 1)))
    raise RuntimeError("Crossref request did not complete")


def collect(previous, now, bootstrap_days):
    last_check = previous.get("last_successful_check")
    if last_check:
        start = datetime.fromisoformat(last_check.replace("Z", "+00:00")).date() - timedelta(days=2)
        field = "deposit"
    else:
        start = now.date() - timedelta(days=bootstrap_days)
        field = "created"
    end = now.date()
    cursor = "*"
    works, expected = [], None
    for page in range(80):
        query = urllib.parse.urlencode({
            "filter": f"from-{field}-date:{start},until-{field}-date:{end}",
            "select": FIELDS,
            "rows": 1000,
            "cursor": cursor,
            "mailto": os.environ.get("CROSSREF_MAILTO", "stillwang@bjtu.edu.cn"),
        })
        result = request_json(CROSSREF + "?" + query)
        message = result.get("message", {})
        items = message.get("items")
        if not isinstance(items, list) or "total-results" not in message:
            raise ValueError("Unexpected Crossref response; keeping the previous feed")
        expected = message["total-results"] if expected is None else expected
        works.extend(items)
        print(f"Crossref page {page + 1}: {len(items)} records", flush=True)
        if len(works) >= expected or not items:
            break
        next_cursor = message.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("Crossref pagination stopped before the query was complete")
        cursor = next_cursor
        time.sleep(0.5)
    else:
        raise RuntimeError("Collection exceeded the page limit; previous feed is retained")
    if len(works) < expected:
        raise RuntimeError("Crossref returned an incomplete window; previous feed is retained")
    return works, {"from": start.isoformat(), "through": end.isoformat(), "date_field": field}


def timestamp(value):
    raw = (value or {}).get("date-time")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def posted_date(value):
    parts = (value or {}).get("date-parts", [[]])[0]
    if len(parts) != 3:
        return None
    try:
        return date(*parts).isoformat()
    except (ValueError, TypeError):
        return None


def shorten(text, limit=380):
    words = text.split()
    if len(text) <= limit and len(words) <= 20:
        return text
    excerpt = " ".join(words[:20])
    if len(excerpt) > limit:
        excerpt = excerpt[:limit].rsplit(" ", 1)[0]
    return excerpt.rstrip(".,;:") + "..."


def normalize(work, now, selector=None):
    doi = str(work.get("DOI", "")).lower()
    match = DOI_PATTERN.fullmatch(doi)
    if not match:
        return None
    title = plain(" ".join(work.get("title") or []))
    abstract = plain(work.get("abstract", ""))
    topics = (selector.classify(title, abstract, doi) if selector else classify(title, abstract, doi))
    if doi in RULES["exclude_dois"]:
        topics = []
    elif doi in RULES["include_dois"]:
        topics = topics or ["Editor inclusion"]
    created = timestamp(work.get("created"))
    if not title or not topics or not created:
        return None
    if datetime.fromisoformat(created) > now + timedelta(hours=1):
        return None
    authors = []
    for author in work.get("author") or []:
        name = plain(" ".join(filter(None, [author.get("given"), author.get("family")])) or author.get("name", ""))
        if name:
            authors.append(name)
    fingerprint = hashlib.sha256(json.dumps(
        [title, authors, abstract], ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    return {
        "id": match[1], "doi": doi, "title": title, "authors": authors,
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=" + match[1],
        "topics": topics, "excerpt": shorten(abstract), "indexed_at": created,
        "has_abstract": bool(abstract),
        "abstract_source": "https://api.crossref.org/works/" + doi,
        "jel_codes": selector.decisions[doi].get("jel_codes", []) if selector else [],
        "posted_date": posted_date(work.get("posted")),
        "source_metadata_updated_at": timestamp(work.get("deposited")),
        "first_seen": now.isoformat(), "record_updated_at": None,
        "ssrn_ids": [match[1]],
        "fingerprint": fingerprint,
    }


def identity(paper):
    title = re.sub(r"[^\w]", "", paper["title"].casefold())
    authors = tuple(sorted(re.sub(r"[^\w]", "", author.casefold()) for author in paper["authors"]))
    return (title, authors) if authors else (paper["id"], ())


def merge(previous, works, now, window, selector=None, rescreen=False):
    coverage_start = previous.get("coverage_start", RULES["registrations_from"])
    existing = {paper["id"]: paper for paper in previous.get("papers", []) if paper["indexed_at"][:10] >= coverage_start}
    new_count = updated_count = 0
    unique_works = {}
    for work in works:
        doi = str(work.get("DOI", "")).lower()
        old = unique_works.get(doi)
        if old is None or (timestamp(work.get("deposited")) or "") > (timestamp(old.get("deposited")) or ""):
            unique_works[doi] = work
    aliases = {alias: paper["id"] for paper in existing.values() for alias in paper.get("ssrn_ids", [paper["id"]])}
    identities = {identity(paper): paper["id"] for paper in existing.values()}
    for work in sorted(unique_works.values(), key=lambda item: timestamp(item.get("created")) or ""):
        registered = timestamp(work.get("created"))
        if not registered or registered[:10] < coverage_start:
            continue
        paper = normalize(work, now, selector)
        if paper is None:
            if selector and not rescreen and selector.decisions.get(str(work.get("DOI", "")).lower(), {}).get("decision") != "include":
                source_match = DOI_PATTERN.fullmatch(str(work.get("DOI", "")).lower())
                if source_match:
                    canonical = aliases.get(source_match[1])
                    if canonical in existing:
                        old = existing[canonical]
                        if len(old.get("ssrn_ids", [old["id"]])) == 1:
                            del existing[canonical]
            continue
        source_id = paper["id"]
        canonical_id = aliases.get(source_id) or identities.get(identity(paper)) or source_id
        old = existing.get(canonical_id)
        if old:
            combined_ids = sorted(set(old.get("ssrn_ids", [old["id"]]) + [source_id]), key=int)
            if (paper.get("source_metadata_updated_at") or "") < (old.get("source_metadata_updated_at") or ""):
                paper = {**old, "ssrn_ids": combined_ids}
            else:
                for field in ("id", "doi", "url", "indexed_at"):
                    paper[field] = old[field]
                paper["ssrn_ids"] = combined_ids
            paper["first_seen"] = old["first_seen"]
            paper["record_updated_at"] = old.get("record_updated_at")
            if paper["fingerprint"] != old.get("fingerprint"):
                paper["record_updated_at"] = now.isoformat()
                updated_count += 1
        else:
            new_count += 1
        existing[paper["id"]] = paper
        aliases[source_id] = paper["id"]
        identities[identity(paper)] = paper["id"]
    if rescreen:
        accepted = {doi for doi, decision in selector.decisions.items() if decision["decision"] == "include"}
        existing = {key: paper for key, paper in existing.items() if any(
            "10.2139/ssrn." + alias in accepted or "10.2139/ssrn." + alias in RULES["include_dois"]
            for alias in paper.get("ssrn_ids", [paper["id"]])
        )}
    papers = [paper for paper in existing.values() if paper["doi"] not in RULES["exclude_dois"]]
    papers.sort(key=lambda paper: (paper["indexed_at"], int(paper["id"])), reverse=True)
    return {
        "schema_version": 1, "title": "Theory Watch", "home_page_url": BASE_URL,
        "source": "SSRN DOI metadata deposited with Crossref",
        "selection": "Semantic topic retrieval plus transparent formal-contribution and empirical-evidence checks; borderline records withheld for review" if selector else "Legacy topic matching",
        "rule_version": __import__("semantic").CONFIG["version"] if selector else RULES["version"],
        "last_successful_check": now.isoformat(),
        "screening": selector.stats if selector else {},
        "coverage_start": coverage_start,
        "last_collection": {**window, "records_checked": len(unique_works), "new_matches": new_count,
                            "changed_matches": updated_count},
        "papers": papers,
    }


def display_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")


def paper_html(paper):
    title, url = escape(paper["title"]), escape(paper["url"], quote=True)
    authors = escape(", ".join(paper["authors"]) or "Authors unavailable in source metadata")
    topics = escape(" / ".join(paper["topics"]))
    changed = ""
    if paper.get("record_updated_at"):
        changed = " &middot; Record updated " + display_date(paper["record_updated_at"])
    excerpt = ('<details class="abstract" data-doi="' + escape(paper["doi"], quote=True) + '">'
               '<summary>Abstract</summary><div class="abstract-body"><p>' + escape(paper["excerpt"] or "No abstract in the indexed record.") + '</p>'
               '<p class="abstract-source">Read the abstract at <a href="' + url + '" target="_blank" rel="noopener">SSRN</a>.</p></div></details>')
    alternate_ids = [value for value in paper.get("ssrn_ids", []) if value != paper["id"]]
    alternates = ""
    if alternate_ids:
        links = ", ".join(
            f'<a href="https://papers.ssrn.com/sol3/papers.cfm?abstract_id={value}" target="_blank" rel="noopener">{value}</a>'
            for value in alternate_ids
        )
        alternates = '<p class="paper-meta">Other SSRN record: ' + links + '</p>'
    return (f'<li class="paper"><h2><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>'
            f'<p class="authors">{authors}</p><p class="paper-meta">DOI registered '
            f'<time datetime="{paper["indexed_at"][:10]}">{display_date(paper["indexed_at"])}</time>'
            f'{changed}</p><p class="paper-topics">{topics}</p>{alternates}{excerpt}</li>')


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def render(data, site):
    output = site / "theory-watch"
    papers = data["papers"]
    topics = sorted({topic for paper in papers for topic in paper["topics"]})
    options = "".join(f'<option value="{escape(topic, quote=True)}">{escape(topic)}</option>' for topic in topics)
    counts = Counter(topic for paper in papers for topic in paper["topics"])
    template = Template((ROOT / "page.html").read_text())
    checked = data["last_successful_check"]
    rendered = template.substitute(
        paper_count=len(papers), checked_at=escape(checked, quote=True),
        checked_label=datetime.fromisoformat(checked).strftime("%d %b %Y, %H:%M UTC"),
        topics=options, papers="\n".join(paper_html(paper) for paper in papers[:50]),
        initial_count=min(50, len(papers)),
        css_version=hashlib.sha256((ROOT / "watch.css").read_bytes()).hexdigest()[:10],
        js_version=hashlib.sha256((ROOT / "watch.js").read_bytes()).hexdigest()[:10],
        coverage_start=datetime.fromisoformat(data.get("coverage_start", RULES["registrations_from"])).strftime("%d %b %Y"),
    )
    write_text(output / "index.html", rendered)
    write_text(output / "papers.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    overrides = {key: RULES[key] for key in ("version", "registrations_from", "include_dois", "exclude_dois")}
    overrides["note"] = "DOI-level editorial overrides only. See method.json and the screening source code for automatic selection."
    write_text(output / "rules.json", json.dumps(overrides, ensure_ascii=False, indent=2) + "\n")
    write_text(output / "method.json", (ROOT / "semantic.json").read_text())
    for asset in ("watch.css", "watch.js"):
        write_text(output / asset, (ROOT / asset).read_text())
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in {
        "title": "Theory Watch: Theoretical Economics on SSRN", "link": BASE_URL,
        "description": "Automatically matched economic-theory papers from SSRN DOI metadata. Coverage is partial; dates are DOI registration dates.",
        "language": "en", "lastBuildDate": format_datetime(datetime.fromisoformat(checked)),
        "ttl": "1440",
    }.items():
        ET.SubElement(channel, tag).text = value
    for paper in papers[:100]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = paper["title"]
        ET.SubElement(item, "link").text = paper["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = paper["doi"]
        ET.SubElement(item, "pubDate").text = format_datetime(datetime.fromisoformat(paper["indexed_at"]))
        ET.SubElement(item, "description").text = (
            ", ".join(paper["authors"]) + ". " + " / ".join(paper["topics"]) + ". " + paper["excerpt"]
        )
    ET.indent(rss)
    write_text(output / "feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n")
    print(f"Rendered {len(papers)} papers; topic counts: {dict(counts)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-days", type=int, default=14)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--rescreen", action="store_true", help="Re-screen the supplied complete coverage window")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--cache", type=Path, default=Path(".cache/theory-watch/decisions.json"))
    parser.add_argument("--review-output", type=Path)
    args = parser.parse_args()
    path = args.site_dir / "theory-watch/papers.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if args.render_only:
        if not previous:
            raise ValueError("No existing feed to render")
        data = previous
    else:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if args.input:
            raw = json.loads(args.input.read_text())
            works, window = raw["works"], raw["window"]
        else:
            days = (now.date() - date.fromisoformat(previous.get("coverage_start", RULES["registrations_from"]))).days if args.rescreen else args.bootstrap_days
            works, window = collect({} if args.rescreen else previous, now, days)
        if args.raw_output:
            write_text(args.raw_output, json.dumps({"works": works, "window": window}, ensure_ascii=False))
        completed = datetime.now(timezone.utc).replace(microsecond=0)
        from semantic import SemanticSelector
        if args.rescreen and (window.get("date_field") != "created" or window.get("from", "9999") > previous.get("coverage_start", RULES["registrations_from"])):
            raise ValueError("Re-screening requires the complete archive coverage window")
        works = [work for work in works if (timestamp(work.get("created")) or "")[:10] >= previous.get("coverage_start", RULES["registrations_from"])]
        selector = SemanticSelector(args.cache, args.model_dir)
        selector.prepare(works)
        completed = datetime.now(timezone.utc).replace(microsecond=0)
        data = merge(previous, works, completed, window, selector, args.rescreen)
        if args.review_output:
            review = [{"doi": work["DOI"], "title": plain(" ".join(work.get("title") or [])),
                       "excerpt": shorten(plain(work.get("abstract", ""))),
                       **selector.decisions[str(work["DOI"]).lower()]} for work in works
                      if selector.decisions[str(work["DOI"]).lower()]["decision"] == "review"]
            write_text(args.review_output, json.dumps(review, ensure_ascii=False, indent=2))
        selector.save()
    render(data, args.site_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Theory Watch update failed: {exc}", file=sys.stderr)
        sys.exit(1)
