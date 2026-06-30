from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class SalesReturnFormData:
    sale_id: int
    product_id: int
    return_date: str
    quantity: float
    refund_amount: float
    reason: str
    item_condition: str
    refund_method: str
    return_to_stock: int
    note: str


class SalesReturnRepository:
    def list_returns(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        sales_returns.id,
                        sales_returns.return_date,
                        sales_returns.quantity,
                        sales_returns.refund_amount,
                        sales_returns.reason,
                        sales_returns.item_condition,
                        sales_returns.refund_method,
                        sales_returns.return_to_stock,
                        sales_returns.note,
                        sales.invoice_no,
                        COALESCE(contacts.name, 'Walk-in Customer') AS customer_name,
                        products.name AS product_name,
                        products.sku AS product_sku
                    FROM sales_returns
                    JOIN sales ON sales.id = sales_returns.sale_id
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    JOIN products ON products.id = sales_returns.product_id
                    ORDER BY sales_returns.return_date DESC, sales_returns.id DESC
                    """
                )
            )

    def get_return_receipt(self, return_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT
                    sales_returns.id,
                    sales_returns.return_date,
                    sales_returns.quantity,
                    sales_returns.refund_amount,
                    sales_returns.reason,
                    sales_returns.item_condition,
                    sales_returns.refund_method,
                    sales_returns.return_to_stock,
                    sales_returns.note,
                    sales.invoice_no,
                    sales.customer_id,
                    contacts.name AS customer_name,
                    products.name AS product_name,
                    products.sku AS product_sku
                FROM sales_returns
                JOIN sales ON sales.id = sales_returns.sale_id
                LEFT JOIN contacts ON contacts.id = sales.customer_id
                JOIN products ON products.id = sales_returns.product_id
                WHERE sales_returns.id = ?
                """,
                (return_id,),
            ).fetchone()

    def create_return(self, sale_return: SalesReturnFormData) -> int:
        if sale_return.quantity <= 0:
            raise ValueError("Return quantity must be greater than zero.")
        if sale_return.refund_amount < 0:
            raise ValueError("Refund amount cannot be negative.")

        valid_refund_methods = {"cash", "card", "bank_transfer", "store_credit", "exchange", "no_refund"}
        if sale_return.refund_method not in valid_refund_methods:
            raise ValueError("Select a valid refund method.")
        if sale_return.return_to_stock not in {0, 1}:
            raise ValueError("Return to stock selection is invalid.")
        if sale_return.refund_method == "no_refund" and sale_return.refund_amount > 0:
            raise ValueError("Refund amount must be zero when no refund is selected.")

        connection = get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            sale_item = connection.execute(
                """
                SELECT
                    SUM(quantity) AS sold_quantity,
                    MAX(unit_price) AS unit_price
                FROM sale_items
                WHERE sale_id = ? AND product_id = ?
                """,
                (sale_return.sale_id, sale_return.product_id),
            ).fetchone()
            sold_quantity = float(sale_item["sold_quantity"] or 0)
            if sold_quantity <= 0:
                raise ValueError("Selected product was not found in the selected sale.")
            returned_row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS quantity
                FROM sales_returns
                WHERE sale_id = ? AND product_id = ?
                """,
                (sale_return.sale_id, sale_return.product_id),
            ).fetchone()
            remaining_quantity = sold_quantity - float(returned_row["quantity"] or 0)
            if sale_return.quantity > remaining_quantity:
                raise ValueError(
                    f"Cannot return more than remaining sold quantity. Remaining: {remaining_quantity:.2f}."
                )
            maximum_refund = sale_return.quantity * float(sale_item["unit_price"] or 0)
            if sale_return.refund_amount > maximum_refund + 0.01:
                raise ValueError(f"Refund cannot exceed {maximum_refund:.2f} for the returned quantity.")

            cursor = connection.execute(
                """
                INSERT INTO sales_returns (
                    sale_id,
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
                    sale_return.sale_id,
                    sale_return.product_id,
                    sale_return.return_date,
                    sale_return.quantity,
                    sale_return.refund_amount,
                    sale_return.reason,
                    sale_return.item_condition,
                    sale_return.refund_method,
                    sale_return.return_to_stock,
                    sale_return.note,
                ),
            )
            return_id = int(cursor.lastrowid)

            if sale_return.refund_amount > 0 and sale_return.refund_method in {"cash", "card", "bank_transfer"}:
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
                    VALUES ('out', 'sale_return', ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        return_id,
                        sale_return.refund_amount,
                        sale_return.refund_method,
                        sale_return.return_date,
                        sale_return.note,
                    ),
                )

            if sale_return.return_to_stock:
                location = connection.execute(
                    "SELECT COALESCE(location_id, 1) AS location_id FROM sales WHERE id = ?",
                    (sale_return.sale_id,),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        product_id, location_id, movement_type, reference_type,
                        reference_id, quantity_in, quantity_out
                    )
                    VALUES (?, ?, 'sale_return', 'sale_return', ?, ?, 0)
                    """,
                    (
                        sale_return.product_id,
                        int(location["location_id"] or 1),
                        return_id,
                        sale_return.quantity,
                    ),
                )

            connection.commit()
            return return_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def sale_options(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, invoice_no || ' - ' || sale_date AS name
                    FROM sales
                    ORDER BY id DESC
                    """
                )
            )

    def sale_product_options(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        sales.id AS sale_id,
                        sale_items.product_id,
                        sales.invoice_no || ' / ' || products.name || ' (' || products.sku || ')' AS name
                    FROM sale_items
                    JOIN sales ON sales.id = sale_items.sale_id
                    JOIN products ON products.id = sale_items.product_id
                    ORDER BY sales.id DESC, products.name
                    """
                )
            )

    def returnable_sale_items(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        sales.id AS sale_id,
                        sales.invoice_no,
                        sales.sale_date,
                        COALESCE(contacts.name, 'Walk-in Customer') AS customer_name,
                        sale_items.product_id,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        products.barcode AS product_barcode,
                        SUM(sale_items.quantity) AS sold_quantity,
                        MAX(sale_items.unit_price) AS unit_price,
                        COALESCE(returned.quantity, 0) AS returned_quantity,
                        SUM(sale_items.quantity) - COALESCE(returned.quantity, 0) AS remaining_quantity
                    FROM sales
                    JOIN sale_items ON sale_items.sale_id = sales.id
                    JOIN products ON products.id = sale_items.product_id
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    LEFT JOIN (
                        SELECT sale_id, product_id, SUM(quantity) AS quantity
                        FROM sales_returns
                        GROUP BY sale_id, product_id
                    ) AS returned
                      ON returned.sale_id = sales.id
                     AND returned.product_id = sale_items.product_id
                    WHERE sales.sale_status = 'final'
                    GROUP BY sales.id, sale_items.product_id
                    HAVING remaining_quantity > 0
                    ORDER BY sales.sale_date DESC, sales.id DESC, products.name
                    """
                )
            )

    def _sold_quantity(self, sale_id: int, product_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS quantity
                FROM sale_items
                WHERE sale_id = ? AND product_id = ?
                """,
                (sale_id, product_id),
            ).fetchone()
        return float(row["quantity"])

    def _returned_quantity(self, sale_id: int, product_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS quantity
                FROM sales_returns
                WHERE sale_id = ? AND product_id = ?
                """,
                (sale_id, product_id),
            ).fetchone()
        return float(row["quantity"])
