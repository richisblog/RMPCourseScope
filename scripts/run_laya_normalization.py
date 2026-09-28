import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "uc_davis_rmp_normalized.sqlite"
sys.path.insert(0, str(ROOT / "work" / "laya_cuda_env"))
sys.path.insert(1, str(ROOT / "work" / "laya_env"))
os.environ.setdefault("USE_TF", "0")
CACHE = {}

def parse_key(key):
    m = re.fullmatch(r"([A-Z]{2,5})(\d+)([A-Z]{0,3})", key or "")
    return (m.group(1), str(int(m.group(2))), m.group(3)) if m else (None, None, None)

def candidates_for(db, legacy_id, raw_key, review_id=None):
    subject, number, suffix = parse_key(raw_key)
    rows = []
    seen = set()

    # A review can spell out the course in its prose even when the RMP
    # course field is abbreviated (for example: "21A" -> "MAT 21A").
    # Use those mentions as high-value candidates before broad fallbacks.
    if review_id is not None:
        for mention_key in CACHE["mentions"].get(review_id, ()):
            for candidate in db.execute(
                "SELECT course_key,display_code,title FROM courses WHERE course_key=?",
                (mention_key,),
            ).fetchall():
                if candidate[0] not in seen:
                    rows.append(candidate)
                    seen.add(candidate[0])

    if number:
        pattern = f"%{number}{suffix}"
        for candidate in CACHE["prof_courses"].get(legacy_id, ()):
            if not candidate[0].endswith(f"{number}{suffix}"):
                continue
            if candidate[0] not in seen:
                rows.append(candidate)
                seen.add(candidate[0])
    if subject and not rows:
        for candidate in CACHE["course_map"].get(raw_key, ()):
            if candidate[0] not in seen:
                rows.append(candidate)
                seen.add(candidate[0])
    if not rows and number:
        for candidate in CACHE["all_courses"]:
            if not candidate[0].endswith(f"{number}{suffix}"):
                continue
            if candidate[0] not in seen:
                rows.append(candidate)
                seen.add(candidate[0])
    return rows[:11]

def build_state(db, row, candidates):
    review_id, legacy_id, raw, key, date, comment = row
    prof = CACHE["professors"].get(legacy_id)
    known = [x[0] for x in CACHE["prof_courses"].get(legacy_id, ())[:30]]
    mentions = list(CACHE["mention_raw"].get(review_id, ()))
    nearby_counts = {}
    try:
        target = datetime.fromisoformat((date or "1900-01-01")[:10])
        for other_date, other_key in CACHE["review_dates"].get(legacy_id, ()):
            if not other_date or not other_key:
                continue
            try:
                if abs((datetime.fromisoformat(other_date[:10]) - target).days) <= 45:
                    nearby_counts[other_key] = nearby_counts.get(other_key, 0) + 1
            except ValueError:
                pass
    except ValueError:
        pass
    nearby = sorted(nearby_counts.items(), key=lambda x: (-x[1], x[0]))[:12]
    return {
        "raw_course": raw, "rule_key": key, "review_date": date,
        "professor": {"name": f"{prof[0]} {prof[1]}", "department": prof[2]} if prof else {},
        "professor_known_courses": known,
        "comment_course_mentions": mentions,
        "nearby_45_day_courses": {k: n for k, n in nearby},
        "comment": (comment or "")[:700],
        "candidates": [{"key": c[0], "official_code": c[1], "title": c[2]} for c in candidates],
    }

def load_agent():
    import torch
    import laya
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this batch; torch.cuda.is_available() is false")
    return laya.load("convaiinnovations/laya", device="cuda")

