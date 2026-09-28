import os
import sys
import time

sys.path.insert(0, "work/laya_cuda_env")
sys.path.insert(1, "work/laya_env")
os.environ["USE_TF"] = "0"
import torch
import laya

t0 = time.perf_counter()
agent = laya.load("convaiinnovations/laya", device="cuda")
load_s = time.perf_counter() - t0
state = {"raw_course": "21A", "candidate": "MAT 021A", "department": "Mathematics", "professor_courses": ["MAT21A", "MAT21B"], "comment": "This is my best teacher I met in MAT 21A."}
questions = {
    "same_course": {"type": "noul", "instructions": "Do the raw label and candidate denote the same exact UC Davis course?"},
    "specificity": {"type": "choice", "instructions": "How specific is the mapping?", "criteria": {"exact": "exact course", "family_only": "course family only", "insufficient": "insufficient evidence"}}
}
for _ in range(5):
    agent.predict(state, questions)
if torch.cuda.is_available(): torch.cuda.synchronize()
t0 = time.perf_counter()
result = agent.predict(state, questions)
if torch.cuda.is_available(): torch.cuda.synchronize()
latency = time.perf_counter() - t0
print({"device": torch.cuda.get_device_name(0), "load_seconds": round(load_s, 2), "latency_seconds": round(latency, 4), "result": result})
