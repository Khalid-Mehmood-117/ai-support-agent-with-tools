"""Create and seed the demo store database.

Usage (from the backend folder):
    python -m app.seed --reset

All dates are relative to the fixed store date 2026-09-15 (see STORE_TODAY in config.py).
"""

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app import db
from app.config import Settings

CUSTOMERS = [
    (1, "Maria Lopez", "maria.lopez@example.com"),
    (2, "James Carter", "james.carter@example.com"),
    (3, "Aisha Khan", "aisha.khan@example.com"),
    (4, "Tom Becker", "tom.becker@example.com"),
    (5, "Priya Nair", "priya.nair@example.com"),
    (6, "Daniel Okafor", "daniel.okafor@example.com"),
    (7, "Sofia Rossi", "sofia.rossi@example.com"),
    (8, "Liam Walsh", "liam.walsh@example.com"),
]

PRODUCTS = [
    ("P01", "Wireless Earbuds Pro", "electronics", 79.00),
    ("P02", "Bluetooth Speaker Mini", "electronics", 39.00),
    ("P03", "USB-C Charging Hub", "electronics", 49.00),
    ("P04", "Smart LED Desk Lamp", "electronics", 59.00),
    ("P05", "Noise Cancelling Headphones", "electronics", 149.00),
    ("P06", "Ceramic Pour-Over Coffee Set", "home", 45.00),
    ("P07", "Linen Throw Blanket", "home", 69.00),
    ("P08", "Stainless Steel Water Bottle", "home", 25.00),
    ("P09", "Bamboo Cutting Board Set", "home", 35.00),
    ("P10", "Aroma Diffuser", "home", 42.00),
    ("P11", "Mechanical Keyboard", "electronics", 119.00),
    ("P12", "Cotton Bath Towel Set", "home", 55.00),
]

# (order id, customer id, status, key date, carrier, items as (product id, quantity))
# The key date is the delivery date for delivered and refunded orders, and the order date otherwise.
# See _order_dates for how the other dates are derived.
ORDERS = [
    ("ORD-1001", 1, "delivered", "2026-09-10", "FastShip", [("P01", 1)]),
    ("ORD-1002", 1, "processing", "2026-09-14", None, [("P06", 1), ("P08", 2)]),
    ("ORD-1003", 2, "delivered", "2026-06-30", "ParcelNet", [("P05", 1)]),
    ("ORD-1004", 2, "shipped", "2026-09-11", "FastShip", [("P03", 1)]),
    ("ORD-1005", 3, "delivered", "2026-09-01", "FastShip", [("P07", 1)]),
    ("ORD-1006", 3, "refunded", "2026-08-28", "ParcelNet", [("P02", 1)]),
    ("ORD-1007", 4, "delivered", "2026-08-25", "FastShip", [("P11", 1)]),
    ("ORD-1008", 4, "cancelled", "2026-09-05", None, [("P10", 1)]),
    ("ORD-1009", 5, "shipped", "2026-09-12", "SwiftPost", [("P12", 1)]),
    ("ORD-1010", 5, "delivered", "2026-08-15", "ParcelNet", [("P04", 1)]),
    ("ORD-1011", 6, "delivered", "2026-08-20", "FastShip", [("P09", 2)]),
    ("ORD-1012", 6, "delivered", "2026-07-20", "FastShip", [("P01", 1), ("P03", 1)]),
    ("ORD-1013", 7, "processing", "2026-09-15", None, [("P05", 1)]),
    ("ORD-1014", 7, "delivered", "2026-08-17", "ParcelNet", [("P06", 1)]),
    ("ORD-1015", 8, "delivered", "2026-08-16", "FastShip", [("P11", 1)]),
    ("ORD-1016", 8, "shipped", "2026-09-10", "ParcelNet", [("P08", 3)]),
    ("ORD-1017", 1, "cancelled", "2026-08-30", None, [("P04", 1)]),
    ("ORD-1018", 2, "refunded", "2026-08-10", "FastShip", [("P10", 1)]),
    ("ORD-1019", 3, "processing", "2026-09-13", None, [("P02", 1), ("P08", 1)]),
    ("ORD-1020", 4, "shipped", "2026-09-09", "FastShip", [("P07", 1), ("P12", 1)]),
]

EXISTING_REFUNDS = [
    ("ORD-1006", "Customer changed their mind", "2026-09-02"),
    ("ORD-1018", "Item arrived damaged", "2026-08-18"),
]


def seed(conn: sqlite3.Connection) -> None:
    prices = {product_id: price for product_id, _, _, price in PRODUCTS}

    conn.executemany(
        "INSERT INTO customers (id, name, email, created_at) VALUES (?, ?, ?, '2026-01-10')",
        CUSTOMERS,
    )
    conn.executemany("INSERT INTO products (id, name, category, price) VALUES (?, ?, ?, ?)", PRODUCTS)

    for order_id, customer_id, status, day, carrier, items in ORDERS:
        ordered_at, shipped_at, delivered_at = _order_dates(status, date.fromisoformat(day))
        tracking = f"{carrier[:2].upper()}{order_id[-4:]}7731" if carrier else None
        total = sum(prices[product_id] * quantity for product_id, quantity in items)
        conn.execute(
            "INSERT INTO orders (id, customer_id, status, ordered_at, shipped_at, delivered_at,"
            " carrier, tracking_number, total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, customer_id, status, ordered_at, shipped_at, delivered_at,
             carrier, tracking, round(total, 2)),
        )
        conn.executemany(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            [(order_id, product_id, quantity, prices[product_id]) for product_id, quantity in items],
        )

    for order_id, reason, created_at in EXISTING_REFUNDS:
        conn.execute(
            "INSERT INTO refunds (order_id, amount, reason, approved_by, created_at)"
            " SELECT id, total, ?, 'staff', ? FROM orders WHERE id = ?",
            (reason, created_at, order_id),
        )


def _order_dates(status: str, day: date) -> tuple[str, str | None, str | None]:
    """Return (ordered_at, shipped_at, delivered_at) as ISO strings.

    Delivered orders were placed 5 days and shipped 3 days before delivery.
    Shipped orders left the warehouse the day after they were placed.
    """
    if status in ("delivered", "refunded"):
        return str(day - timedelta(days=5)), str(day - timedelta(days=3)), str(day)
    if status == "shipped":
        return str(day), str(day + timedelta(days=1)), None
    return str(day), None, None


def create_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with db.connect(path) as conn:
        db.create_schema(conn)
        seed(conn)


def ensure_database(path: Path) -> None:
    """Create and seed the database on first run. Existing data is left alone."""
    if not path.exists():
        create_database(path)


def reset(settings: Settings) -> None:
    """Delete the store and agent checkpoint databases and seed a fresh store.

    The checkpoint file goes first: a running backend keeps it open, and on Windows the delete then
    fails before the store has been touched, so a failed reset leaves everything as it was.
    """
    for path in (settings.resolve(settings.checkpoint_path), settings.resolve(settings.database_path)):
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                Path(f"{path}{suffix}").unlink(missing_ok=True)
            except PermissionError:
                raise SystemExit(f"{path.name} is in use. Stop the backend, then run the reset again.")
    create_database(settings.resolve(settings.database_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the demo store database.")
    parser.add_argument("--reset", action="store_true", help="delete existing data first")
    args = parser.parse_args()

    settings = Settings()
    if args.reset:
        reset(settings)
    else:
        ensure_database(settings.resolve(settings.database_path))
    print(f"Store database ready at {settings.resolve(settings.database_path)}")


if __name__ == "__main__":
    main()
