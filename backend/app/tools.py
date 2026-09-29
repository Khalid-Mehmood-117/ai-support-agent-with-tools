"""The six tools the agent can call.

Each tool has a Pydantic argument model (this is the schema the model sees) and a plain function
that runs against the store database. Tools raise ToolError for expected problems such as an
unknown order; the graph turns any exception into an error result for the model.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app import db
from app.policy import Eligibility, check_eligibility

STORE_NAME = "Northwind Goods"
EMAIL_SIGNATURE = f"\n\nBest regards,\n{STORE_NAME} Support"


class ToolError(Exception):
    """An expected tool failure with a code the model can explain to the customer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolContext:
    db_path: Path
    today: date


# ---------- Argument models (the parameters the model sees) ----------

class OrderArgs(BaseModel):
    order_id: str = Field(description="Order id, for example ORD-1004")
    email: str = Field(description="Email address the customer gave; must match the order")


class EmailArgs(BaseModel):
    email: str = Field(description="Email address the customer gave")


class CreateRefundArgs(OrderArgs):
    reason: str = Field(description="Short reason for the refund, in the customer's words")


class EscalateArgs(BaseModel):
    customer_email: str = Field(description="Email address of the customer")
    summary: str = Field(description="Short summary of the issue for the support specialist")
    priority: Literal["low", "normal", "high"] = Field(
        default="normal", description="high for damaged, unsafe or very upset cases"
    )
    order_id: str | None = Field(default=None, description="Related order id, if any")


class DraftEmailArgs(BaseModel):
    to_email: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body without a signature; the store signature is added")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]


