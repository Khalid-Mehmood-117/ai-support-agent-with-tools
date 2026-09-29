import pytest

from app import db
from app.tools import ToolError, approval_request, run_tool

MARIA = "maria.lopez@example.com"
APPROVE = {"decision": "approve", "note": ""}


def count(ctx, table: str) -> int:
    with db.connect(ctx.db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_get_order_status_returns_items_for_the_owner(ctx):
    result = run_tool(ctx, "get_order_status", {"order_id": "ORD-1001", "email": MARIA})
    assert result["status"] == "delivered"
    assert result["items"] == [{"product": "Wireless Earbuds Pro", "quantity": 1, "unit_price": 79.0}]


def test_order_id_and_email_are_case_insensitive(ctx):
    result = run_tool(ctx, "get_order_status", {"order_id": " ord-1001 ", "email": "Maria.Lopez@Example.com"})
    assert result["order_id"] == "ORD-1001"


def test_wrong_email_and_unknown_order_give_the_same_error(ctx):
    with pytest.raises(ToolError) as wrong_email:
        run_tool(ctx, "get_order_status", {"order_id": "ORD-1001", "email": "tom.becker@example.com"})
    with pytest.raises(ToolError) as unknown_order:
        run_tool(ctx, "get_order_status", {"order_id": "ORD-9999", "email": MARIA})
    assert wrong_email.value.code == unknown_order.value.code == "ORDER_NOT_FOUND"
    assert wrong_email.value.message == unknown_order.value.message


def test_shipped_order_includes_tracking(ctx):
    result = run_tool(ctx, "get_order_status", {"order_id": "ORD-1004", "email": "james.carter@example.com"})
    assert result["tracking"]["carrier_status"] == "in transit"
    assert result["tracking"]["expected_delivery"] == "2026-09-17"


def test_swiftpost_tracking_outage_raises(ctx):
    with pytest.raises(TimeoutError):
        run_tool(ctx, "get_order_status", {"order_id": "ORD-1009", "email": "priya.nair@example.com"})


def test_search_orders_by_email(ctx):
    result = run_tool(ctx, "search_orders_by_email", {"email": MARIA})
    assert [o["order_id"] for o in result["orders"]] == ["ORD-1002", "ORD-1001", "ORD-1017"]
    assert run_tool(ctx, "search_orders_by_email", {"email": "nobody@example.com"})["orders"] == []


@pytest.mark.parametrize(
    ("order_id", "email", "reason_code"),
    [
        ("ORD-1001", MARIA, "ELIGIBLE"),
        ("ORD-1015", "liam.walsh@example.com", "ELIGIBLE"),  # exactly 30 days
        ("ORD-1010", "priya.nair@example.com", "OUTSIDE_WINDOW"),  # 31 days
        ("ORD-1006", "aisha.khan@example.com", "ALREADY_REFUNDED"),
        ("ORD-1008", "tom.becker@example.com", "CANCELLED"),
        ("ORD-1002", MARIA, "NOT_DELIVERED"),
    ],
)
def test_check_refund_eligibility_on_seed_data(ctx, order_id, email, reason_code):
    result = run_tool(ctx, "check_refund_eligibility", {"order_id": order_id, "email": email})
    assert result["reason_code"] == reason_code


def refund_args(order_id="ORD-1001", email=MARIA):
    return {"order_id": order_id, "email": email, "reason": "Stopped working"}


def test_create_refund_needs_an_approval(ctx):
    result = run_tool(ctx, "create_refund", refund_args())
    assert result["refunded"] is False
    assert result["reason_code"] == "APPROVAL_MISSING"
    assert count(ctx, "refunds") == 2  # only the seeded refunds


def test_approved_refund_is_written_once(ctx):
    result = run_tool(ctx, "create_refund", refund_args(), APPROVE)
    assert result["refunded"] is True
    assert result["amount"] == 79.0
    assert count(ctx, "refunds") == 3
    assert run_tool(ctx, "get_order_status", {"order_id": "ORD-1001", "email": MARIA})["status"] == "refunded"

    again = run_tool(ctx, "create_refund", refund_args(), APPROVE)
    assert again["reason_code"] == "ALREADY_REFUNDED"
    assert count(ctx, "refunds") == 3


def test_rejected_refund_writes_nothing(ctx):
    result = run_tool(ctx, "create_refund", refund_args(), {"decision": "reject", "note": "Used item"})
    assert result["reason_code"] == "REJECTED_BY_STAFF"
    assert "Used item" in result["explanation"]
    assert count(ctx, "refunds") == 2


def test_policy_wins_over_an_approval(ctx):
    result = run_tool(ctx, "create_refund", refund_args("ORD-1003", "james.carter@example.com"), APPROVE)
    assert result["reason_code"] == "OUTSIDE_WINDOW"
    assert count(ctx, "refunds") == 2


def test_approval_request_only_for_eligible_orders_of_the_owner(ctx):
    request = approval_request(ctx, refund_args())
    assert request["amount"] == 79.0
    assert request["customer_name"] == "Maria Lopez"
    assert request["reason"] == "Stopped working"
    assert approval_request(ctx, refund_args("ORD-1003", "james.carter@example.com")) is None
    assert approval_request(ctx, refund_args(email="tom.becker@example.com")) is None


def test_escalate_creates_a_ticket(ctx):
    result = run_tool(ctx, "escalate_to_human", {"customer_email": MARIA, "summary": "Wants a call", "priority": "high"})
    assert result["ticket_id"] == "TCK-0001"
    assert count(ctx, "tickets") == 1


def test_draft_email_adds_signature_and_is_not_sent(ctx):
    result = run_tool(ctx, "draft_email", {"to_email": MARIA, "subject": "Your order", "body": "Hi Maria"})
    assert result["body"].endswith("Northwind Goods Support")
    assert result["sent"] is False
    assert count(ctx, "email_drafts") == 1


def test_invalid_arguments_are_a_tool_error(ctx):
    with pytest.raises(ToolError) as error:
        run_tool(ctx, "get_order_status", {"order_id": "ORD-1001"})
    assert error.value.code == "INVALID_ARGUMENTS"
    assert "email" in error.value.message
