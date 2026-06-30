import tkinter as tk
from tkinter import ttk

from pos_inventory_system.services.auth_service import AuthenticatedUser

from .menu_structure import MENU_SECTIONS
from .users_window import UsersScreen


SECTION_ICONS = {
    "Dashboard": "\u2302",
    "User Management": "\u25c9",
    "Sales": "\u25c8",
    "Contacts": "\u260e",
    "Products": "\u25a3",
    "Purchases": "\u21e3",
    "Sell / Sales": "\u25c8",
    "Stock": "\u25a6",
    "Expenses": "\u25cc",
    "Payment Accounts": "\u25ce",
    "Reports": "\u25a4",
    "Settings": "\u2699",
    "Modules / Addons": "\u2726",
    "Add-ons": "\u2726",
}

ITEM_ICONS = {
    "Dashboard": "\u2302",
    "POS": "\u25c8",
    "Sales History": "\u2630",
    "Returns": "\u21b6",
    "Products": "\u25a3",
    "Stock": "\u25a6",
    "Product Setup": "\u2699",
    "Purchases": "\u21e3",
    "Purchase Returns": "\u21b6",
    "Customer Payments": "\u25ce",
    "Expenses": "\u25cc",
    "Expense Setup": "\u2699",
    "Sales Summary": "\u25a4",
    "Stock Summary": "\u25a4",
    "Profit / Loss": "\u25b2",
    "Payments": "\u25ce",
    "Business": "\u2699",
    "Print / Receipt": "\u2399",
    "Users": "\u25c9",
    "Roles": "\u25ce",
    "Sales Commission Agents": "\u25cc",
    "Suppliers": "\u21e2",
    "Customers": "\u21e0",
    "Customer Groups": "\u25c7",
    "Import Contacts": "\u21e9",
    "List Products": "\u2630",
    "Add Product": "+",
    "Print Labels": "\u2399",
    "Variations": "\u25c8",
    "Import Products": "\u21e9",
    "Import Opening Stock": "\u21e9",
    "Selling Price Groups": "\u25ce",
    "Units": "\u25a1",
    "Categories": "\u25a6",
    "Brands": "\u25c6",
    "Warranties": "\u2713",
    "Stock Alert": "!",
    "List Purchases": "\u2630",
    "Add Purchase": "+",
    "Purchase Order": "\u25a3",
    "Purchase Return": "\u21b6",
    "POS": "\u25c8",
    "Add Sale": "+",
    "List Sales": "\u2630",
    "Drafts": "\u25eb",
    "Quotations": "\u201d",
    "Suspended Sales": "\u23f8",
    "Sales Orders": "\u25a3",
    "Sales Return": "\u21b6",
    "Shipments": "\u21e2",
    "Cash Register": "\u25a4",
    "Stock Transfer": "\u21c4",
    "Stock Adjustment": "\u2699",
    "Stock Report": "\u25a4",
    "Product Stock History": "\u25cc",
    "List Expenses": "\u2630",
    "Add Expense": "+",
    "Expense Categories": "\u25a6",
    "Expense Refund": "\u21b6",
    "Accounts": "\u25ce",
    "Deposits": "\u21e3",
    "Transfers": "\u21c4",
    "Transactions": "\u25a4",
    "Profit / Loss Report": "\u25b2",
    "Sales Report": "\u25a4",
    "Purchase Report": "\u21e3",
    "Purchase & Sale Report": "\u25a4",
    "Tax Report": "%",
    "Supplier & Customer Report": "\u260e",
    "Low Stock Report": "!",
    "Stock Adjustment Report": "\u2699",
    "Stock Transfer Report": "\u21c4",
    "Trending Products": "\u25b2",
    "Expense Report": "\u25cc",
    "Payment Report": "\u25ce",
    "Due Payment Report": "!",
    "Cash Register Report": "\u25a4",
    "Sales Representative Report": "\u25c9",
    "Business Settings": "\u2699",
    "Business Locations": "\u2302",
    "Invoice Settings": "\u25a3",
    "Barcode Settings": "\u25a6",
    "Tax Rates": "%",
    "Payment Methods": "\u25ce",
    "Printers": "\u2399",
    "Backup": "\u21e7",
    "System Health": "\u2713",
    "WooCommerce": "\u2726",
    "Manufacturing": "\u2699",
    "Accounting": "\u25ce",
    "HRM / Essentials": "\u25c9",
    "CRM": "\u260e",
    "Restaurant / Kitchen": "\u25c8",
    "SaaS / Super Admin": "\u25a3",
    "API Connector": "\u21c4",
}


