from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class PurchaseOrderFormData:
    supplier_id: int | None
    location_id: int
    order_no: str
    order_date: str
    expected_date: str
    product_id: int
    quantity: float
    purchase_price: float
    status: str
    note: str


class PurchaseOrderRepository:
    def list_orders(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        purchase_orders.id,
                        purchase_orders.order_no,
                        purchase_orders.order_date,
                        purchase_orders.expected_date,
                        purchase_orders.quantity,
                        purchase_orders.purchase_price,
                        purchase_orders.subtotal,
                        purchase_orders.status,
                        purchase_orders.note,
                        contacts.name AS supplier_name,
                        products.name AS product_name,
                        products.sku AS product_sku
                    FROM purchase_orders
                    LEFT JOIN contacts ON contacts.id = purchase_orders.supplier_id
                    JOIN products ON products.id = purchase_orders.product_id
                    ORDER BY purchase_orders.order_date DESC, purchase_orders.id DESC
                    """
                )
            )

    def create_order(self, order: PurchaseOrderFormData) -> int:
        if order.quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if order.purchase_price < 0:
            raise ValueError("Purchase price cannot be negative.")

        subtotal = order.quantity * order.purchase_price
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO purchase_orders (
                    supplier_id,
                    location_id,
                    order_no,
                    order_date,
                    expected_date,
                    product_id,
                    quantity,
                    purchase_price,
                    subtotal,
                    status,
                    note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.supplier_id,
                    order.location_id,
                    order.order_no,
                    order.order_date,
                    order.expected_date,
                    order.product_id,
                    order.quantity,
                    order.purchase_price,
                    subtotal,
                    order.status,
                    order.note,
                ),
            )
            return int(cursor.lastrowid)
