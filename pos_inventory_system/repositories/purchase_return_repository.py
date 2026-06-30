from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class PurchaseReturnFormData:
    purchase_id: int
    product_id: int
    return_date: str
    quantity: float
    refund_amount: float
    reason: str
    item_condition: str
    refund_method: str
    reduce_stock: int
    note: str


class PurchaseReturnRepository:
    def list_returns(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        purchase_returns.id,
                        purchase_returns.return_date,
                        purchase_returns.quantity,
                        purchase_returns.refund_amount,
                        purchase_returns.reason,
                        purchase_returns.item_condition,
                        purchase_returns.refund_method,
                        purchase_returns.return_to_stock,
                        purchase_returns.note,
                        purchases.invoice_no,
                        COALESCE(contacts.name, 'No Supplier') AS supplier_name,
                        products.name AS product_name,
                        products.sku AS product_sku
                    FROM purchase_returns
                    JOIN purchases ON purchases.id = purchase_returns.purchase_id
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    JOIN products ON products.id = purchase_returns.product_id
                    ORDER BY purchase_returns.return_date DESC, purchase_returns.id DESC
                    """
                )
            )

    def create_return(self, purchase_return: PurchaseReturnFormData) -> int:
        if purchase_return.quantity <= 0:
            raise ValueError("Return quantity must be greater than zero.")
        if purchase_return.refund_amount < 0:
            raise ValueError("Refund amount cannot be negative.")
        if purchase_return.refund_method not in {"cash", "card", "bank_transfer", "supplier_credit", "exchange", "no_refund"}:
            raise ValueError("Select a valid refund method.")
        if purchase_return.refund_method == "no_refund" and purchase_return.refund_amount > 0:
            raise ValueError("Refund amount must be zero when no refund is selected.")
        if purchase_return.reduce_stock not in {0, 1}:
            raise ValueError("Stock reduction selection is invalid.")

        purchase_location_id = self._purchase_location_id(purchase_return.purchase_id)
        purchased_quantity = self._purchased_quantity(purchase_return.purchase_id, purchase_return.product_id)
        if purchased_quantity <= 0:
            raise ValueError("Selected product was not found in the selected purchase.")

        returned_quantity = self._returned_quantity(purchase_return.purchase_id, purchase_return.product_id)
        remaining_quantity = purchased_quantity - returned_quantity
        if purchase_return.quantity > remaining_quantity:
            raise ValueError(f"Cannot return more than remaining purchased quantity. Remaining: {remaining_quantity:.2f}.")
        available = self._available_stock(purchase_return.product_id, purchase_location_id)
        if purchase_return.reduce_stock and purchase_return.quantity > available:
            raise ValueError(f"Not enough stock to return to supplier. Available: {available:.2f}.")

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO purchase_returns (
                    purchase_id,
                    product_id,
                    return_date,
                    quantity,
                    refund_amount,
                    reason,
                    item_condition,
                    refund_method,
                    return_to_stock,
                    note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_return.purchase_id,
                    purchase_return.product_id,
                    purchase_return.return_date,
                    purchase_return.quantity,
                    purchase_return.refund_amount,
                    purchase_return.reason,
                    purchase_return.item_condition,
                    purchase_return.refund_method,
                    purchase_return.reduce_stock,
                    purchase_return.note,
                ),
            )
            return_id = int(cursor.lastrowid)

            if purchase_return.refund_amount > 0 and purchase_return.refund_method in {"cash", "card", "bank_transfer"}:
                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_type,
                        reference_type,
                        reference_id,
                        account_id,
                        amount,
                        method,
                        payment_date,
                        note
                    )
                    VALUES ('in', 'purchase_return', ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        return_id,
                        purchase_return.refund_amount,
                        purchase_return.refund_method,
                        purchase_return.return_date,
                        purchase_return.note,
                    ),
                )

            if purchase_return.reduce_stock:
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        product_id,
                        location_id,
                        movement_type,
                        reference_type,
                        reference_id,
                        quantity_in,
                        quantity_out
                    )
                    VALUES (?, ?, 'purchase_return', 'purchase_return', ?, 0, ?)
                    """,
                    (purchase_return.product_id, purchase_location_id, return_id, purchase_return.quantity),
                )

            connection.commit()
            return return_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def purchase_product_options(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        purchases.id AS purchase_id,
                        purchase_items.product_id,
                        purchases.invoice_no || ' / ' || products.name || ' (' || products.sku || ')' AS name
                    FROM purchase_items
                    JOIN purchases ON purchases.id = purchase_items.purchase_id
                    JOIN products ON products.id = purchase_items.product_id
                    ORDER BY purchases.id DESC, products.name
                    """
                )
            )

    def _purchased_quantity(self, purchase_id: int, product_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS quantity
                FROM purchase_items
                WHERE purchase_id = ? AND product_id = ?
                """,
                (purchase_id, product_id),
            ).fetchone()
        return float(row["quantity"])

    def _purchase_location_id(self, purchase_id: int) -> int:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(location_id, 1) AS location_id FROM purchases WHERE id = ?",
                (purchase_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Selected purchase was not found.")
        return int(row["location_id"] or 1)

    def _available_stock(self, product_id: int, location_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity_in - quantity_out), 0) AS available
                FROM stock_movements
                WHERE product_id = ? AND location_id = ?
                """,
                (product_id, location_id),
            ).fetchone()
        return float(row["available"] or 0)

    def _returned_quantity(self, purchase_id: int, product_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS quantity
                FROM purchase_returns
                WHERE purchase_id = ? AND product_id = ?
                """,
                (purchase_id, product_id),
            ).fetchone()
        return float(row["quantity"])
