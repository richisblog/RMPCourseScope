import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "outputs" / "uc_davis_rmp_normalized.sqlite"
PATTERN = re.compile(r"(?<![A-Z0-9])(?:(?P<subject>[A-Z]{2,5})\s*[-._ ]?\s*)?(?P<number>0?\d{1,3})(?P<suffix>[A-Z]{1,3})?(?![A-Z0-9])", re.I)
STOP = {"THE", "THIS", "THAT", "WITH", "FROM", "CLASS", "BEST", "MATH", "BIO", "CHEM"}

def normalize(subject, number, suffix):
    subject = subject.upper() if subject else None
    number = str(int(number))
    suffix = (suffix or "").upper()
    return (subject or "") + number + suffix

def main():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS review_course_mentions(
      mention_id INTEGER PRIMARY KEY, review_id TEXT, legacy_id INTEGER,
      mention_raw TEXT, mention_key TEXT, subject TEXT, number TEXT, suffix TEXT,
      source TEXT, start_offset INTEGER, end_offset INTEGER)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mentions_key ON review_course_mentions(mention_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mentions_teacher ON review_course_mentions(legacy_id)")
    db.execute("DELETE FROM review_course_mentions")
    rows = db.execute("SELECT review_id,legacy_id,comment FROM reviews WHERE comment IS NOT NULL AND comment != ''")
    inserted = 0
    for review_id, legacy_id, comment in rows:
        for m in PATTERN.finditer(comment):
            subject = m.group("subject")
            number = m.group("number")
            suffix = m.group("suffix")
            if subject and subject.upper() in STOP:
                continue
            if not subject and (int(number) < 1 or int(number) > 499 or not suffix):
                continue
            raw = m.group(0)
            db.execute("INSERT INTO review_course_mentions(review_id,legacy_id,mention_raw,mention_key,subject,number,suffix,source,start_offset,end_offset) VALUES(?,?,?,?,?,?,?,?,?,?)", (review_id, legacy_id, raw, normalize(subject, number, suffix), subject.upper() if subject else None, str(int(number)), suffix.upper() if suffix else None, "comment", m.start(), m.end()))
            inserted += 1
    db.commit(); print({"mentions": inserted, "db": str(DB)})

if __name__ == "__main__": main()
