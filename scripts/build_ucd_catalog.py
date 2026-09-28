"""Build an independent SQLite snapshot from UC Davis public subject pages.

The catalog's robots.txt disallows /search/ and /ribbit/; this importer only
requests /courses-subject-code/ pages. It is resumable and preserves the full
courseblock HTML alongside extracted fields.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from lxml import html

BASE = "https://catalog.ucdavis.edu"
INDEX = BASE + "/courses-subject-code/"
AGENT = "CourseScope catalog metadata importer (contact: https://rmp.richis.top/)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(min(30, 2 ** attempt + 1))
    raise AssertionError("unreachable")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def text(node) -> str:
    return clean(" ".join(node.itertext())) if node is not None else ""


def by_class(node, name: str):
    return node.xpath('descendant-or-self::*[contains(concat(" ", normalize-space(@class), " "), " ' + name + ' ")]')


def first(node, name: str) -> str:
    matches = by_class(node, name)
    return text(matches[0]) if matches else ""


def subject_urls(document) -> list[str]:
    found = set()
    for link in document.xpath("//a[@href]"):
        url = urljoin(BASE, link.get("href"))
        if re.fullmatch(r"https://catalog\.ucdavis\.edu/courses-subject-code/[a-z0-9-]+/", url):
            found.add(url)
    return sorted(found)


def parse_courses(document, subject_url: str):
    subject = urlparse(subject_url).path.rstrip("/").split("/")[-1].upper()
    for block in by_class(document, "courseblock"):
        code = first(block, "detail-code")
        match = re.fullmatch(r"([A-Z]{2,5})\s+(\d{1,3}[A-Z]{0,3})", code)
        if not match:
            continue
        course_key = match.group(1) + str(int(re.match(r"\d+", match.group(2)).group())) + re.search(r"[A-Z]*$", match.group(2)).group()
        title = first(block, "detail-title").lstrip("—–- ")
        units = first(block, "detail-hours_html").strip("()")
        description = ""
        for para in by_class(block, "courseblockextra"):
            if para.tag == "p" and "Course Description:" in text(para):
                description = text(para).removeprefix("Course Description:").strip()
                break
        details = {}
        for para in by_class(block, "detail-prerequisite"):
            details["Prerequisite(s)"] = re.sub(r"^Prerequisite\(s\):\s*", "", text(para))
        for item in block.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " notinpdf ")]//li'):
            label = item.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " label ")]')
            if label:
                name = text(label[0]).rstrip(": ")
                value = text(item)[len(text(label[0])):].strip()
                details[name] = value
        yield (course_key, code, subject, title, units, description,
               details.get("Prerequisite(s)"), json.dumps(details, ensure_ascii=False),
               html.tostring(block, encoding="unicode"),
               BASE + "/search/?P=" + code.replace(" ", "%20"), subject_url,
               datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("outputs/ucdavis_catalog.sqlite"))
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--limit-subjects", type=int)
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS subjects (code TEXT PRIMARY KEY, url TEXT NOT NULL, fetched_at TEXT, course_count INTEGER);
        CREATE TABLE IF NOT EXISTS courses (
            course_key TEXT PRIMARY KEY, code TEXT NOT NULL, subject TEXT NOT NULL,
            title_en TEXT NOT NULL, units TEXT, description TEXT, prerequisites TEXT,
            details_json TEXT NOT NULL, raw_html TEXT NOT NULL, catalog_url TEXT NOT NULL,
            subject_url TEXT NOT NULL, fetched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_subject ON courses(subject);
    """)
    urls = subject_urls(html.fromstring(fetch(INDEX)))
    print(f"subject_pages={len(urls)}", flush=True)
    if args.limit_subjects is not None:
        urls = urls[:args.limit_subjects]
    for i, url in enumerate(urls, 1):
        subject = urlparse(url).path.rstrip("/").split("/")[-1].upper()
        if db.execute("SELECT fetched_at FROM subjects WHERE code=?", (subject,)).fetchone():
            continue
        try:
            courses = list(parse_courses(html.fromstring(fetch(url)), url))
        except Exception as error:
            print(f"ERROR {subject}: {error}", flush=True)
            continue
        with db:
            db.executemany("INSERT OR REPLACE INTO courses VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", courses)
            db.execute("INSERT OR REPLACE INTO subjects VALUES (?,?,?,?)",
                       (subject, url, datetime.now(timezone.utc).isoformat(), len(courses)))
        print(f"{i}/{len(urls)} {subject}: {len(courses)}", flush=True)
        time.sleep(args.delay)
    print("totals", *db.execute("SELECT (SELECT COUNT(*) FROM subjects),(SELECT COUNT(*) FROM courses)").fetchone(), flush=True)


if __name__ == "__main__":
    main()
