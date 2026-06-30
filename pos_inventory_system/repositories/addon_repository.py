from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class AddonModuleData:
    module_key: str
    name: str
    is_enabled: int
    connection_mode: str
    endpoint_url: str
    token_label: str
    notes: str


@dataclass(frozen=True)
class AddonModuleUpdateData:
    module_key: str
    is_enabled: int
    connection_mode: str
    endpoint_url: str
    token_label: str
    notes: str


@dataclass(frozen=True)
class AddonWorkItemData:
    module_key: str
    title: str
    status: str
    owner: str
    due_date: str
    notes: str


class AddonRepository:
    def list_modules(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM addon_modules
                    ORDER BY name
                    """
                )
            )

    def get_module(self, module_key: str) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                "SELECT * FROM addon_modules WHERE module_key = ?",
                (module_key,),
            ).fetchone()

    def list_work_items(self, module_key: str) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM addon_work_items
                    WHERE module_key = ?
                    ORDER BY
                        CASE status
                            WHEN 'pending' THEN 1
                            WHEN 'in_progress' THEN 2
                            ELSE 3
                        END,
                        created_at DESC,
                        id DESC
                    """,
                    (module_key,),
                )
            )

    def create_work_item(self, item: AddonWorkItemData) -> int:
        self._validate_status(item.status)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO addon_work_items (module_key, title, status, owner, due_date, notes)
                VALUES (?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''))
                """,
                (item.module_key, item.title, item.status, item.owner, item.due_date, item.notes),
            )
            return int(cursor.lastrowid)

    def update_work_item_status(self, item_id: int, status: str) -> str:
        self._validate_status(status)
        with get_connection() as connection:
            row = connection.execute(
                "SELECT module_key FROM addon_work_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Work item not found.")
            connection.execute(
                """
                UPDATE addon_work_items
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, item_id),
            )
            return str(row["module_key"])

    def list_sync_logs(self, module_key: str, limit: int = 10) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM addon_sync_logs
                    WHERE module_key = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (module_key, limit),
                )
            )

    def record_sync_log(self, module_key: str, run_type: str, status: str, details: str) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO addon_sync_logs (module_key, run_type, status, details)
                VALUES (?, ?, ?, ?)
                """,
                (module_key, run_type, status, details),
            )
            return int(cursor.lastrowid)

    def module_summary(self, module_key: str) -> dict[str, int]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM addon_work_items
                WHERE module_key = ?
                GROUP BY status
                """,
                (module_key,),
            ).fetchall()
        counts = {"pending": 0, "in_progress": 0, "complete": 0}
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        return counts

    def save_defaults(self, modules: list[AddonModuleData]) -> None:
        with get_connection() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO addon_modules (
                    module_key, name, is_enabled, connection_mode, endpoint_url, token_label, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        module.module_key,
                        module.name,
                        module.is_enabled,
                        module.connection_mode,
                        module.endpoint_url,
                        module.token_label,
                        module.notes,
                    )
                    for module in modules
                ],
            )

    def update_module(self, module: AddonModuleUpdateData) -> None:
        if module.connection_mode not in {"manual", "api", "webhook", "file_import"}:
            raise ValueError("Invalid connection mode.")

        with get_connection() as connection:
            connection.execute(
                """
                UPDATE addon_modules
                SET
                    is_enabled = ?,
                    connection_mode = ?,
                    endpoint_url = NULLIF(?, ''),
                    token_label = NULLIF(?, ''),
                    notes = NULLIF(?, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE module_key = ?
                """,
                (
                    module.is_enabled,
                    module.connection_mode,
                    module.endpoint_url,
                    module.token_label,
                    module.notes,
                    module.module_key,
                ),
            )

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in {"pending", "in_progress", "complete"}:
            raise ValueError("Invalid work item status.")