class DashboardWindow(tk.Tk):
    """Main desktop dashboard for the first Python version."""

    def __init__(self, user: AuthenticatedUser | None = None) -> None:
        super().__init__()
        self.user = user
        self.title("POS Ultimate Inventory System")
        self.geometry("1366x768")
        self.minsize(1100, 680)
        self.configure(bg="#eef2f5")

        self.active_button: ttk.Button | None = None
        self.content_widgets: list[tk.Widget] = []

        self._configure_style()
        self._build_layout()
        self.show_page("Dashboard", "Dashboard")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Sidebar.TFrame",
            background="#17202a",
        )
        style.configure(
            "SidebarTitle.TLabel",
            background="#17202a",
            foreground="#ffffff",
            font=("Segoe UI", 15, "bold"),
        )
        style.configure(
            "SidebarSection.TLabel",
            background="#17202a",
            foreground="#9fb0c3",
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Sidebar.TButton",
            background="#17202a",
            foreground="#e8edf3",
            borderwidth=0,
            focusthickness=0,
            anchor="w",
            padding=(12, 8),
            font=("Segoe UI", 10),
        )
        style.map(
            "Sidebar.TButton",
            background=[("active", "#243447"), ("pressed", "#0f766e")],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Header.TFrame",
            background="#ffffff",
        )
        style.configure(
            "Header.TLabel",
            background="#ffffff",
            foreground="#17202a",
            font=("Segoe UI", 18, "bold"),
        )
        style.configure(
            "SubHeader.TLabel",
            background="#ffffff",
            foreground="#607080",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Metric.TFrame",
            background="#ffffff",
            relief="flat",
        )
        style.configure(
            "MetricTitle.TLabel",
            background="#ffffff",
            foreground="#607080",
            font=("Segoe UI", 10),
        )
        style.configure(
            "MetricValue.TLabel",
            background="#ffffff",
            foreground="#17202a",
            font=("Segoe UI", 18, "bold"),
        )
        style.configure(
            "PageTitle.TLabel",
            background="#eef2f5",
            foreground="#17202a",
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "PageHint.TLabel",
            background="#eef2f5",
            foreground="#607080",
            font=("Segoe UI", 10),
        )

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self, width=285, style="Sidebar.TFrame")
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)

        self.main = ttk.Frame(self, style="Header.TFrame")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self._build_sidebar()
        self._build_header()
        self.content = tk.Frame(self.main, bg="#eef2f5")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)

    def _build_sidebar(self) -> None:
        title = ttk.Label(
            self.sidebar,
            text="\u2630  POS Ultimate",
            style="SidebarTitle.TLabel",
            padding=(18, 18, 18, 8),
        )
        title.pack(fill="x")

        subtitle = ttk.Label(
            self.sidebar,
            text="Inventory & Sales",
            style="SidebarSection.TLabel",
            padding=(18, 0, 18, 14),
        )
        subtitle.pack(fill="x")

        canvas = tk.Canvas(
            self.sidebar,
            background="#17202a",
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(self.sidebar, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, style="Sidebar.TFrame")

        scroll_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for section in MENU_SECTIONS:
            section_label = ttk.Label(
                scroll_frame,
                text=f"{SECTION_ICONS.get(section['title'], '\u25aa')}  {section['title'].upper()}",
                style="SidebarSection.TLabel",
                padding=(18, 14, 18, 4),
            )
            section_label.pack(fill="x")

            for item in section["items"]:
                icon = ITEM_ICONS.get(item, "\u25ab")
                button = ttk.Button(
                    scroll_frame,
                    text=f" {icon}   {item}",
                    style="Sidebar.TButton",
                    command=lambda s=section["title"], i=item: self.show_page(s, i),
                )
                button.pack(fill="x", padx=8, pady=1)

    def _build_header(self) -> None:
        header = ttk.Frame(self.main, style="Header.TFrame", padding=(24, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Dashboard",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=self._header_subtitle(),
            style="SubHeader.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        ttk.Button(header, text="Backup").grid(row=0, column=1, rowspan=2, padx=(8, 0))
        ttk.Button(header, text="Settings").grid(row=0, column=2, rowspan=2, padx=(8, 0))

    def _header_subtitle(self) -> str:
        if self.user is None:
            return "Python desktop first version"
        return f"Signed in as {self.user.full_name} ({self.user.role_name})"

    def show_page(self, section: str, item: str) -> None:
        for widget in self.content_widgets:
            widget.destroy()
        self.content_widgets.clear()

        if item == "Dashboard":
            self._show_dashboard()
            return
        if section == "User Management" and item == "Users":
            self._show_users_screen()
            return

        page = tk.Frame(self.content, bg="#eef2f5", padx=28, pady=24)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        self.content_widgets.append(page)

        ttk.Label(page, text=item, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            page,
            text=f"{section} module screen. Forms, tables, filters, permissions, and database services will be added here.",
            style="PageHint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 18))

        self._build_placeholder_panel(page, section, item)

    def _show_dashboard(self) -> None:
        page = tk.Frame(self.content, bg="#eef2f5", padx=28, pady=24)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metrics")
        self.content_widgets.append(page)

        ttk.Label(page, text="Business Dashboard", style="PageTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(
            page,
            text="Daily sales, purchases, stock alerts, cash register, and profit summaries.",
            style="PageHint.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 18))

        metrics = [
            ("Today's Sales", "0.00"),
            ("Today's Purchases", "0.00"),
            ("Products", "0"),
            ("Stock Alerts", "0"),
        ]

        for index, (title, value) in enumerate(metrics):
            card = ttk.Frame(page, style="Metric.TFrame", padding=18)
            card.grid(row=2, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0), pady=(0, 18))
            ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=value, style="MetricValue.TLabel").pack(anchor="w", pady=(8, 0))

        quick_actions = ttk.Frame(page, style="Metric.TFrame", padding=18)
        quick_actions.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 18))
        ttk.Label(quick_actions, text="Quick Actions", style="MetricValue.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        actions = [
            ("New Sale", "Sales", "POS"),
            ("Add Product", "Products", "Add Product"),
            ("Add Purchase", "Purchases", "Add Purchase"),
            ("Add Expense", "Expenses", "Add Expense"),
        ]
        for row, (label, section, item) in enumerate(actions, start=1):
            ttk.Button(
                quick_actions,
                text=label,
                command=lambda s=section, i=item: self.show_page(s, i),
            ).grid(row=row, column=0, sticky="ew", pady=4)

        alerts = ttk.Frame(page, style="Metric.TFrame", padding=18)
        alerts.grid(row=3, column=2, columnspan=2, sticky="nsew", padx=(10, 0), pady=(0, 18))
        ttk.Label(alerts, text="Operational Alerts", style="MetricValue.TLabel").pack(anchor="w")
        for text in ["No low stock items", "No unpaid purchase alerts", "No suspended sales"]:
            ttk.Label(alerts, text=text, style="MetricTitle.TLabel").pack(anchor="w", pady=(10, 0))

    def _build_placeholder_panel(self, parent: tk.Frame, section: str, item: str) -> None:
        panel = ttk.Frame(parent, style="Metric.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        ttk.Label(panel, text="Screen status", style="MetricTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Ready for implementation", style="MetricValue.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 14)
        )

        table = ttk.Treeview(panel, columns=("field", "value"), show="headings", height=6)
        table.heading("field", text="Field")
        table.heading("value", text="Value")
        table.column("field", width=220, anchor="w")
        table.column("value", width=520, anchor="w")
        table.grid(row=2, column=0, sticky="ew")

        rows = [
            ("Module", section),
            ("Screen", item),
            ("Database", "SQLite service layer pending"),
            ("Permissions", "Role-based access pending"),
            ("Audit Log", "Pending"),
            ("Export/Print", "Pending where applicable"),
        ]
        for row in rows:
            table.insert("", "end", values=row)

    def _show_users_screen(self) -> None:
        page = UsersScreen(self.content, self.user)
        page.grid(row=0, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content_widgets.append(page)
