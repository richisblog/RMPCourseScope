import json
import re
import sqlite3
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outputs"))
from rmp_client import RMPAPI, RMPAPIError

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "uc_davis_teachers.json"
OUT = ROOT / "outputs" / "uc_davis_rmp_bulk"
JSON_DIR = OUT / "professors"
DB_PATH = ROOT / "outputs" / "uc_davis_rmp.sqlite"
ZIP_PATH = ROOT / "outputs" / "uc_davis_rmp_professors.zip"
OUT.mkdir(exist_ok=True)
JSON_DIR.mkdir(exist_ok=True)

def normalize_course(value):
    if not value:
        return None
    raw = str(value).strip().upper()
    raw = re.sub(r"[\s._/-]+", "", raw)
    m = re.fullmatch(r"([A-Z&]+)0*(\d+[A-Z]?)", raw)
    if not m:
        return raw
    subject, number = m.groups()
    return f"{subject}{number}"

def fetch_one(teacher):
    legacy = teacher.get("legacyId")
    relay = teacher.get("id")
    path = JSON_DIR / f"{legacy or relay}.json"
    if path.exists() and path.stat().st_size > 100:
        return "skipped"
    api = RMPAPI()
    last = None
    for attempt in range(6):
        try:
            profile = api.get_teacher_profile(relay)
            reviews = list(api.iter_teacher_reviews(relay, page_size=100))
            payload = {
                "teacher": teacher,
                "profile": profile,
                "reviews": reviews,
                "meta": {"course_normalization": "deterministic_v1", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return len(reviews)
        except Exception as exc:
            last = exc
            time.sleep(min(60, 5 * (2 ** attempt)))
    raise RMPAPIError(f"failed teacher {legacy}: {last}")

def build_sqlite():
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
      PRAGMA journal_mode=WAL;
      CREATE TABLE professors(legacy_id INTEGER PRIMARY KEY, relay_id TEXT, first_name TEXT, last_name TEXT, department TEXT, profile_url TEXT, avg_rating REAL, avg_difficulty REAL, num_ratings INTEGER, would_take_again REAL, raw_json TEXT);
      CREATE TABLE courses(course_key TEXT PRIMARY KEY, subject TEXT, number TEXT, display_code TEXT, source TEXT);
      CREATE TABLE professor_courses(legacy_id INTEGER, course_key TEXT, review_count INTEGER, profile_count INTEGER, PRIMARY KEY(legacy_id, course_key));
      CREATE TABLE reviews(review_id TEXT PRIMARY KEY, legacy_id INTEGER, course_raw TEXT, course_key TEXT, course_code TEXT, course_title TEXT, rating REAL, difficulty REAL, grade TEXT, date TEXT, comment TEXT, raw_json TEXT);
      CREATE INDEX idx_pc_course ON professor_courses(course_key);
      CREATE INDEX idx_reviews_teacher ON reviews(legacy_id);
      CREATE INDEX idx_reviews_course ON reviews(course_key);
    """)
    for path in JSON_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = data["profile"]
        teacher = data["teacher"]
        legacy = profile.get("legacyId") or teacher.get("legacyId")
        db.execute("INSERT OR REPLACE INTO professors VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            legacy, profile.get("id"), profile.get("firstName"), profile.get("lastName"), profile.get("department"),
            profile.get("profile_url"), profile.get("avgRating"), profile.get("avgDifficulty"), profile.get("numRatings"),
            profile.get("wouldTakeAgainPercent"), json.dumps(profile, ensure_ascii=False)))
        profile_counts = {}
        for item in profile.get("courseCodes") or []:
            key = normalize_course(item.get("courseName"))
            if key:
                profile_counts[key] = profile_counts.get(key, 0) + (item.get("courseCount") or 0)
                db.execute("INSERT OR IGNORE INTO courses VALUES(?,?,?,?,?)", (key, re.sub(r"\d.*", "", key), re.sub(r"^[A-Z&]+", "", key), item.get("courseName"), "rmp_courseCodes"))
        review_counts = {}
        for review in data.get("reviews", []):
            raw = review.get("course_code")
            key = normalize_course(raw)
            if key:
                review_counts[key] = review_counts.get(key, 0) + 1
                db.execute("INSERT OR IGNORE INTO courses VALUES(?,?,?,?,?)", (key, re.sub(r"\d.*", "", key), re.sub(r"^[A-Z&]+", "", key), raw, "rmp_rating_class"))
            db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                review.get("review_id"), legacy, raw, key, raw, review.get("course_title"), review.get("rating"), review.get("difficulty"), review.get("grade"), review.get("date"), review.get("comment"), json.dumps(review, ensure_ascii=False)))
        for key in set(profile_counts) | set(review_counts):
            db.execute("INSERT OR IGNORE INTO courses VALUES(?,?,?,?,?)", (key, re.sub(r"\d.*", "", key), re.sub(r"^[A-Z&]+", "", key), key, "normalized"))
            db.execute("INSERT OR REPLACE INTO professor_courses VALUES(?,?,?,?)", (legacy, key, review_counts.get(key, 0), profile_counts.get(key, 0)))
    db.commit()
    db.close()

def main():
    teachers = json.loads(INPUT.read_text(encoding="utf-8"))["teachers"]
    done = 0
    completed = 0
    # Bounded concurrency protects the upstream API and local sockets. Increase
    # only after observing that the endpoint is not returning 429/403/timeouts.
    workers = 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_one, teacher) for teacher in teachers]
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            done += result != "skipped"
            if completed % 25 == 0:
                print(f"progress {completed}/{len(teachers)} new={done} workers={workers}", flush=True)
    build_sqlite()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for path in JSON_DIR.glob("*.json"):
            z.write(path, path.relative_to(OUT))
    print(json.dumps({"teachers": len(teachers), "json_files": len(list(JSON_DIR.glob('*.json'))), "sqlite": str(DB_PATH), "zip": str(ZIP_PATH)}))

if __name__ == "__main__":
    main()
