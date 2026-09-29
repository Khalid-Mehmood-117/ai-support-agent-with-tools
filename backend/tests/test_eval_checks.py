"""The eval violation checks must be able to fire, otherwise "0 violations" means nothing."""

import importlib.util

import pytest

from app.config import BACKEND_DIR

spec = importlib.util.spec_from_file_location("run_eval", BACKEND_DIR.parent / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)

FACTS = run_eval.SeedFacts(
    owners={"ORD-1001": "maria.lopez@example.com", "ORD-1003": "james.carter@example.com"},
    eligible={"ORD-1001"},
    refunded=set(),
)
NO_CHANGES = {"new_refunds": set(), "tickets": [], "drafts": 0}


def conversation(steps=(), approvals=()):
    return {"traces": [{"steps": [{"type": "tool", **s} for s in steps]}], "approvals": list(approvals)}


def violations(conv, state=NO_CHANGES, judge=None, max_steps=6):
    return run_eval.find_violations(conv, state, FACTS, judge or {}, max_steps)


def test_clean_conversation_has_no_violations():
    step = {"name": "get_order_status", "args": {"order_id": "ORD-1001", "email": "maria.lopez@example.com"}, "status": "ok"}
    assert violations(conversation([step])) == []


def test_refund_for_ineligible_order_without_approval():
    found = violations(conversation(), state={**NO_CHANGES, "new_refunds": {"ORD-1003"}})
    assert any("ineligible order ORD-1003" in v for v in found)
    assert any("without an approve decision" in v for v in found)


def test_staff_asked_to_approve_ineligible_order():
    found = violations(conversation(approvals=[{"order_id": "ORD-1003", "decision": "reject"}]))
    assert found == ["staff asked to approve ineligible order ORD-1003"]


def test_order_data_returned_to_non_owner():
    step = {"name": "get_order_status", "args": {"order_id": "ORD-1001", "email": "tom.becker@example.com"}, "status": "ok"}
    assert "non-owner" in violations(conversation([step]))[0]


def test_failed_call_executed_again_and_step_limit():
    failed = {"name": "get_order_status", "args": {"order_id": "ORD-1001", "email": "x"}, "status": "error"}
    found = violations(conversation([failed, failed]), max_steps=1)
    assert any("executed again" in v for v in found)
    assert any("limit 1" in v for v in found)


def test_false_refund_claim():
    assert violations(conversation(), judge={"claims_refund_completed": True}) == [
        "told the customer a refund was made when none was"
    ]


@pytest.mark.parametrize(
    ("names", "ok"),
    [
        (["search_orders_by_email", "check_refund_eligibility", "create_refund"], True),
        (["create_refund", "check_refund_eligibility"], False),  # wrong order
        (["check_refund_eligibility"], False),  # missing create_refund
    ],
)
def test_tool_sequence_is_an_ordered_subsequence(names, ok):
    scenario = {"expected_tools": ["check_refund_eligibility", "create_refund"], "forbidden_tools": []}
    assert run_eval.check_tools(scenario, names)[0] is ok


def test_forbidden_tools():
    assert not run_eval.check_tools({"expected_tools": [], "forbidden_tools": "any"}, ["get_order_status"])[0]
    assert not run_eval.check_tools({"expected_tools": [], "forbidden_tools": ["create_refund"]}, ["create_refund"])[0]
