from pos_inventory_system.services.auth_service import AuthenticatedUser
from pos_inventory_system.database.connection import get_connection


ROLE_PERMISSIONS = {
    "Admin": {
        "users.view",
        "users.create",
        "users.delete",
    },
    "Manager": {
        "users.view",
    },
}


class PermissionService:
    def has_permission(self, user: AuthenticatedUser | None, permission_name: str) -> bool:
        if user is None:
            return False
        permissions = self._role_permissions(user.role_name)
        permissions.update(self._permissions_from_text(user.permissions_text))
        if not permissions:
            permissions = ROLE_PERMISSIONS.get(user.role_name, set())
        return permission_name in permissions

    @staticmethod
    def _permissions_from_text(permissions_text: str | None) -> set[str]:
        if not permissions_text:
            return set()
        return {
            permission.strip()
            for permission in permissions_text.split(",")
            if permission.strip()
        }

    def _role_permissions(self, role_name: str) -> set[str]:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT permissions_text FROM roles WHERE name = ?",
                (role_name,),
            ).fetchone()
        if row is None:
            return set()
        return self._permissions_from_text(row["permissions_text"])
