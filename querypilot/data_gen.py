"""Generate a seeded, synthetic 8-table e-commerce warehouse in DuckDB.

Usage:
    python -m querypilot.data_gen --path data/warehouse.duckdb
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

SEED = 42

STATES = {
    "TX": ["Dallas", "Austin", "Houston", "San Antonio"],
    "CA": ["Los Angeles", "San Francisco", "San Diego"],
    "NY": ["New York", "Buffalo"],
    "AZ": ["Phoenix", "Tempe", "Tucson"],
    "WA": ["Seattle", "Spokane"],
    "IL": ["Chicago"],
    "FL": ["Miami", "Orlando", "Tampa"],
}
SEGMENTS = ["consumer", "small_business", "enterprise"]
CATEGORIES = ["Electronics", "Home & Kitchen", "Books", "Sports", "Beauty", "Toys", "Clothing", "Grocery"]
PRODUCT_WORDS = {
    "Electronics": ["Headphones", "Smartwatch", "Charger", "Speaker", "Keyboard", "Monitor"],
    "Home & Kitchen": ["Blender", "Knife Set", "Air Fryer", "Lamp", "Cookware", "Kettle"],
    "Books": ["Novel", "Cookbook", "Biography", "Textbook", "Comic", "Guide"],
    "Sports": ["Yoga Mat", "Dumbbells", "Tennis Racket", "Bike Helmet", "Water Bottle", "Jump Rope"],
    "Beauty": ["Serum", "Moisturizer", "Shampoo", "Lipstick", "Perfume", "Face Mask"],
    "Toys": ["Puzzle", "Board Game", "Action Figure", "Building Blocks", "Plush", "RC Car"],
    "Clothing": ["T-Shirt", "Jacket", "Sneakers", "Jeans", "Hoodie", "Socks"],
    "Grocery": ["Coffee", "Tea", "Olive Oil", "Granola", "Chocolate", "Pasta"],
}
PRICE_RANGE = {
    "Electronics": (25, 450), "Home & Kitchen": (15, 220), "Books": (8, 60), "Sports": (10, 180),
    "Beauty": (6, 90), "Toys": (8, 120), "Clothing": (10, 150), "Grocery": (3, 35),
}
FIRST = ["Ava", "Liam", "Mia", "Noah", "Emma", "Ethan", "Sofia", "Arjun", "Priya", "Lucas", "Zara", "Omar",
         "Chloe", "Ravi", "Hana", "Diego", "Nina", "Leo", "Aisha", "Kai"]
LAST = ["Patel", "Smith", "Garcia", "Kim", "Nguyen", "Johnson", "Khan", "Lopez", "Chen", "Brown", "Rao", "Davis"]
CHANNELS = ["web", "mobile", "marketplace"]
STATUSES = ["delivered", "delivered", "delivered", "delivered", "shipped", "processing", "cancelled", "returned"]
METHODS = ["credit_card", "debit_card", "paypal", "gift_card"]
CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]

START = date(2024, 1, 1)
END = date(2025, 12, 31)


def _insert(con, table: str, rows: list[tuple]) -> None:
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    df = pd.DataFrame(rows, columns=cols)  # noqa: F841  (referenced by DuckDB replacement scan)
    con.execute(f"INSERT INTO {table} SELECT * FROM df")


def _rand_date(rng: random.Random, start: date = START, end: date = END) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build(path: str | Path, n_customers: int = 2000, n_orders: int = 12000) -> Path:
    rng = random.Random(SEED)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))

    con.execute("""
        CREATE TABLE categories (category_id INTEGER PRIMARY KEY, name VARCHAR);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name VARCHAR, category_id INTEGER,
                               price DECIMAL(10,2), cost DECIMAL(10,2), launched_date DATE);
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name VARCHAR, last_name VARCHAR,
                                email VARCHAR, city VARCHAR, state VARCHAR, segment VARCHAR, signup_date DATE);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE,
                             status VARCHAR, channel VARCHAR);
        CREATE TABLE order_items (order_item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
                                  quantity INTEGER, unit_price DECIMAL(10,2), discount DECIMAL(4,2));
        CREATE TABLE payments (payment_id INTEGER PRIMARY KEY, order_id INTEGER, method VARCHAR,
                               amount DECIMAL(12,2), paid_at DATE);
        CREATE TABLE shipments (shipment_id INTEGER PRIMARY KEY, order_id INTEGER, carrier VARCHAR,
                                shipped_date DATE, delivered_date DATE);
        CREATE TABLE reviews (review_id INTEGER PRIMARY KEY, product_id INTEGER, customer_id INTEGER,
                              rating INTEGER, review_date DATE);
    """)

    _insert(con, "categories", [(i + 1, c) for i, c in enumerate(CATEGORIES)])

    products, pid = [], 1
    for ci, cat in enumerate(CATEGORIES, start=1):
        lo, hi = PRICE_RANGE[cat]
        for word in PRODUCT_WORDS[cat]:
            for tier in ("Basic", "Pro"):
                price = round(rng.uniform(lo, hi) * (1.6 if tier == "Pro" else 1.0), 2)
                cost = round(price * rng.uniform(0.45, 0.75), 2)
                products.append((pid, f"{tier} {word}", ci, price, cost, _rand_date(rng, date(2022, 1, 1), date(2025, 6, 30))))
                pid += 1
    _insert(con, "products", products)
    price_of = {p[0]: p[3] for p in products}

    customers = []
    for cid in range(1, n_customers + 1):
        st = rng.choice(list(STATES))
        fn, ln = rng.choice(FIRST), rng.choice(LAST)
        customers.append((cid, fn, ln, f"{fn.lower()}.{ln.lower()}{cid}@example.com", rng.choice(STATES[st]), st,
                          rng.choices(SEGMENTS, weights=[75, 20, 5])[0], _rand_date(rng, date(2023, 1, 1), date(2025, 10, 31))))
    _insert(con, "customers", customers)
    signup = {c[0]: c[7] for c in customers}

    orders, items, payments, shipments = [], [], [], []
    oi_id = 1
    for oid in range(1, n_orders + 1):
        cid = rng.randint(1, n_customers)
        od = _rand_date(rng, max(signup[cid], START), END)
        status = rng.choice(STATUSES)
        orders.append((oid, cid, od, status, rng.choices(CHANNELS, weights=[50, 35, 15])[0]))
        total = 0.0
        for _ in range(rng.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]):
            prod = rng.randint(1, len(products))
            qty = rng.choices([1, 2, 3, 5], weights=[70, 20, 7, 3])[0]
            disc = rng.choice([0, 0, 0, 0.05, 0.1, 0.2])
            up = float(price_of[prod])
            items.append((oi_id, oid, prod, qty, up, disc))
            total += qty * up * (1 - disc)
            oi_id += 1
        if status != "cancelled":
            payments.append((oid, oid, rng.choice(METHODS), round(total, 2), od))
        if status in ("shipped", "delivered", "returned"):
            sd = od + timedelta(days=rng.randint(0, 3))
            dd = sd + timedelta(days=rng.randint(1, 9)) if status != "shipped" else None
            shipments.append((oid, oid, rng.choice(CARRIERS), sd, dd))
    _insert(con, "orders", orders)
    _insert(con, "order_items", items)
    _insert(con, "payments", payments)
    _insert(con, "shipments", shipments)

    reviews = []
    for rid in range(1, 6001):
        reviews.append((rid, rng.randint(1, len(products)), rng.randint(1, n_customers),
                        rng.choices([1, 2, 3, 4, 5], weights=[5, 8, 17, 35, 35])[0], _rand_date(rng)))
    _insert(con, "reviews", reviews)
    con.close()
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="data/warehouse.duckdb")
    args = ap.parse_args()
    p = build(args.path)
    con = duckdb.connect(str(p), read_only=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        print(f"{t:12s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>7,} rows")