def prepare_cache(db):
    CACHE["course_map"] = {}
    CACHE["all_courses"] = db.execute(
        "SELECT course_key,display_code,title FROM courses ORDER BY course_key"
    ).fetchall()
    for row in CACHE["all_courses"]:
        CACHE["course_map"].setdefault(row[0], []).append(row)
    CACHE["prof_courses"] = {}
    for legacy_id, course_key, review_count, profile_count in db.execute(
        "SELECT pc.legacy_id,pc.course_key,pc.review_count,pc.profile_count "
        "FROM professor_courses pc ORDER BY pc.review_count DESC,pc.profile_count DESC"
    ).fetchall():
        course = CACHE["course_map"].get(course_key)
        if course:
            CACHE["prof_courses"].setdefault(legacy_id, []).append(course[0])
    CACHE["professors"] = {
        legacy_id: (first_name, last_name, department)
        for legacy_id, first_name, last_name, department in db.execute(
            "SELECT legacy_id,first_name,last_name,department FROM professors"
        ).fetchall()
    }
    CACHE["mentions"] = {}
    CACHE["mention_raw"] = {}
    for review_id, mention_key, mention_raw in db.execute(
        "SELECT review_id,mention_key,mention_raw FROM review_course_mentions"
    ).fetchall():
        if mention_key:
            CACHE["mentions"].setdefault(review_id, set()).add(mention_key)
        if mention_raw:
            CACHE["mention_raw"].setdefault(review_id, set()).add(mention_raw)
    CACHE["review_dates"] = {}
    for legacy_id, date, course_key in db.execute(
        "SELECT legacy_id,date,course_key FROM reviews WHERE date IS NOT NULL"
    ).fetchall():
        CACHE["review_dates"].setdefault(legacy_id, []).append((date, course_key))

def ask(agent, state):
    criteria = {"UNKNOWN": "No candidate is sufficiently supported; preserve the raw label"}
    for c in state["candidates"]:
        criteria[c["key"]] = f"{c['official_code'] or c['key']}: {c['title'] or 'official course identity'}"
    questions = {
        "course_choice": {"type": "choice", "instructions": "Which candidate, if any, is the same exact UC Davis course as the raw label? Use UNKNOWN if evidence is insufficient.", "criteria": criteria},
        "specificity": {"type": "choice", "instructions": "How specific is the evidence?", "criteria": {
            "exact": "Subject, course number, and suffix all identify the same course.",
            "family_only": "The subject/number family matches but the suffix or exact course is uncertain.",
            "insufficient": "Evidence is contradictory or insufficient."
        }},
        "same_course": {"type": "noul", "instructions": "Does the raw label refer to one of the listed candidates rather than an unrelated course?"}
    }
    return agent.predict(state, questions)

