import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ucd_rmp.laya_runtime import LayaDecisionEngine

class Fake:
    def predict(self, state, questions):
        assert "same_course" in questions and "specificity" in questions
        return {"answers": {"same_course": {"noul": 0.87}, "specificity": {"choice": "exact"}, "evidence_strength": {"score": 3.0}}}

def test_adapter_keeps_probability_and_specificity():
    result = LayaDecisionEngine(agent=Fake(), model_revision="test").predict_batch([{}])[0]
    assert result.same_course_probability == 0.87
    assert result.specificity == "exact"
