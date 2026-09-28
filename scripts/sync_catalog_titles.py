"""Copy exact-key official titles into the RMP course index for fast search."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("outputs/uc_davis_rmp_normalized.sqlite"))
    parser.add_argument("--catalog-db", type=Path, default=Path("outputs/ucdavis_catalog.sqlite"))
    args = parser.parse_args()
    with sqlite3.connect(args.db) as db:
        db.execute("ATTACH DATABASE ? AS catalog", (str(args.catalog_db.resolve()),))
        matched = db.execute("SELECT COUNT(*) FROM courses c JOIN catalog.courses x ON x.course_key=c.course_key").fetchone()[0]
        db.execute("""UPDATE courses SET title=(SELECT title_en FROM catalog.courses x WHERE x.course_key=courses.course_key),
                   catalog_url=(SELECT catalog_url FROM catalog.courses x WHERE x.course_key=courses.course_key),
                   source='ucdavis_catalog'
                   WHERE EXISTS(SELECT 1 FROM catalog.courses x WHERE x.course_key=courses.course_key)""")
        print(f"matched_existing_courses={matched}")
