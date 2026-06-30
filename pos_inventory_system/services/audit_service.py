from pos_inventory_system.database.connection import get_connection


class AuditService:
    def log(self, user_id: int | None, action: str, details: str = "") -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO activity_logs (user_id, action, details)
                VALUES (?, ?, ?)
                """,
                (user_id, action, details),
            )
