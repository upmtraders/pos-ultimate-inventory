from .database.connection import initialize_database
from .services.auth_service import AuthService
from .ui.dashboard_window import DashboardWindow
from .ui.login_window import LoginWindow


def main() -> None:
    initialize_database()

    auth_service = AuthService()
    auth_service.ensure_default_admin()

    login = LoginWindow(auth_service)
    login.mainloop()
    if login.user is None:
        return

    app = DashboardWindow(login.user)
    app.mainloop()


if __name__ == "__main__":
    main()
