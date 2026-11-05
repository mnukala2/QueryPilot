"""Schema catalog: table/column descriptions and join paths used for retrieval and prompting."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: dict[str, str]
    synonyms: tuple[str, ...] = ()
    joins: dict[str, str] = field(default_factory=dict)  # other_table -> join condition

    def ddl(self) -> str:
        cols = ",\n".join(f"  {c} -- {d}" for c, d in self.columns.items())
        return f"-- {self.description}\nTABLE {self.name} (\n{cols}\n)"

    def search_text(self) -> str:
        parts = [self.name.replace("_", " "), self.description, " ".join(self.synonyms)]
        for c, d in self.columns.items():
            parts.append(f"{c.replace('_', ' ')} {d}")
        return " ".join(parts)


CATALOG: dict[str, Table] = {
    t.name: t
    for t in [
        Table(
            "customers",
            "One row per registered customer with location, segment and signup date.",
            {
                "customer_id": "primary key",
                "first_name": "customer first name",
                "last_name": "customer last name",
                "email": "customer email address",
                "city": "customer city",
                "state": "two-letter US state code, e.g. TX, CA",
                "segment": "consumer | small_business | enterprise",
                "signup_date": "date the customer account was created",
            },
            synonyms=("buyer", "user", "client", "shopper", "people", "account", "signups", "location", "region", "state",
                      "city", "texas", "california", "arizona", "segment", "enterprise", "name"),
            joins={"orders": "orders.customer_id = customers.customer_id",
                   "reviews": "reviews.customer_id = customers.customer_id"},
        ),
        Table(
            "orders",
            "One row per order placed by a customer, with date, fulfilment status and sales channel.",
            {
                "order_id": "primary key",
                "customer_id": "foreign key to customers",
                "order_date": "date the order was placed",
                "status": "delivered | shipped | processing | cancelled | returned",
                "channel": "web | mobile | marketplace",
            },
            synonyms=("purchase", "transaction", "sale", "sales", "checkout", "monthly", "cancelled", "returned", "channel",
                      "when", "month", "year", "quarter", "yearly", "growth", "trend", "2024", "2025", "first", "placed", "ordered"),
            joins={"customers": "orders.customer_id = customers.customer_id",
                   "order_items": "order_items.order_id = orders.order_id",
                   "payments": "payments.order_id = orders.order_id",
                   "shipments": "shipments.order_id = orders.order_id"},
        ),
        Table(
            "order_items",
            "Line items of each order: which product, quantity, unit price and discount. Revenue = quantity * unit_price * (1 - discount).",
            {
                "order_item_id": "primary key",
                "order_id": "foreign key to orders",
                "product_id": "foreign key to products",
                "quantity": "units purchased",
                "unit_price": "price per unit at time of purchase (USD)",
                "discount": "fractional discount, e.g. 0.10 = 10% off",
            },
            synonyms=("line item", "revenue", "units", "sold", "quantity", "basket", "discount", "best selling", "gmv",
                      "bought", "buy", "purchased", "selling", "profit", "sales"),
            joins={"orders": "order_items.order_id = orders.order_id",
                   "products": "order_items.product_id = products.product_id"},
        ),
        Table(
            "products",
            "Product catalog with list price, unit cost and launch date.",
            {
                "product_id": "primary key",
                "name": "product name",
                "category_id": "foreign key to categories",
                "price": "current list price (USD)",
                "cost": "unit cost (USD); margin = price - cost",
                "launched_date": "date the product launched",
            },
            synonyms=("item", "sku", "catalog", "merchandise", "margin", "expensive", "cheapest", "price"),
            joins={"categories": "products.category_id = categories.category_id",
                   "order_items": "order_items.product_id = products.product_id",
                   "reviews": "reviews.product_id = products.product_id"},
        ),
        Table(
            "categories",
            "Product categories such as Electronics, Books, Toys.",
            {"category_id": "primary key", "name": "category name, e.g. Electronics, Books, Grocery"},
            synonyms=("category", "department", "product line", "electronics", "books", "toys", "clothing", "grocery", "beauty", "sports", "kitchen"),
            joins={"products": "products.category_id = categories.category_id"},
        ),
        Table(
            "payments",
            "Payments captured for non-cancelled orders.",
            {
                "payment_id": "primary key",
                "order_id": "foreign key to orders",
                "method": "credit_card | debit_card | paypal | gift_card",
                "amount": "amount charged (USD)",
                "paid_at": "payment date",
            },
            synonyms=("paid", "charge", "billing", "card", "paypal", "collected", "amount"),
            joins={"orders": "payments.order_id = orders.order_id"},
        ),
        Table(
            "shipments",
            "Shipments for shipped, delivered or returned orders, with carrier and delivery dates.",
            {
                "shipment_id": "primary key",
                "order_id": "foreign key to orders",
                "carrier": "UPS | FedEx | USPS | DHL",
                "shipped_date": "date the order left the warehouse",
                "delivered_date": "date delivered; NULL if still in transit",
            },
            synonyms=("delivery", "shipping", "carrier", "fedex", "ups", "usps", "dhl", "transit", "logistics", "days to deliver"),
            joins={"orders": "shipments.order_id = orders.order_id"},
        ),
        Table(
            "reviews",
            "Product reviews left by customers with a 1-5 star rating.",
            {
                "review_id": "primary key",
                "product_id": "foreign key to products",
                "customer_id": "foreign key to customers",
                "rating": "integer 1-5 stars",
                "review_date": "date of the review",
            },
            synonyms=("rating", "stars", "feedback", "score", "satisfaction", "rated"),
            joins={"products": "reviews.product_id = products.product_id",
                   "customers": "reviews.customer_id = customers.customer_id"},
        ),
    ]
}


def full_schema() -> str:
    return "\n\n".join(t.ddl() for t in CATALOG.values())


def render(tables: list[str]) -> str:
    """Render the DDL for a subset of tables, plus join hints between them."""
    chosen = [CATALOG[t] for t in tables if t in CATALOG]
    blocks = [t.ddl() for t in chosen]
    names = {t.name for t in chosen}
    hints = sorted({cond for t in chosen for other, cond in t.joins.items() if other in names})
    if hints:
        blocks.append("-- Join keys\n" + "\n".join(f"-- {h}" for h in hints))
    return "\n\n".join(blocks)
