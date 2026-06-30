import tkinter as tk
from tkinter import messagebox, ttk

from pos_inventory_system.services.auth_service import AuthenticatedUser
from pos_inventory_system.services.permission_service import PermissionService
from pos_inventory_system.services.user_service import UserService


class UsersScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, current_user: AuthenticatedUser | None) -> None:
        super().__init__(parent, padding=(28, 24))
        self.current_user = current_user
        self.user_service = UserService()
        self.permission_service = PermissionService()
        self.roles_by_name: dict[str, int] = {}

        self.grid_columnconfigure(0, weight=1)
        self._build_layout()
        self.refresh()

    def _build_layout(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ttk.Label(header, text="Users", style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="SQLite connected through UserService and UserRepository.",
            style="PageHint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 18))

        self.add_button = ttk.Button(header, text="Add User", command=self._open_add_dialog)
        self.add_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(header, text="Refresh", command=self.refresh).grid(row=0, column=2, padx=(8, 0))
        self.deactivate_button = ttk.Button(header, text="Deactivate", command=self._deactivate_selected)
        self.deactivate_button.grid(row=0, column=3, padx=(8, 0))

        status_panel = ttk.Frame(self, style="Metric.TFrame", padding=14)
        status_panel.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        status_panel.grid_columnconfigure(1, weight=1)

        rows = [
            ("Module", "User Management"),
            ("Screen", "Users"),
            ("Database", "SQLite connected"),
            ("Service Layer", "UserService active"),
            ("Repository", "UserRepository active"),
            ("Permissions", "Role-based access active"),
            ("Audit Log", "Create/deactivate actions logged"),
        ]
        for index, (label, value) in enumerate(rows):
            ttk.Label(status_panel, text=label, style="MetricTitle.TLabel").grid(
                row=index, column=0, sticky="w", padx=(0, 18), pady=2
            )
            ttk.Label(status_panel, text=value, style="MetricTitle.TLabel").grid(
                row=index, column=1, sticky="w", pady=2
            )

        self.table = ttk.Treeview(
            self,
            columns=("id", "username", "full_name", "role", "status", "created_at"),
            show="headings",
            height=14,
        )
        headings = {
            "id": "ID",
            "username": "Username",
            "full_name": "Full Name",
            "role": "Role",
            "status": "Status",
            "created_at": "Created At",
        }
        widths = {
            "id": 70,
            "username": 180,
            "full_name": 240,
            "role": 160,
            "status": 100,
            "created_at": 180,
        }
        for column, heading in headings.items():
            self.table.heading(column, text=heading)
            self.table.column(column, width=widths[column], anchor="w")

        self.table.grid(row=2, column=0, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)

    def refresh(self) -> None:
        try:
            users = self.user_service.list_users(self.current_user)
            roles = self.user_service.list_roles(self.current_user)
        except PermissionError as exc:
            messagebox.showerror("Permission denied", str(exc))
            self.add_button.configure(state="disabled")
            self.deactivate_button.configure(state="disabled")
            return

        self.roles_by_name = {role["name"]: role["id"] for role in roles}
        self.table.delete(*self.table.get_children())
        for user in users:
            self.table.insert(
                "",
                "end",
                values=(
                    user["id"],
                    user["username"],
                    user["full_name"],
                    user["role_name"],
                    "Active" if user["is_active"] else "Inactive",
                    user["created_at"],
                ),
            )

        if not self.permission_service.has_permission(self.current_user, "users.create"):
            self.add_button.configure(state="disabled")
        if not self.permission_service.has_permission(self.current_user, "users.delete"):
            self.deactivate_button.configure(state="disabled")

    def _open_add_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Add User")
        dialog.geometry("420x300")
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        form = ttk.Frame(dialog, padding=18)
        form.pack(fill="both", expand=True)
        form.grid_columnconfigure(1, weight=1)

        full_name = tk.StringVar()
        username = tk.StringVar()
        password = tk.StringVar()
        role_name = tk.StringVar(value=next(iter(self.roles_by_name), "Admin"))
        is_active = tk.BooleanVar(value=True)

        ttk.Label(form, text="Full Name").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=full_name).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Username").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=username).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Password").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=password, show="*").grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Role").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(
            form,
            textvariable=role_name,
            values=list(self.roles_by_name),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=6)

        ttk.Checkbutton(form, text="Active", variable=is_active).grid(
            row=4, column=1, sticky="w", pady=6
        )

        buttons = ttk.Frame(form)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            buttons,
            text="Save",
            command=lambda: self._save_new_user(
                dialog,
                self.roles_by_name.get(role_name.get(), 0),
                username.get(),
                password.get(),
                full_name.get(),
                is_active.get(),
            ),
        ).pack(side="right")

    def _save_new_user(
        self,
        dialog: tk.Toplevel,
        role_id: int,
        username: str,
        password: str,
        full_name: str,
        is_active: bool,
    ) -> None:
        try:
            self.user_service.create_user(
                self.current_user,
                role_id=role_id,
                username=username,
                password=password,
                full_name=full_name,
                is_active=is_active,
            )
        except (PermissionError, ValueError) as exc:
            messagebox.showerror("Could not save user", str(exc))
            return

        dialog.destroy()
        self.refresh()

    def _deactivate_selected(self) -> None:
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("Select user", "Please select a user first.")
            return

        values = self.table.item(selected[0], "values")
        user_id = int(values[0])
        username = values[1]
        if not messagebox.askyesno("Deactivate user", f"Deactivate user {username}?"):
            return

        try:
            self.user_service.deactivate_user(self.current_user, user_id)
        except (PermissionError, ValueError) as exc:
            messagebox.showerror("Could not deactivate user", str(exc))
            return

        self.refresh()
