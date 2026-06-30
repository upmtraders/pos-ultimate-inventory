from sqlite3 import Row

from pos_inventory_system.repositories.user_repository import UserFormData, UserRepository
from pos_inventory_system.services.audit_service import AuditService
from pos_inventory_system.services.auth_service import AuthenticatedUser
from pos_inventory_system.services.permission_service import PermissionService


class UserService:
    def __init__(self) -> None:
        self.repository = UserRepository()
        self.audit_service = AuditService()
        self.permission_service = PermissionService()

    def list_users(self, current_user: AuthenticatedUser | None) -> list[Row]:
        self._require_permission(current_user, "users.view")
        return self.repository.list_users()

    def list_roles(self, current_user: AuthenticatedUser | None) -> list[Row]:
        self._require_permission(current_user, "users.view")
        return self.repository.list_roles()

    def create_user(
        self,
        current_user: AuthenticatedUser | None,
        role_id: int,
        username: str,
        password: str,
        full_name: str,
        is_active: bool = True,
    ) -> int:
        self._require_permission(current_user, "users.create")
        username = username.strip()
        full_name = full_name.strip()

        if not username:
            raise ValueError("Username is required.")
        if not full_name:
            raise ValueError("Full name is required.")
        if not password:
            raise ValueError("Password is required.")
        if role_id <= 0:
            raise ValueError("Role is required.")

        user_id = self.repository.create_user(
            UserFormData(
                role_id=role_id,
                username=username,
                password=password,
                full_name=full_name,
                phone="",
                email="",
                address="",
                emergency_contact="",
                permissions_text="",
                sales_commission_rate=0,
                sales_target=0,
                bank_name="",
                bank_account_name="",
                bank_account_number="",
                bank_branch="",
                employee_no="",
                department="",
                designation="",
                joining_date="",
                employment_type="",
                basic_salary=0,
                pay_frequency="",
                allowances=0,
                deductions=0,
                is_active=1 if is_active else 0,
            )
        )
        self.audit_service.log(
            current_user.id if current_user else None,
            "user.created",
            f"Created user {username}",
        )
        return user_id

    def deactivate_user(self, current_user: AuthenticatedUser | None, user_id: int) -> None:
        self._require_permission(current_user, "users.delete")
        if current_user is not None and current_user.id == user_id:
            raise ValueError("You cannot deactivate your own logged-in user.")

        self.repository.deactivate_user(user_id)
        self.audit_service.log(
            current_user.id if current_user else None,
            "user.deactivated",
            f"Deactivated user id {user_id}",
        )

    def _require_permission(
        self,
        current_user: AuthenticatedUser | None,
        permission_name: str,
    ) -> None:
        if not self.permission_service.has_permission(current_user, permission_name):
            self.audit_service.log(
                current_user.id if current_user else None,
                "permission.denied",
                f"Missing permission {permission_name}",
            )
            raise PermissionError("You do not have permission for this action.")