def main():
    db = sqlite3.connect(DB)
    prepare_cache(db)
    db.execute("CREATE TABLE IF NOT EXISTS laya_run_meta(key TEXT PRIMARY KEY,value TEXT)")
    db.execute("""CREATE TABLE IF NOT EXISTS professor_course_links(
      legacy_id INTEGER NOT NULL,
      course_key TEXT NOT NULL,
      inferred_review_count INTEGER NOT NULL,
      max_confidence REAL,
      relationships TEXT,
      PRIMARY KEY(legacy_id,course_key)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_review_raw_key ON reviews(course_key)")
    rows = db.execute("""SELECT review_id,legacy_id,course_raw,course_key,date,comment
      FROM reviews WHERE course_raw IS NOT NULL ORDER BY legacy_id,review_id""").fetchall()
    observations = []
    for row in rows:
        # Fully qualified codes such as MAT21A are deterministic and do not
        # need an Laya decision.  Anything without a subject or suffix stays
        # in the evidence-driven ambiguity pass (21A, MAT21, MATH 21A, etc.).
        subject, number, suffix = parse_key(row[3])
        if subject and suffix:
            continue
        candidates = candidates_for(db, row[1], row[3], row[0])
        if candidates:
            observations.append((row, candidates))
    print({"ambiguous_observations": len(observations), "reviews_total": db.execute("select count(*) from reviews").fetchone()[0]})
    if "--dry-run" in sys.argv:
        return
    agent = load_agent()
    model_revision = "convaiinnovations/laya@runtime"
    db.execute("DELETE FROM course_alias_decisions")
    db.execute("DELETE FROM review_course_links WHERE relationship IN ('auto_linked','search_expansion','weak_alias','unresolved')")
    started = time.perf_counter()
    for index, (row, candidates) in enumerate(observations, 1):
        review_id, legacy_id, raw, key, date, comment = row
        state = build_state(db, row, candidates)
        result = ask(agent, state)
        answers = result.get("answers", {})
        choice = answers.get("course_choice", {})
        selected = choice.get("choice", "UNKNOWN")
        probabilities = choice.get("probabilities", {})
        p_choice = float(probabilities.get(selected, 0.0))
        same = answers.get("same_course", {})
        p_same = float(same.get("noul", 0.0))
        specificity = answers.get("specificity", {}).get("choice", "insufficient")
        if selected == "UNKNOWN" or specificity == "insufficient":
            relationship, confidence = "unresolved", max(p_choice, p_same)
        elif specificity == "family_only":
            relationship, confidence = "family", max(p_choice, p_same)
        elif p_choice >= 0.95 and p_same >= 0.95:
            relationship, confidence = "auto_linked", min(p_choice, p_same)
        elif p_choice >= 0.80 and p_same >= 0.80:
            relationship, confidence = "search_expansion", min(p_choice, p_same)
        else:
            relationship, confidence = "weak_alias", min(p_choice, p_same)
        display = next((c[1] for c in candidates if c[0] == selected), None)
        evidence = {"state": state, "model_result": result, "candidate_probabilities": probabilities}
        cur = db.execute("""INSERT INTO course_alias_decisions(legacy_id,review_id,raw_course,recommended_key,recommended_display,relationship,confidence,method,evidence_json,model_revision)
          VALUES(?,?,?,?,?,?,?,?,?,?)""", (legacy_id, review_id, raw, None if selected == "UNKNOWN" else selected, display, relationship, confidence, "laya", json.dumps(evidence, ensure_ascii=False), model_revision))
        decision_id = cur.lastrowid
        if selected != "UNKNOWN":
            db.execute("INSERT OR REPLACE INTO review_course_links VALUES(?,?,?,?,?)", (review_id, selected, relationship, confidence, decision_id))
        if index % 100 == 0:
            db.commit()
            print({"processed": index, "total": len(observations), "seconds": round(time.perf_counter()-started,1)}, flush=True)
    # Build a reverse index that includes Laya-expanded links while keeping
    # professor_courses as the deterministic/source index.
    db.execute("DELETE FROM professor_course_links")
    db.execute("""INSERT INTO professor_course_links
      (legacy_id,course_key,inferred_review_count,max_confidence,relationships)
      SELECT r.legacy_id,l.course_key,count(*),max(l.confidence),
             group_concat(DISTINCT l.relationship)
      FROM review_course_links l JOIN reviews r ON r.review_id=l.review_id
      WHERE l.relationship IN ('auto_linked','search_expansion','family','weak_alias')
      GROUP BY r.legacy_id,l.course_key""")

    # Add raw and Laya-recommended labels to FTS without replacing canonical rows.
    for key, in db.execute("SELECT DISTINCT course_key FROM courses").fetchall():
        aliases = [x[0] for x in db.execute(
            "SELECT DISTINCT course_raw FROM reviews WHERE course_key=? AND course_raw IS NOT NULL",
            (key,),
        ).fetchall()]
        aliases.extend(x[0] for x in db.execute(
            "SELECT DISTINCT raw_course FROM course_alias_decisions "
            "WHERE recommended_key=? AND raw_course IS NOT NULL", (key,)
        ).fetchall())
        db.execute("UPDATE course_search SET aliases=? WHERE course_key=?", (" ".join(aliases), key))
    db.execute("INSERT OR REPLACE INTO laya_run_meta VALUES('last_run',?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    db.commit(); db.close()
    print({"complete": len(observations), "seconds": round(time.perf_counter()-started,1)})

if __name__ == "__main__": main()
