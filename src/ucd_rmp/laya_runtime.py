"""Optional local Laya adapter; imports the model only when requested."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class LayaDecision:
    same_course_probability: float
    specificity: str
    evidence_score: float
    raw: Dict[str, Any]
    model_revision: str


class LayaDecisionEngine:
    def __init__(self, agent: Any = None, model: str = "convaiinnovations/laya", device: str = "auto", model_revision: str = "unknown"):
        self.model_revision = model_revision
        if agent is not None:
            self.agent = agent
            return
        os.environ.setdefault("USE_TF", "0")
        import laya
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        kwargs = {"device": device}
        self.agent = laya.load(model, **kwargs)

    def predict_batch(self, states: Iterable[Dict[str, Any]]) -> List[LayaDecision]:
        results = []
        questions = {
            "same_course": {"type": "noul", "instructions": "Do the raw label and candidate denote the same exact UC Davis course?"},
            "specificity": {"type": "choice", "instructions": "How specific is this mapping?", "criteria": {
                "exact": "The exact course including subject, number, and suffix is supported.",
                "family_only": "Only a course family or number is supported; a suffix is uncertain.",
                "insufficient": "The evidence is insufficient or contradictory."
            }},
            "evidence_strength": {"type": "score", "instructions": "How strong is the evidence?", "criteria": ["contradictory", "weak", "plausible", "strong", "nearly certain"]}
        }
        for state in states:
            raw = self.agent.predict(state, questions)
            answers = raw.get("answers", {})
            same = answers.get("same_course", {})
            specificity = answers.get("specificity", {})
            score = answers.get("evidence_strength", {})
            results.append(LayaDecision(
                float(same.get("noul", same.get("probability", 0.0))),
                str(specificity.get("choice", "insufficient")),
                float(score.get("score", 0.0)), raw, self.model_revision))
        return results
