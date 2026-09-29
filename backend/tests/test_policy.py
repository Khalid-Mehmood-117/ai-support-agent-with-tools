from datetime import date, timedelta

import pytest

from app.policy import check_eligibility

TODAY = date(2026, 9, 15)


def delivered(days_ago: int, refunded: bool = False):
    return check_eligibility("delivered", TODAY - timedelta(days=days_ago), refunded, 79.0, TODAY)


def test_recent_delivery_is_eligible_for_the_full_total():
    result = delivered(5)
    assert result.eligible
    assert result.reason_code == "ELIGIBLE"
    assert result.refundable_amount == 79.0


def test_window_boundary_is_30_days_inclusive():
    assert delivered(30).eligible
    assert delivered(31).reason_code == "OUTSIDE_WINDOW"
    assert delivered(31).refundable_amount == 0.0


def test_already_refunded_is_denied_even_inside_window():
    assert delivered(3, refunded=True).reason_code == "ALREADY_REFUNDED"
    assert check_eligibility("refunded", TODAY, False, 39.0, TODAY).reason_code == "ALREADY_REFUNDED"


@pytest.mark.parametrize(
    ("status", "reason_code"),
    [("cancelled", "CANCELLED"), ("processing", "NOT_DELIVERED"), ("shipped", "NOT_DELIVERED")],
)
def test_orders_that_were_never_delivered_are_denied(status, reason_code):
    result = check_eligibility(status, None, False, 50.0, TODAY)
    assert not result.eligible
    assert result.reason_code == reason_code
