from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class DepositFormData:
    account_id: int
    amount: float
    payment_date: str
    method: str
    note: str


@dataclass(frozen=True)
class AccountFormData:
    name: str
    account_type: str
    opening_balance: float
    is_active: int


@dataclass(frozen=True)
class TransferFormData:
    from_account_id: int
    to_account_id: int
    transfer_date: str
    amount: float
    note: str


@dataclass(frozen=True)
class DuePaymentData:
    reference_id: int
    account_id: int
    amount: float
    method: str
    payment_date: str
    note: str = ""


class PaymentRepository:
    def list_accounts(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payment_accounts.id,
                        payment_accounts.name,
                        payment_accounts.account_type,
                        payment_accounts.opening_balance,
                        payment_accounts.is_active,
                        payment_accounts.opening_balance
                            + COALESCE(SUM(
                                CASE
                                    WHEN payments.payment_type = 'in' THEN payments.amount
                                    WHEN payments.payment_type = 'out' THEN -payments.amount
                                    ELSE 0
                                END
                            ), 0) AS current_balance
                    FROM payment_accounts
                    LEFT JOIN payments ON payments.account_id = payment_accounts.id
                    GROUP BY payment_accounts.id
                    ORDER BY payment_accounts.name
                    """
                )
            )

    def create_account(self, account: AccountFormData) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO payment_accounts (name, account_type, opening_balance, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (account.name, account.account_type, account.opening_balance, account.is_active),
            )
            return int(cursor.lastrowid)

    def list_transactions(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payments.id,
                        payments.payment_type,
                        payments.reference_type,
                        payments.reference_id,
                        payments.amount,
                        payments.method,
                        payments.payment_date,
                        payments.note,
                        payment_accounts.name AS account_name
                    FROM payments
                    LEFT JOIN payment_accounts ON payment_accounts.id = payments.account_id
                    ORDER BY payments.payment_date DESC, payments.id DESC
                    """
                )
            )

    def get_transaction_receipt(self, payment_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT
                    payments.id,
                    payments.payment_type,
                    payments.reference_type,
                    payments.reference_id,
                    payments.amount,
                    payments.method,
                    payments.payment_date,
                    payments.note,
                    payment_accounts.name AS account_name
                FROM payments
                LEFT JOIN payment_accounts ON payment_accounts.id = payments.account_id
                WHERE payments.id = ?
                """,
                (payment_id,),
            ).fetchone()

    def create_deposit(self, deposit: DepositFormData) -> int:
        if deposit.amount <= 0:
            raise ValueError("Deposit amount must be greater than zero.")

        with get_connection() as connection:
            cursor = connection.execute(
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
                VALUES ('in', 'deposit', 0, ?, ?, ?, ?, ?)
                """,
                (
                    deposit.account_id,
                    deposit.amount,
                    deposit.method,
                    deposit.payment_date,
                    deposit.note,
                ),
            )
            return int(cursor.lastrowid)

    def list_transfers(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payment_transfers.id,
                        payment_transfers.transfer_date,
                        payment_transfers.amount,
                        payment_transfers.note,
                        from_accounts.name AS from_account_name,
                        to_accounts.name AS to_account_name
                    FROM payment_transfers
                    JOIN payment_accounts AS from_accounts ON from_accounts.id = payment_transfers.from_account_id
                    JOIN payment_accounts AS to_accounts ON to_accounts.id = payment_transfers.to_account_id
                    ORDER BY payment_transfers.transfer_date DESC, payment_transfers.id DESC
                    """
                )
            )

    def create_transfer(self, transfer: TransferFormData) -> int:
        if transfer.amount <= 0:
            raise ValueError("Transfer amount must be greater than zero.")
        if transfer.from_account_id == transfer.to_account_id:
            raise ValueError("From and to accounts must be different.")

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO payment_transfers (
                    from_account_id,
                    to_account_id,
                    transfer_date,
                    amount,
                    note
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    transfer.from_account_id,
                    transfer.to_account_id,
                    transfer.transfer_date,
                    transfer.amount,
                    transfer.note,
                ),
            )
            transfer_id = int(cursor.lastrowid)
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
                VALUES ('out', 'transfer', ?, ?, ?, 'transfer', ?, ?)
                """,
                (
                    transfer_id,
                    transfer.from_account_id,
                    transfer.amount,
                    transfer.transfer_date,
                    transfer.note,
                ),
            )
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
                VALUES ('in', 'transfer', ?, ?, ?, 'transfer', ?, ?)
                """,
                (
                    transfer_id,
                    transfer.to_account_id,
                    transfer.amount,
                    transfer.transfer_date,
                    transfer.note,
                ),
            )
            connection.commit()
            return transfer_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def account_options(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    "SELECT id, name FROM payment_accounts WHERE is_active = 1 ORDER BY name"
                )
            )

    def customer_due_sales(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        sales.id,
                        sales.invoice_no,
                        sales.sale_date,
                        sales.total,
                        sales.paid_amount,
                        sales.due_amount,
                        sales.payment_status,
                        COALESCE(contacts.name, 'Walk-in Customer') AS customer_name,
                        COALESCE(contacts.phone, '') AS customer_phone
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    WHERE sales.sale_status = 'final'
                      AND sales.due_amount > 0
                    ORDER BY sales.sale_date DESC, sales.id DESC
                    """
                )
            )

    def supplier_due_purchases(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        purchases.id,
                        purchases.invoice_no,
                        purchases.purchase_date,
                        purchases.total,
                        purchases.paid_amount,
                        purchases.due_amount,
                        purchases.payment_status,
                        COALESCE(contacts.name, 'No Supplier') AS supplier_name,
                        COALESCE(contacts.phone, '') AS supplier_phone
                    FROM purchases
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    WHERE purchases.due_amount > 0
                    ORDER BY purchases.purchase_date DESC, purchases.id DESC
                    """
                )
            )

    def customer_payment_history(self, limit: int = 100) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payments.id,
                        payments.payment_date,
                        payments.amount,
                        payments.method,
                        payments.note,
                        payment_accounts.name AS account_name,
                        sales.invoice_no,
                        contacts.name AS customer_name
                    FROM payments
                    JOIN sales ON sales.id = payments.reference_id
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    LEFT JOIN payment_accounts ON payment_accounts.id = payments.account_id
                    WHERE payments.payment_type = 'in'
                      AND payments.reference_type = 'sale'
                    ORDER BY payments.payment_date DESC, payments.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def supplier_payment_history(self, limit: int = 100) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payments.id,
                        payments.payment_date,
                        payments.amount,
                        payments.method,
                        payments.note,
                        payment_accounts.name AS account_name,
                        purchases.invoice_no,
                        contacts.name AS supplier_name
                    FROM payments
                    JOIN purchases ON purchases.id = payments.reference_id
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    LEFT JOIN payment_accounts ON payment_accounts.id = payments.account_id
                    WHERE payments.payment_type = 'out'
                      AND payments.reference_type = 'purchase'
                    ORDER BY payments.payment_date DESC, payments.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def record_customer_payment(self, payment: DuePaymentData) -> int:
        if payment.amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        connection = get_connection()
        try:
            sale = connection.execute(
                """
                SELECT id, invoice_no, total, paid_amount, due_amount
                FROM sales
                WHERE id = ? AND sale_status = 'final'
                """,
                (payment.reference_id,),
            ).fetchone()
            if sale is None:
                raise ValueError("Sale invoice was not found.")
            due_amount = float(sale["due_amount"] or 0)
            if due_amount <= 0:
                raise ValueError("This sale invoice is already paid.")
            if payment.amount > due_amount:
                raise ValueError("Payment amount cannot be greater than the invoice due amount.")
            paid_amount = float(sale["paid_amount"] or 0) + payment.amount
            new_due = max(float(sale["total"] or 0) - paid_amount, 0)
            status = self._payment_status(float(sale["total"] or 0), paid_amount)
            cursor = connection.execute(
                """
                INSERT INTO payments (
                    payment_type, reference_type, reference_id, account_id,
                    amount, method, payment_date, note
                )
                VALUES ('in', 'sale', ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment.reference_id,
                    payment.account_id,
                    payment.amount,
                    payment.method,
                    payment.payment_date,
                    payment.note or f"Customer payment for sale {sale['invoice_no']}",
                ),
            )
            connection.execute(
                """
                UPDATE sales
                SET paid_amount = ?, due_amount = ?, payment_status = ?
                WHERE id = ?
                """,
                (paid_amount, new_due, status, payment.reference_id),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_supplier_payment(self, payment: DuePaymentData) -> int:
        if payment.amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        connection = get_connection()
        try:
            purchase = connection.execute(
                """
                SELECT id, invoice_no, total, paid_amount, due_amount
                FROM purchases
                WHERE id = ?
                """,
                (payment.reference_id,),
            ).fetchone()
            if purchase is None:
                raise ValueError("Purchase invoice was not found.")
            due_amount = float(purchase["due_amount"] or 0)
            if due_amount <= 0:
                raise ValueError("This purchase invoice is already paid.")
            if payment.amount > due_amount:
                raise ValueError("Payment amount cannot be greater than the purchase due amount.")
            paid_amount = float(purchase["paid_amount"] or 0) + payment.amount
            new_due = max(float(purchase["total"] or 0) - paid_amount, 0)
            status = self._payment_status(float(purchase["total"] or 0), paid_amount)
            cursor = connection.execute(
                """
                INSERT INTO payments (
                    payment_type, reference_type, reference_id, account_id,
                    amount, method, payment_date, note
                )
                VALUES ('out', 'purchase', ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment.reference_id,
                    payment.account_id,
                    payment.amount,
                    payment.method,
                    payment.payment_date,
                    payment.note or f"Supplier payment for purchase {purchase['invoice_no']}",
                ),
            )
            connection.execute(
                """
                UPDATE purchases
                SET paid_amount = ?, due_amount = ?, payment_status = ?
                WHERE id = ?
                """,
                (paid_amount, new_due, status, payment.reference_id),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _payment_status(total: float, paid_amount: float) -> str:
        if paid_amount <= 0:
            return "due"
        if paid_amount >= total:
            return "paid"
        return "partial"
