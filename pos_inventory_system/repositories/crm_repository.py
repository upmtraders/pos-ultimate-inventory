from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class LeadData:
    name: str
    phone: str
    email: str
    source: str
    interested_in: str
    status: str
    assigned_user_id: int | None
    next_followup_date: str
    note: str


@dataclass(frozen=True)
class FollowUpData:
    lead_id: int | None
    customer_id: int | None
    assigned_user_id: int | None
    followup_type: str
    due_date: str
    due_time: str
    status: str
    note: str


class CRMRepository:
    def create_lead(self, lead: LeadData) -> int:
        self._validate_lead(lead)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crm_leads (
                    name, phone, email, source, interested_in, status,
                    assigned_user_id, next_followup_date, note
                )
                VALUES (?, NULLIF(?, ''), NULLIF(?, ''), ?, NULLIF(?, ''), ?, ?, NULLIF(?, ''), NULLIF(?, ''))
                """,
                (
                    lead.name.strip(),
                    lead.phone.strip(),
                    lead.email.strip(),
                    lead.source,
                    lead.interested_in.strip(),
                    lead.status,
                    lead.assigned_user_id,
                    lead.next_followup_date,
                    lead.note.strip(),
                ),
            )
            return int(cursor.lastrowid)

    def update_lead_status(self, lead_id: int, status: str) -> None:
        if status not in {"new", "contacted", "qualified", "converted", "lost"}:
            raise ValueError("Invalid lead status.")
        with get_connection() as connection:
            cursor = connection.execute(
                "UPDATE crm_leads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, lead_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Lead not found.")

    def list_leads(self, limit: int = 100) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT crm_leads.*, users.full_name AS assigned_name
                    FROM crm_leads
                    LEFT JOIN users ON users.id = crm_leads.assigned_user_id
                    ORDER BY
                        CASE crm_leads.status
                            WHEN 'new' THEN 1
                            WHEN 'contacted' THEN 2
                            WHEN 'qualified' THEN 3
                            WHEN 'converted' THEN 4
                            ELSE 5
                        END,
                        crm_leads.created_at DESC,
                        crm_leads.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def lead_options(self) -> list[LookupItem]:
        rows = self.list_leads(300)
        return [LookupItem(id=row["id"], name=f"{row['name']} ({row['status']})") for row in rows if row["status"] != "lost"]

    def create_followup(self, followup: FollowUpData) -> int:
        self._validate_followup(followup)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crm_followups (
                    lead_id, customer_id, assigned_user_id, followup_type,
                    due_date, due_time, status, note
                )
                VALUES (?, ?, ?, ?, ?, NULLIF(?, ''), ?, NULLIF(?, ''))
                """,
                (
                    followup.lead_id,
                    followup.customer_id,
                    followup.assigned_user_id,
                    followup.followup_type,
                    followup.due_date,
                    followup.due_time,
                    followup.status,
                    followup.note.strip(),
                ),
            )
            return int(cursor.lastrowid)

    def update_followup_status(self, followup_id: int, status: str) -> None:
        if status not in {"pending", "done", "missed", "cancelled"}:
            raise ValueError("Invalid follow-up status.")
        with get_connection() as connection:
            cursor = connection.execute(
                "UPDATE crm_followups SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, followup_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Follow-up not found.")

    def list_followups(self, limit: int = 120) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        crm_followups.*,
                        crm_leads.name AS lead_name,
                        contacts.name AS customer_name,
                        users.full_name AS assigned_name
                    FROM crm_followups
                    LEFT JOIN crm_leads ON crm_leads.id = crm_followups.lead_id
                    LEFT JOIN contacts ON contacts.id = crm_followups.customer_id
                    LEFT JOIN users ON users.id = crm_followups.assigned_user_id
                    ORDER BY
                        CASE crm_followups.status WHEN 'pending' THEN 1 WHEN 'missed' THEN 2 ELSE 3 END,
                        crm_followups.due_date,
                        crm_followups.due_time,
                        crm_followups.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def list_customers(self, limit: int = 100) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        contacts.id,
                        contacts.name,
                        contacts.phone,
                        contacts.email,
                        contacts.city,
                        contacts.is_active,
                        COALESCE(sale_summary.sale_count, 0) AS sale_count,
                        COALESCE(sale_summary.sale_total, 0) AS sale_total,
                        COALESCE(sale_summary.due_total, 0) AS due_total
                    FROM contacts
                    LEFT JOIN (
                        SELECT customer_id, COUNT(*) AS sale_count, SUM(total) AS sale_total, SUM(due_amount) AS due_total
                        FROM sales
                        WHERE customer_id IS NOT NULL
                        GROUP BY customer_id
                    ) AS sale_summary ON sale_summary.customer_id = contacts.id
                    WHERE contacts.contact_type IN ('customer', 'both')
                    ORDER BY contacts.created_at DESC, contacts.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def list_quotations(self, limit: int = 100) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT sales.*, contacts.name AS customer_name
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    WHERE sales.sale_status = 'quotation'
                    ORDER BY sales.sale_date DESC, sales.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def staff_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, full_name || ' (' || username || ')' AS name FROM users WHERE is_active = 1 ORDER BY full_name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def customer_options(self) -> list[LookupItem]:
        customers = self.list_customers(500)
        return [LookupItem(id=row["id"], name=row["name"]) for row in customers if row["is_active"]]

    def summary(self) -> dict[str, int]:
        with get_connection() as connection:
            customers = connection.execute("SELECT COUNT(*) AS count FROM contacts WHERE contact_type IN ('customer', 'both') AND is_active = 1").fetchone()
            leads = connection.execute("SELECT COUNT(*) AS count FROM crm_leads WHERE status NOT IN ('converted', 'lost')").fetchone()
            followups = connection.execute("SELECT COUNT(*) AS count FROM crm_followups WHERE status = 'pending'").fetchone()
            quotations = connection.execute("SELECT COUNT(*) AS count FROM sales WHERE sale_status = 'quotation'").fetchone()
        return {
            "customers": int(customers["count"]),
            "open_leads": int(leads["count"]),
            "pending_followups": int(followups["count"]),
            "quotations": int(quotations["count"]),
        }

    @staticmethod
    def _validate_lead(lead: LeadData) -> None:
        if not lead.name.strip():
            raise ValueError("Lead name is required.")
        if lead.source not in {"walk_in", "phone", "whatsapp", "facebook", "website", "referral", "other"}:
            raise ValueError("Invalid lead source.")
        if lead.status not in {"new", "contacted", "qualified", "converted", "lost"}:
            raise ValueError("Invalid lead status.")

    @staticmethod
    def _validate_followup(followup: FollowUpData) -> None:
        if not followup.lead_id and not followup.customer_id:
            raise ValueError("Select a lead or a customer.")
        if followup.followup_type not in {"call", "whatsapp", "visit", "email", "quotation", "payment"}:
            raise ValueError("Invalid follow-up type.")
        if not followup.due_date:
            raise ValueError("Due date is required.")
        if followup.status not in {"pending", "done", "missed", "cancelled"}:
            raise ValueError("Invalid follow-up status.")
