from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class StockAdjustmentFormData:
    product_id: int
    location_id: int
    adjustment_date: str
    adjustment_type: str
    quantity: float
    reason: str


@dataclass(frozen=True)
class StockTransferFormData:
    product_id: int
    from_location_id: int
    to_location_id: int
    transfer_date: str
    quantity: float
    note: str


class StockOperationRepository:
    def location_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name FROM locations WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_adjustments(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        stock_adjustments.*,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        locations.name AS location_name
                    FROM stock_adjustments
                    JOIN products ON products.id = stock_adjustments.product_id
                    LEFT JOIN locations ON locations.id = stock_adjustments.location_id
                    ORDER BY stock_adjustments.adjustment_date DESC, stock_adjustments.id DESC
                    """
                )
            )

    def create_adjustment(self, adjustment: StockAdjustmentFormData) -> int:
        if adjustment.quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if adjustment.adjustment_type not in {"increase", "decrease"}:
            raise ValueError("Adjustment type must be increase or decrease.")
        if adjustment.adjustment_type == "decrease":
            available = self.available_stock(adjustment.product_id, adjustment.location_id)
            if adjustment.quantity > available:
                raise ValueError(f"Not enough stock at this location. Available: {available:.2f}.")

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_adjustments (
                    product_id, location_id, adjustment_date, adjustment_type, quantity, reason
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    adjustment.product_id,
                    adjustment.location_id,
                    adjustment.adjustment_date,
                    adjustment.adjustment_type,
                    adjustment.quantity,
                    adjustment.reason,
                ),
            )
            adjustment_id = int(cursor.lastrowid)
            quantity_in = adjustment.quantity if adjustment.adjustment_type == "increase" else 0
            quantity_out = adjustment.quantity if adjustment.adjustment_type == "decrease" else 0
            connection.execute(
                """
                INSERT INTO stock_movements (
                    product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                )
                VALUES (?, ?, 'stock_adjustment', 'stock_adjustment', ?, ?, ?)
                """,
                (adjustment.product_id, adjustment.location_id, adjustment_id, quantity_in, quantity_out),
            )
            connection.commit()
            return adjustment_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_transfers(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        stock_transfers.*,
                        products.name AS product_name,
                        products.sku AS product_sku,
                        from_locations.name AS from_location_name,
                        to_locations.name AS to_location_name
                    FROM stock_transfers
                    JOIN products ON products.id = stock_transfers.product_id
                    JOIN locations AS from_locations ON from_locations.id = stock_transfers.from_location_id
                    JOIN locations AS to_locations ON to_locations.id = stock_transfers.to_location_id
                    ORDER BY stock_transfers.transfer_date DESC, stock_transfers.id DESC
                    """
                )
            )

    def create_transfer(self, transfer: StockTransferFormData) -> int:
        if transfer.quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if transfer.from_location_id == transfer.to_location_id:
            raise ValueError("From and to locations must be different.")

        available = self.available_stock(transfer.product_id, transfer.from_location_id)
        if transfer.quantity > available:
            raise ValueError(f"Not enough stock at source location. Available: {available:.2f}.")

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_transfers (
                    product_id, from_location_id, to_location_id, transfer_date, quantity, note
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer.product_id,
                    transfer.from_location_id,
                    transfer.to_location_id,
                    transfer.transfer_date,
                    transfer.quantity,
                    transfer.note,
                ),
            )
            transfer_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO stock_movements (
                    product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                )
                VALUES (?, ?, 'stock_transfer_out', 'stock_transfer', ?, 0, ?)
                """,
                (transfer.product_id, transfer.from_location_id, transfer_id, transfer.quantity),
            )
            connection.execute(
                """
                INSERT INTO stock_movements (
                    product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                )
                VALUES (?, ?, 'stock_transfer_in', 'stock_transfer', ?, ?, 0)
                """,
                (transfer.product_id, transfer.to_location_id, transfer_id, transfer.quantity),
            )
            connection.commit()
            return transfer_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def available_stock(self, product_id: int, location_id: int) -> float:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity_in - quantity_out), 0) AS available
                FROM stock_movements
                WHERE product_id = ? AND location_id = ?
                """,
                (product_id, location_id),
            ).fetchone()
        return float(row["available"])
