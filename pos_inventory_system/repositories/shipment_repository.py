from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.product_repository import LookupItem


@dataclass(frozen=True)
class ShipmentFormData:
    sale_id: int
    shipment_date: str
    courier: str
    tracking_no: str
    status: str
    note: str


class ShipmentRepository:
    def list_shipments(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        shipments.id,
                        shipments.shipment_date,
                        shipments.courier,
                        shipments.tracking_no,
                        shipments.status,
                        shipments.note,
                        sales.invoice_no
                    FROM shipments
                    JOIN sales ON sales.id = shipments.sale_id
                    ORDER BY shipments.shipment_date DESC, shipments.id DESC
                    """
                )
            )

    def create_shipment(self, shipment: ShipmentFormData) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO shipments (sale_id, shipment_date, courier, tracking_no, status, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    shipment.sale_id,
                    shipment.shipment_date,
                    shipment.courier,
                    shipment.tracking_no,
                    shipment.status,
                    shipment.note,
                ),
            )
            return int(cursor.lastrowid)

    def sale_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, invoice_no || ' - ' || sale_date AS name
                FROM sales
                WHERE sale_status = 'final'
                ORDER BY id DESC
                """
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]
