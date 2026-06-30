from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem
from pos_inventory_system.services.auth_service import AuthService


@dataclass(frozen=True)
class UserFormData:
    role_id: int
    username: str
    password: str
    full_name: str
    phone: str
    email: str
    address: str
    emergency_contact: str
    permissions_text: str
    sales_commission_rate: float
    sales_target: float
    bank_name: str
    bank_account_name: str
    bank_account_number: str
    bank_branch: str
    employee_no: str
    department: str
    designation: str
    joining_date: str
    employment_type: str
    basic_salary: float
    pay_frequency: str
    allowances: float
    deductions: float
    is_active: int


class UserRepository:
    def list_users(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        users.id,
                        users.username,
                        users.full_name,
                        users.phone,
                        users.email,
                        users.department,
                        users.designation,
                        users.permissions_text,
                        users.sales_commission_rate,
                        users.sales_target,
                        users.basic_salary,
                        users.pay_frequency,
                        users.is_active,
                        users.created_at,
                        roles.name AS role_name
                    FROM users
                    JOIN roles ON roles.id = users.role_id
                    ORDER BY users.id
                    """
                )
            )

    def deactivate_user(self, user_id: int, current_user_id: int | None = None) -> None:
        if user_id <= 0:
            raise ValueError("User is required.")
        if current_user_id is not None and user_id == current_user_id:
            raise ValueError("You cannot deactivate your own active login.")
        with get_connection() as connection:
            user = connection.execute(
                """
                SELECT users.id, users.is_active, roles.name AS role_name
                FROM users
                JOIN roles ON roles.id = users.role_id
                WHERE users.id = ?
                """,
                (user_id,),
            ).fetchone()
            if user is None:
                raise ValueError("User was not found.")
            if not user["is_active"]:
                raise ValueError("User is already inactive.")
            if user["role_name"] == "Admin":
                active_admins = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM users
                    JOIN roles ON roles.id = users.role_id
                    WHERE roles.name = 'Admin' AND users.is_active = 1
                    """
                ).fetchone()
                if int(active_admins["count"] or 0) <= 1:
                    raise ValueError("At least one active Admin user is required.")
            cursor = connection.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?",
                (user_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError("User was not found.")

    def create_user(self, user: UserFormData) -> int:
        username = user.username.strip().lower()
        full_name = user.full_name.strip()
        if not username:
            raise ValueError("Username is required.")
        if not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise ValueError("Username can use letters, numbers, dot, dash, and underscore only.")
        if not full_name:
            raise ValueError("Full name is required.")
        if len(user.password) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if user.sales_commission_rate < 0 or user.sales_commission_rate > 100:
            raise ValueError("Sales commission rate must be between 0 and 100.")
        for label, amount in (
            ("Sales target", user.sales_target),
            ("Basic salary", user.basic_salary),
            ("Allowances", user.allowances),
            ("Deductions", user.deductions),
        ):
            if amount < 0:
                raise ValueError(f"{label} cannot be negative.")

        password_hash = AuthService.hash_password(user.password)
        with get_connection() as connection:
            role = connection.execute("SELECT id FROM roles WHERE id = ?", (user.role_id,)).fetchone()
            if role is None:
                raise ValueError("Selected role was not found.")
            existing = connection.execute(
                "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?) LIMIT 1",
                (username,),
            ).fetchone()
            if existing is not None:
                raise ValueError("Username is already used.")
            cursor = connection.execute(
                """
                INSERT INTO users (
                    role_id,
                    username,
                    password_hash,
                    full_name,
                    phone,
                    email,
                    address,
                    emergency_contact,
                    permissions_text,
                    sales_commission_rate,
                    sales_target,
                    bank_name,
                    bank_account_name,
                    bank_account_number,
                    bank_branch,
                    employee_no,
                    department,
                    designation,
                    joining_date,
                    employment_type,
                    basic_salary,
                    pay_frequency,
                    allowances,
                    deductions,
                    is_active
                )
                VALUES (?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, NULLIF(?, ''), ?, ?, ?)
                """,
                (
                    user.role_id,
                    username,
                    password_hash,
                    full_name,
                    user.phone,
                    user.email,
                    user.address,
                    user.emergency_contact,
                    user.permissions_text,
                    user.sales_commission_rate,
                    user.sales_target,
                    user.bank_name,
                    user.bank_account_name,
                    user.bank_account_number,
                    user.bank_branch,
                    user.employee_no,
                    user.department,
                    user.designation,
                    user.joining_date,
                    user.employment_type,
                    user.basic_salary,
                    user.pay_frequency,
                    user.allowances,
                    user.deductions,
                    user.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def list_roles(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, name, description, COALESCE(permissions_text, '') AS permissions_text, created_at
                    FROM roles
                    ORDER BY id
                    """
                )
            )

    def create_role(self, name: str, description: str, permissions_text: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("Role name is required.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM roles WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A role with this name already exists.")
            cursor = connection.execute(
                "INSERT INTO roles (name, description, permissions_text) VALUES (?, NULLIF(?, ''), NULLIF(?, ''))",
                (name, description.strip(), permissions_text.strip()),
            )
            return int(cursor.lastrowid)

    def update_role(self, role_id: int, name: str, description: str, permissions_text: str = "") -> None:
        name = name.strip()
        if role_id <= 0:
            raise ValueError("Role is required.")
        if not name:
            raise ValueError("Role name is required.")

        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM roles WHERE LOWER(name) = LOWER(?) AND id <> ? LIMIT 1",
                (name, role_id),
            ).fetchone()
            if exists is not None:
                raise ValueError("A role with this name already exists.")
            cursor = connection.execute(
                """
                UPDATE roles
                SET name = ?, description = NULLIF(?, ''), permissions_text = NULLIF(?, '')
                WHERE id = ?
                """,
                (name, description.strip(), permissions_text.strip(), role_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Role was not found.")

    def role_user_counts(self) -> dict[int, int]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT role_id, COUNT(*) AS user_count
                FROM users
                GROUP BY role_id
                """
            ).fetchall()
        return {int(row["role_id"]): int(row["user_count"]) for row in rows}

    def role_options(self) -> list[LookupItem]:
        roles = self.list_roles()
        return [LookupItem(id=row["id"], name=row["name"]) for row in roles]
