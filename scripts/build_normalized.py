import json
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "uc_davis_rmp.sqlite"
OUT = ROOT / "outputs" / "uc_davis_rmp_normalized.sqlite"
CATALOG_JSON = ROOT / "outputs" / "uc_davis_catalog_courses.json"

def parse_date(value):
    if not value:
        return None
    m = re.match(r"(\d{4})", str(value))
    return int(m.group(1)) if m else None

def clean_course(raw):
    value = unicodedata.normalize("NFKC", str(raw or "")).upper()
    value = re.sub(r"[^A-Z0-9]", "", value)
    m = re.fullmatch(r"([A-Z]{2,4})(\d{1,3})([A-Z]{0,3})", value)
    if m:
        subject, number, suffix = m.groups()
        return subject + str(int(number)) + suffix, subject, str(int(number)).zfill(3) + suffix
    m = re.fullmatch(r"(\d{1,3})([A-Z]{0,3})", value)
    if m:
        number, suffix = m.groups()
        return str(int(number)) + suffix, None, str(int(number)).zfill(3) + suffix
    return value, None, value

def fetch_catalog():
    index = urlopen(Request("https://catalog.ucdavis.edu/courses-subject-code/", headers={"User-Agent": "ucd-rmp-normalizer/1.0"}), timeout=30).read().decode("utf-8", "ignore")
    links = sorted(set(re.findall(r'href="(/courses-subject-code/([a-z]{2,4})/)"', index, re.I)))
    def fetch_one(item):
        path, subject = item
        try:
            html = urlopen(Request("https://catalog.ucdavis.edu" + path, headers={"User-Agent": "ucd-rmp-normalizer/1.0"}), timeout=8).read().decode("utf-8", "ignore")
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            pattern = re.compile(rf"\b{subject.upper()}\s+(\d{{3}}[A-Z]{{0,3}})\s*[—-]\s*([^<|]+?)\s*(?=\b{subject.upper()}\s+\d{{3}}|$)")
            found = []
            for number, title in pattern.findall(text):
                title = title.strip(" -–—")
                if title and len(title) < 240:
                    found.append({"subject": subject.upper(), "number": number, "display_code": f"{subject.upper()} {number}", "title": title, "url": "https://catalog.ucdavis.edu" + path})
            return found
        except Exception:
            return []
    courses = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for future in as_completed([pool.submit(fetch_one, item) for item in links]):
            courses.extend(future.result())
    unique = {(x["display_code"], x["title"]): x for x in courses}
    CATALOG_JSON.write_text(json.dumps(list(unique.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    return list(unique.values())

def main():
    catalog = fetch_catalog()
    official = {re.sub(r"[^A-Z0-9]", "", x["display_code"]): x for x in catalog}
    src = sqlite3.connect(SOURCE)
    if OUT.exists(): OUT.unlink()
    db = sqlite3.connect(OUT)
    db.executescript("""
      PRAGMA foreign_keys=ON;
      CREATE TABLE professors(legacy_id INTEGER PRIMARY KEY, relay_id TEXT, first_name TEXT, last_name TEXT, department TEXT, profile_url TEXT, avg_rating REAL, avg_difficulty REAL, num_ratings INTEGER, would_take_again REAL, raw_json TEXT);
      CREATE TABLE reviews(review_id TEXT PRIMARY KEY, legacy_id INTEGER, course_raw TEXT, course_key TEXT, course_code TEXT, course_title TEXT, rating REAL, difficulty REAL, grade TEXT, date TEXT, comment TEXT, raw_json TEXT);
      CREATE TABLE courses(course_key TEXT PRIMARY KEY, subject TEXT, number TEXT, display_code TEXT, title TEXT, catalog_url TEXT, source TEXT);
      CREATE TABLE professor_courses(legacy_id INTEGER, course_key TEXT, review_count INTEGER, profile_count INTEGER, PRIMARY KEY(legacy_id, course_key));
      CREATE TABLE course_alias_decisions(decision_id INTEGER PRIMARY KEY, legacy_id INTEGER, review_id TEXT, raw_course TEXT, recommended_key TEXT, recommended_display TEXT, relationship TEXT, confidence REAL, method TEXT, evidence_json TEXT, model_revision TEXT);
      CREATE TABLE review_course_links(review_id TEXT, course_key TEXT, relationship TEXT, confidence REAL, decision_id INTEGER);
      CREATE VIRTUAL TABLE course_search USING fts5(course_key, display_code, title, aliases, professor_names, department);
      CREATE INDEX idx_review_course ON reviews(course_key);
      CREATE INDEX idx_prof_course ON professor_courses(course_key);
    """)
    active = {row[0] for row in src.execute("SELECT DISTINCT legacy_id FROM reviews WHERE substr(date,1,4) >= '2020'")}
    professors = src.execute("SELECT * FROM professors WHERE legacy_id IN (%s)" % ",".join("?" * len(active)), tuple(active)).fetchall() if active else []
    pcols = [x[1] for x in src.execute("PRAGMA table_info(professors)")]
    rcols = [x[1] for x in src.execute("PRAGMA table_info(reviews)")]
    for row in professors: db.execute("INSERT INTO professors VALUES(" + ",".join("?" * len(row)) + ")", row)
    keep_review_ids = set()
    for row in src.execute("SELECT * FROM reviews WHERE substr(date,1,4) >= '2013'"):
        if row[rcols.index("legacy_id")] not in active: continue
        db.execute("INSERT INTO reviews VALUES(" + ",".join("?" * len(row)) + ")", row)
        keep_review_ids.add(row[rcols.index("review_id")])
    for row in db.execute("SELECT review_id,legacy_id,course_raw FROM reviews"):
        review_id, legacy, raw = row
        key, subject, number = clean_course(raw)
        catalog_key = re.sub(r"[^A-Z0-9]", "", (subject or "") + number) if subject else None
        official_row = official.get(catalog_key or "")
        display = official_row["display_code"] if official_row else (f"{subject} {number}" if subject else None)
        title = official_row["title"] if official_row else None
        db.execute("INSERT OR IGNORE INTO courses VALUES(?,?,?,?,?,?,?)", (key, subject, number, display, title, official_row["url"] if official_row else None, "ucdavis_catalog" if official_row else "observed"))
        if catalog_key:
            db.execute("INSERT OR REPLACE INTO review_course_links VALUES(?,?,?,?,?)", (review_id, key, "canonical" if official_row else "deterministic", 1.0, None))
        db.execute("UPDATE reviews SET course_key=? WHERE review_id=?", (key, review_id))
    # professor/course aggregates are rebuilt from filtered review links
    db.execute("INSERT OR REPLACE INTO professor_courses SELECT r.legacy_id,r.course_key,count(*),0 FROM reviews r WHERE r.course_key IS NOT NULL GROUP BY r.legacy_id,r.course_key")
    for row in db.execute("SELECT legacy_id,first_name,last_name,department FROM professors"):
        legacy, first, last, dept = row
        for key, in db.execute("SELECT course_key FROM professor_courses WHERE legacy_id=?", (legacy,)).fetchall():
            course = db.execute("SELECT display_code,title FROM courses WHERE course_key=?", (key,)).fetchone()
            db.execute("INSERT INTO course_search VALUES(?,?,?,?,?,?)", (key, course[0] or key, course[1] or "", key, f"{first} {last}", dept or ""))
    db.commit(); src.close(); db.close()
    print(json.dumps({"professors": len(professors), "catalog_courses": len(catalog), "db": str(OUT), "catalog": str(CATALOG_JSON)}))

if __name__ == "__main__": main()
