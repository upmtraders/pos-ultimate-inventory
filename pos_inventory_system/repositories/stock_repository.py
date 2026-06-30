from __future__ import annotations

import sqlite3

from pos_inventory_system.database.connection import get_connection


class StockRepository:
    def stock_report(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        products.id,
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
                    WHERE products.is_active = 1
                    GROUP BY products.id
                    ORDER BY products.name
                    """
                )
            )

    def movement_history(
        self, product_id: int | None = None, filters: dict[str, str] | None = None
    ) -> list[dict[str, object]]:
        filters = filters or {}
        clauses: list[str] = []
        params: list[object] = []
        if product_id is not None:
            clauses.append("stock_movements.product_id = ?")
            params.append(product_id)
        if filters.get("location_id"):
            clauses.append("stock_movements.location_id = ?")
            params.append(filters["location_id"])
        if filters.get("search"):
            clauses.append(
                """
                (
                    products.name LIKE ? OR products.sku LIKE ? OR products.barcode LIKE ?
                    OR product_variants.sku LIKE ? OR product_variants.barcode LIKE ?
                )
                """
            )
            search = f"%{filters['search']}%"
            params.extend([search, search, search, search, search])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT
                stock_movements.id,
                stock_movements.product_id,
                stock_movements.variant_id,
                stock_movements.location_id,
                stock_movements.movement_type,
                stock_movements.reference_type,
                stock_movements.reference_id,
                stock_movements.quantity_in,
                stock_movements.quantity_out,
                stock_movements.created_at,
                products.name AS product_name,
                products.sku AS product_sku,
                products.barcode AS product_barcode,
                products.purchase_price AS product_purchase_price,
                COALESCE(product_variants.variation_summary, '') AS variation_name,
                COALESCE(product_variants.sku, '') AS variant_sku,
                COALESCE(product_variants.barcode, '') AS variant_barcode,
                COALESCE(product_variants.purchase_price, products.purchase_price) AS unit_cost,
                COALESCE(locations.name, 'No Location') AS location_name,
                CASE stock_movements.reference_type
                    WHEN 'purchase' THEN (SELECT invoice_no FROM purchases WHERE id = stock_movements.reference_id)
                    WHEN 'sale' THEN (SELECT invoice_no FROM sales WHERE id = stock_movements.reference_id)
                    WHEN 'purchase_return' THEN 'Purchase Return #' || stock_movements.reference_id
                    WHEN 'sale_return' THEN 'Sales Return #' || stock_movements.reference_id
                    WHEN 'stock_adjustment' THEN 'Adjustment #' || stock_movements.reference_id
                    WHEN 'stock_transfer' THEN 'Transfer #' || stock_movements.reference_id
                    WHEN 'opening_stock' THEN 'Opening Stock'
                    ELSE COALESCE(stock_movements.reference_type, 'Stock') || ' #' || COALESCE(stock_movements.reference_id, '')
                END AS reference_label,
                CASE stock_movements.reference_type
                    WHEN 'purchase_return' THEN (SELECT note FROM purchase_returns WHERE id = stock_movements.reference_id)
                    WHEN 'sale_return' THEN (SELECT note FROM sales_returns WHERE id = stock_movements.reference_id)
                    WHEN 'stock_adjustment' THEN (SELECT reason FROM stock_adjustments WHERE id = stock_movements.reference_id)
                    WHEN 'stock_transfer' THEN (SELECT note FROM stock_transfers WHERE id = stock_movements.reference_id)
                    ELSE ''
                END AS note
            FROM stock_movements
            JOIN products ON products.id = stock_movements.product_id
            LEFT JOIN product_variants ON product_variants.id = stock_movements.variant_id
            LEFT JOIN locations ON locations.id = stock_movements.location_id
            {where}
            ORDER BY stock_movements.created_at ASC, stock_movements.id ASC
        """

        with get_connection() as connection:
            rows = list(connection.execute(query, params))
        running_by_key: dict[tuple[int, int | None, int | None], float] = {}
        output: list[dict[str, object]] = []
        for row in rows:
            key = (int(row["product_id"]), row["variant_id"], row["location_id"])
            running = running_by_key.get(key, 0.0)
            running += float(row["quantity_in"]) - float(row["quantity_out"])
            running_by_key[key] = running
            item = dict(row)
            item["running_balance"] = running
            item["stock_value"] = running * float(row["unit_cost"])
            output.append(item)
        if filters.get("date_from"):
            output = [
                row for row in output
                if str(row["created_at"])[:10] >= filters["date_from"]
            ]
        if filters.get("date_to"):
            output = [
                row for row in output
                if str(row["created_at"])[:10] <= filters["date_to"]
            ]
        if filters.get("movement_type"):
            output = [
                row for row in output
                if row["movement_type"] == filters["movement_type"]
            ]
        if filters.get("reference_type"):
            output = [
                row for row in output
                if row["reference_type"] == filters["reference_type"]
            ]
        output.reverse()
        return output
