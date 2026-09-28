"""Backfill subjectless labels using department and professor-course context.

This is intentionally separate from Laya: it is an auditable deterministic
rule for cases such as Chemistry professor + `2A` + observed CHE2A.
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "uc_davis_rmp_normalized.sqlite"

DEPARTMENT_SUBJECTS = {
    "chemistry": ["CHE", "CHEM"],
    "mathematics": ["MAT", "MATH"],
    "computer science": ["ECS", "CSC"],
    "biology": ["BIS", "BIO"],
    "physics": ["PHY"],
    "economics": ["ECN", "ECO"],
}

def main():
    db = sqlite3.connect(DB)
    added = 0
    rows = db.execute("""SELECT r.review_id,r.legacy_id,r.course_raw,r.course_key,
             p.first_name,p.last_name,p.department
      FROM reviews r JOIN professors p ON p.legacy_id=r.legacy_id
      WHERE r.course_raw IS NOT NULL
        AND upper(trim(r.course_raw)) GLOB '[0-9]*'
        AND upper(trim(r.course_raw)) NOT GLOB '*[^0-9A-Z ]*'
        AND NOT EXISTS (SELECT 1 FROM course_alias_decisions d
                        WHERE d.review_id=r.review_id)""").fetchall()
    for review_id, legacy_id, raw, raw_key, first, last, department in rows:
        m = re.fullmatch(r"\s*(\d+)([A-Za-z]{0,3})\s*", raw or "")
        if not m:
            continue
        number, suffix = str(int(m.group(1))), m.group(2).upper()
        subjects = DEPARTMENT_SUBJECTS.get((department or "").strip().lower(), [])
        if not subjects:
            continue
        candidates = db.execute("""SELECT c.course_key,c.display_code,c.title,pc.review_count
          FROM professor_courses pc JOIN courses c ON c.course_key=pc.course_key
          WHERE pc.legacy_id=? AND c.subject IN ({})
          ORDER BY CASE WHEN c.subject=? THEN 0 ELSE 1 END, pc.review_count DESC""".format(
              ",".join("?" for _ in subjects)),
              (legacy_id, *subjects, subjects[0])).fetchall()
        filtered = []
        for candidate in candidates:
            cm = re.fullmatch(r"[A-Z]+(\d+)([A-Z]{0,3})", candidate[0])
            if not cm or str(int(cm.group(1))) != number:
                continue
            if suffix and cm.group(2) != suffix:
                continue
            filtered.append(candidate)
        candidates = filtered
        if not candidates:
            continue
        selected = candidates[0]
        evidence = {
            "rule": "department_subject_context_v2",
            "raw_course": raw,
            "department": department,
            "professor": f"{first} {last}",
            "department_subjects": subjects,
            "candidate_courses": [
                {"key": c[0], "display": c[1], "review_count": c[3]}
                for c in candidates
            ],
        }
        cur = db.execute("""INSERT INTO course_alias_decisions
          (legacy_id,review_id,raw_course,recommended_key,recommended_display,
           relationship,confidence,method,evidence_json,model_revision)
          VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            legacy_id, review_id, raw, selected[0], selected[1],
            "search_expansion", 0.97, "department_context", json.dumps(evidence),
            "rule:department_subject_context_v2",
        ))
        db.execute("INSERT INTO review_course_links VALUES (?,?,?,?,?)", (
            review_id, selected[0], "search_expansion", 0.97, cur.lastrowid
        ))
        added += 1

    # Refresh the expanded professor reverse index.
    db.execute("DELETE FROM professor_course_links")
    db.execute("""INSERT INTO professor_course_links
      (legacy_id,course_key,inferred_review_count,max_confidence,relationships)
      SELECT r.legacy_id,l.course_key,count(*),max(l.confidence),
             group_concat(DISTINCT l.relationship)
      FROM review_course_links l JOIN reviews r ON r.review_id=l.review_id
      WHERE l.relationship IN ('auto_linked','search_expansion','family','weak_alias')
      GROUP BY r.legacy_id,l.course_key""")
    # Update only affected canonical course aliases; this is much faster than
    # rebuilding every FTS row for a targeted backfill.
    affected = db.execute("SELECT DISTINCT recommended_key FROM course_alias_decisions WHERE method='department_context'").fetchall()
    for (key,) in affected:
        aliases = [x[0] for x in db.execute(
            "SELECT DISTINCT course_raw FROM reviews WHERE course_key=? AND course_raw IS NOT NULL", (key,)
        ).fetchall()]
        aliases += [x[0] for x in db.execute(
            "SELECT DISTINCT raw_course FROM course_alias_decisions WHERE recommended_key=?", (key,)
        ).fetchall()]
        db.execute("UPDATE course_search SET aliases=? WHERE course_key=?", (" ".join(sorted(set(aliases))), key))
    db.commit()
    print({"added": added, "affected_courses": len(affected)})

if __name__ == "__main__":
    main()
