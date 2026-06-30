import tkinter as tk
from tkinter import messagebox, ttk

from pos_inventory_system.services.auth_service import AuthService, AuthenticatedUser


class LoginWindow(tk.Tk):
    def __init__(self, auth_service: AuthService) -> None:
        super().__init__()
        self.auth_service = auth_service
        self.user: AuthenticatedUser | None = None

        self.title("Login - POS Ultimate Inventory System")
        self.geometry("460x420")
        self.resizable(False, False)
        self.configure(bg="#eef2f5")

        self._configure_style()
        self._build_form()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("LoginCard.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#ffffff", foreground="#17202a", font=("Segoe UI", 18, "bold"))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#607080", font=("Segoe UI", 10))
        style.configure("Field.TLabel", background="#ffffff", foreground="#17202a", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))

    def _build_form(self) -> None:
        wrapper = tk.Frame(self, bg="#eef2f5")
        wrapper.pack(expand=True, fill="both", padx=44, pady=36)

        card = ttk.Frame(wrapper, style="LoginCard.TFrame", padding=28)
        card.pack(expand=True, fill="both")
        card.grid_columnconfigure(0, weight=1)

        ttk.Label(card, text="POS Ultimate", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text="Sign in to continue", style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 22))

        ttk.Label(card, text="Username", style="Field.TLabel").grid(row=2, column=0, sticky="w")
        self.username_var = tk.StringVar()
        username_entry = ttk.Entry(card, textvariable=self.username_var)
        username_entry.grid(row=3, column=0, sticky="ew", pady=(6, 16))

        ttk.Label(card, text="Password", style="Field.TLabel").grid(row=4, column=0, sticky="w")
        self.password_var = tk.StringVar()
        password_entry = ttk.Entry(card, textvariable=self.password_var, show="*")
        password_entry.grid(row=5, column=0, sticky="ew", pady=(6, 18))

        ttk.Button(card, text="Login", style="Primary.TButton", command=self._login).grid(
            row=6, column=0, sticky="ew"
        )

        ttk.Label(card, text="Use your assigned staff login.", style="Hint.TLabel").grid(
            row=7, column=0, sticky="w", pady=(18, 0)
        )

        self.bind("<Return>", lambda event: self._login())
        username_entry.focus_set()

    def _login(self) -> None:
        user = self.auth_service.authenticate(
            self.username_var.get(),
            self.password_var.get(),
        )
        if user is None:
            messagebox.showerror("Login failed", "Invalid username or password.")
            return

        self.user = user
        self.destroy()
