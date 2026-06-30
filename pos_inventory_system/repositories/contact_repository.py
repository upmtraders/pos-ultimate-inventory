from __future__ import annotations

import sqlite3
import csv
from dataclasses import dataclass
from io import StringIO

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class ContactFormData:
    contact_type: str
    supplier_type: str
    name: str
    business_name: str
    contact_code: str
    tax_number: str
    phone: str
    alternate_phone: str
    email: str
    website: str
    address: str
    city: str
    state: str
    country: str
    postal_code: str
    payment_terms: str
    credit_days: int
    opening_balance: float
    credit_limit: float
    customer_group_id: int | None
    contact_person_1_name: str
    contact_person_1_designation: str
    contact_person_1_phone: str
    contact_person_1_email: str
    contact_person_2_name: str
    contact_person_2_designation: str
    contact_person_2_phone: str
    contact_person_2_email: str
    contact_person_3_name: str
    contact_person_3_designation: str
    contact_person_3_phone: str
    contact_person_3_email: str
    notes: str
    is_active: int


@dataclass(frozen=True)
class CustomerGroupFormData:
    name: str
    price_discount_percent: float
    note: str
    is_active: int


class ContactRepository:
    def list_contacts(self, contact_type: str) -> list[sqlite3.Row]:
        self._validate_type(contact_type)
        roles = {
            "customer": ("customer", "both"),
            "supplier": ("supplier", "both"),
            "both": ("both",),
        }[contact_type]
        placeholders = ", ".join("?" for _ in roles)
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        contacts.id,
                        contacts.contact_type,
                        contacts.supplier_type,
                        contacts.name,
                        contacts.business_name,
                        contacts.contact_code,
                        contacts.tax_number,
                        contacts.phone,
                        contacts.alternate_phone,
                        contacts.email,
                        contacts.website,
                        contacts.address,
                        contacts.city,
                        contacts.state,
                        contacts.country,
                        contacts.postal_code,
                        contacts.payment_terms,
                        contacts.credit_days,
                        contacts.opening_balance,
                        contacts.credit_limit,
                        contacts.customer_group_id,
                        contacts.contact_person_1_name,
                        contacts.contact_person_1_designation,
                        contacts.contact_person_1_phone,
                        contacts.contact_person_1_email,
                        contacts.contact_person_2_name,
                        contacts.contact_person_2_designation,
                        contacts.contact_person_2_phone,
                        contacts.contact_person_2_email,
                        contacts.contact_person_3_name,
                        contacts.contact_person_3_designation,
                        contacts.contact_person_3_phone,
                        contacts.contact_person_3_email,
                        contacts.notes,
                        contacts.is_active,
                        contacts.created_at,
                        contacts.updated_at,
                        customer_groups.name AS customer_group_name,
                        COALESCE(purchase_summary.document_count, 0) AS purchase_count,
                        COALESCE(purchase_summary.total_amount, 0) AS purchase_total,
                        COALESCE(purchase_summary.due_amount, 0) AS purchase_due,
                        COALESCE(sale_summary.document_count, 0) AS sale_count,
                        COALESCE(sale_summary.total_amount, 0) AS sale_total,
                        COALESCE(sale_summary.due_amount, 0) AS sale_due
                    FROM contacts
                    LEFT JOIN customer_groups ON customer_groups.id = contacts.customer_group_id
                    LEFT JOIN (
                        SELECT
                            supplier_id AS contact_id,
                            COUNT(*) AS document_count,
                            SUM(total) AS total_amount,
                            SUM(due_amount) AS due_amount
                        FROM purchases
                        GROUP BY supplier_id
                    ) AS purchase_summary ON purchase_summary.contact_id = contacts.id
                    LEFT JOIN (
                        SELECT
                            customer_id AS contact_id,
                            COUNT(*) AS document_count,
                            SUM(total) AS total_amount,
                            SUM(due_amount) AS due_amount
                        FROM sales
                        GROUP BY customer_id
                    ) AS sale_summary ON sale_summary.contact_id = contacts.id
                    WHERE contacts.contact_type IN ({placeholders})
                    ORDER BY contacts.created_at DESC, contacts.id DESC
                    """,
                    roles,
                )
            )

    def create_contact(self, contact: ContactFormData) -> int:
        self._validate_type(contact.contact_type)
        self._validate_contact(contact)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO contacts (
                    contact_type,
                    supplier_type,
                    name,
                    business_name,
                    contact_code,
                    tax_number,
                    phone,
                    alternate_phone,
                    email,
                    website,
                    address,
                    city,
                    state,
                    country,
                    postal_code,
                    payment_terms,
                    credit_days,
                    opening_balance,
                    credit_limit,
                    customer_group_id,
                    contact_person_1_name,
                    contact_person_1_designation,
                    contact_person_1_phone,
                    contact_person_1_email,
                    contact_person_2_name,
                    contact_person_2_designation,
                    contact_person_2_phone,
                    contact_person_2_email,
                    contact_person_3_name,
                    contact_person_3_designation,
                    contact_person_3_phone,
                    contact_person_3_email,
                    notes,
                    is_active
                )
                VALUES (?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?)
                """,
                self._contact_params(contact),
            )
            return int(cursor.lastrowid)

    def update_contact(self, contact_id: int, contact: ContactFormData) -> None:
        if contact_id <= 0:
            raise ValueError("Contact is required.")
        self._validate_type(contact.contact_type)
        self._validate_contact(contact)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE contacts
                SET
                    contact_type = ?,
                    supplier_type = ?,
                    name = ?,
                    business_name = NULLIF(?, ''),
                    contact_code = NULLIF(?, ''),
                    tax_number = NULLIF(?, ''),
                    phone = NULLIF(?, ''),
                    alternate_phone = NULLIF(?, ''),
                    email = NULLIF(?, ''),
                    website = NULLIF(?, ''),
                    address = NULLIF(?, ''),
                    city = NULLIF(?, ''),
                    state = NULLIF(?, ''),
                    country = NULLIF(?, ''),
                    postal_code = NULLIF(?, ''),
                    payment_terms = NULLIF(?, ''),
                    credit_days = ?,
                    opening_balance = ?,
                    credit_limit = ?,
                    customer_group_id = ?,
                    contact_person_1_name = NULLIF(?, ''),
                    contact_person_1_designation = NULLIF(?, ''),
                    contact_person_1_phone = NULLIF(?, ''),
                    contact_person_1_email = NULLIF(?, ''),
                    contact_person_2_name = NULLIF(?, ''),
                    contact_person_2_designation = NULLIF(?, ''),
                    contact_person_2_phone = NULLIF(?, ''),
                    contact_person_2_email = NULLIF(?, ''),
                    contact_person_3_name = NULLIF(?, ''),
                    contact_person_3_designation = NULLIF(?, ''),
                    contact_person_3_phone = NULLIF(?, ''),
                    contact_person_3_email = NULLIF(?, ''),
                    notes = NULLIF(?, ''),
                    is_active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*self._contact_params(contact), contact_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Contact was not found.")

    def deactivate_contact(self, contact_id: int) -> None:
        with get_connection() as connection:
            connection.execute("UPDATE contacts SET is_active = 0 WHERE id = ?", (contact_id,))

    def create_customer_group(self, group: CustomerGroupFormData) -> int:
        if group.price_discount_percent < 0 or group.price_discount_percent > 100:
            raise ValueError("Group discount must be between 0 and 100.")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO customer_groups (name, price_discount_percent, note, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (group.name, group.price_discount_percent, group.note, group.is_active),
            )
            return int(cursor.lastrowid)

    def update_customer_group(self, group_id: int, group: CustomerGroupFormData) -> None:
        if group_id <= 0:
            raise ValueError("Customer group is required.")
        if not group.name.strip():
            raise ValueError("Group name is required.")
        if group.price_discount_percent < 0 or group.price_discount_percent > 100:
            raise ValueError("Group discount must be between 0 and 100.")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE customer_groups
                SET name = ?, price_discount_percent = ?, note = ?, is_active = ?
                WHERE id = ?
                """,
                (group.name.strip(), group.price_discount_percent, group.note.strip(), group.is_active, group_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Customer group was not found.")

    def list_customer_groups(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        customer_groups.id,
                        customer_groups.name,
                        customer_groups.price_discount_percent,
                        customer_groups.note,
                        customer_groups.is_active,
                        COUNT(contacts.id) AS customer_count
                    FROM customer_groups
                    LEFT JOIN contacts
                        ON contacts.customer_group_id = customer_groups.id
                        AND contacts.contact_type IN ('customer', 'both')
                    GROUP BY customer_groups.id
                    ORDER BY customer_groups.name
                    """
                )
            )

    def customer_group_options(self) -> list[LookupItem]:
        rows = self.list_customer_groups()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows if row["is_active"]]

    def import_contacts_csv(self, csv_text: str) -> tuple[int, list[str]]:
        reader = csv.DictReader(StringIO(csv_text.strip()))
        required = {"type", "name"}
        if reader.fieldnames is None or not required.issubset({field.strip().lower() for field in reader.fieldnames}):
            raise ValueError("CSV must include at least type and name columns.")

        imported = 0
        errors: list[str] = []
        normalized_fieldnames = {field.lower(): field for field in reader.fieldnames}
        for index, row in enumerate(reader, start=2):
            try:
                contact_type = self._csv_text(row, normalized_fieldnames, "type").lower()
                name = self._csv_text(row, normalized_fieldnames, "name")
                if contact_type not in {"customer", "supplier", "both"}:
                    raise ValueError("type must be customer, supplier, or both")
                if not name:
                    raise ValueError("name is required")
                supplier_type = self._csv_text(row, normalized_fieldnames, "supplier_type").lower()
                if not supplier_type:
                    supplier_type = self._csv_text(row, normalized_fieldnames, "individual_business").lower()
                if not supplier_type:
                    supplier_type = "business"
                if supplier_type not in {"individual", "business"}:
                    raise ValueError("supplier_type must be individual or business")

                contact = ContactFormData(
                    contact_type=contact_type,
                    supplier_type=supplier_type,
                    name=name,
                    business_name=self._csv_text(row, normalized_fieldnames, "business_name"),
                    contact_code=self._csv_text(row, normalized_fieldnames, "contact_code"),
                    tax_number=self._csv_text(row, normalized_fieldnames, "tax_number"),
                    phone=self._csv_text(row, normalized_fieldnames, "phone"),
                    alternate_phone=self._csv_text(row, normalized_fieldnames, "alternate_phone"),
                    email=self._csv_text(row, normalized_fieldnames, "email"),
                    website=self._csv_text(row, normalized_fieldnames, "website"),
                    address=self._csv_text(row, normalized_fieldnames, "address"),
                    city=self._csv_text(row, normalized_fieldnames, "city"),
                    state=self._csv_text(row, normalized_fieldnames, "state"),
                    country=self._csv_text(row, normalized_fieldnames, "country"),
                    postal_code=self._csv_text(row, normalized_fieldnames, "postal_code"),
                    payment_terms=self._csv_text(row, normalized_fieldnames, "payment_terms"),
                    credit_days=self._csv_int(row, normalized_fieldnames, "credit_days"),
                    opening_balance=self._csv_float(row, normalized_fieldnames, "opening_balance"),
                    credit_limit=self._csv_float(row, normalized_fieldnames, "credit_limit"),
                    customer_group_id=None,
                    contact_person_1_name=self._csv_text(row, normalized_fieldnames, "contact_person_1_name"),
                    contact_person_1_designation=self._csv_text(row, normalized_fieldnames, "contact_person_1_designation"),
                    contact_person_1_phone=self._csv_text(row, normalized_fieldnames, "contact_person_1_phone"),
                    contact_person_1_email=self._csv_text(row, normalized_fieldnames, "contact_person_1_email"),
                    contact_person_2_name=self._csv_text(row, normalized_fieldnames, "contact_person_2_name"),
                    contact_person_2_designation=self._csv_text(row, normalized_fieldnames, "contact_person_2_designation"),
                    contact_person_2_phone=self._csv_text(row, normalized_fieldnames, "contact_person_2_phone"),
                    contact_person_2_email=self._csv_text(row, normalized_fieldnames, "contact_person_2_email"),
                    contact_person_3_name=self._csv_text(row, normalized_fieldnames, "contact_person_3_name"),
                    contact_person_3_designation=self._csv_text(row, normalized_fieldnames, "contact_person_3_designation"),
                    contact_person_3_phone=self._csv_text(row, normalized_fieldnames, "contact_person_3_phone"),
                    contact_person_3_email=self._csv_text(row, normalized_fieldnames, "contact_person_3_email"),
                    notes=self._csv_text(row, normalized_fieldnames, "notes"),
                    is_active=self._csv_active(row, normalized_fieldnames),
                )
                self.create_contact(contact)
                imported += 1
            except Exception as exc:
                errors.append(f"Line {index}: {exc}")
        return imported, errors

    def customer_ledger(self, customer_id: int) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT sale_date AS entry_date, invoice_no AS reference, total, paid_amount, due_amount
                    FROM sales
                    WHERE customer_id = ?
                    ORDER BY sale_date DESC, id DESC
                    """,
                    (customer_id,),
                )
            )

    def supplier_ledger(self, supplier_id: int) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT purchase_date AS entry_date, invoice_no AS reference, total, paid_amount, due_amount
                    FROM purchases
                    WHERE supplier_id = ?
                    ORDER BY purchase_date DESC, id DESC
                    """,
                    (supplier_id,),
                )
            )

    def customer_count(self) -> int:
        return self._count("customer")

    def supplier_count(self) -> int:
        return self._count("supplier")

    def supplier_options(self) -> list[LookupItem]:
        rows = self.list_contacts("supplier")
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows if row["is_active"]]

    def customer_options(self) -> list[LookupItem]:
        rows = self.list_contacts("customer")
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows if row["is_active"]]

    @staticmethod
    def _csv_text(row: dict[str, str], fieldnames: dict[str, str], key: str) -> str:
        field = fieldnames.get(key)
        if not field:
            return ""
        return (row.get(field) or "").strip()

    @staticmethod
    def _csv_float(row: dict[str, str], fieldnames: dict[str, str], key: str) -> float:
        field = fieldnames.get(key)
        if not field:
            return 0.0
        value = (row.get(field) or "").strip()
        return float(value) if value else 0.0

    @staticmethod
    def _csv_int(row: dict[str, str], fieldnames: dict[str, str], key: str) -> int:
        field = fieldnames.get(key)
        if not field:
            return 0
        value = (row.get(field) or "").strip()
        return int(value) if value else 0

    @staticmethod
    def _csv_active(row: dict[str, str], fieldnames: dict[str, str]) -> int:
        field = fieldnames.get("is_active")
        if not field:
            return 1
        value = (row.get(field) or "").strip().lower()
        if value in {"", "1", "true", "yes", "active"}:
            return 1
        if value in {"0", "false", "no", "inactive"}:
            return 0
        raise ValueError("is_active must be active/inactive, yes/no, true/false, or 1/0")

    def _count(self, contact_type: str) -> int:
        roles = {
            "customer": ("customer", "both"),
            "supplier": ("supplier", "both"),
            "both": ("both",),
        }[contact_type]
        placeholders = ", ".join("?" for _ in roles)
        with get_connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM contacts WHERE contact_type IN ({placeholders})",
                roles,
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _validate_type(contact_type: str) -> None:
        if contact_type not in {"customer", "supplier", "both"}:
            raise ValueError("Contact type must be customer, supplier, or both.")

    @staticmethod
    def _validate_contact(contact: ContactFormData) -> None:
        if not contact.name.strip():
            raise ValueError("Contact name is required.")
        if contact.opening_balance < 0:
            raise ValueError("Opening balance cannot be negative.")
        if contact.credit_limit < 0:
            raise ValueError("Credit limit cannot be negative.")
        if contact.credit_days < 0:
            raise ValueError("Credit days cannot be negative.")
        if contact.supplier_type not in {"individual", "business"}:
            raise ValueError("Contact type must be individual or business.")

    @staticmethod
    def _contact_params(contact: ContactFormData) -> tuple:
        return (
            contact.contact_type,
            contact.supplier_type,
            contact.name.strip(),
            contact.business_name.strip(),
            contact.contact_code.strip(),
            contact.tax_number.strip(),
            contact.phone.strip(),
            contact.alternate_phone.strip(),
            contact.email.strip(),
            contact.website.strip(),
            contact.address.strip(),
            contact.city.strip(),
            contact.state.strip(),
            contact.country.strip(),
            contact.postal_code.strip(),
            contact.payment_terms.strip(),
            contact.credit_days,
            contact.opening_balance,
            contact.credit_limit,
            contact.customer_group_id,
            contact.contact_person_1_name.strip(),
            contact.contact_person_1_designation.strip(),
            contact.contact_person_1_phone.strip(),
            contact.contact_person_1_email.strip(),
            contact.contact_person_2_name.strip(),
            contact.contact_person_2_designation.strip(),
            contact.contact_person_2_phone.strip(),
            contact.contact_person_2_email.strip(),
            contact.contact_person_3_name.strip(),
            contact.contact_person_3_designation.strip(),
            contact.contact_person_3_phone.strip(),
            contact.contact_person_3_email.strip(),
            contact.notes.strip(),
            contact.is_active,
        )
