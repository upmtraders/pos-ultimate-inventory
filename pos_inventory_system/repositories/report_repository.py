from __future__ import annotations

import sqlite3

from pos_inventory_system.database.connection import get_connection


class ReportRepository:
    def sales_report(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        clauses = ["sales.sale_status = 'final'"]
        params: list[object] = []
        self._date_clauses(clauses, params, "sales.sale_date", filters)
        self._exact_clause(clauses, params, "sales.location_id", filters.get("location_id"))
        self._exact_clause(clauses, params, "sales.payment_status", filters.get("payment_status"))
        if filters.get("search"):
            clauses.append("(sales.invoice_no LIKE ? OR contacts.name LIKE ?)")
            search = f"%{filters['search']}%"
            params.extend([search, search])
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        sales.id,
                        sales.invoice_no,
                        sales.sale_date,
                        COALESCE(contacts.name, 'Walk-in Customer') AS customer_name,
                        COALESCE(locations.name, 'No Location') AS location_name,
                        sales.subtotal,
                        sales.discount,
                        sales.tax,
                        sales.total,
                        sales.paid_amount,
                        sales.due_amount,
                        sales.payment_status,
                        sales.sale_status,
                        COALESCE((
                            SELECT SUM(sale_items.quantity * products.purchase_price)
                            FROM sale_items
                            JOIN products ON products.id = sale_items.product_id
                            WHERE sale_items.sale_id = sales.id
                        ), 0) AS cost_of_goods,
                        COALESCE((
                            SELECT SUM(sales_returns.refund_amount)
                            FROM sales_returns
                            WHERE sales_returns.sale_id = sales.id
                        ), 0) AS return_amount
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    LEFT JOIN locations ON locations.id = sales.location_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY sales.sale_date DESC, sales.id DESC
                    """,
                    params,
                )
            )

    def stock_report(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        movement_conditions = ["stock_movements.product_id = products.id"]
        params: list[object] = []
        if filters.get("location_id"):
            movement_conditions.append("stock_movements.location_id = ?")
            params.append(filters["location_id"])
        if filters.get("date_from"):
            movement_conditions.append("DATE(stock_movements.created_at) >= ?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            movement_conditions.append("DATE(stock_movements.created_at) <= ?")
            params.append(filters["date_to"])
        product_clauses = ["products.is_active = 1"]
        if filters.get("category_id"):
            product_clauses.append("products.category_id = ?")
            params.append(filters["category_id"])
        if filters.get("brand_id"):
            product_clauses.append("products.brand_id = ?")
            params.append(filters["brand_id"])
        if filters.get("search"):
            product_clauses.append("(products.name LIKE ? OR products.sku LIKE ? OR products.barcode LIKE ?)")
            search = f"%{filters['search']}%"
            params.extend([search, search, search])
        movement_where = " AND ".join(movement_conditions)
        with get_connection() as connection:
            rows = list(
                connection.execute(
                    f"""
                    SELECT
                        products.id, products.name, products.sku, products.barcode,
                        products.alert_quantity, products.purchase_price, products.selling_price,
                        COALESCE(product_categories.name, '') AS category_name,
                        COALESCE(product_brands.name, '') AS brand_name,
                        COALESCE(product_units.short_name, '') AS unit_name,
                        COALESCE((SELECT SUM(quantity_in) FROM stock_movements WHERE {movement_where}), 0) AS quantity_in,
                        COALESCE((SELECT SUM(quantity_out) FROM stock_movements WHERE {movement_where}), 0) AS quantity_out,
                        COALESCE((SELECT SUM(quantity_in - quantity_out) FROM stock_movements WHERE {movement_where}), 0) AS available_stock
                    FROM products
                    LEFT JOIN product_categories ON product_categories.id = products.category_id
                    LEFT JOIN product_brands ON product_brands.id = products.brand_id
                    LEFT JOIN product_units ON product_units.id = products.unit_id
                    WHERE {' AND '.join(product_clauses)}
                    ORDER BY products.name
                    """,
                    params[: len(movement_conditions) - 1]
                    + params[: len(movement_conditions) - 1]
                    + params[: len(movement_conditions) - 1]
                    + params[len(movement_conditions) - 1 :],
                )
            )
        if filters.get("stock_status") == "low":
            return [row for row in rows if float(row["available_stock"]) <= float(row["alert_quantity"])]
        if filters.get("stock_status") == "out":
            return [row for row in rows if float(row["available_stock"]) <= 0]
        return rows

    def purchase_report(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        clauses = ["1 = 1"]
        params: list[object] = []
        self._date_clauses(clauses, params, "purchases.purchase_date", filters)
        self._exact_clause(clauses, params, "purchases.location_id", filters.get("location_id"))
        self._exact_clause(clauses, params, "purchases.supplier_id", filters.get("supplier_id"))
        self._exact_clause(clauses, params, "purchase_items.product_id", filters.get("product_id"))
        self._exact_clause(clauses, params, "purchases.payment_status", filters.get("payment_status"))
        if filters.get("cheque_status"):
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM purchase_payments cheque_filter
                    WHERE cheque_filter.purchase_id = purchases.id
                        AND cheque_filter.payment_type = 'cheque'
                        AND cheque_filter.status = ?
                )
                """
            )
            params.append(filters["cheque_status"])
        if filters.get("search"):
            clauses.append(
                """
                (
                    purchases.invoice_no LIKE ?
                    OR contacts.name LIKE ?
                    OR products.name LIKE ?
                    OR products.sku LIKE ?
                    OR products.barcode LIKE ?
                )
                """
            )
            search = f"%{filters['search']}%"
            params.extend([search, search, search, search, search])
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        purchases.id AS purchase_id,
                        purchases.invoice_no,
                        purchases.purchase_date,
                        COALESCE(contacts.name, 'No Supplier') AS supplier_name,
                        COALESCE(locations.name, 'Main Shop') AS location_name,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        products.barcode AS product_barcode,
                        COALESCE(product_units.short_name, '') AS unit_name,
                        purchase_items.quantity,
                        purchase_items.purchase_price,
                        purchase_items.line_total,
                        purchases.subtotal,
                        purchases.discount,
                        purchases.tax,
                        purchases.total,
                        purchases.paid_amount,
                        purchases.due_amount,
                        purchases.payment_status,
                        COALESCE(payment_summary.payment_methods, '') AS payment_methods,
                        COALESCE(payment_summary.cleared_amount, 0) AS cleared_amount,
                        COALESCE(payment_summary.pending_cheque_amount, 0) AS pending_cheque_amount,
                        COALESCE(payment_summary.cheque_numbers, '') AS cheque_numbers,
                        COALESCE(payment_summary.cheque_statuses, '') AS cheque_statuses
                    FROM purchases
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    LEFT JOIN locations ON locations.id = purchases.location_id
                    LEFT JOIN purchase_items ON purchase_items.purchase_id = purchases.id
                    LEFT JOIN products ON products.id = purchase_items.product_id
                    LEFT JOIN product_units ON product_units.id = products.unit_id
                    LEFT JOIN (
                        SELECT
                            purchase_id,
                            GROUP_CONCAT(DISTINCT payment_type) AS payment_methods,
                            SUM(CASE WHEN status = 'cleared' THEN amount ELSE 0 END) AS cleared_amount,
                            SUM(CASE WHEN payment_type = 'cheque' AND status = 'pending' THEN amount ELSE 0 END) AS pending_cheque_amount,
                            GROUP_CONCAT(DISTINCT CASE WHEN payment_type = 'cheque' THEN cheque_no END) AS cheque_numbers,
                            GROUP_CONCAT(DISTINCT CASE WHEN payment_type = 'cheque' THEN status END) AS cheque_statuses
                        FROM purchase_payments
                        GROUP BY purchase_id
                    ) payment_summary ON payment_summary.purchase_id = purchases.id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY purchases.purchase_date DESC, purchases.id DESC
                    """,
                    params,
                )
            )

    def profit_loss_summary(self, filters: dict[str, str] | None = None) -> dict[str, float]:
        filters = filters or {}
        sale_where, sale_params = self._where_for_date_location(
            "sale_date", "location_id", filters, ["sale_status = 'final'"]
        )
        expense_where, expense_params = self._where_for_date_location(
            "expense_date", "location_id", filters,
            ["expense_type = 'expense'", "status IN ('approved', 'paid')"],
        )
        cash_in_where, cash_in_params = self._where_for_date_location(
            "expense_date", "location_id", filters,
            ["expense_type = 'in'", "status IN ('approved', 'paid')"],
        )
        cash_out_where, cash_out_params = self._where_for_date_location(
            "expense_date", "location_id", filters,
            ["expense_type = 'out'", "status IN ('approved', 'paid')"],
        )
        with get_connection() as connection:
            gross_sales = self._amount(connection, f"SELECT COALESCE(SUM(total), 0) FROM sales {sale_where}", sale_params)
            discounts = self._amount(connection, f"SELECT COALESCE(SUM(discount), 0) FROM sales {sale_where}", sale_params)
            sales_tax = self._amount(connection, f"SELECT COALESCE(SUM(tax), 0) FROM sales {sale_where}", sale_params)
            returns = self._amount(
                connection,
                f"""
                SELECT COALESCE(SUM(sales_returns.refund_amount), 0)
                FROM sales_returns
                JOIN sales ON sales.id = sales_returns.sale_id
                {sale_where.replace('sale_date', 'sales.sale_date').replace('location_id', 'sales.location_id').replace('sale_status', 'sales.sale_status')}
                """,
                sale_params,
            )
            cogs = self._amount(
                connection,
                f"""
                SELECT COALESCE(SUM(sale_items.quantity * products.purchase_price), 0)
                FROM sale_items
                JOIN sales ON sales.id = sale_items.sale_id
                JOIN products ON products.id = sale_items.product_id
                {sale_where.replace('sale_date', 'sales.sale_date').replace('location_id', 'sales.location_id').replace('sale_status', 'sales.sale_status')}
                """,
                sale_params,
            )
            total_expenses = self._amount(
                connection,
                f"""
                SELECT COALESCE(SUM(
                    expenses.amount + expenses.tax_amount
                    - COALESCE((
                        SELECT SUM(expense_refunds.amount)
                        FROM expense_refunds
                        WHERE expense_refunds.expense_id = expenses.id
                    ), 0)
                ), 0)
                FROM expenses
                {expense_where.replace('expense_type', 'expenses.expense_type').replace('status', 'expenses.status').replace('expense_date', 'expenses.expense_date').replace('location_id', 'expenses.location_id')}
                """,
                expense_params,
            )
            cash_in = self._amount(
                connection,
                f"SELECT COALESCE(SUM(amount), 0) FROM expenses {cash_in_where}",
                cash_in_params,
            )
            cash_out = self._amount(
                connection,
                f"SELECT COALESCE(SUM(amount), 0) FROM expenses {cash_out_where}",
                cash_out_params,
            )
        net_sales = gross_sales - returns
        gross_profit = net_sales - cogs
        net_profit = gross_profit - total_expenses
        return {
            "total_sales": gross_sales,
            "gross_sales": gross_sales,
            "discounts": discounts,
            "sales_tax": sales_tax,
            "sales_returns": returns,
            "net_sales": net_sales,
            "cost_of_goods": cogs,
            "total_purchases": cogs,
            "total_expenses": total_expenses,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
            "profit_margin": (net_profit / net_sales * 100) if net_sales else 0,
            "cash_in": cash_in,
            "cash_out": cash_out,
        }

    def purchase_sale_summary(self) -> dict[str, float]:
        with get_connection() as connection:
            sales_total = self._single_amount(connection, "SELECT COALESCE(SUM(total), 0) FROM sales")
            sales_paid = self._single_amount(connection, "SELECT COALESCE(SUM(paid_amount), 0) FROM sales")
            sales_due = self._single_amount(connection, "SELECT COALESCE(SUM(due_amount), 0) FROM sales")
            purchase_total = self._single_amount(connection, "SELECT COALESCE(SUM(total), 0) FROM purchases")
            purchase_paid = self._single_amount(connection, "SELECT COALESCE(SUM(paid_amount), 0) FROM purchases")
            purchase_due = self._single_amount(connection, "SELECT COALESCE(SUM(due_amount), 0) FROM purchases")
        return {
            "sales_total": sales_total,
            "sales_paid": sales_paid,
            "sales_due": sales_due,
            "purchase_total": purchase_total,
            "purchase_paid": purchase_paid,
            "purchase_due": purchase_due,
        }

    def expense_by_category(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        COALESCE(expense_categories.name, 'Uncategorized') AS category_name,
                        COUNT(expenses.id) AS expense_count,
                        COALESCE(SUM(expenses.amount + expenses.tax_amount), 0)
                        - COALESCE(SUM((
                            SELECT COALESCE(SUM(expense_refunds.amount), 0)
                            FROM expense_refunds
                            WHERE expense_refunds.expense_id = expenses.id
                        )), 0) AS total_amount
                    FROM expenses
                    LEFT JOIN expense_categories ON expense_categories.id = expenses.category_id
                    WHERE expenses.expense_type = 'expense'
                      AND expenses.status IN ('approved', 'paid')
                    GROUP BY COALESCE(expense_categories.name, 'Uncategorized')
                    ORDER BY total_amount DESC
                    """
                )
            )

    def tax_report(self) -> dict[str, list[sqlite3.Row] | dict[str, float]]:
        with get_connection() as connection:
            sales_tax = list(
                connection.execute(
                    """
                    SELECT sale_date AS entry_date, invoice_no, tax, total, 'Sale' AS source
                    FROM sales
                    WHERE tax > 0
                    ORDER BY sale_date DESC, id DESC
                    """
                )
            )
            purchase_tax = list(
                connection.execute(
                    """
                    SELECT purchase_date AS entry_date, invoice_no, tax, total, 'Purchase' AS source
                    FROM purchases
                    WHERE tax > 0
                    ORDER BY purchase_date DESC, id DESC
                    """
                )
            )
            summary = {
                "sales_tax": self._single_amount(connection, "SELECT COALESCE(SUM(tax), 0) FROM sales"),
                "purchase_tax": self._single_amount(connection, "SELECT COALESCE(SUM(tax), 0) FROM purchases"),
            }
        summary["net_tax"] = summary["sales_tax"] - summary["purchase_tax"]
        return {"summary": summary, "sales": sales_tax, "purchases": purchase_tax}

    def supplier_customer_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        contacts.contact_type,
                        contacts.name,
                        contacts.phone,
                        contacts.email,
                        contacts.opening_balance,
                        contacts.credit_limit,
                        contacts.is_active,
                        CASE
                            WHEN contacts.contact_type = 'customer' THEN COUNT(DISTINCT sales.id)
                            ELSE COUNT(DISTINCT purchases.id)
                        END AS document_count,
                        CASE
                            WHEN contacts.contact_type = 'customer' THEN COALESCE(SUM(sales.total), 0)
                            ELSE COALESCE(SUM(purchases.total), 0)
                        END AS total_amount,
                        CASE
                            WHEN contacts.contact_type = 'customer' THEN COALESCE(SUM(sales.due_amount), 0)
                            ELSE COALESCE(SUM(purchases.due_amount), 0)
                        END AS due_amount
                    FROM contacts
                    LEFT JOIN sales ON sales.customer_id = contacts.id AND contacts.contact_type = 'customer'
                    LEFT JOIN purchases ON purchases.supplier_id = contacts.id AND contacts.contact_type = 'supplier'
                    GROUP BY contacts.id
                    ORDER BY contacts.contact_type, contacts.name
                    """
                )
            )

    def trending_products(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        products.id,
                        products.name,
                        products.sku,
                        COALESCE(SUM(sale_items.quantity), 0) AS quantity_sold,
                        COALESCE(SUM(sale_items.line_total), 0) AS sales_amount,
                        COUNT(DISTINCT sale_items.sale_id) AS sale_count
                    FROM products
                    LEFT JOIN sale_items ON sale_items.product_id = products.id
                    LEFT JOIN sales ON sales.id = sale_items.sale_id AND sales.sale_status = 'final'
                    GROUP BY products.id
                    HAVING quantity_sold > 0
                    ORDER BY quantity_sold DESC, sales_amount DESC
                    LIMIT 25
                    """
                )
            )

    def sales_representative_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        name,
                        phone,
                        email,
                        commission_rate,
                        is_active,
                        created_at
                    FROM sales_commission_agents
                    ORDER BY is_active DESC, name
                    """
                )
            )

    def low_stock_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        products.name,
                        products.sku,
                        products.alert_quantity,
                        COALESCE(product_units.short_name, '') AS unit_name,
                        COALESCE(SUM(stock_movements.quantity_in), 0) AS quantity_in,
                        COALESCE(SUM(stock_movements.quantity_out), 0) AS quantity_out,
                        COALESCE(SUM(stock_movements.quantity_in - stock_movements.quantity_out), 0) AS available_stock
                    FROM products
                    LEFT JOIN product_units ON product_units.id = products.unit_id
                    LEFT JOIN stock_movements ON stock_movements.product_id = products.id
                    WHERE products.alert_quantity > 0
                    GROUP BY products.id
                    HAVING available_stock <= products.alert_quantity
                    ORDER BY available_stock ASC, products.name
                    """
                )
            )

    def stock_adjustment_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        stock_adjustments.adjustment_date,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        COALESCE(locations.name, 'No Location') AS location_name,
                        stock_adjustments.adjustment_type,
                        stock_adjustments.quantity,
                        stock_adjustments.reason
                    FROM stock_adjustments
                    JOIN products ON products.id = stock_adjustments.product_id
                    LEFT JOIN locations ON locations.id = stock_adjustments.location_id
                    ORDER BY stock_adjustments.adjustment_date DESC, stock_adjustments.id DESC
                    """
                )
            )

    def stock_transfer_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        stock_transfers.transfer_date,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        from_locations.name AS from_location_name,
                        to_locations.name AS to_location_name,
                        stock_transfers.quantity,
                        stock_transfers.note
                    FROM stock_transfers
                    JOIN products ON products.id = stock_transfers.product_id
                    JOIN locations AS from_locations ON from_locations.id = stock_transfers.from_location_id
                    JOIN locations AS to_locations ON to_locations.id = stock_transfers.to_location_id
                    ORDER BY stock_transfers.transfer_date DESC, stock_transfers.id DESC
                    """
                )
            )

    def payment_report(self, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[object] = []
        self._date_clauses(clauses, params, "payments.payment_date", filters)
        self._exact_clause(clauses, params, "payments.account_id", filters.get("account_id"))
        self._exact_clause(clauses, params, "payments.payment_type", filters.get("payment_type"))
        self._exact_clause(clauses, params, "payments.method", filters.get("method"))
        self._exact_clause(clauses, params, "payments.reference_type", filters.get("reference_type"))
        if filters.get("search"):
            clauses.append("(payments.note LIKE ? OR payment_accounts.name LIKE ?)")
            search = f"%{filters['search']}%"
            params.extend([search, search])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        payments.id,
                        payments.payment_date,
                        payments.payment_type,
                        payments.reference_type,
                        payments.reference_id,
                        COALESCE(payment_accounts.name, 'No Account') AS account_name,
                        payments.method,
                        payments.amount,
                        payments.note
                    FROM payments
                    LEFT JOIN payment_accounts ON payment_accounts.id = payments.account_id
                    {where}
                    ORDER BY payments.payment_date DESC, payments.id DESC
                    """,
                    params,
                )
            )

    def due_payment_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        'Sale' AS source,
                        sales.id AS source_id,
                        sales.invoice_no,
                        sales.sale_date AS entry_date,
                        COALESCE(contacts.name, 'Walk-in Customer') AS party_name,
                        sales.total,
                        sales.paid_amount,
                        sales.due_amount
                    FROM sales
                    LEFT JOIN contacts ON contacts.id = sales.customer_id
                    WHERE sales.due_amount > 0
                    UNION ALL
                    SELECT
                        'Purchase' AS source,
                        purchases.id AS source_id,
                        purchases.invoice_no,
                        purchases.purchase_date AS entry_date,
                        COALESCE(contacts.name, 'No Supplier') AS party_name,
                        purchases.total,
                        purchases.paid_amount,
                        purchases.due_amount
                    FROM purchases
                    LEFT JOIN contacts ON contacts.id = purchases.supplier_id
                    WHERE purchases.due_amount > 0
                    ORDER BY entry_date DESC
                    """
                )
            )

    def cash_register_summary(self) -> dict[str, float]:
        with get_connection() as connection:
            cash_in = self._single_amount(
                connection,
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE payment_type = 'in' AND LOWER(COALESCE(method, '')) = 'cash'",
            )
            cash_out = self._single_amount(
                connection,
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE payment_type = 'out' AND LOWER(COALESCE(method, '')) = 'cash'",
            )
        return {
            "cash_in": cash_in,
            "cash_out": cash_out,
            "net_cash": cash_in - cash_out,
        }

    @staticmethod
    def _single_amount(connection: sqlite3.Connection, query: str) -> float:
        row = connection.execute(query).fetchone()
        return float(row[0] or 0)

    @staticmethod
    def _amount(connection: sqlite3.Connection, query: str, params: list[object]) -> float:
        row = connection.execute(query, params).fetchone()
        return float(row[0] or 0)

    @staticmethod
    def _date_clauses(
        clauses: list[str], params: list[object], column: str, filters: dict[str, str]
    ) -> None:
        if filters.get("date_from"):
            clauses.append(f"{column} >= ?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append(f"{column} <= ?")
            params.append(filters["date_to"])

    @staticmethod
    def _exact_clause(
        clauses: list[str], params: list[object], column: str, value: str | None
    ) -> None:
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    @staticmethod
    def _where_for_date_location(
        date_column: str,
        location_column: str,
        filters: dict[str, str],
        initial: list[str],
    ) -> tuple[str, list[object]]:
        clauses = list(initial)
        params: list[object] = []
        ReportRepository._date_clauses(clauses, params, date_column, filters)
        ReportRepository._exact_clause(
            clauses, params, location_column, filters.get("location_id")
        )
        return f"WHERE {' AND '.join(clauses)}", params
