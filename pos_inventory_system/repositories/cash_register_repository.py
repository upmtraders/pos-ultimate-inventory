from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class OpenRegisterData:
    user_id: int
    location_id: int
    opening_cash: float


@dataclass(frozen=True)
class CloseRegisterData:
    register_id: int
    denomination_counts: dict[int, int]
    coins_total: float
    closing_note: str
    approved_by: int | None


@dataclass(frozen=True)
class CashMovementData:
    register_id: int
    movement_type: str
    amount: float
    reason: str


CASH_DENOMINATIONS = (5000, 2000, 1000, 500, 100, 50, 20, 10)


class CashRegisterRepository:
    def current_open_register(self, user_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT cash_registers.*, users.full_name AS user_name, locations.name AS location_name
                FROM cash_registers
                JOIN users ON users.id = cash_registers.user_id
                LEFT JOIN locations ON locations.id = cash_registers.location_id
                WHERE cash_registers.user_id = ? AND cash_registers.status = 'open'
                ORDER BY cash_registers.id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

    def list_registers(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        cash_registers.*,
                        users.full_name AS user_name,
                        locations.name AS location_name
                    FROM cash_registers
                    JOIN users ON users.id = cash_registers.user_id
                    LEFT JOIN locations ON locations.id = cash_registers.location_id
                    ORDER BY cash_registers.opened_at DESC, cash_registers.id DESC
                    """
                )
            )

    def get_register(self, register_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT
                    cash_registers.*,
                    users.full_name AS user_name,
                    locations.name AS location_name
                FROM cash_registers
                JOIN users ON users.id = cash_registers.user_id
                LEFT JOIN locations ON locations.id = cash_registers.location_id
                WHERE cash_registers.id = ?
                """,
                (register_id,),
            ).fetchone()

    def open_register(self, data: OpenRegisterData) -> int:
        if data.opening_cash < 0:
            raise ValueError("Opening cash cannot be negative.")
        if self.current_open_register(data.user_id) is not None:
            raise ValueError("This user already has an open cash register.")

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO cash_registers (user_id, location_id, opening_cash, status)
                VALUES (?, ?, ?, 'open')
                """,
                (data.user_id, data.location_id, data.opening_cash),
            )
            return int(cursor.lastrowid)

    def close_register(self, data: CloseRegisterData) -> None:
        if data.coins_total < 0:
            raise ValueError("Coins total cannot be negative.")
        counts: dict[int, int] = {}
        for denomination in CASH_DENOMINATIONS:
            count = int(data.denomination_counts.get(denomination, 0))
            if count < 0:
                raise ValueError("Note count cannot be negative.")
            counts[denomination] = count
        closing_cash = sum(denomination * count for denomination, count in counts.items()) + data.coins_total
        breakdown = {
            "notes": {str(denomination): counts[denomination] for denomination in CASH_DENOMINATIONS},
            "coins_total": data.coins_total,
            "counted_cash": closing_cash,
        }

        with get_connection() as connection:
            register = connection.execute(
                "SELECT * FROM cash_registers WHERE id = ? AND status = 'open'",
                (data.register_id,),
            ).fetchone()
            if register is None:
                raise ValueError("Open register not found.")
            summary = self.register_summary(register)
            difference = closing_cash - summary["expected_cash"]
            if abs(difference) > 0.01 and not data.closing_note.strip():
                raise ValueError("Closing note is required when counted cash does not match expected cash.")
            connection.execute(
                """
                UPDATE cash_registers
                SET closed_at = CURRENT_TIMESTAMP,
                    closing_cash = ?,
                    denomination_breakdown = ?,
                    closing_note = NULLIF(?, ''),
                    approval_status = ?,
                    approved_by = ?,
                    approved_at = CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END,
                    status = 'closed'
                WHERE id = ?
                """,
                (
                    closing_cash,
                    json.dumps(breakdown, separators=(",", ":")),
                    data.closing_note.strip(),
                    "approved" if data.approved_by is not None else "pending",
                    data.approved_by,
                    data.approved_by,
                    data.register_id,
                ),
            )

    @staticmethod
    def denomination_breakdown(register: sqlite3.Row) -> dict[str, object]:
        raw = register["denomination_breakdown"] if "denomination_breakdown" in register.keys() else None
        if not raw:
            return {"notes": {}, "coins_total": 0.0, "counted_cash": float(register["closing_cash"] or 0)}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {"notes": {}, "coins_total": 0.0, "counted_cash": float(register["closing_cash"] or 0)}
        return {
            "notes": data.get("notes", {}),
            "coins_total": float(data.get("coins_total", 0) or 0),
            "counted_cash": float(data.get("counted_cash", register["closing_cash"] or 0) or 0),
        }

    def create_manual_movement(self, data: CashMovementData) -> int:
        if data.movement_type not in {"in", "out"}:
            raise ValueError("Select Cash In or Cash Out.")
        if data.amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        if not data.reason.strip():
            raise ValueError("Reason is required.")
        with get_connection() as connection:
            register = connection.execute(
                "SELECT id FROM cash_registers WHERE id = ? AND status = 'open'",
                (data.register_id,),
            ).fetchone()
            if register is None:
                raise ValueError("Open register not found.")
            cursor = connection.execute(
                """
                INSERT INTO payments (
                    payment_type, reference_type, reference_id, account_id,
                    amount, method, payment_date, note
                )
                VALUES (?, 'cash_register_adjustment', ?, 1, ?, 'cash', DATE('now'), ?)
                """,
                (
                    data.movement_type,
                    data.register_id,
                    data.amount,
                    data.reason.strip(),
                ),
            )
            return int(cursor.lastrowid)

    def register_transactions(self, register: sqlite3.Row) -> list[sqlite3.Row]:
        end_time = register["closed_at"] or self._current_timestamp()
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        payments.id,
                        payments.created_at,
                        payments.payment_date,
                        payments.payment_type,
                        payments.reference_type,
                        payments.reference_id,
                        payments.amount,
                        payments.method,
                        payments.note
                    FROM payments
                    WHERE LOWER(COALESCE(payments.method, '')) = 'cash'
                      AND payments.created_at >= ?
                      AND payments.created_at <= ?
                      AND (
                        payments.reference_type <> 'cash_register_adjustment'
                        OR payments.reference_id = ?
                      )
                    ORDER BY payments.created_at DESC, payments.id DESC
                    """,
                    (register["opened_at"], end_time, register["id"]),
                )
            )

    def approve_register(self, register_id: int, approved_by: int) -> None:
        with get_connection() as connection:
            register = connection.execute(
                """
                SELECT id
                FROM cash_registers
                WHERE id = ? AND status = 'closed' AND approval_status = 'pending'
                """,
                (register_id,),
            ).fetchone()
            if register is None:
                raise ValueError("Closed pending register not found.")
            connection.execute(
                """
                UPDATE cash_registers
                SET approval_status = 'approved',
                    approved_by = ?,
                    approved_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (approved_by, register_id),
            )

    def register_summary(self, register: sqlite3.Row) -> dict[str, float]:
        transactions = self.register_transactions(register)
        cash_in = sum(float(row["amount"]) for row in transactions if row["payment_type"] == "in")
        cash_out = sum(float(row["amount"]) for row in transactions if row["payment_type"] == "out")
        cash_sales = sum(
            float(row["amount"])
            for row in transactions
            if row["payment_type"] == "in" and row["reference_type"] == "sale"
        )
        other_cash_in = cash_in - cash_sales
        purchase_cash_out = sum(
            float(row["amount"]) for row in transactions if row["reference_type"] == "purchase"
        )
        expense_cash_out = sum(
            float(row["amount"]) for row in transactions if row["reference_type"] == "expense"
        )
        return_cash_out = sum(
            float(row["amount"]) for row in transactions if row["reference_type"] == "sale_return"
        )
        manual_cash_in = sum(
            float(row["amount"])
            for row in transactions
            if row["payment_type"] == "in" and row["reference_type"] == "cash_register_adjustment"
        )
        manual_cash_out = sum(
            float(row["amount"])
            for row in transactions
            if row["payment_type"] == "out" and row["reference_type"] == "cash_register_adjustment"
        )
        expected_cash = float(register["opening_cash"]) + cash_in - cash_out
        closing_cash = register["closing_cash"]
        difference = 0.0 if closing_cash is None else float(closing_cash) - expected_cash
        return {
            "cash_in": cash_in,
            "cash_out": cash_out,
            "cash_sales": cash_sales,
            "other_cash_in": other_cash_in,
            "purchase_cash_out": purchase_cash_out,
            "expense_cash_out": expense_cash_out,
            "return_cash_out": return_cash_out,
            "manual_cash_in": manual_cash_in,
            "manual_cash_out": manual_cash_out,
            "expected_cash": expected_cash,
            "difference": difference,
            "transaction_count": float(len(transactions)),
        }

    @staticmethod
    def _current_timestamp() -> str:
        with get_connection() as connection:
            row = connection.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()
        return str(row["now"])
