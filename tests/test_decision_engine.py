import pytest
from app.services.decision_engine import DecisionEngine

def test_priority_evaluation_imminent_deadline():
    de = DecisionEngine()
    # Due in 12 hours -> urgency should scale to near 1.0
    res = de.evaluate_obligation_priority(
        base_urgency=0.3,
        base_importance=0.8,
        due_date="2026-10-25T02:00:00Z"
    )
    assert res["urgency_score"] >= 0.8
    assert res["importance_score"] == 0.8
    assert res["eisenhower_quadrant"] == "Q1_DO_FIRST"

def test_priority_evaluation_graph_boost():
    de = DecisionEngine()
    # Base importance 0.5 with 3 dependent obligations blocked -> should boost importance
    res = de.evaluate_obligation_priority(
        base_urgency=0.4,
        base_importance=0.5,
        dependent_count=3
    )
    assert res["importance_score"] > 0.5
    assert res["graph_boost_applied"] is True

def test_calendar_action_appointment():
    de = DecisionEngine()
    res = de.decide_calendar_action(
        node_title="Dentist Checkup",
        node_type="event",
        is_calendar_candidate=True,
        calendar_start="2026-10-27T10:00:00",
        calendar_end="2026-10-27T11:00:00"
    )
    assert res["action"] == "DIRECT_EVENT"
    assert res["confidence"] >= 0.9

def test_calendar_action_focus_block():
    de = DecisionEngine()
    res = de.decide_calendar_action(
        node_title="Refactor PostgreSQL Storage Engine",
        node_type="obligation",
        is_calendar_candidate=False,
        estimated_minutes=90,
        quadrant="Q1_DO_FIRST"
    )
    assert res["action"] == "FOCUS_BLOCK"
