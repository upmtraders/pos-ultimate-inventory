import hashlib
import hmac
import os
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    full_name: str
    role_name: str
    permissions_text: str = ""


class AuthService:
    def ensure_default_admin(self) -> None:
        default_username = os.environ.get("POS_DEFAULT_ADMIN_USERNAME", "admin").strip() or "admin"
        default_password = os.environ.get("POS_DEFAULT_ADMIN_PASSWORD", "admin123")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?",
                (default_username,),
            ).fetchone()
            if row is not None:
                return

            connection.execute(
                """
                INSERT INTO users (role_id, username, password_hash, full_name)
                VALUES (1, ?, ?, ?)
                """,
                (default_username, self.hash_password(default_password), "System Administrator"),
            )

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None:
        username = username.strip()
        if not username or not password:
            return None

        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    users.full_name,
                    users.password_hash,
                    COALESCE(users.permissions_text, '') AS permissions_text,
                    roles.name AS role_name
                FROM users
                JOIN roles ON roles.id = users.role_id
                WHERE users.username = ? AND users.is_active = 1
                """,
                (username,),
            ).fetchone()

        if row is None or not self.verify_password(password, row["password_hash"]):
            return None

        return AuthenticatedUser(
            id=row["id"],
            username=row["username"],
            full_name=row["full_name"],
            role_name=row["role_name"],
            permissions_text=row["permissions_text"],
        )

    @staticmethod
    def hash_password(password: str) -> str:
        salt = os.urandom(16).hex()
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return f"pbkdf2_sha256$100000${salt}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        try:
            algorithm, iterations, salt, expected_digest = stored_hash.split("$", 3)
        except ValueError:
            return False

        if algorithm != "pbkdf2_sha256":
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected_digest)
