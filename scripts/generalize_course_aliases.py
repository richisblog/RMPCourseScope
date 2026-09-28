"""Generate department-agnostic course alias candidates.

Unlike the Chemistry backfill, this derives subject prefixes from observed
professor/course data and does not maintain a hard-coded department map.
Use --dry-run first; writes are deliberately opt-in.
"""
import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "uc_davis_rmp_normalized.sqlite"
CODE_RE = re.compile(r"^([A-Z]{2,8})(\d+)([A-Z]{0,3})$")
RAW_RE = re.compile(r"^\s*(\d+)([A-Za-z]{0,3})\s*$")

def parse_code(key):
    m = CODE_RE.fullmatch(key or "")
    return (m.group(1), str(int(m.group(2))), m.group(3)) if m else (None, None, None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(DB)

    courses = {r[0]: r for r in db.execute(
        "SELECT course_key,display_code,title,subject,number FROM courses"
    )}
    prof_courses = defaultdict(list)
    for legacy, key, review_count, profile_count in db.execute(
        "SELECT legacy_id,course_key,review_count,profile_count FROM professor_courses"
    ):
        parsed = parse_code(key)
        if parsed[1] and key in courses:
            prof_courses[legacy].append((key, parsed, review_count or 0))
    dept_subjects = defaultdict(Counter)
    for legacy, department in db.execute("SELECT legacy_id,department FROM professors"):
        if department:
            for _, (subject, _, _), count in prof_courses.get(legacy, []):
                dept_subjects[department][subject] += max(1, count)

    candidates = []
    decided = {x[0] for x in db.execute(
        "SELECT DISTINCT review_id FROM course_alias_decisions"
    ).fetchall()}
    rows = [r for r in db.execute("""SELECT r.review_id,r.legacy_id,r.course_raw,p.department
      FROM reviews r JOIN professors p ON p.legacy_id=r.legacy_id
      WHERE r.course_raw IS NOT NULL""").fetchall() if r[0] not in decided]
    for review_id, legacy, raw, department in rows:
        m = RAW_RE.fullmatch(raw or "")
        if not m:
            continue
        number, suffix = str(int(m.group(1))), m.group(2).upper()
        pool = []
        for key, (subject, n, s), review_count in prof_courses.get(legacy, []):
            if n == number and s == suffix:
                dept_weight = dept_subjects[department][subject] if department else 0
                pool.append((key, subject, review_count, dept_weight))
        if not pool:
            continue
        pool.sort(key=lambda x: (x[3], x[2]), reverse=True)
        top = pool[0]
        second = pool[1] if len(pool) > 1 else None
        top_score = top[3] + top[2]
        second_score = (second[3] + second[2]) if second else 0
        margin = (top_score - second_score) / max(top_score, 1)
        status = "candidate" if len(pool) == 1 or margin >= 0.35 else "ambiguous"
        candidates.append({
            "review_id": review_id, "legacy_id": legacy, "raw_course": raw,
            "department": department, "status": status, "margin": round(margin, 4),
            "selected_key": top[0] if status == "candidate" else None,
            "candidate_keys": [x[0] for x in pool[:8]],
        })

    print(json.dumps({
        "rows_scanned": len(rows),
        "candidate_rows": len(candidates),
        "unique_reviews_with_candidate": len({x["review_id"] for x in candidates}),
        "clear_candidates": sum(x["status"] == "candidate" for x in candidates),
        "ambiguous_candidates": sum(x["status"] == "ambiguous" for x in candidates),
        "sample": candidates[:10],
    }, ensure_ascii=False, indent=2))
    if args.dry_run:
        return

    # Writes only clear candidates. Ambiguous rows remain available for Laya.
    added = 0
    for item in candidates:
        if item["status"] != "candidate":
            continue
        course = courses[item["selected_key"]]
        evidence = {"method": "derived_professor_department_context_v1", **item}
        cur = db.execute("""INSERT INTO course_alias_decisions
          (legacy_id,review_id,raw_course,recommended_key,recommended_display,
           relationship,confidence,method,evidence_json,model_revision)
          VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            item["legacy_id"], item["review_id"], item["raw_course"],
            item["selected_key"], course[1], "search_expansion",
            min(0.96, 0.75 + item["margin"] * 0.25),
            "derived_context", json.dumps(evidence, ensure_ascii=False),
            "rule:derived_professor_department_context_v1",
        ))
        db.execute("INSERT INTO review_course_links VALUES (?,?,?,?,?)", (
            item["review_id"], item["selected_key"], "search_expansion",
            min(0.96, 0.75 + item["margin"] * 0.25), cur.lastrowid,
        ))
        added += 1
    db.commit()
    print(json.dumps({"added": added}, ensure_ascii=False))

if __name__ == "__main__":
    main()
