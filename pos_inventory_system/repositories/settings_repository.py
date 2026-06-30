from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class BusinessSettingsData:
    business_name: str
    currency_symbol: str
    tax_number: str
    phone: str
    email: str
    address: str


@dataclass(frozen=True)
class LocationData:
    name: str
    phone: str
    address: str
    is_active: int


@dataclass(frozen=True)
class InvoiceSettingsData:
    invoice_prefix: str
    next_invoice_number: int
    receipt_footer: str
    terms: str
    show_tax: int
    show_logo: int


@dataclass(frozen=True)
class BarcodeSettingsData:
    barcode_prefix: str
    next_barcode_number: int
    label_width: float
    label_height: float
    copies_per_product: int
    show_price: int
    show_product_name: int


@dataclass(frozen=True)
class TaxRateData:
    name: str
    rate: float


@dataclass(frozen=True)
class PaymentMethodData:
    name: str
    method_key: str
    is_active: int


@dataclass(frozen=True)
class PrinterSettingsData:
    name: str
    printer_type: str
    connection_type: str
    paper_width: str
    device_name: str
    is_default: int
    is_active: int


class SettingsRepository:
    def get_business_settings(self) -> sqlite3.Row:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    business_name,
                    currency_symbol,
                    tax_number,
                    phone,
                    email,
                    address
                FROM business_settings
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("Business settings are not initialized.")
        return row

    def update_business_settings(self, settings: BusinessSettingsData) -> None:
        if not settings.business_name.strip():
            raise ValueError("Business name is required.")
        if not settings.currency_symbol.strip():
            raise ValueError("Currency symbol is required.")
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE business_settings
                SET
                    business_name = ?,
                    currency_symbol = ?,
                    tax_number = ?,
                    phone = ?,
                    email = ?,
                    address = ?
                WHERE id = 1
                """,
                (
                    settings.business_name,
                    settings.currency_symbol,
                    settings.tax_number,
                    settings.phone,
                    settings.email,
                    settings.address,
                ),
            )

    def list_locations(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, name, phone, address, is_active, created_at
                    FROM locations
                    ORDER BY id
                    """
                )
            )

    def create_location(self, location: LocationData) -> int:
        if not location.name.strip():
            raise ValueError("Location name is required.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM locations WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (location.name.strip(),),
            ).fetchone()
            if exists is not None:
                raise ValueError("A location with this name already exists.")
            cursor = connection.execute(
                """
                INSERT INTO locations (name, phone, address, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (location.name.strip(), location.phone, location.address, location.is_active),
            )
            return int(cursor.lastrowid)

    def get_invoice_settings(self) -> sqlite3.Row:
        with get_connection() as connection:
            row = connection.execute("SELECT * FROM invoice_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Invoice settings are not initialized.")
        return row

    def update_invoice_settings(self, settings: InvoiceSettingsData) -> None:
        if not settings.invoice_prefix.strip():
            raise ValueError("Invoice prefix is required.")
        if settings.next_invoice_number <= 0:
            raise ValueError("Next invoice number must be greater than zero.")
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE invoice_settings
                SET invoice_prefix = ?, next_invoice_number = ?, receipt_footer = ?, terms = ?,
                    show_tax = ?, show_logo = ?
                WHERE id = 1
                """,
                (
                    settings.invoice_prefix.strip().upper(),
                    settings.next_invoice_number,
                    settings.receipt_footer,
                    settings.terms,
                    settings.show_tax,
                    settings.show_logo,
                ),
            )

    def get_barcode_settings(self) -> sqlite3.Row:
        with get_connection() as connection:
            row = connection.execute("SELECT * FROM barcode_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Barcode settings are not initialized.")
        return row

    def update_barcode_settings(self, settings: BarcodeSettingsData) -> None:
        prefix = "".join(character for character in settings.barcode_prefix.upper() if character.isalnum())
        if not prefix:
            raise ValueError("Barcode prefix must contain letters or numbers.")
        if settings.next_barcode_number <= 0:
            raise ValueError("Next barcode number must be greater than zero.")
        if settings.label_width <= 0 or settings.label_height <= 0:
            raise ValueError("Label width and height must be greater than zero.")
        if settings.copies_per_product <= 0:
            raise ValueError("Copies per product must be greater than zero.")
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE barcode_settings
                SET barcode_prefix = ?, next_barcode_number = ?, label_width = ?, label_height = ?, copies_per_product = ?,
                    show_price = ?, show_product_name = ?
                WHERE id = 1
                """,
                (
                    prefix,
                    settings.next_barcode_number,
                    settings.label_width,
                    settings.label_height,
                    settings.copies_per_product,
                    settings.show_price,
                    settings.show_product_name,
                ),
            )

    def generate_product_barcode(self) -> str:
        connection = get_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            settings = connection.execute(
                "SELECT barcode_prefix, next_barcode_number FROM barcode_settings WHERE id = 1"
            ).fetchone()
            if settings is None:
                raise RuntimeError("Barcode settings are not initialized.")
            prefix = "".join(
                character for character in str(settings["barcode_prefix"]).upper() if character.isalnum()
            ) or "PRD"
            sequence = max(int(settings["next_barcode_number"] or 1), 1)
            while True:
                barcode = f"{prefix}-{sequence:06d}"
                product_exists = connection.execute(
                    "SELECT 1 FROM products WHERE barcode = ? LIMIT 1", (barcode,)
                ).fetchone()
                variant_exists = connection.execute(
                    "SELECT 1 FROM product_variants WHERE barcode = ? LIMIT 1", (barcode,)
                ).fetchone()
                if product_exists is None and variant_exists is None:
                    break
                sequence += 1
            connection.execute(
                "UPDATE barcode_settings SET next_barcode_number = ? WHERE id = 1",
                (sequence + 1,),
            )
            connection.commit()
            return barcode
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_tax_rates(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(connection.execute("SELECT id, name, rate FROM tax_rates ORDER BY name"))

    def create_tax_rate(self, tax_rate: TaxRateData) -> int:
        if not tax_rate.name.strip():
            raise ValueError("Tax name is required.")
        if tax_rate.rate < 0 or tax_rate.rate > 100:
            raise ValueError("Tax rate must be between 0 and 100.")
        with get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO tax_rates (name, rate) VALUES (?, ?)",
                (tax_rate.name.strip(), tax_rate.rate),
            )
            return int(cursor.lastrowid)

    def list_payment_methods(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    "SELECT id, name, method_key, is_active, created_at FROM payment_methods ORDER BY is_active DESC, name"
                )
            )

    def create_payment_method(self, method: PaymentMethodData) -> int:
        name = method.name.strip()
        key = "_".join(method.method_key.strip().lower().replace("-", "_").split())
        if not name:
            raise ValueError("Payment method name is required.")
        if not key or not key.replace("_", "").isalnum():
            raise ValueError("Payment method key can use letters, numbers, and underscores only.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM payment_methods WHERE LOWER(method_key) = LOWER(?) LIMIT 1",
                (key,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A payment method with this key already exists.")
            cursor = connection.execute(
                """
                INSERT INTO payment_methods (name, method_key, is_active)
                VALUES (?, ?, ?)
                """,
                (name, key, method.is_active),
            )
            return int(cursor.lastrowid)

    def list_printers(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, name, printer_type, connection_type, paper_width, device_name,
                           is_default, is_active, created_at
                    FROM printer_settings
                    ORDER BY is_default DESC, is_active DESC, name
                    """
                )
            )

    def create_printer(self, printer: PrinterSettingsData) -> int:
        if not printer.name.strip():
            raise ValueError("Printer name is required.")
        if printer.printer_type not in {"receipt", "invoice", "barcode"}:
            raise ValueError("Select a valid printer type.")
        if printer.connection_type not in {"windows", "usb", "network"}:
            raise ValueError("Select a valid printer connection.")
        if printer.paper_width not in {"80mm", "58mm", "A4", "Label"}:
            raise ValueError("Select a valid paper width.")
        connection = get_connection()
        try:
            exists = connection.execute(
                "SELECT 1 FROM printer_settings WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (printer.name.strip(),),
            ).fetchone()
            if exists is not None:
                raise ValueError("A printer with this name already exists.")
            if printer.is_default:
                connection.execute(
                    "UPDATE printer_settings SET is_default = 0 WHERE printer_type = ?",
                    (printer.printer_type,),
                )
            cursor = connection.execute(
                """
                INSERT INTO printer_settings (
                    name, printer_type, connection_type, paper_width, device_name, is_default, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    printer.name.strip(),
                    printer.printer_type,
                    printer.connection_type,
                    printer.paper_width,
                    printer.device_name,
                    printer.is_default,
                    printer.is_active,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def system_health(self) -> dict[str, int | str]:
        with get_connection() as connection:
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            counts = {
                "products": int(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]),
                "sales": int(connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0]),
                "purchases": int(connection.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]),
                "users": int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            }
        return {
            "database_size_bytes": page_count * page_size,
            "integrity": integrity,
            **counts,
        }
