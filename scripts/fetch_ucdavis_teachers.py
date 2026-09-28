import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outputs"))
from rmp_client import RMPAPI

rmp = RMPAPI()
query = """query($query: TeacherSearchQuery!, $first: Int!, $after: String) {
  newSearch { teachers(query: $query, first: $first, after: $after) {
    resultCount edges { cursor node {
      id legacyId firstName lastName department avgRating avgDifficulty
      numRatings wouldTakeAgainPercent school { id legacyId name city state }
    }} pageInfo { hasNextPage endCursor }
  }}
}"""

school_id = "U2Nob29sLTEwNzM="
after = None
teachers = []
reported_count = None

while True:
    data = rmp._post(query, {
        "query": {"text": "", "schoolID": school_id},
        "first": 100,
        "after": after,
    })
    result = data["newSearch"]["teachers"]
    reported_count = result.get("resultCount", reported_count)
    for edge in result.get("edges", []):
        node = edge["node"]
        node["profile_url"] = rmp.get_teacher_url(node.get("legacyId") or rmp.numeric_id(node["id"]))
        teachers.append(node)
    page = result.get("pageInfo") or {}
    if not page.get("hasNextPage"):
        break
    next_after = page.get("endCursor")
    if not next_after or next_after == after:
        raise RuntimeError("Pagination cursor did not advance")
    after = next_after

out_dir = Path(__file__).resolve().parents[1] / "outputs"
json_path = out_dir / "uc_davis_teachers.json"
csv_path = out_dir / "uc_davis_teachers.csv"
json_path.write_text(json.dumps({
    "school": {"id": school_id, "legacyId": 1073, "name": "University of California Davis"},
    "reported_count": reported_count,
    "fetched_count": len(teachers),
    "teachers": teachers,
}, ensure_ascii=False, indent=2), encoding="utf-8")

with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
    fields = ["legacyId", "id", "firstName", "lastName", "profile_url", "department",
              "avgRating", "avgDifficulty", "numRatings", "wouldTakeAgainPercent"]
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(teachers)

print(json.dumps({"reported_count": reported_count, "fetched_count": len(teachers),
                  "json": str(json_path), "csv": str(csv_path)}, ensure_ascii=False))
