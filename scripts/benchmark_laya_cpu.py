import os
import sys
import time

sys.path.insert(0, "work/laya_env")
os.environ["USE_TF"] = "0"
import laya

t0 = time.perf_counter()
agent = laya.load("convaiinnovations/laya")
load_s = time.perf_counter() - t0
state = {"raw_course": "mat 21a", "candidate": "MAT 021A", "department": "Mathematics", "nearby_reviews": ["MAT21A", "MAT21A", "MAT21B"]}
questions = {
    "same_course": {"type": "noul", "instructions": "Do these labels refer to the same exact course?"},
    "specificity": {"type": "choice", "instructions": "Is the mapping exact, family-only, or insufficient?", "criteria": {
        "exact": "exact subject, number, suffix", "family_only": "number family but suffix uncertain", "insufficient": "not enough evidence"
    }}
}
for _ in range(2):
    agent.predict(state, questions)
t0 = time.perf_counter()
result = agent.predict(state, questions)
latency = time.perf_counter() - t0
print({"load_seconds": round(load_s, 2), "latency_seconds": round(latency, 4), "result": result})
