"""Refund policy. Decided here in code, never by the model."""

from dataclasses import asdict, dataclass
from datetime import date

REFUND_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason_code: str
    explanation: str
    refundable_amount: float

    def to_dict(self) -> dict:
        return asdict(self)


def check_eligibility(
    status: str,
    delivered_at: date | None,
    already_refunded: bool,
    total: float,
    today: date,
) -> Eligibility:
    """An order is refundable only if it was delivered, is not refunded and is inside the window."""
    if already_refunded or status == "refunded":
        return _denied("ALREADY_REFUNDED", "This order has already been refunded.")
    if status == "cancelled":
        return _denied("CANCELLED", "This order was cancelled, so there is nothing to refund.")
    if status != "delivered" or delivered_at is None:
        return _denied(
            "NOT_DELIVERED",
            f"This order is {status} and has not been delivered yet. "
            "Refunds are only possible after delivery.",
        )

    days_since_delivery = (today - delivered_at).days
    if days_since_delivery > REFUND_WINDOW_DAYS:
        return _denied(
            "OUTSIDE_WINDOW",
            f"This order was delivered {days_since_delivery} days ago. "
            f"Refunds are only possible within {REFUND_WINDOW_DAYS} days of delivery.",
        )

    return Eligibility(
        eligible=True,
        reason_code="ELIGIBLE",
        explanation=(
            f"Delivered {days_since_delivery} days ago, inside the {REFUND_WINDOW_DAYS} day window, "
            "and not refunded before."
        ),
        refundable_amount=round(total, 2),
    )


def _denied(reason_code: str, explanation: str) -> Eligibility:
    return Eligibility(False, reason_code, explanation, 0.0)