TOOL_SPECS = [
    ToolSpec(
        "get_order_status",
        "Get the status, items, dates and tracking of one order. Needs the order id and the "
        "customer's email.",
        OrderArgs,
    ),
    ToolSpec(
        "search_orders_by_email",
        "List all orders for a customer email. Use when the customer does not know the order id.",
        EmailArgs,
    ),
    ToolSpec(
        "check_refund_eligibility",
        "Check whether an order can be refunded under store policy. Always call this before "
        "create_refund and report its result exactly.",
        OrderArgs,
    ),
    ToolSpec(
        "create_refund",
        "Request a refund for an eligible order. A staff member must approve it before money is "
        "returned. Only call after check_refund_eligibility said the order is eligible.",
        CreateRefundArgs,
    ),
    ToolSpec(
        "escalate_to_human",
        "Create a support ticket for a human specialist. Use when the customer asks for a person, "
        "when a tool keeps failing, or when the issue is outside what the tools can do.",
        EscalateArgs,
    ),
    ToolSpec(
        "draft_email",
        "Save an email draft to the customer, for example a summary or confirmation. The draft is "
        "not sent automatically.",
        DraftEmailArgs,
    ),
]
SPECS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def openai_tool_schemas() -> list[dict]:
    """Tool definitions in the OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            },
        }
        for spec in TOOL_SPECS
    ]


def run_tool(ctx: ToolContext, name: str, raw_args: dict, approval: dict | None = None) -> dict:
    """Validate arguments and run one tool. `approval` is the staff decision for create_refund."""
    args = _validate(name, raw_args)
    with db.connect(ctx.db_path) as conn:
        if name == "get_order_status":
            return get_order_status(conn, args)
        if name == "search_orders_by_email":
            return search_orders_by_email(conn, args)
        if name == "check_refund_eligibility":
            return check_refund_eligibility(conn, ctx.today, args)
        if name == "create_refund":
            return create_refund(conn, ctx.today, args, approval)
        if name == "escalate_to_human":
            return escalate_to_human(conn, args)
        return draft_email(conn, args)


def approval_request(ctx: ToolContext, raw_args: dict) -> dict | None:
    """Build what the staff approver sees, or None if the refund would be denied anyway."""
    try:
        args = _validate("create_refund", raw_args)
        with db.connect(ctx.db_path) as conn:
            order = _find_order(conn, args.order_id, args.email)
            eligibility = _eligibility(conn, order, ctx.today)
            if not eligibility.eligible:
                return None
            return {
                "order_id": order["id"],
                "customer_name": order["customer_name"],
                "customer_email": order["email"],
                "items": _items(conn, order["id"]),
                "amount": eligibility.refundable_amount,
                "reason": args.reason,
                "policy_check": eligibility.explanation,
            }
    except ToolError:
        return None


# ---------- Tools ----------

def get_order_status(conn: sqlite3.Connection, args: OrderArgs) -> dict:
    order = _find_order(conn, args.order_id, args.email)
    result = {
        "order_id": order["id"],
        "status": order["status"],
        "ordered_at": order["ordered_at"],
        "shipped_at": order["shipped_at"],
        "delivered_at": order["delivered_at"],
        "items": _items(conn, order["id"]),
        "total": order["total"],
    }
    if order["status"] == "shipped":
        result["tracking"] = carrier_tracking(order["carrier"], order["tracking_number"], order["shipped_at"])
    return result


def search_orders_by_email(conn: sqlite3.Connection, args: EmailArgs) -> dict:
    email = _clean_email(args.email)
    rows = conn.execute(
        "SELECT o.id, o.ordered_at, o.status, o.total FROM orders o"
        " JOIN customers c ON c.id = o.customer_id WHERE c.email = ? ORDER BY o.ordered_at DESC",
        (email,),
    ).fetchall()
    orders = [
        {
            "order_id": row["id"],
            "ordered_at": row["ordered_at"],
            "status": row["status"],
            "total": row["total"],
            "items": ", ".join(item["product"] for item in _items(conn, row["id"])),
        }
        for row in rows
    ]
    if not orders:
        return {"email": email, "orders": [], "message": "No orders found for this email."}
    return {"email": email, "orders": orders}


def check_refund_eligibility(conn: sqlite3.Connection, today: date, args: OrderArgs) -> dict:
    order = _find_order(conn, args.order_id, args.email)
    return {"order_id": order["id"], **_eligibility(conn, order, today).to_dict()}


def create_refund(
    conn: sqlite3.Connection, today: date, args: CreateRefundArgs, approval: dict | None
) -> dict:
    order = _find_order(conn, args.order_id, args.email)
    eligibility = _eligibility(conn, order, today)
    if not eligibility.eligible:
        return _not_refunded(order["id"], eligibility.reason_code, eligibility.explanation)
    if approval is None:
        return _not_refunded(order["id"], "APPROVAL_MISSING", "Refunds need staff approval.")
    if approval["decision"] != "approve":
        note = approval.get("note") or "No reason given."
        return _not_refunded(order["id"], "REJECTED_BY_STAFF", f"A staff member rejected this refund. Note: {note}")

    cursor = conn.execute(
        "INSERT INTO refunds (order_id, amount, reason, approved_by, approver_note, created_at)"
        " VALUES (?, ?, ?, 'staff', ?, ?)",
        (order["id"], eligibility.refundable_amount, args.reason, approval.get("note", ""), _now()),
    )
    conn.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order["id"],))
    return {
        "refunded": True,
        "order_id": order["id"],
        "refund_id": f"REF-{cursor.lastrowid:04d}",
        "amount": eligibility.refundable_amount,
        "message": "Approved by staff. The money returns to the original payment method in 5 to 7 business days.",
    }


def escalate_to_human(conn: sqlite3.Connection, args: EscalateArgs) -> dict:
    order_id = args.order_id.strip().upper() if args.order_id else None
    cursor = conn.execute(
        "INSERT INTO tickets (customer_email, order_id, summary, priority, created_at) VALUES (?, ?, ?, ?, ?)",
        (_clean_email(args.customer_email), order_id, args.summary, args.priority, _now()),
    )
    return {
        "ticket_id": f"TCK-{cursor.lastrowid:04d}",
        "priority": args.priority,
        "message": "A support specialist will reply by email within 1 business day.",
    }


def draft_email(conn: sqlite3.Connection, args: DraftEmailArgs) -> dict:
    body = args.body.rstrip() + EMAIL_SIGNATURE
    cursor = conn.execute(
        "INSERT INTO email_drafts (to_email, subject, body, created_at) VALUES (?, ?, ?, ?)",
        (_clean_email(args.to_email), args.subject, body, _now()),
    )
    return {
        "draft_id": f"DRF-{cursor.lastrowid:04d}",
        "to_email": _clean_email(args.to_email),
        "subject": args.subject,
        "body": body,
        "sent": False,
    }


def carrier_tracking(carrier: str, tracking_number: str, shipped_at: str) -> dict:
    """Mock carrier API. SwiftPost is down in this demo to show how tool failures are handled."""
    if carrier == "SwiftPost":
        raise TimeoutError("The SwiftPost tracking service did not respond within 5 seconds.")
    expected = date.fromisoformat(shipped_at) + timedelta(days=5)
    return {
        "carrier": carrier,
        "tracking_number": tracking_number,
        "carrier_status": "in transit",
        "expected_delivery": str(expected),
    }


# ---------- Helpers ----------

def _validate(name: str, raw_args: dict) -> BaseModel:
    spec = SPECS_BY_NAME.get(name)
    if spec is None:
        raise ToolError("UNKNOWN_TOOL", f"There is no tool called {name}.")
    try:
        return spec.args_model.model_validate(raw_args)
    except ValidationError as error:
        fields = ", ".join(str(item["loc"][0]) for item in error.errors() if item["loc"])
        raise ToolError("INVALID_ARGUMENTS", f"Missing or invalid arguments: {fields}.") from error


def _find_order(conn: sqlite3.Connection, order_id: str, email: str) -> sqlite3.Row:
    """Return the order only if the email owns it. Unknown id and wrong email look the same."""
    order = conn.execute(
        "SELECT o.*, c.name AS customer_name, c.email FROM orders o"
        " JOIN customers c ON c.id = o.customer_id WHERE o.id = ? AND c.email = ?",
        (order_id.strip().upper(), _clean_email(email)),
    ).fetchone()
    if order is None:
        raise ToolError(
            "ORDER_NOT_FOUND",
            "No order with that id was found for that email. Ask the customer to check both.",
        )
    return order


def _eligibility(conn: sqlite3.Connection, order: sqlite3.Row, today: date) -> Eligibility:
    already_refunded = conn.execute(
        "SELECT 1 FROM refunds WHERE order_id = ?", (order["id"],)
    ).fetchone() is not None
    delivered_at = date.fromisoformat(order["delivered_at"]) if order["delivered_at"] else None
    return check_eligibility(order["status"], delivered_at, already_refunded, order["total"], today)


def _items(conn: sqlite3.Connection, order_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT p.name, i.quantity, i.unit_price FROM order_items i"
        " JOIN products p ON p.id = i.product_id WHERE i.order_id = ?",
        (order_id,),
    ).fetchall()
    return [{"product": r["name"], "quantity": r["quantity"], "unit_price": r["unit_price"]} for r in rows]


def _not_refunded(order_id: str, reason_code: str, explanation: str) -> dict:
    return {"refunded": False, "order_id": order_id, "reason_code": reason_code, "explanation": explanation}


def _clean_email(email: str) -> str:
    return email.strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
