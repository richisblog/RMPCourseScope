"""Materialize descriptive professor-by-course review statistics in the RMP DB.

One review contributes at most once to a course, even if multiple link methods
suggested it. These are voluntary-review summaries, not teaching-quality or
official enrollment estimates.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

VERSION = "2026-09-22-v1"


def summarize(rows: list[dict]) -> dict:
    ratings = [r["rating"] for r in rows if r["rating"] is not None]
    difficulties = [r["difficulty"] for r in rows if r["difficulty"] is not None]
    distribution = {str(i): sum(round(x) == i for x in ratings) for i in range(1, 6)}
    result = {
        "reviews": len(rows), "rating_n": len(ratings),
        "rating_mean": round(statistics.mean(ratings), 3) if ratings else None,
        "rating_median": round(statistics.median(ratings), 3) if ratings else None,
        "rating_sd": round(statistics.stdev(ratings), 3) if len(ratings) > 1 else None,
        "rating_distribution": distribution,
        "difficulty_n": len(difficulties),
        "difficulty_mean": round(statistics.mean(difficulties), 3) if difficulties else None,
        "difficulty_median": round(statistics.median(difficulties), 3) if difficulties else None,
    }
    if ratings:
        good = sum(x >= 4 for x in ratings)
        poor = sum(x <= 2 for x in ratings)
        result["positive_share"] = round(good / len(ratings), 4)
        result["negative_share"] = round(poor / len(ratings), 4)
        # Wilson interval describes observed share uncertainty only; it cannot
        # correct self-selection or other RMP sampling bias.
        z = 1.96
        p, n = good / len(ratings), len(ratings)
        center = (p + z*z/(2*n)) / (1 + z*z/n)
        half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
        result["positive_share_wilson95"] = [round(max(0, center-half), 4), round(min(1, center+half), 4)]
    else:
        result.update(positive_share=None, negative_share=None, positive_share_wilson95=None)
    return result


def build(db: sqlite3.Connection, as_of: date) -> int:
    db.row_factory = sqlite3.Row
    db.execute("DROP TABLE IF EXISTS course_professor_stats_new")
    db.execute("""CREATE TABLE course_professor_stats_new (
        course_key TEXT NOT NULL, professor_id INTEGER NOT NULL,
        review_count INTEGER NOT NULL, rating_count INTEGER NOT NULL,
        avg_rating REAL, avg_difficulty REAL, latest_review_date TEXT,
        recent_24m_count INTEGER NOT NULL, recent_24m_avg_rating REAL,
        previous_24m_count INTEGER NOT NULL, previous_24m_avg_rating REAL,
        trend_delta REAL, trend_status TEXT NOT NULL,
        stats_json TEXT NOT NULL, as_of TEXT NOT NULL, method_version TEXT NOT NULL,
        PRIMARY KEY (course_key, professor_id)
    )""")
    groups = defaultdict(list)
    query = """SELECT l.course_key, r.legacy_id professor_id, r.review_id, r.date,
                      r.rating, r.difficulty, MAX(l.confidence) confidence
               FROM review_course_links l JOIN reviews r ON r.review_id=l.review_id
               GROUP BY l.course_key, r.legacy_id, r.review_id"""
    for row in db.execute(query):
        try:
            when = date.fromisoformat(row["date"][:10])
        except (ValueError, TypeError):
            when = None
        if when and when > as_of:
            continue
        groups[(row["course_key"], row["professor_id"])].append({
            "date": when, "rating": row["rating"], "difficulty": row["difficulty"],
            "confidence": row["confidence"]})
    recent_start = as_of - timedelta(days=730)
    previous_start = recent_start - timedelta(days=730)
    insert = "INSERT INTO course_professor_stats_new VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    for (key, professor_id), rows in groups.items():
        overall = summarize(rows)
        recent = summarize([r for r in rows if r["date"] and recent_start <= r["date"] <= as_of])
        previous = summarize([r for r in rows if r["date"] and previous_start <= r["date"] < recent_start])
        by_year = defaultdict(list)
        for row in rows:
            if row["date"]:
                by_year[str(row["date"].year)].append(row)
        delta = None
        if recent["rating_n"] >= 5 and previous["rating_n"] >= 5:
            delta = round(recent["rating_mean"] - previous["rating_mean"], 3)
        status = "insufficient_data" if delta is None else (
            "up" if delta >= 0.3 else "down" if delta <= -0.3 else "stable")
        dates = [r["date"] for r in rows if r["date"]]
        detail = {
            "description": "Descriptive summaries of voluntarily submitted student reviews linked to this professor and course. Not an official UC Davis grade, enrollment, or teaching-quality measure.",
            "as_of": as_of.isoformat(), "method_version": VERSION,
            "link_scope": "all linked reviews, deduplicated by review ID per course; inferred links included",
            "overall": overall, "recent_24m": recent, "previous_24m": previous,
            "calendar_years": {year: summarize(values) for year, values in sorted(by_year.items())},
            "link_confidence": {
                "at_least_0_8": sum(r["confidence"] >= 0.8 for r in rows),
                "below_0_8": sum(r["confidence"] < 0.8 for r in rows),
            },
            "trend": {"status": status, "rating_mean_delta": delta,
                      "description": "Recent 730 days minus preceding 730 days; shown only when each window has at least 5 numeric ratings. Up/down threshold is 0.3 rating points, descriptive rather than a significance test."},
            "cautions": ["RMP reviews are self-selected and may not represent all students.",
                         "A review-to-course link may be inferred; use min_confidence and inspect original course labels for sensitive comparisons.",
                         "Course-level would-take-again is omitted when individual review values are unavailable."],
        }
        db.execute(insert, (key, professor_id, len(rows), overall["rating_n"],
                   overall["rating_mean"], overall["difficulty_mean"],
                   max(dates).isoformat() if dates else None,
                   recent["reviews"], recent["rating_mean"],
                   previous["reviews"], previous["rating_mean"], delta, status,
                   json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                   as_of.isoformat(), VERSION))
    db.execute("DROP TABLE IF EXISTS course_professor_stats")
    db.execute("ALTER TABLE course_professor_stats_new RENAME TO course_professor_stats")
    db.execute("CREATE INDEX IF NOT EXISTS idx_course_stats_prof ON course_professor_stats(professor_id)")
    db.commit()
    return len(groups)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("outputs/uc_davis_rmp_normalized.sqlite"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    connection = sqlite3.connect(args.db)
    print(f"professor_course_groups={build(connection, args.as_of)}", flush=True)
