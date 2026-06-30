from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class PurchaseFormData:
    supplier_id: int | None
    location_id: int
    invoice_no: str
    purchase_date: str
    product_id: int
    quantity: float
    purchase_price: float
    discount: float
    tax: float
    paid_amount: float
    payment_method: str


@dataclass(frozen=True)
class PurchaseItemData:
    product_id: int
    quantity: float
    purchase_price: float


@dataclass(frozen=True)
class PurchasePaymentData:
    payment_type: str
    amount: float
    payment_date: str
    cheque_no: str = ""
    cheque_date: str = ""
    bank_name: str = ""
    note: str = ""


@dataclass(frozen=True)
class PurchaseCheckoutData:
    supplier_id: int | None
    location_id: int
    invoice_no: str
    purchase_date: str
    items: list[PurchaseItemData]
    discount: float
    tax: float
    paid_amount: float
    payment_method: str
    payments: list[PurchasePaymentData] | None = None


class PurchaseRepository:
    def list_purchases(
        self,
        supplier_id: int | None = None,
        product_id: int | None = None,
        start_date: str = "",
        end_date: str = "",
    ) -> list[sqlite3.Row]:
        conditions = []
        parameters: list[object] = []
        if supplier_id is not None:
            conditions.append("purchases.supplier_id = ?")
            parameters.append(supplier_id)
        if product_id is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM purchase_items filter_items "
                "WHERE filter_items.purchase_id = purchases.id AND filter_items.product_id = ?)"
            )
            parameters.append(product_id)
        if start_date:
            conditions.append("purchases.purchase_date >= ?")
            parameters.append(start_date)
        if end_date:
            conditions.append("purchases.purchase_date <= ?")
            parameters.append(end_date)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        purchases.id,
                        purchases.invoice_no,
                        purchases.purchase_date,
                        purchases.subtotal,
                        purchases.discount,
                        purchases.tax,
                        purchases.total,
                        purchases.paid_amount,
                        purchases.due_amount,
                        purchases.payment_status,
                        contacts.name AS supplier_name,
                        COUNT(purchase_items.id) AS item_count,
                        COALESCE(SUM(purchase_items.quantity), 0) AS total_quantity,
                        COALESCE((
                            SELECT SUM(amount)
                            FROM purchase_payments
                            WHERE purchase_payments.purchase_id = purchases.id
                                AND purchase_payments.status = 'cleared'
                        ), 0) AS cleared_amount,
                        COALESCE((
                            SELECT SUM(amount)
                            FROM purchase_payments
                            WHERE purchase_payments.purchase_id = purchases.id
                                AND purchase_payments.payment_type = 'cheque'
                                AND purchase_payments.status = 'pending'
                        ), 0) AS pending_cheque_amount,
                        COALESCE((
                            SELECT COUNT(*)
                            FROM purchase_payments
                            WHERE purchase_payments.purchase_id = purchases.id
                        ), 0) AS payment_line_count
                    FROM purchases
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    LEFT JOIN purchase_items ON purchase_items.purchase_id = purchases.id
                    {where_clause}
                    GROUP BY purchases.id
                    ORDER BY purchases.purchase_date DESC, purchases.id DESC
                    """,
                    parameters,
                )
            )

    def get_purchase_detail(
        self, purchase_id: int
    ) -> tuple[sqlite3.Row | None, list[sqlite3.Row], list[sqlite3.Row]]:
        with get_connection() as connection:
            purchase = connection.execute(
                """
                SELECT
                    purchases.*,
                    COALESCE(contacts.name, 'No Supplier') AS supplier_name,
                    contacts.phone AS supplier_phone,
                    contacts.email AS supplier_email,
                    contacts.address AS supplier_address,
                    COALESCE(locations.name, 'Main Shop') AS location_name,
                    COALESCE(payments.method, '') AS payment_method,
                    payments.id AS payment_id
                FROM purchases
                LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                LEFT JOIN locations ON locations.id = purchases.location_id
                LEFT JOIN payments
                    ON payments.reference_type = 'purchase'
                    AND payments.reference_id = purchases.id
                WHERE purchases.id = ?
                ORDER BY payments.id DESC
                LIMIT 1
                """,
                (purchase_id,),
            ).fetchone()
            items = list(
                connection.execute(
                    """
                    SELECT
                        purchase_items.*,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        products.barcode AS product_barcode,
                        COALESCE(product_units.short_name, '') AS unit_name
                    FROM purchase_items
                    JOIN products ON products.id = purchase_items.product_id
                    LEFT JOIN product_units ON product_units.id = products.unit_id
                    WHERE purchase_items.purchase_id = ?
                    ORDER BY purchase_items.id
                    """,
                    (purchase_id,),
                )
            )
            payments = list(
                connection.execute(
                    """
                    SELECT *
                    FROM purchase_payments
                    WHERE purchase_id = ?
                    ORDER BY id
                    """,
                    (purchase_id,),
                )
            )
        return purchase, items, payments

    def create_purchase(self, purchase: PurchaseFormData) -> int:
        return self.create_checkout_purchase(
            PurchaseCheckoutData(
                supplier_id=purchase.supplier_id,
                location_id=purchase.location_id,
                invoice_no=purchase.invoice_no,
                purchase_date=purchase.purchase_date,
                items=[
                    PurchaseItemData(
                        product_id=purchase.product_id,
                        quantity=purchase.quantity,
                        purchase_price=purchase.purchase_price,
                    )
                ],
                discount=purchase.discount,
                tax=purchase.tax,
                paid_amount=purchase.paid_amount,
                payment_method=purchase.payment_method,
            )
        )

    def create_checkout_purchase(self, purchase: PurchaseCheckoutData) -> int:
        if not purchase.items:
            raise ValueError("Add at least one product to the purchase.")
        for item in purchase.items:
            if item.quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            if item.purchase_price < 0:
                raise ValueError("Purchase price cannot be negative.")

        subtotal = sum(item.quantity * item.purchase_price for item in purchase.items)
        total = max(subtotal - purchase.discount + purchase.tax, 0)
        purchase_payments = self._normalise_payments(purchase, total)
        paid_amount = min(sum(payment.amount for payment in purchase_payments), total)
        due_amount = total - paid_amount
        payment_status = self._payment_status(
            total,
            paid_amount,
            any(payment.payment_type == "cheque" for payment in purchase_payments),
            due_amount,
        )

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO purchases (
                    supplier_id, location_id, invoice_no, purchase_date,
                    subtotal, discount, tax, total, paid_amount, due_amount, payment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase.supplier_id,
                    purchase.location_id,
                    purchase.invoice_no,
                    purchase.purchase_date,
                    subtotal,
                    purchase.discount,
                    purchase.tax,
                    total,
                    paid_amount,
                    due_amount,
                    payment_status,
                ),
            )
            purchase_id = int(cursor.lastrowid)

            for item in purchase.items:
                line_total = item.quantity * item.purchase_price
                connection.execute(
                    """
                    INSERT INTO purchase_items (
                        purchase_id, product_id, quantity, purchase_price, tax, discount, line_total
                    )
                    VALUES (?, ?, ?, ?, 0, 0, ?)
                    """,
                    (purchase_id, item.product_id, item.quantity, item.purchase_price, line_total),
                )
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        product_id, location_id, movement_type, reference_type,
                        reference_id, quantity_in, quantity_out
                    )
                    VALUES (?, ?, 'purchase', 'purchase', ?, ?, 0)
                    """,
                    (item.product_id, purchase.location_id, purchase_id, item.quantity),
                )

            for payment in purchase_payments:
                status = "pending" if payment.payment_type == "cheque" else "cleared"
                connection.execute(
                    """
                    INSERT INTO purchase_payments (
                        purchase_id, payment_type, amount, payment_date, status,
                        cheque_no, cheque_date, bank_name, note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        purchase_id,
                        payment.payment_type,
                        payment.amount,
                        payment.payment_date,
                        status,
                        payment.cheque_no,
                        payment.cheque_date,
                        payment.bank_name,
                        payment.note,
                    ),
                )
                if payment.amount > 0 and payment.payment_type != "cheque":
                    connection.execute(
                        """
                        INSERT INTO payments (
                            payment_type, reference_type, reference_id, account_id,
                            amount, method, payment_date, note
                        )
                        VALUES ('out', 'purchase', ?, 1, ?, ?, ?, ?)
                        """,
                        (
                            purchase_id,
                            payment.amount,
                            payment.payment_type,
                            payment.payment_date,
                            payment.note or f"Payment for purchase {purchase.invoice_no}",
                        ),
                    )

            connection.commit()
            return purchase_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def purchase_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM purchases").fetchone()
        return int(row["count"])

    def pending_cheque_summary(self) -> dict[str, float]:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS amount
                FROM purchase_payments
                WHERE payment_type = 'cheque' AND status = 'pending'
                """
            ).fetchone()
        return {"count": int(row["count"]), "amount": float(row["amount"] or 0)}

    def list_purchase_cheques(self, status: str = "") -> list[sqlite3.Row]:
        conditions = ["purchase_payments.payment_type = 'cheque'"]
        params: list[object] = []
        if status:
            conditions.append("purchase_payments.status = ?")
            params.append(status)
        clause = "WHERE " + " AND ".join(conditions)
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        purchase_payments.*,
                        purchases.invoice_no,
                        purchases.purchase_date,
                        purchases.total AS purchase_total,
                        purchases.payment_status AS purchase_status,
                        COALESCE(contacts.name, 'No Supplier') AS supplier_name
                    FROM purchase_payments
                    JOIN purchases ON purchases.id = purchase_payments.purchase_id
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    {clause}
                    ORDER BY
                        CASE purchase_payments.status WHEN 'pending' THEN 0 WHEN 'bounced' THEN 1 ELSE 2 END,
                        purchase_payments.cheque_date,
                        purchase_payments.id DESC
                    """,
                    params,
                )
            )

    def update_cheque_status(self, payment_id: int, status: str, action_date: str, note: str = "") -> None:
        if status not in {"cleared", "bounced"}:
            raise ValueError("Cheque status must be cleared or bounced.")

        connection = get_connection()
        try:
            cheque = connection.execute(
                """
                SELECT purchase_payments.*, purchases.invoice_no, purchases.total, purchases.paid_amount
                FROM purchase_payments
                JOIN purchases ON purchases.id = purchase_payments.purchase_id
                WHERE purchase_payments.id = ?
                    AND purchase_payments.payment_type = 'cheque'
                    AND purchase_payments.status = 'pending'
                """,
                (payment_id,),
            ).fetchone()
            if cheque is None:
                raise ValueError("Pending cheque was not found.")

            timestamp_column = "cleared_at" if status == "cleared" else "bounced_at"
            connection.execute(
                f"""
                UPDATE purchase_payments
                SET status = ?, {timestamp_column} = ?, note = COALESCE(NULLIF(?, ''), note)
                WHERE id = ?
                """,
                (status, action_date, note, payment_id),
            )

            purchase_id = int(cheque["purchase_id"])
            amount = float(cheque["amount"] or 0)
            if status == "cleared":
                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_type, reference_type, reference_id, account_id,
                        amount, method, payment_date, note
                    )
                    VALUES ('out', 'purchase', ?, 1, ?, 'cheque', ?, ?)
                    """,
                    (
                        purchase_id,
                        amount,
                        action_date,
                        note or f"Cheque cleared for purchase {cheque['invoice_no']}",
                    ),
                )
            else:
                paid_amount = max(float(cheque["paid_amount"] or 0) - amount, 0)
                due_amount = max(float(cheque["total"] or 0) - paid_amount, 0)
                connection.execute(
                    """
                    UPDATE purchases
                    SET paid_amount = ?, due_amount = ?, payment_status = ?
                    WHERE id = ?
                    """,
                    (
                        paid_amount,
                        due_amount,
                        self._payment_status(float(cheque["total"] or 0), paid_amount, False, due_amount),
                        purchase_id,
                    ),
                )

            self._refresh_purchase_payment_status(connection, purchase_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _refresh_purchase_payment_status(self, connection: sqlite3.Connection, purchase_id: int) -> None:
        purchase = connection.execute("SELECT total, paid_amount, due_amount FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if purchase is None:
            return
        has_pending_cheque = connection.execute(
            """
            SELECT 1 FROM purchase_payments
            WHERE purchase_id = ? AND payment_type = 'cheque' AND status = 'pending'
            LIMIT 1
            """,
            (purchase_id,),
        ).fetchone() is not None
        status = self._payment_status(
            float(purchase["total"] or 0),
            float(purchase["paid_amount"] or 0),
            has_pending_cheque,
            float(purchase["due_amount"] or 0),
        )
        connection.execute("UPDATE purchases SET payment_status = ? WHERE id = ?", (status, purchase_id))

    @staticmethod
    def _normalise_payments(purchase: PurchaseCheckoutData, total: float) -> list[PurchasePaymentData]:
        if purchase.payments:
            payments = [payment for payment in purchase.payments if payment.amount > 0]
        elif purchase.paid_amount > 0:
            payments = [
                PurchasePaymentData(
                    payment_type=purchase.payment_method or "cash",
                    amount=purchase.paid_amount,
                    payment_date=purchase.purchase_date,
                    note=f"Payment for purchase {purchase.invoice_no}",
                )
            ]
        else:
            payments = []
        scheduled = sum(payment.amount for payment in payments)
        if scheduled > total:
            raise ValueError("Payment total cannot be greater than purchase total.")
        for payment in payments:
            if payment.amount < 0:
                raise ValueError("Payment amount cannot be negative.")
            if payment.payment_type == "cheque" and not payment.cheque_no.strip():
                raise ValueError("Cheque number is required for cheque payment.")
        return payments

    @staticmethod
    def _payment_status(
        total: float,
        paid_amount: float,
        has_pending_cheque: bool = False,
        due_amount: float | None = None,
    ) -> str:
        if has_pending_cheque:
            return "cheque_pending"
        if paid_amount <= 0:
            return "due"
        if paid_amount >= total:
            return "paid"
        return "partial"
