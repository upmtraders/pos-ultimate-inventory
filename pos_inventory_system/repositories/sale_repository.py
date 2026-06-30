from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class SaleFormData:
    customer_id: int | None
    location_id: int
    invoice_no: str
    sale_date: str
    product_id: int
    quantity: float
    unit_price: float
    discount: float
    tax: float
    paid_amount: float
    payment_method: str


@dataclass(frozen=True)
class SaleItemData:
    product_id: int
    quantity: float
    unit_price: float
    discount: float = 0
    tax: float = 0


@dataclass(frozen=True)
class SalePaymentData:
    method: str
    amount: float
    payment_date: str = ""
    note: str = ""


@dataclass(frozen=True)
class SaleCheckoutData:
    customer_id: int | None
    location_id: int
    invoice_no: str
    sale_date: str
    items: list[SaleItemData]
    discount: float
    tax: float
    paid_amount: float
    payment_method: str
    sale_status: str = "final"
    payments: list[SalePaymentData] | None = None


class SaleRepository:
    NON_FINAL_STATUSES = {"draft", "quotation", "suspended", "sales_order"}

    def _unique_invoice_no(self, connection: sqlite3.Connection, invoice_no: str, exclude_sale_id: int | None = None) -> str:
        base_invoice = (invoice_no or "").strip() or f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        candidate = base_invoice
        suffix = 2
        while True:
            if exclude_sale_id is None:
                row = connection.execute("SELECT id FROM sales WHERE invoice_no = ? LIMIT 1", (candidate,)).fetchone()
            else:
                row = connection.execute(
                    "SELECT id FROM sales WHERE invoice_no = ? AND id <> ? LIMIT 1",
                    (candidate, exclude_sale_id),
                ).fetchone()
            if row is None:
                return candidate
            candidate = f"{base_invoice}-{suffix}"
            suffix += 1

    def list_sales(self) -> list[sqlite3.Row]:
        return self.list_sales_by_status("final")

    def sales_history(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[object] = []
        exact_fields = {
            "customer_id": "sales.customer_id",
            "location_id": "sales.location_id",
            "sale_status": "sales.sale_status",
            "payment_status": "sales.payment_status",
        }
        for key, column in exact_fields.items():
            value = filters.get(key, "")
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if filters.get("date_from"):
            clauses.append("sales.sale_date >= ?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append("sales.sale_date <= ?")
            params.append(filters["date_to"])
        if filters.get("payment_method"):
            clauses.append(
                "EXISTS (SELECT 1 FROM payments WHERE payments.reference_type = 'sale' AND payments.reference_id = sales.id AND payments.method = ?)"
            )
            params.append(filters["payment_method"])
        product_filters = {
            "product_id": "sale_items_filter.product_id",
            "category_id": "products_filter.category_id",
            "brand_id": "products_filter.brand_id",
        }
        for key, column in product_filters.items():
            value = filters.get(key, "")
            if value:
                clauses.append(
                    f"""
                    EXISTS (
                        SELECT 1 FROM sale_items AS sale_items_filter
                        JOIN products AS products_filter ON products_filter.id = sale_items_filter.product_id
                        WHERE sale_items_filter.sale_id = sales.id AND {column} = ?
                    )
                    """
                )
                params.append(value)
        if filters.get("search"):
            clauses.append(
                """
                (
                    sales.invoice_no LIKE ? OR contacts.name LIKE ? OR contacts.phone LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM sale_items AS search_items
                        JOIN products AS search_products ON search_products.id = search_items.product_id
                        WHERE search_items.sale_id = sales.id
                          AND (search_products.name LIKE ? OR search_products.sku LIKE ? OR search_products.barcode LIKE ?)
                    )
                )
                """
            )
            search = f"%{filters['search']}%"
            params.extend([search, search, search, search, search, search])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        sales.id, sales.invoice_no, sales.sale_date, sales.created_at,
                        sales.subtotal, sales.discount, sales.tax, sales.total,
                        sales.paid_amount, sales.due_amount, sales.payment_status, sales.sale_status,
                        COALESCE(contacts.name, 'Walk-in Customer') AS customer_name,
                        COALESCE(contacts.phone, '') AS customer_phone,
                        COALESCE(locations.name, 'No Location') AS location_name,
                        COALESCE((SELECT COUNT(*) FROM sale_items WHERE sale_items.sale_id = sales.id), 0) AS item_count,
                        COALESCE((SELECT SUM(quantity) FROM sale_items WHERE sale_items.sale_id = sales.id), 0) AS total_quantity,
                        COALESCE((
                            SELECT GROUP_CONCAT(products.name, ', ')
                            FROM sale_items JOIN products ON products.id = sale_items.product_id
                            WHERE sale_items.sale_id = sales.id
                        ), '') AS product_names,
                        COALESCE((
                            SELECT SUM(sale_items.quantity * products.purchase_price)
                            FROM sale_items JOIN products ON products.id = sale_items.product_id
                            WHERE sale_items.sale_id = sales.id
                        ), 0) AS cost_of_goods,
                        COALESCE((
                            SELECT SUM(sales_returns.refund_amount)
                            FROM sales_returns WHERE sales_returns.sale_id = sales.id
                        ), 0) AS return_amount,
                        COALESCE((
                            SELECT GROUP_CONCAT(DISTINCT payments.method)
                            FROM payments
                            WHERE payments.reference_type = 'sale' AND payments.reference_id = sales.id
                        ), '') AS payment_methods
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    LEFT JOIN locations ON locations.id = sales.location_id
                    {where}
                    ORDER BY sales.sale_date DESC, sales.id DESC
                    """,
                    params,
                )
            )

    def list_sales_by_status(self, sale_status: str) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        sales.id,
                        sales.invoice_no,
                        sales.sale_date,
                        sales.subtotal,
                        sales.discount,
                        sales.tax,
                        sales.total,
                        sales.paid_amount,
                        sales.due_amount,
                        sales.payment_status,
                        sales.sale_status,
                        contacts.name AS customer_name
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    WHERE sales.sale_status = ?
                    ORDER BY sales.sale_date DESC, sales.id DESC
                    """,
                    (sale_status,),
                )
            )

    def get_sale_invoice(self, sale_id: int) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
        with get_connection() as connection:
            sale = connection.execute(
                """
                SELECT
                    sales.id,
                    sales.invoice_no,
                    sales.sale_date,
                    sales.subtotal,
                    sales.discount,
                    sales.tax,
                    sales.total,
                    sales.paid_amount,
                    sales.due_amount,
                    sales.payment_status,
                    sales.sale_status,
                    sales.customer_id,
                    sales.location_id,
                    contacts.name AS customer_name,
                    contacts.phone AS customer_phone,
                    contacts.email AS customer_email,
                    contacts.address AS customer_address
                FROM sales
                LEFT JOIN contacts ON contacts.id = sales.customer_id
                WHERE sales.id = ?
                """,
                (sale_id,),
            ).fetchone()
            items = list(
                connection.execute(
                    """
                    SELECT
                        sale_items.quantity,
                        sale_items.unit_price,
                        sale_items.discount,
                        sale_items.tax,
                        sale_items.line_total,
                        sale_items.product_id,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        products.barcode AS product_barcode
                    FROM sale_items
                    JOIN products ON products.id = sale_items.product_id
                    WHERE sale_items.sale_id = ?
                    ORDER BY sale_items.id
                    """,
                    (sale_id,),
                )
            )
        return sale, items

    def convert_document_to_final(self, sale_id: int, sale: SaleCheckoutData) -> int:
        existing, _ = self.get_sale_invoice(sale_id)
        if existing is None:
            raise ValueError("Sale document not found.")
        if existing["sale_status"] not in self.NON_FINAL_STATUSES:
            raise ValueError("Only draft, quotation, or suspended documents can be converted.")
        if sale.sale_status != "final":
            raise ValueError("Converted sale must be final.")
        if not sale.items:
            raise ValueError("Add at least one product to the cart.")
        if sale.discount < 0 or sale.tax < 0:
            raise ValueError("Discount and tax cannot be negative.")

        requested_by_product: dict[int, float] = {}
        subtotal = 0.0
        item_rows = []
        for item in sale.items:
            if item.product_id <= 0:
                raise ValueError("Product is required.")
            if item.quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            if item.unit_price < 0:
                raise ValueError("Unit price cannot be negative.")
            requested_by_product[item.product_id] = requested_by_product.get(item.product_id, 0.0) + item.quantity
            line_subtotal = item.quantity * item.unit_price
            line_total = max(line_subtotal - item.discount + item.tax, 0)
            subtotal += line_subtotal
            item_rows.append((item, line_total))

        for product_id, quantity in requested_by_product.items():
            available_stock = self.available_stock(product_id)
            if quantity > available_stock:
                raise ValueError(f"Not enough stock for product #{product_id}. Available stock is {available_stock:.2f}.")

        total = max(sum(line_total for _, line_total in item_rows) - sale.discount + sale.tax, 0)
        sale_payments = self._normalise_payments(sale, total)
        paid_amount = min(sum(payment.amount for payment in sale_payments), total)
        due_amount = total - paid_amount
        if due_amount > 0 and sale.customer_id is None:
            raise ValueError("Select a customer before converting to a due sale.")
        payment_status = self._payment_status(total, paid_amount)

        connection = get_connection()
        try:
            invoice_no = self._unique_invoice_no(connection, sale.invoice_no, exclude_sale_id=sale_id)
            connection.execute("DELETE FROM sale_items WHERE sale_id = ?", (sale_id,))
            connection.execute("DELETE FROM payments WHERE reference_type = 'sale' AND reference_id = ?", (sale_id,))
            connection.execute("DELETE FROM stock_movements WHERE reference_type = 'sale' AND reference_id = ?", (sale_id,))
            connection.execute(
                """
                UPDATE sales
                SET customer_id = ?, location_id = ?, invoice_no = ?, sale_date = ?,
                    subtotal = ?, discount = ?, tax = ?, total = ?,
                    paid_amount = ?, due_amount = ?, payment_status = ?, sale_status = 'final'
                WHERE id = ?
                """,
                (
                    sale.customer_id,
                    sale.location_id,
                    invoice_no,
                    sale.sale_date,
                    subtotal,
                    sale.discount,
                    sale.tax,
                    total,
                    paid_amount,
                    due_amount,
                    payment_status,
                    sale_id,
                ),
            )
            for item, line_total in item_rows:
                connection.execute(
                    """
                    INSERT INTO sale_items (
                        sale_id, product_id, quantity, unit_price, discount, tax, line_total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sale_id, item.product_id, item.quantity, item.unit_price, item.discount, item.tax, line_total),
                )
            for payment in sale_payments:
                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_type, reference_type, reference_id, account_id, amount, method, payment_date, note
                    )
                    VALUES ('in', 'sale', ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        payment.amount,
                        payment.method,
                        payment.payment_date or sale.sale_date,
                        payment.note or f"Payment for sale {invoice_no}",
                    ),
                )
            for product_id, quantity in requested_by_product.items():
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                    )
                    VALUES (?, ?, 'sale', 'sale', ?, 0, ?)
                    """,
                    (product_id, sale.location_id, sale_id, quantity),
                )
            connection.commit()
            return sale_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_sale(self, sale: SaleFormData) -> int:
        return self.create_checkout_sale(
            SaleCheckoutData(
                customer_id=sale.customer_id,
                location_id=sale.location_id,
                invoice_no=sale.invoice_no,
                sale_date=sale.sale_date,
                items=[
                    SaleItemData(
                        product_id=sale.product_id,
                        quantity=sale.quantity,
                        unit_price=sale.unit_price,
                        discount=sale.discount,
                        tax=sale.tax,
                    )
                ],
                discount=0,
                tax=0,
                paid_amount=sale.paid_amount,
                payment_method=sale.payment_method,
            )
        )

    def create_checkout_sale(self, sale: SaleCheckoutData) -> int:
        if sale.sale_status != "final" and sale.sale_status not in self.NON_FINAL_STATUSES:
            raise ValueError("Unsupported sale status.")
        if not sale.items:
            raise ValueError("Add at least one product to the cart.")
        if sale.discount < 0:
            raise ValueError("Discount cannot be negative.")
        if sale.tax < 0:
            raise ValueError("Tax cannot be negative.")

        requested_by_product: dict[int, float] = {}
        subtotal = 0.0
        item_rows = []
        for item in sale.items:
            if item.product_id <= 0:
                raise ValueError("Product is required.")
            if item.quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            if item.unit_price < 0:
                raise ValueError("Unit price cannot be negative.")
            if item.discount < 0:
                raise ValueError("Line discount cannot be negative.")
            if item.tax < 0:
                raise ValueError("Line tax cannot be negative.")

            requested_by_product[item.product_id] = requested_by_product.get(item.product_id, 0.0) + item.quantity
            line_subtotal = item.quantity * item.unit_price
            line_total = max(line_subtotal - item.discount + item.tax, 0)
            subtotal += line_subtotal
            item_rows.append((item, line_total))

        if sale.sale_status == "final":
            for product_id, quantity in requested_by_product.items():
                available_stock = self.available_stock(product_id)
                if quantity > available_stock:
                    raise ValueError(f"Not enough stock for product #{product_id}. Available stock is {available_stock:.2f}.")

        total = max(sum(line_total for _, line_total in item_rows) - sale.discount + sale.tax, 0)
        sale_payments = self._normalise_payments(sale, total)
        paid_amount = min(sum(payment.amount for payment in sale_payments), total) if sale.sale_status == "final" else 0
        due_amount = total - paid_amount
        if sale.sale_status == "final" and due_amount > 0 and sale.customer_id is None:
            raise ValueError("Select a customer before saving a credit or due sale.")
        payment_status = self._payment_status(total, paid_amount)

        connection = get_connection()
        try:
            invoice_no = self._unique_invoice_no(connection, sale.invoice_no)
            cursor = connection.execute(
                """
                INSERT INTO sales (
                    customer_id,
                    location_id,
                    invoice_no,
                    sale_date,
                    subtotal,
                    discount,
                    tax,
                    total,
                    paid_amount,
                    due_amount,
                    payment_status,
                    sale_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.customer_id,
                    sale.location_id,
                    invoice_no,
                    sale.sale_date,
                    subtotal,
                    sale.discount,
                    sale.tax,
                    total,
                    paid_amount,
                    due_amount,
                    payment_status,
                    sale.sale_status,
                ),
            )
            sale_id = int(cursor.lastrowid)

            for item, line_total in item_rows:
                connection.execute(
                    """
                    INSERT INTO sale_items (
                        sale_id,
                        product_id,
                        quantity,
                        unit_price,
                        discount,
                        tax,
                        line_total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        item.product_id,
                        item.quantity,
                        item.unit_price,
                        item.discount,
                        item.tax,
                        line_total,
                    ),
                )

            if sale.sale_status == "final":
                for payment in sale_payments:
                    if payment.amount <= 0:
                        continue
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
                        VALUES ('in', 'sale', ?, 1, ?, ?, ?, ?)
                        """,
                        (
                            sale_id,
                            payment.amount,
                            payment.method,
                            payment.payment_date or sale.sale_date,
                            payment.note or f"Payment for sale {invoice_no}",
                        ),
                    )
            if sale.sale_status == "final":
                for product_id, quantity in requested_by_product.items():
                    connection.execute(
                        """
                        INSERT INTO stock_movements (
                            product_id,
                            location_id,
                            movement_type,
                            reference_type,
                            reference_id,
                            quantity_in,
                            quantity_out
                        )
                        VALUES (?, ?, 'sale', 'sale', ?, 0, ?)
                        """,
                        (product_id, sale.location_id, sale_id, quantity),
                    )

            connection.commit()
            return sale_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_non_final_sale(self, sale: SaleFormData, sale_status: str) -> int:
        if sale_status not in self.NON_FINAL_STATUSES:
            raise ValueError("Unsupported sale document status.")
        if sale.quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if sale.unit_price < 0:
            raise ValueError("Unit price cannot be negative.")

        subtotal = sale.quantity * sale.unit_price
        total = max(subtotal - sale.discount + sale.tax, 0)
        line_total = subtotal - sale.discount + sale.tax

        connection = get_connection()
        try:
            invoice_no = self._unique_invoice_no(connection, sale.invoice_no)
            cursor = connection.execute(
                """
                INSERT INTO sales (
                    customer_id,
                    location_id,
                    invoice_no,
                    sale_date,
                    subtotal,
                    discount,
                    tax,
                    total,
                    paid_amount,
                    due_amount,
                    payment_status,
                    sale_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'due', ?)
                """,
                (
                    sale.customer_id,
                    sale.location_id,
                    invoice_no,
                    sale.sale_date,
                    subtotal,
                    sale.discount,
                    sale.tax,
                    total,
                    total,
                    sale_status,
                ),
            )
            sale_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO sale_items (
                    sale_id,
                    product_id,
                    quantity,
                    unit_price,
                    discount,
                    tax,
                    line_total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale_id,
                    sale.product_id,
                    sale.quantity,
                    sale.unit_price,
                    sale.discount,
                    sale.tax,
                    line_total,
                ),
            )
            connection.commit()
            return sale_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def available_stock(self, product_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity_in - quantity_out), 0) AS available_stock
                FROM stock_movements
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
        return float(row["available_stock"])

    def sale_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM sales").fetchone()
        return int(row["count"])

    @staticmethod
    def _normalise_payments(sale: SaleCheckoutData, total: float) -> list[SalePaymentData]:
        if sale.sale_status != "final":
            return []
        if sale.payments:
            payments = [payment for payment in sale.payments if payment.amount > 0]
        elif sale.paid_amount > 0:
            payments = [
                SalePaymentData(
                    method=sale.payment_method or "cash",
                    amount=sale.paid_amount,
                    payment_date=sale.sale_date,
                    note=f"Payment for sale {sale.invoice_no}",
                )
            ]
        else:
            payments = []
        paid_total = sum(payment.amount for payment in payments)
        if paid_total > total:
            raise ValueError("Payment total cannot be greater than sale total.")
        for payment in payments:
            if payment.amount < 0:
                raise ValueError("Payment amount cannot be negative.")
            if not payment.method.strip():
                raise ValueError("Payment method is required.")
        return payments

    @staticmethod
    def _payment_status(total: float, paid_amount: float) -> str:
        if paid_amount <= 0:
            return "due"
        if paid_amount >= total:
            return "paid"
        return "partial"
