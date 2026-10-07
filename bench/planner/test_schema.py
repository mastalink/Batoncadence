"""Run: python -m pytest bench/planner/test_schema.py (no model needed)."""
import schema
from eval_set import CASES


def _plan(action, approved):
    return {"title": "t", "schedule": {"kind": "on_demand", "detail": ""}, "confidence": "high",
            "steps": [{"id": "s1", "action": action, "what": "x", "depends_on": [], "condition": "", "needs_approval": approved}]}


def test_score_mapping_validates():
    assert schema.validate_score(schema.to_score(_plan("fetch_data", False))) == []


def test_code_forces_gate_on_risky_steps_even_if_model_says_no():
    for a in ("send_email", "publish", "buy", "pay", "delete"):
        score = schema.to_score(_plan(a, False))
        assert score["tasks"][0]["checkpoint"] is not None, a


def test_forward_reference_is_rejected():
    p = _plan("fetch_data", False)
    p["steps"][0]["depends_on"] = ["s2"]
    assert schema.semantic_errors(p)


def test_eval_set_shape():
    assert len(CASES) == 40
