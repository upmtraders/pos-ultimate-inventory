from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class AttendanceData:
    user_id: int
    attendance_date: str
    status: str
    check_in: str
    check_out: str
    overtime_hours: float
    note: str


@dataclass(frozen=True)
class LeaveRequestData:
    user_id: int
    leave_type: str
    date_from: str
    date_to: str
    days: float
    reason: str


@dataclass(frozen=True)
class PayrollData:
    user_id: int
    pay_period: str
    basic_salary: float
    allowances: float
    overtime_amount: float
    commission_amount: float
    deductions: float
    payment_status: str
    payment_date: str
    note: str


@dataclass(frozen=True)
class DocumentData:
    user_id: int
    document_type: str
    document_no: str
    expiry_date: str
    status: str
    note: str


class HRMRepository:
    def staff_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, full_name || ' (' || username || ')' AS name
                FROM users
                WHERE is_active = 1
                ORDER BY full_name, username
                """
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_staff(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        users.id,
                        users.full_name,
                        users.username,
                        users.phone,
                        users.email,
                        users.department,
                        users.designation,
                        users.basic_salary,
                        users.pay_frequency,
                        users.is_active,
                        roles.name AS role_name
                    FROM users
                    JOIN roles ON roles.id = users.role_id
                    ORDER BY users.full_name, users.username
                    """
                )
            )

    def save_attendance(self, data: AttendanceData) -> None:
        self._validate_user(data.user_id)
        if data.status not in {"present", "absent", "half_day", "leave", "late"}:
            raise ValueError("Invalid attendance status.")
        if not data.attendance_date:
            raise ValueError("Attendance date is required.")
        if data.overtime_hours < 0:
            raise ValueError("Overtime cannot be negative.")
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO hrm_attendance (
                    user_id, attendance_date, status, check_in, check_out, overtime_hours, note
                )
                VALUES (?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, NULLIF(?, ''))
                ON CONFLICT(user_id, attendance_date) DO UPDATE SET
                    status = excluded.status,
                    check_in = excluded.check_in,
                    check_out = excluded.check_out,
                    overtime_hours = excluded.overtime_hours,
                    note = excluded.note
                """,
                (data.user_id, data.attendance_date, data.status, data.check_in, data.check_out, data.overtime_hours, data.note),
            )

    def list_attendance(self, limit: int = 80) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT hrm_attendance.*, users.full_name
                    FROM hrm_attendance
                    JOIN users ON users.id = hrm_attendance.user_id
                    ORDER BY hrm_attendance.attendance_date DESC, hrm_attendance.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def create_leave(self, data: LeaveRequestData) -> int:
        self._validate_user(data.user_id)
        if data.leave_type not in {"annual", "sick", "casual", "unpaid", "other"}:
            raise ValueError("Invalid leave type.")
        if not data.date_from or not data.date_to:
            raise ValueError("Leave from/to dates are required.")
        if data.days <= 0:
            raise ValueError("Leave days must be greater than zero.")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO hrm_leave_requests (
                    user_id, leave_type, date_from, date_to, days, reason
                )
                VALUES (?, ?, ?, ?, ?, NULLIF(?, ''))
                """,
                (data.user_id, data.leave_type, data.date_from, data.date_to, data.days, data.reason),
            )
            return int(cursor.lastrowid)

    def update_leave_status(self, leave_id: int, status: str) -> None:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("Invalid leave status.")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE hrm_leave_requests
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, leave_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Leave request not found.")

    def list_leaves(self, limit: int = 80) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT hrm_leave_requests.*, users.full_name
                    FROM hrm_leave_requests
                    JOIN users ON users.id = hrm_leave_requests.user_id
                    ORDER BY hrm_leave_requests.created_at DESC, hrm_leave_requests.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def save_payroll(self, data: PayrollData) -> int:
        self._validate_user(data.user_id)
        if not data.pay_period:
            raise ValueError("Pay period is required.")
        if data.payment_status not in {"unpaid", "paid", "partial"}:
            raise ValueError("Invalid payroll payment status.")
        values = [data.basic_salary, data.allowances, data.overtime_amount, data.commission_amount, data.deductions]
        if any(value < 0 for value in values):
            raise ValueError("Payroll amounts cannot be negative.")
        net_salary = max(data.basic_salary + data.allowances + data.overtime_amount + data.commission_amount - data.deductions, 0)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO hrm_payroll (
                    user_id, pay_period, basic_salary, allowances, overtime_amount,
                    commission_amount, deductions, net_salary, payment_status, payment_date, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''))
                ON CONFLICT(user_id, pay_period) DO UPDATE SET
                    basic_salary = excluded.basic_salary,
                    allowances = excluded.allowances,
                    overtime_amount = excluded.overtime_amount,
                    commission_amount = excluded.commission_amount,
                    deductions = excluded.deductions,
                    net_salary = excluded.net_salary,
                    payment_status = excluded.payment_status,
                    payment_date = excluded.payment_date,
                    note = excluded.note
                """,
                (
                    data.user_id,
                    data.pay_period,
                    data.basic_salary,
                    data.allowances,
                    data.overtime_amount,
                    data.commission_amount,
                    data.deductions,
                    net_salary,
                    data.payment_status,
                    data.payment_date,
                    data.note,
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_payroll(self, limit: int = 80) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT hrm_payroll.*, users.full_name
                    FROM hrm_payroll
                    JOIN users ON users.id = hrm_payroll.user_id
                    ORDER BY hrm_payroll.pay_period DESC, hrm_payroll.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def create_document(self, data: DocumentData) -> int:
        self._validate_user(data.user_id)
        if not data.document_type.strip():
            raise ValueError("Document type is required.")
        if data.status not in {"valid", "expiring", "expired", "missing"}:
            raise ValueError("Invalid document status.")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO hrm_documents (
                    user_id, document_type, document_no, expiry_date, status, note
                )
                VALUES (?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, NULLIF(?, ''))
                """,
                (data.user_id, data.document_type.strip(), data.document_no, data.expiry_date, data.status, data.note),
            )
            return int(cursor.lastrowid)

    def list_documents(self, limit: int = 80) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT hrm_documents.*, users.full_name
                    FROM hrm_documents
                    JOIN users ON users.id = hrm_documents.user_id
                    ORDER BY hrm_documents.created_at DESC, hrm_documents.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def summary(self) -> dict[str, int | float]:
        with get_connection() as connection:
            staff = connection.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()
            attendance = connection.execute("SELECT COUNT(*) AS count FROM hrm_attendance").fetchone()
            pending_leave = connection.execute("SELECT COUNT(*) AS count FROM hrm_leave_requests WHERE status = 'pending'").fetchone()
            unpaid_payroll = connection.execute("SELECT COUNT(*) AS count FROM hrm_payroll WHERE payment_status != 'paid'").fetchone()
        return {
            "staff": int(staff["count"]),
            "attendance": int(attendance["count"]),
            "pending_leave": int(pending_leave["count"]),
            "unpaid_payroll": int(unpaid_payroll["count"]),
        }

    @staticmethod
    def _validate_user(user_id: int) -> None:
        if user_id <= 0:
            raise ValueError("Staff member is required.")
        with get_connection() as connection:
            row = connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("Staff member not found.")
