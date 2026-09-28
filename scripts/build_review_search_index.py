"""Build the read-only FTS/activity sidecar for CourseScope.

Run after importing or normalizing reviews:
    python scripts/build_review_search_index.py [source.sqlite] [search.sqlite]
"""
from __future__ import annotations

import sqlite3
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "outputs" / "uc_davis_rmp_normalized.sqlite"
TARGET = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "outputs" / "coursescope_search.sqlite"
TEMP = TARGET.with_suffix(TARGET.suffix + ".tmp")


def main() -> None:
    source = sqlite3.connect(SOURCE.resolve().as_uri() + "?mode=ro", uri=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TEMP.unlink(missing_ok=True)
    target = sqlite3.connect(TEMP)
    try:
        target.execute("PRAGMA journal_mode=DELETE")
        target.execute("DROP TABLE IF EXISTS review_fts")
        target.execute("DROP TABLE IF EXISTS professor_activity")
        target.execute("CREATE VIRTUAL TABLE review_fts USING fts5(review_id UNINDEXED, comment, tokenize='unicode61 remove_diacritics 2')")
        target.execute("CREATE TABLE professor_activity (professor_id INTEGER PRIMARY KEY, last_review_date TEXT)")
        target.execute("CREATE INDEX idx_activity_date ON professor_activity(last_review_date)")
        target.execute("BEGIN")
        target.executemany(
            "INSERT INTO review_fts(review_id,comment) VALUES (?,?)",
            source.execute("SELECT review_id,comment FROM reviews WHERE comment IS NOT NULL AND comment<>''"),
        )
        target.executemany(
            "INSERT INTO professor_activity(professor_id,last_review_date) VALUES (?,?)",
            source.execute(
                "SELECT legacy_id,MAX(SUBSTR(date,1,10)) FROM reviews "
                "WHERE legacy_id IS NOT NULL AND date IS NOT NULL GROUP BY legacy_id"
            ),
        )
        target.commit()
        target.execute("PRAGMA optimize")
        target.commit()
        print(f"Built {TARGET}: {target.execute('SELECT COUNT(*) FROM review_fts').fetchone()[0]} comments, "
              f"{target.execute('SELECT COUNT(*) FROM professor_activity').fetchone()[0]} professor activity rows")
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
    os.replace(TEMP, TARGET)
    print(f"Published sidecar atomically: {TARGET}")


if __name__ == "__main__":
    main()
