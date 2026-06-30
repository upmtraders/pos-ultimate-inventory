from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class ExpenseFormData:
    category_id: int | None
    location_id: int
    account_id: int
    expense_date: str
    expense_time: str
    expense_type: str
    amount: float
    payment_method: str
    party_name: str
    reference_no: str
    tax_rate: float
    tax_mode: str
    status: str
    recurrence: str
    attachment_name: str
    attachment_data: str
    note: str
    created_by: int | None


@dataclass(frozen=True)
class ExpenseRefundFormData:
    expense_id: int
    refund_date: str
    amount: float
    note: str


@dataclass(frozen=True)
class ExpenseCategoryData:
    name: str
    parent_id: int | None
    transaction_type: str
    monthly_budget: float
    requires_attachment: int


@dataclass(frozen=True)
class ExpenseSettingsData:
    default_account_id: int
    default_location_id: int
    approval_limit: float
    require_attachment_over: float
    reference_prefix: str


class ExpenseRepository:
    def list_expenses(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        clauses: list[str] = []
        parameters: list[object] = []
        field_map = {
            "expense_type": "expenses.expense_type",
            "status": "expenses.status",
            "category_id": "expenses.category_id",
            "account_id": "expenses.account_id",
            "location_id": "expenses.location_id",
        }
        for key, column in field_map.items():
            value = filters.get(key, "").strip()
            if value:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if filters.get("date_from"):
            clauses.append("expenses.expense_date >= ?")
            parameters.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append("expenses.expense_date <= ?")
            parameters.append(filters["date_to"])
        if filters.get("search"):
            clauses.append(
                """
                (
                    expenses.reference_no LIKE ?
                    OR expenses.party_name LIKE ?
                    OR expenses.note LIKE ?
                    OR expense_categories.name LIKE ?
                )
                """
            )
            search = f"%{filters['search'].strip()}%"
            parameters.extend([search, search, search, search])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sort_columns = {
            "date": "expenses.expense_date",
            "type": "expenses.expense_type",
            "category": "expense_categories.name",
            "account": "payment_accounts.name",
            "amount": "expenses.amount",
            "status": "expenses.status",
        }
        sort_column = sort_columns.get(filters.get("sort", ""), "expenses.expense_date")
        direction = "ASC" if filters.get("direction") == "asc" else "DESC"
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        expenses.*,
                        expense_categories.name AS category_name,
                        parent_categories.name AS parent_category_name,
                        locations.name AS location_name,
                        payment_accounts.name AS account_name,
                        users.full_name AS created_by_name
                    FROM expenses
                    LEFT JOIN expense_categories ON expense_categories.id = expenses.category_id
                    LEFT JOIN expense_categories AS parent_categories
                        ON parent_categories.id = expense_categories.parent_id
                    LEFT JOIN locations ON locations.id = expenses.location_id
                    LEFT JOIN payment_accounts ON payment_accounts.id = expenses.account_id
                    LEFT JOIN users ON users.id = expenses.created_by
                    {where_sql}
                    ORDER BY {sort_column} {direction}, expenses.id DESC
                    """,
                    parameters,
                )
            )

    def get_expense(self, expense_id: int) -> sqlite3.Row | None:
        rows = self.list_expenses({"search": ""})
        return next((row for row in rows if int(row["id"]) == expense_id), None)

    def create_expense(self, expense: ExpenseFormData) -> int:
        self._validate_expense(expense)
        tax_amount = self._tax_amount(expense.amount, expense.tax_rate, expense.tax_mode)
        settings = self.get_settings()
        status = expense.status
        if (
            expense.expense_type == "expense"
            and settings["approval_limit"] > 0
            and expense.amount > float(settings["approval_limit"])
            and status in {"paid", "approved"}
        ):
            status = "pending"
        if (
            expense.expense_type == "expense"
            and settings["require_attachment_over"] > 0
            and expense.amount >= float(settings["require_attachment_over"])
            and not expense.attachment_data
        ):
            raise ValueError("An attachment is required for this amount.")

        connection = get_connection()
        try:
            reference_no = expense.reference_no or self._next_reference(connection, settings)
            cursor = connection.execute(
                """
                INSERT INTO expenses (
                    category_id, location_id, account_id, expense_date, expense_time,
                    expense_type, amount, payment_method, party_name, reference_no,
                    tax_rate, tax_amount, tax_mode, status, recurrence,
                    attachment_name, attachment_data, note, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    expense.category_id,
                    expense.location_id,
                    expense.account_id,
                    expense.expense_date,
                    expense.expense_time,
                    expense.expense_type,
                    expense.amount,
                    expense.payment_method,
                    expense.party_name,
                    reference_no,
                    expense.tax_rate,
                    tax_amount,
                    expense.tax_mode,
                    status,
                    expense.recurrence,
                    expense.attachment_name,
                    expense.attachment_data,
                    expense.note,
                    expense.created_by,
                ),
            )
            expense_id = int(cursor.lastrowid)
            if status in {"paid", "approved"}:
                self._insert_payment(connection, expense_id, expense, tax_amount)
            connection.commit()
            return expense_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_status(self, expense_id: int, status: str, user_id: int | None = None) -> None:
        if status not in {"draft", "pending", "approved", "paid", "cancelled"}:
            raise ValueError("Invalid transaction status.")
        connection = get_connection()
        try:
            row = connection.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
            if row is None:
                raise ValueError("Transaction was not found.")
            connection.execute(
                """
                UPDATE expenses
                SET status = ?, approved_by = CASE WHEN ? IN ('approved', 'paid') THEN ? ELSE approved_by END,
                    approved_at = CASE WHEN ? IN ('approved', 'paid') THEN CURRENT_TIMESTAMP ELSE approved_at END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, status, user_id, status, expense_id),
            )
            existing_payment = connection.execute(
                "SELECT id FROM payments WHERE reference_type = 'expense' AND reference_id = ?",
                (expense_id,),
            ).fetchone()
            if status == "cancelled" and existing_payment:
                connection.execute("DELETE FROM payments WHERE id = ?", (existing_payment["id"],))
            elif status in {"approved", "paid"} and existing_payment is None:
                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_type, reference_type, reference_id, account_id,
                        amount, method, payment_date, note
                    )
                    VALUES (?, 'expense', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out" if row["expense_type"] == "expense" else row["expense_type"],
                        expense_id,
                        row["account_id"],
                        float(row["amount"]) + float(row["tax_amount"] or 0),
                        row["payment_method"],
                        row["expense_date"],
                        row["note"],
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def duplicate_expense(self, expense_id: int, user_id: int | None) -> int:
        row = self.get_expense(expense_id)
        if row is None:
            raise ValueError("Transaction was not found.")
        return self.create_expense(
            ExpenseFormData(
                category_id=row["category_id"],
                location_id=row["location_id"],
                account_id=row["account_id"],
                expense_date=datetime.now().date().isoformat(),
                expense_time=datetime.now().strftime("%H:%M"),
                expense_type=row["expense_type"],
                amount=row["amount"],
                payment_method=row["payment_method"],
                party_name=row["party_name"] or "",
                reference_no="",
                tax_rate=row["tax_rate"],
                tax_mode=row["tax_mode"],
                status="draft",
                recurrence=row["recurrence"],
                attachment_name="",
                attachment_data="",
                note=row["note"] or "",
                created_by=user_id,
            )
        )

    def summary(self, filters: dict[str, str] | None = None) -> dict[str, float]:
        rows = self.list_expenses(filters)
        active = [row for row in rows if row["status"] in {"approved", "paid"}]
        expense_total = sum(
            float(row["amount"]) + float(row["tax_amount"] or 0)
            for row in active
            if row["expense_type"] == "expense"
        )
        cash_in = sum(float(row["amount"]) for row in active if row["expense_type"] == "in")
        cash_out = sum(float(row["amount"]) for row in active if row["expense_type"] == "out")
        return {
            "expense": expense_total,
            "cash_in": cash_in,
            "cash_out": cash_out,
            "net_cash": cash_in - cash_out - expense_total,
            "count": float(len(active)),
        }

    def list_refunds(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT expense_refunds.*, expenses.expense_date,
                           expenses.amount AS expense_amount,
                           expense_categories.name AS category_name
                    FROM expense_refunds
                    JOIN expenses ON expenses.id = expense_refunds.expense_id
                    LEFT JOIN expense_categories ON expense_categories.id = expenses.category_id
                    ORDER BY expense_refunds.refund_date DESC, expense_refunds.id DESC
                    """
                )
            )

    def create_refund(self, refund: ExpenseRefundFormData) -> int:
        if refund.amount <= 0:
            raise ValueError("Refund amount must be greater than zero.")
        connection = get_connection()
        try:
            expense = connection.execute(
                "SELECT * FROM expenses WHERE id = ? AND expense_type = 'expense'",
                (refund.expense_id,),
            ).fetchone()
            if expense is None:
                raise ValueError("Selected expense was not found.")
            refunded = connection.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM expense_refunds WHERE expense_id = ?",
                (refund.expense_id,),
            ).fetchone()[0]
            if float(refunded) + refund.amount > float(expense["amount"]) + float(expense["tax_amount"] or 0):
                raise ValueError("Refund cannot exceed the remaining expense amount.")
            cursor = connection.execute(
                """
                INSERT INTO expense_refunds (expense_id, refund_date, amount, note)
                VALUES (?, ?, ?, ?)
                """,
                (refund.expense_id, refund.refund_date, refund.amount, refund.note),
            )
            refund_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO payments (
                    payment_type, reference_type, reference_id, account_id,
                    amount, method, payment_date, note
                )
                VALUES ('in', 'expense_refund', ?, ?, ?, ?, ?, ?)
                """,
                (
                    refund_id,
                    expense["account_id"],
                    refund.amount,
                    expense["payment_method"],
                    refund.refund_date,
                    refund.note,
                ),
            )
            connection.commit()
            return refund_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def expense_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT expenses.id,
                       COALESCE(expenses.reference_no, 'Expense #' || expenses.id)
                       || ' - ' || COALESCE(expense_categories.name, 'Expense')
                       || ' - ' || expenses.amount AS name
                FROM expenses
                LEFT JOIN expense_categories ON expense_categories.id = expenses.category_id
                WHERE expenses.expense_type = 'expense' AND expenses.status != 'cancelled'
                ORDER BY expenses.id DESC
                """
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def create_category(self, category: ExpenseCategoryData | str) -> None:
        if isinstance(category, str):
            category = ExpenseCategoryData(category, None, "all", 0, 0)
        if category.transaction_type not in {"all", "expense", "in", "out"}:
            raise ValueError("Invalid category transaction type.")
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO expense_categories (
                    name, parent_id, transaction_type, monthly_budget, requires_attachment
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    category.name,
                    category.parent_id,
                    category.transaction_type,
                    category.monthly_budget,
                    category.requires_attachment,
                ),
            )

    def list_categories(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT categories.*, parents.name AS parent_name
                    FROM expense_categories AS categories
                    LEFT JOIN expense_categories AS parents ON parents.id = categories.parent_id
                    ORDER BY COALESCE(parents.name, categories.name), categories.parent_id, categories.name
                    """
                )
            )

    def category_options(self) -> list[LookupItem]:
        return [
            LookupItem(
                id=row["id"],
                name=f"{row['parent_name']} / {row['name']}" if row["parent_name"] else row["name"],
            )
            for row in self.list_categories()
            if row["is_active"]
        ]

    def account_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name FROM payment_accounts WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def location_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name FROM locations WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def party_options(self) -> list[str]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT name FROM contacts WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def get_settings(self) -> sqlite3.Row:
        with get_connection() as connection:
            row = connection.execute("SELECT * FROM expense_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Expense settings are not initialized.")
        return row

    def update_settings(self, settings: ExpenseSettingsData) -> None:
        prefix = settings.reference_prefix.strip().upper() or "EXP-"
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE expense_settings
                SET default_account_id = ?, default_location_id = ?, approval_limit = ?,
                    require_attachment_over = ?, reference_prefix = ?
                WHERE id = 1
                """,
                (
                    settings.default_account_id,
                    settings.default_location_id,
                    settings.approval_limit,
                    settings.require_attachment_over,
                    prefix,
                ),
            )

    def expense_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM expenses").fetchone()
        return int(row["count"])

    @staticmethod
    def _validate_expense(expense: ExpenseFormData) -> None:
        if expense.expense_type not in {"expense", "in", "out"}:
            raise ValueError("Type must be Expense, Cash In, or Cash Out.")
        if expense.status not in {"draft", "pending", "approved", "paid"}:
            raise ValueError("Invalid transaction status.")
        if expense.recurrence not in {"once", "daily", "weekly", "monthly", "yearly"}:
            raise ValueError("Invalid recurrence.")
        if expense.tax_mode not in {"inclusive", "exclusive"}:
            raise ValueError("Invalid tax mode.")
        if expense.amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        if not expense.note.strip():
            raise ValueError("Description / note is required.")

    @staticmethod
    def _tax_amount(amount: float, rate: float, mode: str) -> float:
        if rate <= 0:
            return 0.0
        if mode == "inclusive":
            return round(amount - (amount / (1 + rate / 100)), 2)
        return round(amount * rate / 100, 2)

    @staticmethod
    def _next_reference(connection: sqlite3.Connection, settings: sqlite3.Row) -> str:
        sequence = int(settings["next_reference_number"])
        connection.execute(
            "UPDATE expense_settings SET next_reference_number = ? WHERE id = 1",
            (sequence + 1,),
        )
        return f"{settings['reference_prefix']}{sequence:06d}"

    @staticmethod
    def _insert_payment(
        connection: sqlite3.Connection,
        expense_id: int,
        expense: ExpenseFormData,
        tax_amount: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO payments (
                payment_type, reference_type, reference_id, account_id,
                amount, method, payment_date, note
            )
            VALUES (?, 'expense', ?, ?, ?, ?, ?, ?)
            """,
            (
                "out" if expense.expense_type == "expense" else expense.expense_type,
                expense_id,
                expense.account_id,
                expense.amount + (tax_amount if expense.tax_mode == "exclusive" else 0),
                expense.payment_method,
                expense.expense_date,
                expense.note,
            ),
        )
