from __future__ import annotations

import csv
import html
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from io import StringIO
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from pos_inventory_system.database.connection import get_connection, initialize_database
from pos_inventory_system.repositories.cash_register_repository import (
    CASH_DENOMINATIONS,
    CashMovementData,
    CashRegisterRepository,
    CloseRegisterData,
    OpenRegisterData,
)
from pos_inventory_system.repositories.addon_repository import AddonModuleUpdateData, AddonRepository, AddonWorkItemData
from pos_inventory_system.repositories.commission_agent_repository import (
    CommissionAgentFormData,
    CommissionAgentRepository,
)
from pos_inventory_system.repositories.contact_repository import (
    ContactFormData,
    ContactRepository,
    CustomerGroupFormData,
)
from pos_inventory_system.repositories.crm_repository import CRMRepository, FollowUpData, LeadData
from pos_inventory_system.repositories.expense_repository import (
    ExpenseCategoryData,
    ExpenseFormData,
    ExpenseRefundFormData,
    ExpenseRepository,
    ExpenseSettingsData,
)
from pos_inventory_system.repositories.hrm_repository import (
    AttendanceData,
    DocumentData,
    HRMRepository,
    LeaveRequestData,
    PayrollData,
)
from pos_inventory_system.repositories.payment_repository import (
    AccountFormData,
    DepositFormData,
    DuePaymentData,
    PaymentRepository,
    TransferFormData,
)
from pos_inventory_system.repositories.product_repository import (
    BRAND_TEMPLATES,
    CATEGORY_TEMPLATES,
    BrandFormData,
    CategoryFormData,
    PriceGroupFormData,
    ProductFormData,
    ProductVariantFormData,
    ProductRepository,
    LookupItem,
    VariationFormData,
    WarrantyFormData,
)
from pos_inventory_system.repositories.purchase_return_repository import PurchaseReturnFormData, PurchaseReturnRepository
from pos_inventory_system.repositories.purchase_order_repository import PurchaseOrderFormData, PurchaseOrderRepository
from pos_inventory_system.repositories.purchase_repository import (
    PurchaseCheckoutData,
    PurchaseFormData,
    PurchaseItemData,
    PurchasePaymentData,
    PurchaseRepository,
)
from pos_inventory_system.repositories.report_repository import ReportRepository
from pos_inventory_system.repositories.sale_repository import SaleCheckoutData, SaleFormData, SaleItemData, SalePaymentData, SaleRepository
from pos_inventory_system.repositories.sales_return_repository import SalesReturnFormData, SalesReturnRepository
from pos_inventory_system.repositories.settings_repository import (
    BarcodeSettingsData,
    BusinessSettingsData,
    InvoiceSettingsData,
    LocationData,
    PaymentMethodData,
    PrinterSettingsData,
    SettingsRepository,
    TaxRateData,
)
from pos_inventory_system.repositories.shipment_repository import ShipmentFormData, ShipmentRepository
from pos_inventory_system.repositories.stock_operation_repository import (
    StockAdjustmentFormData,
    StockOperationRepository,
    StockTransferFormData,
)
from pos_inventory_system.repositories.stock_repository import StockRepository
from pos_inventory_system.repositories.user_repository import UserFormData, UserRepository
from pos_inventory_system.services.backup_service import BackupService
from pos_inventory_system.services.auth_service import AuthService, AuthenticatedUser
from pos_inventory_system.services.permission_service import PermissionService
from pos_inventory_system.services.woocommerce_service import WooCommerceService
from pos_inventory_system.ui.menu_structure import MENU_SECTIONS


HOST = "127.0.0.1"
PORT = 8000
SESSION_TIMEOUT_SECONDS = 8 * 60 * 60


@dataclass
class SessionState:
    user: AuthenticatedUser
    csrf_token: str
    password_hash: str
    issued_at: float
    last_seen: float


SESSIONS: dict[str, SessionState] = {}
ADDON_PAGE_KEYS = {
    "WooCommerce": "woocommerce",
    "Manufacturing": "manufacturing",
    "Accounting": "accounting",
    "HRM / Essentials": "hrm_essentials",
    "CRM": "crm",
    "Restaurant / Kitchen": "restaurant_kitchen",
    "SaaS / Super Admin": "saas_super_admin",
    "API Connector": "api_connector",
}
ADDON_CAPABILITIES = {
    "woocommerce": [
        "Product catalog export",
        "Order import queue",
        "Customer sync profile",
        "Stock push readiness",
    ],
    "manufacturing": [
        "Bill of materials planning",
        "Production issue tracking",
        "Finished goods stock intake",
        "Wastage and cost review",
    ],
    "accounting": [
        "Chart of accounts mapping",
        "Sales and purchase journal review",
        "Expense posting controls",
        "Tax summary handoff",
    ],
    "hrm_essentials": [
        "Staff profile control",
        "Attendance source mapping",
        "Payroll export notes",
        "Role access alignment",
    ],
    "crm": [
        "Lead and customer segmentation",
        "Follow-up activity tracking",
        "Quotation handoff",
        "Customer ledger visibility",
    ],
    "restaurant_kitchen": [
        "Kitchen order token readiness",
        "Table and service area notes",
        "Counter sale routing",
        "Receipt printer assignment",
    ],
    "saas_super_admin": [
        "Tenant setup notes",
        "Subscription status tracking",
        "Business location limits",
        "Admin access review",
    ],
    "api_connector": [
        "Endpoint registry",
        "Webhook mode selection",
        "Token reference label",
        "Manual sync checklist",
    ],
}
ROLE_PERMISSION_OPTIONS = [
    ("Dashboard", "dashboard"),
    ("POS / Sales", "sales"),
    ("Purchases", "purchases"),
    ("Products", "products"),
    ("Contacts", "contacts"),
    ("Stock", "stock"),
    ("Expenses", "expenses"),
    ("Payments", "payments"),
    ("Reports", "reports"),
    ("Settings", "settings"),
    ("Users - View", "users.view"),
    ("Users - Create", "users.create"),
    ("Users - Delete", "users.delete"),
    ("Addons", "addons"),
]
SECTION_PERMISSIONS = {
    "Dashboard": "dashboard",
    "Sales": "sales",
    "Customers": "contacts",
    "Add-ons": "addons",
    "User Management": "users.view",
    "Contacts": "contacts",
    "Products": "products",
    "Purchases": "purchases",
    "Sell / Sales": "sales",
    "Stock": "stock",
    "Expenses": "expenses",
    "Payment Accounts": "payments",
    "Reports": "reports",
    "Settings": "settings",
    "Modules / Addons": "addons",
}
PAGE_PERMISSIONS = {
    item: SECTION_PERMISSIONS[section["title"]]
    for section in MENU_SECTIONS
    for item in section["items"]
}
PAGE_PERMISSIONS["Backup"] = "settings"
PAGE_PERMISSIONS["System Health"] = "settings"
PAGE_PERMISSIONS["Customer Payments"] = "payments"
PAGE_PERMISSIONS["Supplier Payments"] = "payments"
for expense_page in (
    "Add Expense",
    "List Expenses",
    "Expense Categories",
    "Expense Subcategories",
    "Expense Payees",
    "Expense Budgets",
    "Expense Controls",
    "Recurring Expenses",
    "Expense Refund",
):
    PAGE_PERMISSIONS[expense_page] = "expenses"
POST_PERMISSIONS = {
    "/products/create": "products",
    "/products/update": "products",
    "/products/deactivate": "products",
    "/products/import": "products",
    "/products/opening-stock/import": "products",
    "/barcodes/generate": "products",
    "/variations/create": "products",
    "/variants/create": "products",
    "/price-groups/create": "products",
    "/price-groups/update": "products",
    "/warranties/create": "products",
    "/lookups/create": "products",
    "/categories/create": "products",
    "/categories/template/apply": "products",
    "/categories/update": "products",
    "/categories/deactivate": "products",
    "/brands/create": "products",
    "/brands/template/apply": "products",
    "/brands/update": "products",
    "/brands/deactivate": "products",
    "/contacts/create": "contacts",
    "/contacts/update": "contacts",
    "/contacts/deactivate": "contacts",
    "/customer-groups/create": "contacts",
    "/customer-groups/update": "contacts",
    "/contacts/import": "contacts",
    "/purchases/create": "purchases",
    "/purchases/products/create": "purchases",
    "/purchase-cheques/status": "purchases",
    "/purchase-orders/create": "purchases",
    "/purchase-return/create": "purchases",
    "/sales/create": "sales",
    "/sales-document/create": "sales",
    "/sales-return/create": "sales",
    "/shipments/create": "sales",
    "/cash-register/open": "sales",
    "/cash-register/close": "sales",
    "/cash-register/approve": "sales",
    "/cash-register/movement": "sales",
    "/stock-adjustments/create": "stock",
    "/stock-transfers/create": "stock",
    "/expenses/create": "expenses",
    "/expenses/status": "expenses",
    "/expenses/duplicate": "expenses",
    "/expense-refunds/create": "expenses",
    "/expense-categories/create": "expenses",
    "/expense-settings/update": "expenses",
    "/deposits/create": "payments",
    "/accounts/create": "payments",
    "/transfers/create": "payments",
    "/customer-payments/create": "payments",
    "/supplier-payments/create": "payments",
    "/settings/business/update": "settings",
    "/settings/locations/create": "settings",
    "/settings/invoice/update": "settings",
    "/settings/barcode/update": "settings",
    "/settings/tax-rates/create": "settings",
    "/settings/payment-methods/create": "settings",
    "/settings/printers/create": "settings",
    "/backup/create": "settings",
    "/backup/verify": "settings",
    "/backup/restore": "settings",
    "/backup/settings": "settings",
    "/roles/create": "users.create",
    "/roles/update": "users.create",
    "/users/create": "users.create",
    "/users/deactivate": "users.delete",
    "/commission-agents/create": "users.create",
    "/commission-agents/update": "users.create",
    "/addons/update": "addons",
    "/addons/work/create": "addons",
    "/addons/work/status": "addons",
    "/addons/sync/run": "addons",
    "/woocommerce/test": "addons",
    "/woocommerce/import-products": "addons",
    "/woocommerce/import-customers": "addons",
    "/woocommerce/import-orders": "addons",
    "/woocommerce/push-stock": "addons",
    "/hrm/attendance/save": "addons",
    "/hrm/leave/create": "addons",
    "/hrm/leave/status": "addons",
    "/hrm/payroll/save": "addons",
    "/hrm/documents/create": "addons",
    "/crm/leads/create": "addons",
    "/crm/leads/status": "addons",
    "/crm/followups/create": "addons",
    "/crm/followups/status": "addons",
}


class POSWebHandler(BaseHTTPRequestHandler):
    auth_service = AuthService()
    cash_register_repository = CashRegisterRepository()
    commission_agent_repository = CommissionAgentRepository()
    contact_repository = ContactRepository()
    expense_repository = ExpenseRepository()
    payment_repository = PaymentRepository()
    product_repository = ProductRepository()
    purchase_return_repository = PurchaseReturnRepository()
    purchase_order_repository = PurchaseOrderRepository()
    purchase_repository = PurchaseRepository()
    sale_repository = SaleRepository()
    sales_return_repository = SalesReturnRepository()
    settings_repository = SettingsRepository()
    shipment_repository = ShipmentRepository()
    stock_operation_repository = StockOperationRepository()
    user_repository = UserRepository()
    addon_repository = AddonRepository()
    hrm_repository = HRMRepository()
    crm_repository = CRMRepository()
    backup_service = BackupService()
    permission_service = PermissionService()
    woocommerce_service = WooCommerceService()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/logout":
            self._logout()
            return
        if path in ("/", "/login"):
            user = self._current_user()
            if user:
                self._redirect("/dashboard")
                return
            self._send_html(render_login())
            return
        if path == "/dashboard":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            page = query.get("page", ["Dashboard"])[0]
            message = query.get("message", [""])[0]
            error = query.get("error", [""])[0]
            scheduled_message = self._run_scheduled_backup_if_due()
            if scheduled_message and not message:
                message = scheduled_message
            if not self._has_page_permission(user, page):
                self._send_html(render_dashboard(user, "Dashboard", error="You do not have permission to open that page."), HTTPStatus.FORBIDDEN)
                return
            self._send_html(render_dashboard(user, page, message=message, error=error, query=query))
            return
        if path == "/sales/invoice":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            sale_id = optional_query_int(query, "id")
            if sale_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Sale id is required")
                return
            if not self._has_permission(user, "sales"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            self._send_html(render_sale_invoice(sale_id))
            return
        if path == "/purchases/detail":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            if not self._has_permission(user, "purchases"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            query = parse_qs(urlparse(self.path).query)
            purchase_id = optional_query_int(query, "id")
            if purchase_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Purchase id is required")
                return
            self._send_html(render_purchase_detail(purchase_id))
            return
        if path == "/sales/receipt":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            sale_id = optional_query_int(query, "id")
            receipt_type = query.get("type", ["pos"])[0]
            if sale_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Sale id is required")
                return
            self._send_html(render_sale_receipt(sale_id, receipt_type))
            return
        if path == "/payments/receipt":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            payment_id = optional_query_int(query, "id")
            if payment_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Payment id is required")
                return
            self._send_html(render_payment_receipt(payment_id))
            return
        if path == "/expenses/export.csv":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            if not self._has_permission(user, "expenses"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            query = parse_qs(urlparse(self.path).query)
            self._send_expense_csv(query)
            return
        if path == "/reports/export.csv":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            if not self._has_permission(user, "reports"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            self._send_report_csv(parse_qs(urlparse(self.path).query))
            return
        if path == "/stock-history/export.csv":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            if not self._has_permission(user, "stock"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            self._send_stock_history_csv(parse_qs(urlparse(self.path).query))
            return
        if path == "/sales-history/export.csv":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            if not self._has_permission(user, "sales"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            self._send_sales_history_csv(parse_qs(urlparse(self.path).query))
            return
        if path == "/expenses/attachment":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            expense_id = optional_query_int(parse_qs(urlparse(self.path).query), "id")
            row = self.expense_repository.get_expense(expense_id or 0)
            if row is None or not row["attachment_data"]:
                self.send_error(HTTPStatus.NOT_FOUND, "Attachment not found")
                return
            self._send_html(render_attachment(row))
            return
        if path == "/sales-return/receipt":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            return_id = optional_query_int(query, "id")
            if return_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Return id is required")
                return
            self._send_html(render_sales_return_receipt(return_id))
            return
        if path == "/cash-register/receipt":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            register_id = optional_query_int(query, "id")
            if register_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Register id is required")
                return
            self._send_html(render_cash_register_receipt(register_id))
            return
        if path == "/contacts/ledger":
            user = self._current_user()
            if not user:
                self._redirect("/login")
                return
            query = parse_qs(urlparse(self.path).query)
            contact_type = query.get("type", ["customer"])[0]
            contact_id = optional_query_int(query, "id")
            if contact_id is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Contact id is required")
                return
            if not self._has_permission(user, "contacts"):
                self.send_error(HTTPStatus.FORBIDDEN, "Permission denied")
                return
            self._send_html(render_contact_ledger(contact_type, contact_id))
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/login":
            self._handle_login()
            return

        user = self._current_user()
        if not user:
            self._redirect("/login")
            return
        fields = self._read_form()
        if not self._valid_csrf(fields):
            self._send_html(
                render_dashboard(user, "Dashboard", error="Security token expired. Please retry the action."),
                HTTPStatus.FORBIDDEN,
            )
            return
        permission = POST_PERMISSIONS.get(path)
        if permission and not self._has_permission(user, permission):
            page = self._page_for_permission(permission)
            self._send_html(
                render_dashboard(user, page, error="You do not have permission for this action."),
                HTTPStatus.FORBIDDEN,
            )
            return

        if path == "/products/create":
            self._handle_create_product()
            return
        if path == "/products/update":
            self._handle_update_product()
            return
        if path == "/products/deactivate":
            self._handle_deactivate_product()
            return
        if path == "/products/import":
            self._handle_import_products()
            return
        if path == "/products/opening-stock/import":
            self._handle_import_opening_stock()
            return
        if path == "/barcodes/generate":
            self._handle_generate_barcode()
            return
        if path == "/variations/create":
            self._handle_create_variation()
            return
        if path == "/variants/create":
            self._handle_create_variant()
            return
        if path == "/price-groups/create":
            self._handle_create_price_group()
            return
        if path == "/price-groups/update":
            self._handle_update_price_group()
            return
        if path == "/warranties/create":
            self._handle_create_warranty()
            return
        if path == "/contacts/create":
            self._handle_create_contact()
            return
        if path == "/contacts/update":
            self._handle_update_contact()
            return
        if path == "/contacts/deactivate":
            self._handle_deactivate_contact()
            return
        if path == "/customer-groups/create":
            self._handle_create_customer_group()
            return
        if path == "/customer-groups/update":
            self._handle_update_customer_group()
            return
        if path == "/contacts/import":
            self._handle_import_contacts()
            return
        if path == "/purchases/create":
            self._handle_create_purchase()
            return
        if path == "/purchases/products/create":
            self._handle_create_purchase_product()
            return
        if path == "/purchase-cheques/status":
            self._handle_purchase_cheque_status()
            return
        if path == "/purchase-orders/create":
            self._handle_create_purchase_order()
            return
        if path == "/purchase-return/create":
            self._handle_create_purchase_return()
            return
        if path == "/sales/create":
            self._handle_create_sale()
            return
        if path == "/sales-document/create":
            self._handle_create_sales_document()
            return
        if path == "/sales-return/create":
            self._handle_create_sales_return()
            return
        if path == "/shipments/create":
            self._handle_create_shipment()
            return
        if path == "/stock-adjustments/create":
            self._handle_create_stock_adjustment()
            return
        if path == "/stock-transfers/create":
            self._handle_create_stock_transfer()
            return
        if path == "/cash-register/open":
            self._handle_open_cash_register(user)
            return
        if path == "/cash-register/close":
            self._handle_close_cash_register(user)
            return
        if path == "/cash-register/approve":
            self._handle_approve_cash_register(user)
            return
        if path == "/cash-register/movement":
            self._handle_cash_register_movement()
            return
        if path == "/expenses/create":
            self._handle_create_expense()
            return
        if path == "/expenses/status":
            self._handle_expense_status(user)
            return
        if path == "/expenses/duplicate":
            self._handle_duplicate_expense(user)
            return
        if path == "/expense-refunds/create":
            self._handle_create_expense_refund()
            return
        if path == "/expense-categories/create":
            self._handle_create_expense_category()
            return
        if path == "/expense-settings/update":
            self._handle_update_expense_settings()
            return
        if path == "/deposits/create":
            self._handle_create_deposit()
            return
        if path == "/accounts/create":
            self._handle_create_payment_account()
            return
        if path == "/transfers/create":
            self._handle_create_transfer()
            return
        if path == "/customer-payments/create":
            self._handle_create_customer_payment()
            return
        if path == "/supplier-payments/create":
            self._handle_create_supplier_payment()
            return
        if path == "/settings/business/update":
            self._handle_update_business_settings()
            return
        if path == "/settings/locations/create":
            self._handle_create_location()
            return
        if path == "/settings/invoice/update":
            self._handle_update_invoice_settings()
            return
        if path == "/settings/barcode/update":
            self._handle_update_barcode_settings()
            return
        if path == "/settings/tax-rates/create":
            self._handle_create_tax_rate()
            return
        if path == "/settings/payment-methods/create":
            self._handle_create_payment_method()
            return
        if path == "/settings/printers/create":
            self._handle_create_printer()
            return
        if path == "/roles/create":
            self._handle_create_role()
            return
        if path == "/roles/update":
            self._handle_update_role()
            return
        if path == "/users/create":
            self._handle_create_user()
            return
        if path == "/users/deactivate":
            self._handle_deactivate_user(user)
            return
        if path == "/commission-agents/create":
            self._handle_create_commission_agent()
            return
        if path == "/commission-agents/update":
            self._handle_update_commission_agent()
            return
        if path == "/backup/create":
            self._handle_create_backup()
            return
        if path == "/backup/verify":
            self._handle_verify_backup()
            return
        if path == "/backup/restore":
            self._handle_restore_backup()
            return
        if path == "/backup/settings":
            self._handle_backup_settings()
            return
        if path == "/lookups/create":
            self._handle_create_lookup()
            return
        if path == "/categories/create":
            self._handle_create_category()
            return
        if path == "/categories/template/apply":
            self._handle_apply_category_template()
            return
        if path == "/categories/update":
            self._handle_update_category()
            return
        if path == "/categories/deactivate":
            self._handle_deactivate_category()
            return
        if path == "/brands/create":
            self._handle_create_brand()
            return
        if path == "/brands/template/apply":
            self._handle_apply_brand_template()
            return
        if path == "/brands/update":
            self._handle_update_brand()
            return
        if path == "/brands/deactivate":
            self._handle_deactivate_brand()
            return
        if path == "/addons/update":
            self._handle_update_addon()
            return
        if path == "/addons/work/create":
            self._handle_create_addon_work_item()
            return
        if path == "/addons/work/status":
            self._handle_update_addon_work_status()
            return
        if path == "/addons/sync/run":
            self._handle_run_addon_sync()
            return
        if path == "/woocommerce/test":
            self._handle_woocommerce_action("test")
            return
        if path == "/woocommerce/import-products":
            self._handle_woocommerce_action("import_products")
            return
        if path == "/woocommerce/import-customers":
            self._handle_woocommerce_action("import_customers")
            return
        if path == "/woocommerce/import-orders":
            self._handle_woocommerce_action("import_orders")
            return
        if path == "/woocommerce/push-stock":
            self._handle_woocommerce_action("push_stock")
            return
        if path == "/hrm/attendance/save":
            self._handle_save_hrm_attendance()
            return
        if path == "/hrm/leave/create":
            self._handle_create_hrm_leave()
            return
        if path == "/hrm/leave/status":
            self._handle_update_hrm_leave_status()
            return
        if path == "/hrm/payroll/save":
            self._handle_save_hrm_payroll()
            return
        if path == "/hrm/documents/create":
            self._handle_create_hrm_document()
            return
        if path == "/crm/leads/create":
            self._handle_create_crm_lead()
            return
        if path == "/crm/leads/status":
            self._handle_update_crm_lead_status()
            return
        if path == "/crm/followups/create":
            self._handle_create_crm_followup()
            return
        if path == "/crm/followups/status":
            self._handle_update_crm_followup_status()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def _handle_login(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        fields = parse_qs(body)
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]

        user = self.auth_service.authenticate(username, password)
        if not user:
            self._send_html(render_login("Invalid username or password."), HTTPStatus.UNAUTHORIZED)
            return

        session_id = secrets.token_urlsafe(32)
        now = time.time()
        SESSIONS[session_id] = SessionState(
            user=user,
            csrf_token=secrets.token_urlsafe(32),
            password_hash=self._password_hash_for_user(user.id),
            issued_at=now,
            last_seen=now,
        )
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/dashboard")
        self.send_header(
            "Set-Cookie",
            f"pos_session={session_id}; Max-Age={SESSION_TIMEOUT_SECONDS}; HttpOnly; SameSite=Lax; Path=/",
        )
        self.end_headers()

    def _handle_create_product(self) -> None:
        fields = self._read_form()
        try:
            barcode = form_text(fields, "barcode") or self.settings_repository.generate_product_barcode()
            product = ProductFormData(
                name=required_text(fields, "name"),
                sku=required_text(fields, "sku"),
                barcode=barcode,
                image_path=form_text(fields, "image_path"),
                category_id=optional_int(fields, "category_id"),
                brand_id=optional_int(fields, "brand_id"),
                unit_id=optional_int(fields, "unit_id"),
                purchase_price=money_value(fields, "purchase_price"),
                selling_price=money_value(fields, "selling_price"),
                offer_price=money_value(fields, "offer_price"),
                offer_start_date=form_text(fields, "offer_start_date"),
                offer_end_date=form_text(fields, "offer_end_date"),
                tax_rate_id=optional_int(fields, "tax_rate_id"),
                warranty_id=optional_int(fields, "warranty_id"),
                profit_margin=money_value(fields, "profit_margin"),
                alert_quantity=money_value(fields, "alert_quantity"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.product_repository.create_product(product)
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Add Product", str(error)), HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Add Product", f"Could not save product: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=List%20Products&message=Product%20saved")

    def _product_from_fields(self, fields: dict[str, list[str]]) -> ProductFormData:
        return ProductFormData(
            name=required_text(fields, "name"),
            sku=required_text(fields, "sku"),
            barcode=form_text(fields, "barcode"),
            image_path=form_text(fields, "image_path"),
            category_id=optional_int(fields, "category_id"),
            brand_id=optional_int(fields, "brand_id"),
            unit_id=optional_int(fields, "unit_id"),
            purchase_price=money_value(fields, "purchase_price"),
            selling_price=money_value(fields, "selling_price"),
            offer_price=money_value(fields, "offer_price"),
            offer_start_date=form_text(fields, "offer_start_date"),
            offer_end_date=form_text(fields, "offer_end_date"),
            tax_rate_id=optional_int(fields, "tax_rate_id"),
            warranty_id=optional_int(fields, "warranty_id"),
            profit_margin=money_value(fields, "profit_margin"),
            alert_quantity=money_value(fields, "alert_quantity"),
            is_active=1 if form_text(fields, "is_active") == "1" else 0,
        )

    def _handle_update_product(self) -> None:
        fields = self._read_form()
        product_id = required_int(fields, "product_id")
        try:
            self.product_repository.update_product(product_id, self._product_from_fields(fields))
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "List Products", error=f"Could not update product: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=List%20Products&message=Product%20updated")

    def _handle_deactivate_product(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.deactivate_product(required_int(fields, "product_id"))
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "List Products", error=f"Could not deactivate product: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=List%20Products&message=Product%20deactivated")

    def _handle_import_products(self) -> None:
        fields = self._read_form()
        try:
            imported, errors = self.product_repository.import_products_csv(required_text(fields, "csv_text"))
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Import Products", error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        message = f"Imported {imported} products"
        if errors:
            message += f"; {len(errors)} rows skipped"
        self._redirect(f"/dashboard?page=Import%20Products&message={quote(message)}")

    def _handle_import_opening_stock(self) -> None:
        fields = self._read_form()
        try:
            imported, errors = self.product_repository.import_opening_stock_csv(required_text(fields, "csv_text"))
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Import Opening Stock", error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        message = f"Imported opening stock for {imported} products"
        if errors:
            message += f"; {len(errors)} rows skipped"
        self._redirect(f"/dashboard?page=Import%20Opening%20Stock&message={quote(message)}")

    def _handle_create_variation(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_variation(
                VariationFormData(
                    name=required_text(fields, "name"),
                    values_text=required_text(fields, "values_text"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Variations", error=f"Could not save variation: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Variations&message=Variation%20saved")

    def _handle_create_variant(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_product_variant(
                ProductVariantFormData(
                    product_id=required_int(fields, "product_id"),
                    sku=required_text(fields, "sku"),
                    barcode=form_text(fields, "barcode"),
                    variation_summary=required_text(fields, "variation_summary"),
                    option_values_text=form_text(fields, "option_values_text"),
                    purchase_price=money_value(fields, "purchase_price"),
                    selling_price=money_value(fields, "selling_price"),
                    alert_quantity=money_value(fields, "alert_quantity"),
                    image_path=form_text(fields, "image_path"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Variations", error=f"Could not save variant: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Variations&message=Variant%20saved")

    def _handle_create_price_group(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_price_group(
                PriceGroupFormData(
                    name=required_text(fields, "name"),
                    description=form_text(fields, "description"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Selling Price Groups", error=f"Could not save price group: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Selling%20Price%20Groups&message=Price%20group%20saved")

    def _handle_update_price_group(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.update_price_group(
                required_int(fields, "group_id"),
                PriceGroupFormData(
                    name=required_text(fields, "name"),
                    description=form_text(fields, "description"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                ),
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Selling Price Groups", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Selling Price Groups", error=f"Could not update price group: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Selling%20Price%20Groups&message=Price%20group%20updated")

    def _handle_create_warranty(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_warranty(
                WarrantyFormData(
                    name=required_text(fields, "name"),
                    duration_value=required_int(fields, "duration_value"),
                    duration_unit=required_text(fields, "duration_unit"),
                    description=form_text(fields, "description"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Warranties", error=f"Could not save warranty: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Warranties&message=Warranty%20saved")

    def _handle_create_contact(self) -> None:
        fields = self._read_form()
        contact_type = form_text(fields, "contact_type")
        page_by_type = {
            "customer": "Customers",
            "supplier": "Suppliers",
            "both": form_text(fields, "return_page") or "Suppliers",
        }
        if contact_type not in page_by_type:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid contact type")
            return

        try:
            self.contact_repository.create_contact(self._contact_from_fields(fields, contact_type))
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), page_by_type[contact_type], error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    page_by_type[contact_type],
                    error=f"Could not save contact: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/dashboard?page={quote(page_by_type[contact_type])}&message=Contact%20saved")

    def _handle_update_contact(self) -> None:
        fields = self._read_form()
        contact_type = form_text(fields, "contact_type")
        page_by_type = {
            "customer": "Customers",
            "supplier": "Suppliers",
            "both": form_text(fields, "return_page") or "Suppliers",
        }
        if contact_type not in page_by_type:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid contact type")
            return

        try:
            self.contact_repository.update_contact(
                required_int(fields, "contact_id"),
                self._contact_from_fields(fields, contact_type),
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), page_by_type[contact_type], error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    page_by_type[contact_type],
                    error=f"Could not update contact: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/dashboard?page={quote(page_by_type[contact_type])}&message=Contact%20updated")

    def _contact_from_fields(self, fields: dict[str, list[str]], contact_type: str) -> ContactFormData:
        return ContactFormData(
            contact_type=contact_type,
            supplier_type=form_text(fields, "supplier_type") or "business",
            name=required_text(fields, "name"),
            business_name=form_text(fields, "business_name"),
            contact_code=form_text(fields, "contact_code"),
            tax_number=form_text(fields, "tax_number"),
            phone=form_text(fields, "phone"),
            alternate_phone=form_text(fields, "alternate_phone"),
            email=form_text(fields, "email"),
            website=form_text(fields, "website"),
            address=form_text(fields, "address"),
            city=form_text(fields, "city"),
            state=form_text(fields, "state"),
            country=form_text(fields, "country"),
            postal_code=form_text(fields, "postal_code"),
            payment_terms=form_text(fields, "payment_terms"),
            credit_days=optional_int(fields, "credit_days") or 0,
            opening_balance=money_value(fields, "opening_balance"),
            credit_limit=money_value(fields, "credit_limit"),
            customer_group_id=optional_int(fields, "customer_group_id") if contact_type in {"customer", "both"} else None,
            contact_person_1_name=form_text(fields, "contact_person_1_name"),
            contact_person_1_designation=form_text(fields, "contact_person_1_designation"),
            contact_person_1_phone=form_text(fields, "contact_person_1_phone"),
            contact_person_1_email=form_text(fields, "contact_person_1_email"),
            contact_person_2_name=form_text(fields, "contact_person_2_name"),
            contact_person_2_designation=form_text(fields, "contact_person_2_designation"),
            contact_person_2_phone=form_text(fields, "contact_person_2_phone"),
            contact_person_2_email=form_text(fields, "contact_person_2_email"),
            contact_person_3_name=form_text(fields, "contact_person_3_name"),
            contact_person_3_designation=form_text(fields, "contact_person_3_designation"),
            contact_person_3_phone=form_text(fields, "contact_person_3_phone"),
            contact_person_3_email=form_text(fields, "contact_person_3_email"),
            notes=form_text(fields, "notes"),
            is_active=1 if form_text(fields, "is_active") == "1" else 0,
        )

    def _handle_deactivate_contact(self) -> None:
        fields = self._read_form()
        contact_type = form_text(fields, "contact_type")
        page = form_text(fields, "return_page") or ("Customers" if contact_type == "customer" else "Suppliers")
        try:
            self.contact_repository.deactivate_contact(required_int(fields, "contact_id"))
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), page, error=f"Could not deactivate contact: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect(f"/dashboard?page={quote(page)}&message=Contact%20deactivated")

    def _handle_create_customer_group(self) -> None:
        fields = self._read_form()
        try:
            group = CustomerGroupFormData(
                name=required_text(fields, "name"),
                price_discount_percent=money_value(fields, "price_discount_percent"),
                note=form_text(fields, "note"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.contact_repository.create_customer_group(group)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Customer Groups", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Customer Groups", error=f"Could not save group: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Customer%20Groups&message=Customer%20group%20saved")

    def _handle_update_customer_group(self) -> None:
        fields = self._read_form()
        try:
            group = CustomerGroupFormData(
                name=required_text(fields, "name"),
                price_discount_percent=money_value(fields, "price_discount_percent"),
                note=form_text(fields, "note"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.contact_repository.update_customer_group(required_int(fields, "group_id"), group)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Customer Groups", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Customer Groups", error=f"Could not update group: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Customer%20Groups&message=Customer%20group%20updated")

    def _handle_import_contacts(self) -> None:
        fields = self._read_form()
        try:
            imported, errors = self.contact_repository.import_contacts_csv(required_text(fields, "csv_text"))
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Import Contacts", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        message = f"Imported {imported} contacts"
        if errors:
            message += f"; {len(errors)} rows skipped: {' | '.join(errors[:5])}"
        self._redirect(f"/dashboard?page=Import%20Contacts&message={quote(message)}")

    def _handle_create_purchase(self) -> None:
        fields = self._read_form()
        try:
            purchase_date = required_text(fields, "purchase_date")
            split_payments = self._purchase_payment_entries(fields, purchase_date)
            paid_amount = (
                sum(payment.amount for payment in split_payments)
                if split_payments
                else money_value(fields, "paid_amount")
            )
            payment_method = (
                "split"
                if len(split_payments) > 1
                else (split_payments[0].payment_type if split_payments else form_text(fields, "payment_method") or "cash")
            )
            if "product_ids" in fields:
                product_ids = fields.get("product_ids", [])
                quantities = fields.get("quantities", [])
                purchase_prices = fields.get("purchase_prices", [])
                items = []
                for index, product_id_text in enumerate(product_ids):
                    if not product_id_text.strip():
                        continue
                    items.append(
                        PurchaseItemData(
                            product_id=int(product_id_text),
                            quantity=float(quantities[index] if index < len(quantities) else 0),
                            purchase_price=float(purchase_prices[index] if index < len(purchase_prices) else 0),
                        )
                    )
                purchase_id = self.purchase_repository.create_checkout_purchase(
                    PurchaseCheckoutData(
                        supplier_id=optional_int(fields, "supplier_id"),
                        location_id=1,
                        invoice_no=required_text(fields, "invoice_no"),
                        purchase_date=purchase_date,
                        items=items,
                        discount=money_value(fields, "discount"),
                        tax=money_value(fields, "tax"),
                        paid_amount=paid_amount,
                        payment_method=payment_method,
                        payments=split_payments,
                    )
                )
            else:
                purchase = PurchaseFormData(
                    supplier_id=optional_int(fields, "supplier_id"),
                    location_id=1,
                    invoice_no=required_text(fields, "invoice_no"),
                    purchase_date=purchase_date,
                    product_id=required_int(fields, "product_id"),
                    quantity=money_value(fields, "quantity"),
                    purchase_price=money_value(fields, "purchase_price"),
                    discount=money_value(fields, "discount"),
                    tax=money_value(fields, "tax"),
                    paid_amount=paid_amount,
                    payment_method=payment_method,
                )
                purchase_id = self.purchase_repository.create_checkout_purchase(
                    PurchaseCheckoutData(
                        supplier_id=purchase.supplier_id,
                        location_id=purchase.location_id,
                        invoice_no=purchase.invoice_no,
                        purchase_date=purchase.purchase_date,
                        items=[
                            PurchaseItemData(
                                product_id=purchase.product_id,
                                quantity=purchase.quantity,
                                purchase_price=purchase.purchase_price,
                            )
                        ],
                        discount=purchase.discount,
                        tax=purchase.tax,
                        paid_amount=purchase.paid_amount,
                        payment_method=purchase.payment_method,
                        payments=split_payments,
                    )
                )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Add Purchase", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Add Purchase", error=f"Could not save purchase: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/purchases/detail?id={purchase_id}")

    @staticmethod
    def _purchase_payment_entries(
        fields: dict[str, list[str]],
        purchase_date: str,
    ) -> list[PurchasePaymentData]:
        payments: list[PurchasePaymentData] = []
        cash_amount = money_value(fields, "cash_amount")
        cheque_amount = money_value(fields, "cheque_amount")
        if cash_amount > 0:
            payments.append(
                PurchasePaymentData(
                    payment_type=form_text(fields, "cash_method") or "cash",
                    amount=cash_amount,
                    payment_date=purchase_date,
                    note="Purchase cash payment",
                )
            )
        if cheque_amount > 0:
            payments.append(
                PurchasePaymentData(
                    payment_type="cheque",
                    amount=cheque_amount,
                    payment_date=purchase_date,
                    cheque_no=required_text(fields, "cheque_no"),
                    cheque_date=form_text(fields, "cheque_date") or purchase_date,
                    bank_name=form_text(fields, "cheque_bank"),
                    note=form_text(fields, "cheque_note") or "Pending purchase cheque",
                )
            )
        return payments

    def _handle_purchase_cheque_status(self) -> None:
        fields = self._read_form()
        return_to = form_text(fields, "return_to")
        try:
            self.purchase_repository.update_cheque_status(
                payment_id=required_int(fields, "payment_id"),
                status=required_text(fields, "status"),
                action_date=required_text(fields, "action_date"),
                note=form_text(fields, "note"),
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Pending Cheques", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        if return_to.startswith("/purchases/detail"):
            separator = "&" if "?" in return_to else "?"
            self._redirect(f"{return_to}{separator}message=Cheque%20status%20updated")
            return
        self._redirect("/dashboard?page=Pending%20Cheques&message=Cheque%20status%20updated")

    def _handle_create_purchase_product(self) -> None:
        fields = self._read_form()
        try:
            barcode = form_text(fields, "barcode") or self.settings_repository.generate_product_barcode()
            product = ProductFormData(
                name=required_text(fields, "name"),
                sku=required_text(fields, "sku"),
                barcode=barcode,
                image_path="",
                category_id=optional_int(fields, "category_id"),
                brand_id=optional_int(fields, "brand_id"),
                unit_id=optional_int(fields, "unit_id"),
                purchase_price=money_value(fields, "purchase_price"),
                selling_price=money_value(fields, "selling_price"),
                offer_price=0,
                offer_start_date="",
                offer_end_date="",
                tax_rate_id=None,
                warranty_id=None,
                profit_margin=0,
                alert_quantity=money_value(fields, "alert_quantity"),
                is_active=1,
            )
            quantity = money_value(fields, "quantity")
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            product_id = self.product_repository.create_product(product)
        except Exception as error:
            self._send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(
            {
                "ok": True,
                "product": {
                    "id": product_id,
                    "name": product.name,
                    "sku": product.sku,
                    "purchase_price": product.purchase_price,
                    "quantity": quantity,
                },
            }
        )

    def _handle_create_purchase_order(self) -> None:
        fields = self._read_form()
        try:
            order = PurchaseOrderFormData(
                supplier_id=optional_int(fields, "supplier_id"),
                location_id=1,
                order_no=required_text(fields, "order_no"),
                order_date=required_text(fields, "order_date"),
                expected_date=form_text(fields, "expected_date"),
                product_id=required_int(fields, "product_id"),
                quantity=money_value(fields, "quantity"),
                purchase_price=money_value(fields, "purchase_price"),
                status=required_text(fields, "status"),
                note=form_text(fields, "note"),
            )
            self.purchase_order_repository.create_order(order)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Purchase Order", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Purchase Order", error=f"Could not save order: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Purchase%20Order&message=Purchase%20order%20saved")

    def _handle_create_purchase_return(self) -> None:
        fields = self._read_form()
        try:
            purchase_product = required_text(fields, "purchase_product")
            purchase_id_text, product_id_text = purchase_product.split(":", 1)
            purchase_return = PurchaseReturnFormData(
                purchase_id=int(purchase_id_text),
                product_id=int(product_id_text),
                return_date=required_text(fields, "return_date"),
                quantity=money_value(fields, "quantity"),
                refund_amount=money_value(fields, "refund_amount"),
                reason=required_text(fields, "reason"),
                item_condition=required_text(fields, "item_condition"),
                refund_method=required_text(fields, "refund_method"),
                reduce_stock=1 if form_text(fields, "reduce_stock") == "1" else 0,
                note=form_text(fields, "note"),
            )
            self.purchase_return_repository.create_return(purchase_return)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Purchase Return", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Purchase Return",
                    error=f"Could not save purchase return: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Purchase%20Return&message=Purchase%20return%20saved%20and%20stock%20updated")

    def _handle_create_sale(self) -> None:
        fields = self._read_form()
        try:
            split_payments = self._sale_payment_entries(fields)
            paid_amount = sum(payment.amount for payment in split_payments) if split_payments else money_value(fields, "paid_amount")
            payment_method = (
                "multiple"
                if len(split_payments) > 1
                else (split_payments[0].method if split_payments else form_text(fields, "payment_method") or "cash")
            )
            if "product_ids" in fields:
                product_ids = fields.get("product_ids", [])
                quantities = fields.get("quantities", [])
                unit_prices = fields.get("unit_prices", [])
                item_discounts = fields.get("item_discounts", [])
                items = []
                for index, product_id_text in enumerate(product_ids):
                    product_id_text = product_id_text.strip()
                    if not product_id_text:
                        continue
                    quantity_text = quantities[index] if index < len(quantities) else "0"
                    unit_price_text = unit_prices[index] if index < len(unit_prices) else "0"
                    item_discount_text = item_discounts[index] if index < len(item_discounts) else "0"
                    items.append(
                        SaleItemData(
                            product_id=int(product_id_text),
                            quantity=float(quantity_text or 0),
                            unit_price=float(unit_price_text or 0),
                            discount=float(item_discount_text or 0),
                        )
                    )
                checkout = SaleCheckoutData(
                    customer_id=optional_int(fields, "customer_id"),
                    location_id=1,
                    invoice_no=required_text(fields, "invoice_no"),
                    sale_date=required_text(fields, "sale_date"),
                    items=items,
                    discount=money_value(fields, "discount"),
                    tax=money_value(fields, "tax"),
                    paid_amount=paid_amount,
                    payment_method=payment_method,
                    sale_status=form_text(fields, "sale_status") or "final",
                    payments=split_payments,
                )
                source_sale_id = optional_int(fields, "source_sale_id")
                if source_sale_id and checkout.sale_status == "final":
                    sale_id = self.sale_repository.convert_document_to_final(source_sale_id, checkout)
                else:
                    sale_id = self.sale_repository.create_checkout_sale(checkout)
            else:
                sale = SaleFormData(
                    customer_id=optional_int(fields, "customer_id"),
                    location_id=1,
                    invoice_no=required_text(fields, "invoice_no"),
                    sale_date=required_text(fields, "sale_date"),
                    product_id=required_int(fields, "product_id"),
                    quantity=money_value(fields, "quantity"),
                    unit_price=money_value(fields, "unit_price"),
                    discount=money_value(fields, "discount"),
                    tax=money_value(fields, "tax"),
                    paid_amount=paid_amount,
                    payment_method=payment_method,
                )
                sale_id = self.sale_repository.create_sale(sale)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "POS", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "POS", error=f"Could not save sale: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        sale_status = form_text(fields, "sale_status") or "final"
        if sale_status != "final":
            page_by_status = {
                "draft": "Drafts",
                "quotation": "Quotations",
                "suspended": "Suspended Sales",
                "sales_order": "Sales Orders",
            }
            page = page_by_status.get(sale_status, "Sales History")
            self._redirect(f"/dashboard?page={quote(page)}&message=Document%20saved")
            return

        receipt_type = form_text(fields, "receipt_type") or "invoice"
        receipt_paths = {
            "invoice": f"/sales/invoice?id={sale_id}",
            "pos": f"/sales/receipt?id={sale_id}&type=pos",
            "gift": f"/sales/receipt?id={sale_id}&type=gift",
            "delivery": f"/sales/receipt?id={sale_id}&type=delivery",
            "tax": f"/sales/receipt?id={sale_id}&type=tax",
        }
        self._redirect(receipt_paths.get(receipt_type, receipt_paths["invoice"]))

    @staticmethod
    def _sale_payment_entries(fields: dict[str, list[str]]) -> list[SalePaymentData]:
        methods = fields.get("payment_methods", [])
        amounts = fields.get("payment_amounts", [])
        notes = fields.get("payment_notes", [])
        sale_date = form_text(fields, "sale_date")
        payments: list[SalePaymentData] = []
        for index, method in enumerate(methods):
            method = method.strip()
            amount_text = amounts[index] if index < len(amounts) else "0"
            note = notes[index] if index < len(notes) else ""
            amount = float(amount_text or 0)
            if amount <= 0:
                continue
            payments.append(SalePaymentData(method=method, amount=amount, payment_date=sale_date, note=note))
        return payments

    def _handle_create_sales_document(self) -> None:
        fields = self._read_form()
        status = required_text(fields, "sale_status")
        page_by_status = {
            "draft": "Drafts",
            "quotation": "Quotations",
            "suspended": "Suspended Sales",
            "sales_order": "Sales Orders",
        }
        page = page_by_status.get(status, "Drafts")
        try:
            sale = SaleFormData(
                customer_id=optional_int(fields, "customer_id"),
                location_id=1,
                invoice_no=required_text(fields, "invoice_no"),
                sale_date=required_text(fields, "sale_date"),
                product_id=required_int(fields, "product_id"),
                quantity=money_value(fields, "quantity"),
                unit_price=money_value(fields, "unit_price"),
                discount=money_value(fields, "discount"),
                tax=money_value(fields, "tax"),
                paid_amount=0,
                payment_method="cash",
            )
            self.sale_repository.create_non_final_sale(sale, status)
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), page, error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), page, error=f"Could not save document: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page={quote(page)}&message=Document%20saved")

    def _handle_create_shipment(self) -> None:
        fields = self._read_form()
        try:
            shipment = ShipmentFormData(
                sale_id=required_int(fields, "sale_id"),
                shipment_date=required_text(fields, "shipment_date"),
                courier=form_text(fields, "courier"),
                tracking_no=form_text(fields, "tracking_no"),
                status=required_text(fields, "status"),
                note=form_text(fields, "note"),
            )
            self.shipment_repository.create_shipment(shipment)
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Shipments", error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Shipments", error=f"Could not save shipment: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Shipments&message=Shipment%20saved")

    def _handle_create_stock_adjustment(self) -> None:
        fields = self._read_form()
        try:
            adjustment = StockAdjustmentFormData(
                product_id=required_int(fields, "product_id"),
                location_id=required_int(fields, "location_id"),
                adjustment_date=required_text(fields, "adjustment_date"),
                adjustment_type=required_text(fields, "adjustment_type"),
                quantity=money_value(fields, "quantity"),
                reason=form_text(fields, "reason"),
            )
            self.stock_operation_repository.create_adjustment(adjustment)
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Stock Adjustment", error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Stock Adjustment", error=f"Could not save adjustment: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Stock%20Adjustment&message=Stock%20adjustment%20saved")

    def _handle_create_stock_transfer(self) -> None:
        fields = self._read_form()
        try:
            transfer = StockTransferFormData(
                product_id=required_int(fields, "product_id"),
                from_location_id=required_int(fields, "from_location_id"),
                to_location_id=required_int(fields, "to_location_id"),
                transfer_date=required_text(fields, "transfer_date"),
                quantity=money_value(fields, "quantity"),
                note=form_text(fields, "note"),
            )
            self.stock_operation_repository.create_transfer(transfer)
        except ValueError as error:
            self._send_html(render_dashboard(self._current_user_required(), "Stock Transfer", error=str(error)), HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Stock Transfer", error=f"Could not save transfer: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Stock%20Transfer&message=Stock%20transfer%20saved")

    def _handle_create_sales_return(self) -> None:
        fields = self._read_form()
        try:
            sale_return = SalesReturnFormData(
                sale_id=required_int(fields, "sale_id"),
                product_id=required_int(fields, "product_id"),
                return_date=required_text(fields, "return_date"),
                quantity=money_value(fields, "quantity"),
                refund_amount=money_value(fields, "refund_amount"),
                reason=required_text(fields, "reason"),
                item_condition=required_text(fields, "item_condition"),
                refund_method=required_text(fields, "refund_method"),
                return_to_stock=1 if form_text(fields, "return_to_stock") == "1" else 0,
                note=form_text(fields, "note"),
            )
            return_id = self.sales_return_repository.create_return(sale_return)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Returns", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Returns", error=f"Could not save return: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(
            f"/dashboard?page=Returns&message=Sales%20return%20saved&return_id={return_id}"
        )

    def _handle_open_cash_register(self, user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.cash_register_repository.open_register(
                OpenRegisterData(
                    user_id=user.id,
                    location_id=required_int(fields, "location_id"),
                    opening_cash=money_value(fields, "opening_cash"),
                )
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=f"Could not open register: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Cash%20Register&message=Cash%20register%20opened")

    def _handle_close_cash_register(self, user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.cash_register_repository.close_register(
                CloseRegisterData(
                    register_id=required_int(fields, "register_id"),
                    denomination_counts={
                        denomination: int(form_text(fields, f"denomination_{denomination}") or 0)
                        for denomination in CASH_DENOMINATIONS
                    },
                    coins_total=money_value(fields, "coins_total"),
                    closing_note=form_text(fields, "closing_note"),
                    approved_by=user.id if form_text(fields, "manager_approved") == "1" else None,
                )
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=f"Could not close register: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Cash%20Register&message=Cash%20register%20closed")

    def _handle_approve_cash_register(self, user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.cash_register_repository.approve_register(
                register_id=required_int(fields, "register_id"),
                approved_by=user.id,
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=f"Could not approve register: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Cash%20Register&message=Cash%20register%20approved")

    def _handle_cash_register_movement(self) -> None:
        fields = self._read_form()
        try:
            self.cash_register_repository.create_manual_movement(
                CashMovementData(
                    register_id=required_int(fields, "register_id"),
                    movement_type=required_text(fields, "movement_type"),
                    amount=money_value(fields, "amount"),
                    reason=required_text(fields, "reason"),
                )
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Cash Register", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Cash Register",
                    error=f"Could not save cash movement: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Cash%20Register&message=Cash%20movement%20saved")

    def _handle_create_expense(self) -> None:
        fields = self._read_form()
        try:
            user = self._current_user_required()
            expense = ExpenseFormData(
                category_id=optional_int(fields, "category_id"),
                location_id=required_int(fields, "location_id"),
                account_id=required_int(fields, "account_id"),
                expense_date=required_text(fields, "expense_date"),
                expense_time=form_text(fields, "expense_time") or "00:00",
                expense_type=required_text(fields, "expense_type"),
                amount=money_value(fields, "amount"),
                payment_method=required_text(fields, "payment_method"),
                party_name=form_text(fields, "party_name"),
                reference_no=form_text(fields, "reference_no"),
                tax_rate=money_value(fields, "tax_rate"),
                tax_mode=required_text(fields, "tax_mode"),
                status=required_text(fields, "status"),
                recurrence=required_text(fields, "recurrence"),
                attachment_name=form_text(fields, "attachment_name"),
                attachment_data=form_text(fields, "attachment_data"),
                note=required_text(fields, "note"),
                created_by=user.id,
            )
            self.expense_repository.create_expense(expense)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Add Expense", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Add Expense", error=f"Could not save expense: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=List%20Expenses&message=Expense%20saved")

    def _handle_expense_status(self, user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.expense_repository.update_status(
                required_int(fields, "expense_id"),
                required_text(fields, "status"),
                user.id,
            )
        except Exception as error:
            self._redirect(
                f"/dashboard?page=List%20Expenses&error={quote(str(error))}"
            )
            return
        self._redirect("/dashboard?page=List%20Expenses&message=Transaction%20status%20updated")

    def _handle_duplicate_expense(self, user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.expense_repository.duplicate_expense(required_int(fields, "expense_id"), user.id)
        except Exception as error:
            self._redirect(f"/dashboard?page=List%20Expenses&error={quote(str(error))}")
            return
        self._redirect("/dashboard?page=List%20Expenses&message=Draft%20copy%20created")

    def _handle_create_expense_refund(self) -> None:
        fields = self._read_form()
        try:
            refund = ExpenseRefundFormData(
                expense_id=required_int(fields, "expense_id"),
                refund_date=required_text(fields, "refund_date"),
                amount=money_value(fields, "amount"),
                note=form_text(fields, "note"),
            )
            self.expense_repository.create_refund(refund)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Expense Refund", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Expense Refund", error=f"Could not save refund: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Expense%20Refund&message=Expense%20refund%20saved")

    def _handle_create_expense_category(self) -> None:
        fields = self._read_form()
        try:
            self.expense_repository.create_category(
                ExpenseCategoryData(
                    name=required_text(fields, "name"),
                    parent_id=optional_int(fields, "parent_id"),
                    transaction_type=required_text(fields, "transaction_type"),
                    monthly_budget=money_value(fields, "monthly_budget"),
                    requires_attachment=1 if form_text(fields, "requires_attachment") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Expense Categories",
                    error=f"Could not save category: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Expense%20Categories&message=Category%20saved")

    def _handle_update_expense_settings(self) -> None:
        fields = self._read_form()
        try:
            self.expense_repository.update_settings(
                ExpenseSettingsData(
                    default_account_id=required_int(fields, "default_account_id"),
                    default_location_id=required_int(fields, "default_location_id"),
                    approval_limit=money_value(fields, "approval_limit"),
                    require_attachment_over=money_value(fields, "require_attachment_over"),
                    reference_prefix=required_text(fields, "reference_prefix"),
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Expense Controls",
                    error=f"Could not update expense settings: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Expense%20Controls&message=Expense%20settings%20updated")

    def _handle_create_deposit(self) -> None:
        fields = self._read_form()
        try:
            deposit = DepositFormData(
                account_id=required_int(fields, "account_id"),
                amount=money_value(fields, "amount"),
                payment_date=required_text(fields, "payment_date"),
                method=form_text(fields, "method") or "cash",
                note=form_text(fields, "note"),
            )
            self.payment_repository.create_deposit(deposit)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Deposits", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Deposits", error=f"Could not save deposit: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Transactions&message=Deposit%20saved")

    def _handle_create_payment_account(self) -> None:
        fields = self._read_form()
        try:
            account = AccountFormData(
                name=required_text(fields, "name"),
                account_type=required_text(fields, "account_type"),
                opening_balance=money_value(fields, "opening_balance"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.payment_repository.create_account(account)
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Accounts", error=f"Could not save account: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Accounts&message=Account%20saved")

    def _handle_create_transfer(self) -> None:
        fields = self._read_form()
        try:
            transfer = TransferFormData(
                from_account_id=required_int(fields, "from_account_id"),
                to_account_id=required_int(fields, "to_account_id"),
                transfer_date=required_text(fields, "transfer_date"),
                amount=money_value(fields, "amount"),
                note=form_text(fields, "note"),
            )
            self.payment_repository.create_transfer(transfer)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Transfers", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Transfers", error=f"Could not save transfer: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Transfers&message=Transfer%20saved")

    def _handle_create_customer_payment(self) -> None:
        fields = self._read_form()
        try:
            self.payment_repository.record_customer_payment(
                DuePaymentData(
                    reference_id=required_int(fields, "sale_id"),
                    account_id=required_int(fields, "account_id"),
                    amount=money_value(fields, "amount"),
                    method=required_text(fields, "method"),
                    payment_date=required_text(fields, "payment_date"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Customer Payments", error=f"Could not save customer payment: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Customer%20Payments&message=Customer%20payment%20saved")

    def _handle_create_supplier_payment(self) -> None:
        fields = self._read_form()
        try:
            self.payment_repository.record_supplier_payment(
                DuePaymentData(
                    reference_id=required_int(fields, "purchase_id"),
                    account_id=required_int(fields, "account_id"),
                    amount=money_value(fields, "amount"),
                    method=required_text(fields, "method"),
                    payment_date=required_text(fields, "payment_date"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Supplier Payments", error=f"Could not save supplier payment: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Supplier%20Payments&message=Supplier%20payment%20saved")

    def _handle_update_business_settings(self) -> None:
        fields = self._read_form()
        try:
            settings = BusinessSettingsData(
                business_name=required_text(fields, "business_name"),
                currency_symbol=required_text(fields, "currency_symbol"),
                tax_number=form_text(fields, "tax_number"),
                phone=form_text(fields, "phone"),
                email=form_text(fields, "email"),
                address=form_text(fields, "address"),
            )
            self.settings_repository.update_business_settings(settings)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Business Settings", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Business Settings",
                    error=f"Could not update business settings: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Business%20Settings&message=Business%20settings%20saved")

    def _handle_create_location(self) -> None:
        fields = self._read_form()
        try:
            location = LocationData(
                name=required_text(fields, "name"),
                phone=form_text(fields, "phone"),
                address=form_text(fields, "address"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.settings_repository.create_location(location)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Business Locations", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Business Locations",
                    error=f"Could not save location: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Business%20Locations&message=Location%20saved")

    def _handle_update_invoice_settings(self) -> None:
        fields = self._read_form()
        try:
            settings = InvoiceSettingsData(
                invoice_prefix=required_text(fields, "invoice_prefix"),
                next_invoice_number=required_int(fields, "next_invoice_number"),
                receipt_footer=form_text(fields, "receipt_footer"),
                terms=form_text(fields, "terms"),
                show_tax=1 if form_text(fields, "show_tax") == "1" else 0,
                show_logo=1 if form_text(fields, "show_logo") == "1" else 0,
            )
            self.settings_repository.update_invoice_settings(settings)
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Invoice Settings", error=f"Could not save invoice settings: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Invoice%20Settings&message=Invoice%20settings%20saved")

    def _handle_update_barcode_settings(self) -> None:
        fields = self._read_form()
        try:
            settings = BarcodeSettingsData(
                barcode_prefix=required_text(fields, "barcode_prefix"),
                next_barcode_number=required_int(fields, "next_barcode_number"),
                label_width=money_value(fields, "label_width"),
                label_height=money_value(fields, "label_height"),
                copies_per_product=required_int(fields, "copies_per_product"),
                show_price=1 if form_text(fields, "show_price") == "1" else 0,
                show_product_name=1 if form_text(fields, "show_product_name") == "1" else 0,
            )
            self.settings_repository.update_barcode_settings(settings)
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Barcode Settings", error=f"Could not save barcode settings: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Barcode%20Settings&message=Barcode%20settings%20saved")

    def _handle_generate_barcode(self) -> None:
        try:
            barcode = self.settings_repository.generate_product_barcode()
        except Exception as error:
            self._send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "barcode": barcode})

    def _handle_create_tax_rate(self) -> None:
        fields = self._read_form()
        try:
            self.settings_repository.create_tax_rate(
                TaxRateData(name=required_text(fields, "name"), rate=money_value(fields, "rate"))
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Tax Rates", error=f"Could not save tax rate: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Tax%20Rates&message=Tax%20rate%20saved")

    def _handle_create_payment_method(self) -> None:
        fields = self._read_form()
        try:
            self.settings_repository.create_payment_method(
                PaymentMethodData(
                    name=required_text(fields, "name"),
                    method_key=required_text(fields, "method_key"),
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Payment Methods", error=f"Could not save payment method: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Payment%20Methods&message=Payment%20method%20saved")

    def _handle_create_printer(self) -> None:
        fields = self._read_form()
        try:
            self.settings_repository.create_printer(
                PrinterSettingsData(
                    name=required_text(fields, "name"),
                    printer_type=required_text(fields, "printer_type"),
                    connection_type=required_text(fields, "connection_type"),
                    paper_width=required_text(fields, "paper_width"),
                    device_name=form_text(fields, "device_name"),
                    is_default=1 if form_text(fields, "is_default") == "1" else 0,
                    is_active=1 if form_text(fields, "is_active") == "1" else 0,
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Printers", error=f"Could not save printer: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Printers&message=Printer%20saved")

    def _handle_create_role(self) -> None:
        fields = self._read_form()
        try:
            self.user_repository.create_role(
                name=required_text(fields, "name"),
                description=form_text(fields, "description"),
                permissions_text=normalise_permissions(fields.get("permissions", [])),
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Roles", error=f"Could not save role: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Roles&message=Role%20saved")

    def _handle_update_role(self) -> None:
        fields = self._read_form()
        try:
            self.user_repository.update_role(
                role_id=required_int(fields, "role_id"),
                name=required_text(fields, "name"),
                description=form_text(fields, "description"),
                permissions_text=normalise_permissions(fields.get("permissions", [])),
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Roles", error=f"Could not update role: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Roles&message=Role%20updated")

    def _handle_create_user(self) -> None:
        fields = self._read_form()
        try:
            user = UserFormData(
                role_id=required_int(fields, "role_id"),
                username=required_text(fields, "username"),
                password=required_text(fields, "password"),
                full_name=required_text(fields, "full_name"),
                phone=form_text(fields, "phone"),
                email=form_text(fields, "email"),
                address=form_text(fields, "address"),
                emergency_contact=form_text(fields, "emergency_contact"),
                permissions_text=normalise_permissions(fields.get("permissions", [])),
                sales_commission_rate=money_value(fields, "sales_commission_rate"),
                sales_target=money_value(fields, "sales_target"),
                bank_name=form_text(fields, "bank_name"),
                bank_account_name=form_text(fields, "bank_account_name"),
                bank_account_number=form_text(fields, "bank_account_number"),
                bank_branch=form_text(fields, "bank_branch"),
                employee_no=form_text(fields, "employee_no"),
                department=form_text(fields, "department"),
                designation=form_text(fields, "designation"),
                joining_date=form_text(fields, "joining_date"),
                employment_type=form_text(fields, "employment_type"),
                basic_salary=money_value(fields, "basic_salary"),
                pay_frequency=form_text(fields, "pay_frequency"),
                allowances=money_value(fields, "allowances"),
                deductions=money_value(fields, "deductions"),
                is_active=1 if form_text(fields, "is_active") == "1" else 0,
            )
            self.user_repository.create_user(user)
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Users", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Users", error=f"Could not save user: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Users&message=User%20saved")

    def _handle_deactivate_user(self, current_user: AuthenticatedUser) -> None:
        fields = self._read_form()
        try:
            self.user_repository.deactivate_user(
                user_id=required_int(fields, "user_id"),
                current_user_id=current_user.id,
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Users", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Users", error=f"Could not deactivate user: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Users&message=User%20deactivated")

    def _handle_create_commission_agent(self) -> None:
        fields = self._read_form()
        try:
            self.commission_agent_repository.create_agent(self._commission_agent_from_fields(fields))
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Sales Commission Agents", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Sales Commission Agents",
                    error=f"Could not save agent: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Sales%20Commission%20Agents&message=Agent%20saved")

    def _handle_update_commission_agent(self) -> None:
        fields = self._read_form()
        try:
            self.commission_agent_repository.update_agent(
                required_int(fields, "agent_id"),
                self._commission_agent_from_fields(fields),
            )
        except ValueError as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Sales Commission Agents", error=str(error)),
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Sales Commission Agents",
                    error=f"Could not update agent: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Sales%20Commission%20Agents&message=Agent%20updated")

    def _commission_agent_from_fields(self, fields: dict[str, list[str]]) -> CommissionAgentFormData:
        return CommissionAgentFormData(
            name=required_text(fields, "name"),
            agent_code=form_text(fields, "agent_code"),
            phone=form_text(fields, "phone"),
            email=form_text(fields, "email"),
            commission_rate=money_value(fields, "commission_rate"),
            sales_target=money_value(fields, "sales_target"),
            territory=form_text(fields, "territory"),
            payout_frequency=form_text(fields, "payout_frequency"),
            payable_account=form_text(fields, "payable_account"),
            address=form_text(fields, "address"),
            notes=form_text(fields, "notes"),
            is_active=1 if form_text(fields, "is_active") == "1" else 0,
        )

    def _handle_create_backup(self) -> None:
        try:
            self.backup_service.create_backup()
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Backup", error=f"Could not create backup: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect("/dashboard?page=Backup&message=Backup%20created")

    def _handle_verify_backup(self) -> None:
        fields = self._read_form()
        backup_name = required_text(fields, "backup_name")
        try:
            status = self.backup_service.verify_backup(backup_name)
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Backup", error=f"Could not verify backup: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect(f"/dashboard?page=Backup&message={quote('Backup verified: ' + status)}")

    def _handle_restore_backup(self) -> None:
        fields = self._read_form()
        backup_name = required_text(fields, "backup_name")
        confirmation = required_text(fields, "restore_confirmation")
        try:
            pre_restore = self.backup_service.restore_backup(backup_name, confirmation)
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Backup", error=f"Could not restore backup: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        message = f"Backup restored. Safety backup created first: {pre_restore.name}"
        self._redirect(f"/dashboard?page=Backup&message={quote(message)}")

    def _handle_backup_settings(self) -> None:
        fields = self._read_form()
        try:
            retention_count = required_int(fields, "retention_count")
            self.backup_service.update_settings(
                enabled=form_text(fields, "enabled") == "1",
                schedule=required_text(fields, "schedule"),
                retention_count=retention_count,
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "Backup", error=f"Could not save backup settings: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Backup&message=Backup%20settings%20saved")

    def _handle_create_lookup(self) -> None:
        fields = self._read_form()
        lookup_type = form_text(fields, "lookup_type")
        table_by_type = {
            "category": ("product_categories", "Categories"),
            "brand": ("product_brands", "Brands"),
            "unit": ("product_units", "Units"),
        }
        if lookup_type not in table_by_type:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return

        table, page = table_by_type[lookup_type]
        try:
            self.product_repository.create_lookup(
                table=table,
                name=required_text(fields, "name"),
                short_name=form_text(fields, "short_name"),
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), page, f"Could not save: {error}"), HTTPStatus.BAD_REQUEST)
            return

        self._redirect(f"/dashboard?page={quote(page)}&message=Saved")

    def _category_from_fields(self, fields: dict[str, list[str]]) -> CategoryFormData:
        display_order = required_int(fields, "display_order")
        if display_order < 0:
            raise ValueError("Display order cannot be negative.")
        return CategoryFormData(
            name=required_text(fields, "name"),
            parent_id=optional_int(fields, "parent_id"),
            code=form_text(fields, "code"),
            description=form_text(fields, "description"),
            image_path=form_text(fields, "image_path"),
            color_hex=form_text(fields, "color_hex") or "#0f766e",
            default_tax_rate_id=optional_int(fields, "default_tax_rate_id"),
            default_unit_id=optional_int(fields, "default_unit_id"),
            default_warranty_id=optional_int(fields, "default_warranty_id"),
            default_profit_margin=money_value(fields, "default_profit_margin"),
            attributes_text=form_text(fields, "attributes_text"),
            display_order=display_order,
            show_on_pos=1 if form_text(fields, "show_on_pos") == "1" else 0,
            is_active=1 if form_text(fields, "is_active") == "1" else 0,
        )

    def _handle_create_category(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_category(self._category_from_fields(fields))
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Categories",
                    error=f"Could not save category: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Categories&message=Category%20saved")

    def _handle_apply_category_template(self) -> None:
        fields = self._read_form()
        try:
            created = self.product_repository.apply_category_template(required_text(fields, "template_key"))
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Categories",
                    error=f"Could not apply category template: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        message = f"Category template applied; {created} categories added"
        self._redirect(f"/dashboard?page=Categories&message={quote(message)}")

    def _handle_update_category(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.update_category(
                required_int(fields, "category_id"),
                self._category_from_fields(fields),
            )
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Categories",
                    error=f"Could not update category: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Categories&message=Category%20updated")

    def _handle_deactivate_category(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.deactivate_category(required_int(fields, "category_id"))
        except Exception as error:
            self._send_html(
                render_dashboard(
                    self._current_user_required(),
                    "Categories",
                    error=f"Could not deactivate category: {error}",
                ),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/dashboard?page=Categories&message=Category%20deactivated")

    def _brand_from_fields(self, fields: dict[str, list[str]]) -> BrandFormData:
        return BrandFormData(
            name=required_text(fields, "name"),
            code=form_text(fields, "code"),
            logo_path=form_text(fields, "logo_path"),
            website=form_text(fields, "website"),
            contact_person=form_text(fields, "contact_person"),
            phone=form_text(fields, "phone"),
            email=form_text(fields, "email"),
            country=form_text(fields, "country"),
            supplier_id=optional_int(fields, "supplier_id"),
            default_warranty_id=optional_int(fields, "default_warranty_id"),
            default_profit_margin=money_value(fields, "default_profit_margin"),
            description=form_text(fields, "description"),
            is_active=1 if form_text(fields, "is_active") == "1" else 0,
        )

    def _handle_create_brand(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.create_brand(self._brand_from_fields(fields))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Brands", error=f"Could not save brand: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Brands&message=Brand%20saved")

    def _handle_apply_brand_template(self) -> None:
        fields = self._read_form()
        try:
            created = self.product_repository.apply_brand_template(required_text(fields, "template_key"))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Brands", error=f"Could not apply brand template: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=Brands&message={quote(f'Brand template applied; {created} brands added')}")

    def _handle_update_brand(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.update_brand(required_int(fields, "brand_id"), self._brand_from_fields(fields))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Brands", error=f"Could not update brand: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Brands&message=Brand%20updated")

    def _handle_deactivate_brand(self) -> None:
        fields = self._read_form()
        try:
            self.product_repository.deactivate_brand(required_int(fields, "brand_id"))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "Brands", error=f"Could not deactivate brand: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect("/dashboard?page=Brands&message=Brand%20deactivated")

    def _handle_update_addon(self) -> None:
        fields = self._read_form()
        module_key = required_text(fields, "module_key")
        module = self.addon_repository.get_module(module_key)
        if module is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Addon not found")
            return

        try:
            self.addon_repository.update_module(
                AddonModuleUpdateData(
                    module_key=module_key,
                    is_enabled=1 if form_text(fields, "is_enabled") == "1" else 0,
                    connection_mode=required_text(fields, "connection_mode"),
                    endpoint_url=form_text(fields, "endpoint_url"),
                    token_label=form_text(fields, "token_label"),
                    notes=form_text(fields, "notes"),
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), module["name"], error=f"Could not save addon: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/dashboard?page={quote(module['name'])}&message=Addon%20settings%20saved")

    def _handle_create_addon_work_item(self) -> None:
        fields = self._read_form()
        module_key = required_text(fields, "module_key")
        module = self.addon_repository.get_module(module_key)
        if module is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Addon not found")
            return

        try:
            self.addon_repository.create_work_item(
                AddonWorkItemData(
                    module_key=module_key,
                    title=required_text(fields, "title"),
                    status=required_text(fields, "status"),
                    owner=form_text(fields, "owner"),
                    due_date=form_text(fields, "due_date"),
                    notes=form_text(fields, "notes"),
                )
            )
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), module["name"], error=f"Could not save work item: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/dashboard?page={quote(module['name'])}&message=Work%20item%20saved")

    def _handle_update_addon_work_status(self) -> None:
        fields = self._read_form()
        try:
            module_key = self.addon_repository.update_work_item_status(
                required_int(fields, "work_item_id"),
                required_text(fields, "status"),
            )
            module = self.addon_repository.get_module(module_key)
            if module is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Addon not found")
                return
        except Exception as error:
            self._send_html(
                render_dashboard(self._current_user_required(), "API Connector", error=f"Could not update work item: {error}"),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self._redirect(f"/dashboard?page={quote(module['name'])}&message=Work%20status%20updated")

    def _handle_run_addon_sync(self) -> None:
        fields = self._read_form()
        module_key = required_text(fields, "module_key")
        module = self.addon_repository.get_module(module_key)
        if module is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Addon not found")
            return

        summary = self.addon_repository.module_summary(module_key)
        if summary["pending"] or summary["in_progress"]:
            status = "attention"
            details = f"{summary['pending']} pending and {summary['in_progress']} in progress work items remain."
        elif not module["is_enabled"]:
            status = "ready-disabled"
            details = "Addon work is complete. Enable the module when the business is ready to use it."
        else:
            status = "ready"
            mode = str(module["connection_mode"]).replace("_", " ").title()
            endpoint = module["endpoint_url"] or "No endpoint configured"
            details = f"Addon is enabled with {mode} mode. Endpoint: {endpoint}."

        self.addon_repository.record_sync_log(module_key, "manual_check", status, details)
        self._redirect(f"/dashboard?page={quote(module['name'])}&message=Addon%20check%20logged")

    def _handle_woocommerce_action(self, action: str) -> None:
        module = self.addon_repository.get_module("woocommerce")
        if module is None:
            self.send_error(HTTPStatus.NOT_FOUND, "WooCommerce addon not found")
            return
        action_labels = {
            "test": "test_connection",
            "import_products": "import_products",
            "import_customers": "import_customers",
            "import_orders": "import_orders",
            "push_stock": "push_stock",
        }
        try:
            if action == "test":
                result = self.woocommerce_service.test_connection(module)
            elif action == "import_products":
                result = self.woocommerce_service.import_products(module)
            elif action == "import_customers":
                result = self.woocommerce_service.import_customers(module)
            elif action == "import_orders":
                result = self.woocommerce_service.import_orders(module)
            elif action == "push_stock":
                result = self.woocommerce_service.push_stock(module)
            else:
                raise ValueError("Unsupported WooCommerce action.")
        except Exception as error:
            details = f"{action_labels.get(action, action)} failed: {error}"
            self.addon_repository.record_sync_log("woocommerce", action_labels.get(action, action), "failed", details)
            self._send_html(
                render_dashboard(self._current_user_required(), "WooCommerce", error=details),
                HTTPStatus.BAD_REQUEST,
            )
            return

        self.addon_repository.record_sync_log("woocommerce", action_labels[action], result.status, result.details)
        self._redirect(f"/dashboard?page=WooCommerce&message={quote(result.details)}")

    def _handle_save_hrm_attendance(self) -> None:
        fields = self._read_form()
        tab = "attendance"
        try:
            self.hrm_repository.save_attendance(
                AttendanceData(
                    user_id=required_int(fields, "user_id"),
                    attendance_date=required_text(fields, "attendance_date"),
                    status=required_text(fields, "status"),
                    check_in=form_text(fields, "check_in"),
                    check_out=form_text(fields, "check_out"),
                    overtime_hours=money_value(fields, "overtime_hours"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "HRM / Essentials", query={"tab": [tab]}, error=f"Could not save attendance: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=HRM%20%2F%20Essentials&tab={tab}&message=Attendance%20saved")

    def _handle_create_hrm_leave(self) -> None:
        fields = self._read_form()
        tab = "leave"
        try:
            self.hrm_repository.create_leave(
                LeaveRequestData(
                    user_id=required_int(fields, "user_id"),
                    leave_type=required_text(fields, "leave_type"),
                    date_from=required_text(fields, "date_from"),
                    date_to=required_text(fields, "date_to"),
                    days=money_value(fields, "days"),
                    reason=form_text(fields, "reason"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "HRM / Essentials", query={"tab": [tab]}, error=f"Could not save leave: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=HRM%20%2F%20Essentials&tab={tab}&message=Leave%20request%20saved")

    def _handle_update_hrm_leave_status(self) -> None:
        fields = self._read_form()
        tab = "leave"
        try:
            self.hrm_repository.update_leave_status(required_int(fields, "leave_id"), required_text(fields, "status"))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "HRM / Essentials", query={"tab": [tab]}, error=f"Could not update leave: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=HRM%20%2F%20Essentials&tab={tab}&message=Leave%20status%20updated")

    def _handle_save_hrm_payroll(self) -> None:
        fields = self._read_form()
        tab = "payroll"
        try:
            self.hrm_repository.save_payroll(
                PayrollData(
                    user_id=required_int(fields, "user_id"),
                    pay_period=required_text(fields, "pay_period"),
                    basic_salary=money_value(fields, "basic_salary"),
                    allowances=money_value(fields, "allowances"),
                    overtime_amount=money_value(fields, "overtime_amount"),
                    commission_amount=money_value(fields, "commission_amount"),
                    deductions=money_value(fields, "deductions"),
                    payment_status=required_text(fields, "payment_status"),
                    payment_date=form_text(fields, "payment_date"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "HRM / Essentials", query={"tab": [tab]}, error=f"Could not save payroll: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=HRM%20%2F%20Essentials&tab={tab}&message=Payroll%20saved")

    def _handle_create_hrm_document(self) -> None:
        fields = self._read_form()
        tab = "documents"
        try:
            self.hrm_repository.create_document(
                DocumentData(
                    user_id=required_int(fields, "user_id"),
                    document_type=required_text(fields, "document_type"),
                    document_no=form_text(fields, "document_no"),
                    expiry_date=form_text(fields, "expiry_date"),
                    status=required_text(fields, "status"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "HRM / Essentials", query={"tab": [tab]}, error=f"Could not save document: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=HRM%20%2F%20Essentials&tab={tab}&message=Document%20saved")

    def _handle_create_crm_lead(self) -> None:
        fields = self._read_form()
        tab = "leads"
        assigned_user_id = optional_int(fields, "assigned_user_id")
        try:
            self.crm_repository.create_lead(
                LeadData(
                    name=required_text(fields, "name"),
                    phone=form_text(fields, "phone"),
                    email=form_text(fields, "email"),
                    source=required_text(fields, "source"),
                    interested_in=form_text(fields, "interested_in"),
                    status=required_text(fields, "status"),
                    assigned_user_id=assigned_user_id,
                    next_followup_date=form_text(fields, "next_followup_date"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "CRM", query={"tab": [tab]}, error=f"Could not save lead: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=CRM&tab={tab}&message=Lead%20saved")

    def _handle_update_crm_lead_status(self) -> None:
        fields = self._read_form()
        tab = "leads"
        try:
            self.crm_repository.update_lead_status(required_int(fields, "lead_id"), required_text(fields, "status"))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "CRM", query={"tab": [tab]}, error=f"Could not update lead: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=CRM&tab={tab}&message=Lead%20status%20updated")

    def _handle_create_crm_followup(self) -> None:
        fields = self._read_form()
        tab = "followups"
        try:
            self.crm_repository.create_followup(
                FollowUpData(
                    lead_id=optional_int(fields, "lead_id"),
                    customer_id=optional_int(fields, "customer_id"),
                    assigned_user_id=optional_int(fields, "assigned_user_id"),
                    followup_type=required_text(fields, "followup_type"),
                    due_date=required_text(fields, "due_date"),
                    due_time=form_text(fields, "due_time"),
                    status=required_text(fields, "status"),
                    note=form_text(fields, "note"),
                )
            )
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "CRM", query={"tab": [tab]}, error=f"Could not save follow-up: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=CRM&tab={tab}&message=Follow-up%20saved")

    def _handle_update_crm_followup_status(self) -> None:
        fields = self._read_form()
        tab = "followups"
        try:
            self.crm_repository.update_followup_status(required_int(fields, "followup_id"), required_text(fields, "status"))
        except Exception as error:
            self._send_html(render_dashboard(self._current_user_required(), "CRM", query={"tab": [tab]}, error=f"Could not update follow-up: {error}"), HTTPStatus.BAD_REQUEST)
            return
        self._redirect(f"/dashboard?page=CRM&tab={tab}&message=Follow-up%20status%20updated")

    def _read_form(self) -> dict[str, list[str]]:
        if hasattr(self, "_cached_form_fields"):
            return self._cached_form_fields  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self._cached_form_fields = parse_qs(body)
        return self._cached_form_fields  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        return

    def _current_user(self) -> AuthenticatedUser | None:
        session = self._current_session()
        return session.user if session is not None else None

    def _current_session(self) -> SessionState | None:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "pos_session":
                session = SESSIONS.get(value)
                if session is None:
                    return None
                if time.time() - session.last_seen > SESSION_TIMEOUT_SECONDS:
                    SESSIONS.pop(value, None)
                    return None
                if self._password_hash_for_user(session.user.id) != session.password_hash:
                    SESSIONS.pop(value, None)
                    return None
                session.last_seen = time.time()
                return session
        return None

    def _valid_csrf(self, fields: dict[str, list[str]]) -> bool:
        session = self._current_session()
        if session is None:
            return False
        submitted = fields.get("csrf_token", [""])[0]
        return secrets.compare_digest(submitted, session.csrf_token)

    @staticmethod
    def _password_hash_for_user(user_id: int) -> str:
        with get_connection() as connection:
            row = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        return str(row["password_hash"]) if row is not None else ""

    def _run_scheduled_backup_if_due(self) -> str:
        try:
            backup = self.backup_service.maybe_run_scheduled_backup()
        except Exception:
            return ""
        if backup is None:
            return ""
        return f"Scheduled backup created: {backup.name}"

    def _current_user_required(self) -> AuthenticatedUser:
        user = self._current_user()
        if user is None:
            raise RuntimeError("Login required.")
        return user

    def _has_permission(self, user: AuthenticatedUser, permission: str) -> bool:
        return self.permission_service.has_permission(user, permission)

    def _has_page_permission(self, user: AuthenticatedUser, page: str) -> bool:
        permission = PAGE_PERMISSIONS.get(unquote(page), "dashboard")
        return self._has_permission(user, permission)

    @staticmethod
    def _page_for_permission(permission: str) -> str:
        return {
            "products": "List Products",
            "contacts": "Customers",
            "purchases": "List Purchases",
            "sales": "List Sales",
            "stock": "Stock Report",
            "expenses": "List Expenses",
            "payments": "Transactions",
            "settings": "System Health",
            "users.view": "Users",
            "users.create": "Users",
            "addons": "API Connector",
        }.get(permission, "Dashboard")

    def _logout(self) -> None:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "pos_session":
                SESSIONS.pop(value, None)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", "pos_session=; Max-Age=0; Path=/")
        self.end_headers()

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        session = self._current_session()
        if session is not None:
            token_field = (
                f'<input type="hidden" name="csrf_token" '
                f'value="{html.escape(session.csrf_token, quote=True)}">'
            )
            body = body.replace("</form>", f"{token_field}</form>")
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_expense_csv(self, query: dict[str, list[str]]) -> None:
        filters = expense_filters_from_query(query)
        rows = self.expense_repository.list_expenses(filters)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Date",
                "Time",
                "Reference",
                "Type",
                "Category",
                "Account",
                "Location",
                "Paid To / Received From",
                "Method",
                "Amount",
                "Tax",
                "Total",
                "Status",
                "Recurring",
                "Description",
                "Created By",
            ]
        )
        for row in rows:
            total = float(row["amount"]) + (
                float(row["tax_amount"] or 0) if row["tax_mode"] == "exclusive" else 0
            )
            writer.writerow(
                [
                    row["expense_date"],
                    row["expense_time"] or "",
                    row["reference_no"] or "",
                    expense_type_label(row["expense_type"]),
                    row["category_name"] or "",
                    row["account_name"] or "",
                    row["location_name"] or "",
                    row["party_name"] or "",
                    str(row["payment_method"]).replace("_", " ").title(),
                    f"{row['amount']:.2f}",
                    f"{float(row['tax_amount'] or 0):.2f}",
                    f"{total:.2f}",
                    str(row["status"]).title(),
                    str(row["recurrence"]).title(),
                    row["note"] or "",
                    row["created_by_name"] or "",
                ]
            )
        encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="expenses.csv"')
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_report_csv(self, query: dict[str, list[str]]) -> None:
        report_type = query.get("report", ["sales"])[0]
        filters = report_filters_from_query(query)
        repository = ReportRepository()
        output = StringIO()
        writer = csv.writer(output)
        if report_type == "sales":
            rows = repository.sales_report(filters)
            headers = ["Date", "Invoice", "Customer", "Location", "Subtotal", "Discount", "Tax", "Returns", "Net Sales", "COGS", "Gross Profit", "Paid", "Due", "Payment Status"]
            writer.writerow(headers)
            for row in rows:
                net = float(row["total"]) - float(row["return_amount"])
                writer.writerow([row["sale_date"], row["invoice_no"], row["customer_name"], row["location_name"], row["subtotal"], row["discount"], row["tax"], row["return_amount"], net, row["cost_of_goods"], net - float(row["cost_of_goods"]), row["paid_amount"], row["due_amount"], row["payment_status"]])
        elif report_type == "stock":
            rows = repository.stock_report(filters)
            writer.writerow(["Product", "SKU", "Barcode", "Category", "Brand", "Unit", "Stock In", "Stock Out", "Available", "Alert Qty", "Purchase Value", "Selling Value", "Potential Profit"])
            for row in rows:
                available = float(row["available_stock"])
                writer.writerow([row["name"], row["sku"], row["barcode"] or "", row["category_name"], row["brand_name"], row["unit_name"], row["quantity_in"], row["quantity_out"], available, row["alert_quantity"], available * float(row["purchase_price"]), available * float(row["selling_price"]), available * (float(row["selling_price"]) - float(row["purchase_price"]))])
        elif report_type == "purchase":
            rows = repository.purchase_report(filters)
            writer.writerow(["Date", "Invoice", "Supplier", "Location", "Product", "SKU", "Barcode", "Qty", "Unit", "Unit Cost", "Line Total", "Invoice Total", "Paid", "Due", "Payment Status", "Methods", "Cleared", "Pending Cheque", "Cheque No", "Cheque Status"])
            for row in rows:
                writer.writerow([
                    row["purchase_date"],
                    row["invoice_no"],
                    row["supplier_name"],
                    row["location_name"],
                    row["product_name"] or "",
                    row["product_sku"] or "",
                    row["product_barcode"] or "",
                    row["quantity"] or 0,
                    row["unit_name"] or "",
                    row["purchase_price"] or 0,
                    row["line_total"] or 0,
                    row["total"],
                    row["paid_amount"],
                    row["due_amount"],
                    row["payment_status"],
                    row["payment_methods"],
                    row["cleared_amount"],
                    row["pending_cheque_amount"],
                    row["cheque_numbers"],
                    row["cheque_statuses"],
                ])
        elif report_type == "profit":
            summary = repository.profit_loss_summary(filters)
            writer.writerow(["Line", "Amount"])
            for key, label in [("gross_sales", "Gross Sales"), ("sales_returns", "Sales Returns"), ("net_sales", "Net Sales"), ("cost_of_goods", "Cost of Goods Sold"), ("gross_profit", "Gross Profit"), ("total_expenses", "Operating Expenses"), ("net_profit", "Net Profit"), ("profit_margin", "Profit Margin %"), ("cash_in", "Cash In (non-profit)"), ("cash_out", "Cash Out (non-profit)")]:
                writer.writerow([label, summary[key]])
        else:
            rows = repository.payment_report(filters)
            writer.writerow(["Date", "Type", "Reference Type", "Reference ID", "Account", "Method", "Amount", "Note"])
            for row in rows:
                writer.writerow([row["payment_date"], row["payment_type"], row["reference_type"], row["reference_id"], row["account_name"], row["method"], row["amount"], row["note"] or ""])
        encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{report_type}_report.csv"')
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_stock_history_csv(self, query: dict[str, list[str]]) -> None:
        filters = report_filters_from_query(query)
        product_id = optional_query_int(query, "product_id")
        rows = StockRepository().movement_history(product_id, filters)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Date & Time", "Product", "SKU / Barcode", "Variation", "Location",
                "Movement", "Reference", "Quantity In", "Quantity Out",
                "Running Balance", "Unit Cost", "Stock Value", "User", "Note",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["created_at"], row["product_name"],
                    row["variant_sku"] or row["product_sku"],
                    row["variation_name"], row["location_name"],
                    str(row["movement_type"]).replace("_", " ").title(),
                    row["reference_label"], row["quantity_in"], row["quantity_out"],
                    row["running_balance"], row["unit_cost"], row["stock_value"],
                    "System", row["note"] or "",
                ]
            )
        encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="product_stock_history.csv"')
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_sales_history_csv(self, query: dict[str, list[str]]) -> None:
        filters = sales_history_filters(query)
        rows = SaleRepository().sales_history(filters)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Date & Time", "Invoice", "Customer", "Phone", "Location", "Cashier",
                "Sales Representative", "Products", "Items", "Quantity", "Subtotal",
                "Discount", "Tax", "Returns", "Net Total", "COGS", "Gross Profit",
                "Paid", "Due", "Payment Method", "Payment Status", "Sale Status",
            ]
        )
        for row in rows:
            is_final = row["sale_status"] == "final"
            returns = float(row["return_amount"]) if is_final else 0.0
            net = float(row["total"]) - returns
            cost = float(row["cost_of_goods"]) if is_final else 0.0
            writer.writerow(
                [
                    row["created_at"], row["invoice_no"], row["customer_name"],
                    row["customer_phone"], row["location_name"], "System", "Not assigned",
                    row["product_names"], row["item_count"], row["total_quantity"],
                    row["subtotal"], row["discount"], row["tax"], returns, net, cost,
                    net - cost if is_final else 0, row["paid_amount"], row["due_amount"],
                    row["payment_methods"], row["payment_status"], row["sale_status"],
                ]
            )
        encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="sales_history.csv"')
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def render_login(error: str = "") -> str:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login - POS Ultimate</title>
  <style>{styles()}</style>
</head>
<body class="login-body">
  <main class="login-shell" data-login-shell>
    <section class="login-showcase" aria-hidden="true">
      <div class="login-brand-lockup">
        <div class="login-brand-mark">PU</div>
        <div>
          <h1>POS Ultimate</h1>
          <p>One workspace for every sale, shelf, and stock movement.</p>
        </div>
        <span class="login-live-pill"><i></i> System ready</span>
      </div>
      <div class="login-showcase-copy">
        <span>COMMERCE OPERATING SYSTEM</span>
        <h2>Your entire store.<br><em>Moving as one.</em></h2>
      </div>
      <div class="login-metrics">
        <div><span>Today's sales</span><strong>Rs. 84,260</strong><small>+12.8%</small></div>
        <div><span>Products live</span><strong>1,248</strong><small>Synced</small></div>
        <div><span>Stock alerts</span><strong>08</strong><small>Review</small></div>
      </div>
      <div class="login-counter-scene">
        <div class="scan-beam"></div>
        <div class="counter-terminal">
          <div class="terminal-top"><i></i><i></i><i></i><span>Live counter overview</span><strong>MAIN SHOP</strong></div>
          <div class="terminal-screen">
            <div class="terminal-chart-head"><span>Sales velocity</span><strong>LIVE</strong></div>
            <div class="terminal-chart">
              <i style="--bar:34%"></i><i style="--bar:48%"></i><i style="--bar:42%"></i><i style="--bar:68%"></i><i style="--bar:58%"></i><i style="--bar:82%"></i><i style="--bar:72%"></i><i style="--bar:94%"></i>
            </div>
          </div>
          <div class="terminal-keys">
            <div><span class="sale-product-dot dot-mint"></span><p><strong>Organic Rice</strong><small>SKU 00481</small></p><b>Rs. 1,250</b></div>
            <div><span class="sale-product-dot dot-coral"></span><p><strong>Classic Shirt</strong><small>SKU 01820</small></p><b>Rs. 2,890</b></div>
          </div>
        </div>
        <div class="receipt-strip">
          <div class="receipt-success"><i></i><strong>PAID</strong></div>
          <small>INV-20260629-1048</small>
          <span><b>3 items</b><b>Rs. 4,140</b></span>
          <span>Stock updated</span>
          <span>Receipt queued</span>
        </div>
        <div class="scene-scan-tag"><i></i><span>Barcode matched</span><strong>890104</strong></div>
      </div>
      <div class="inventory-flow">
        <div class="flow-card flow-card-a"><span>SKU</span><strong>Matched</strong></div>
        <div class="flow-card flow-card-b"><span>Stock</span><strong>Live</strong></div>
        <div class="flow-card flow-card-c"><span>Invoice</span><strong>Ready</strong></div>
        <div class="barcode-ribbon"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      </div>
      <div class="login-status-row">
        <span><i></i>Barcode checkout</span>
        <span><i></i>Live inventory</span>
        <span><i></i>Daily reports</span>
      </div>
    </section>
    <section class="login-card">
      <div class="login-card-head">
        <span class="login-kicker">STAFF ACCESS</span>
        <h2>Welcome back</h2>
        <p>Sign in to open your counter workspace.</p>
      </div>
      {error_html}
      <form method="post" action="/login" data-login-form>
        <label for="login-username">Username</label>
        <div class="login-input-wrap"><span aria-hidden="true">@</span><input id="login-username" name="username" autocomplete="username" autofocus></div>
        <label for="login-password">Password</label>
        <div class="login-input-wrap"><span aria-hidden="true">&#9679;</span><input id="login-password" name="password" type="password" autocomplete="current-password"></div>
        <button type="submit" data-login-button><span>Open workspace</span><i></i></button>
      </form>
      <div class="login-help-row"><span class="hint">Use your assigned staff login.</span><span class="secure-note"><i></i>Secure login</span></div>
    </section>
    <div class="login-loader" data-login-loader>
      <div class="loader-inventory"><span></span><span></span><span></span></div>
      <strong>Preparing your counter</strong>
      <span>Syncing products, stock, and today's sales...</span>
    </div>
  </main>
  <script>
    document.querySelector('[data-login-form]')?.addEventListener('submit', () => {{
      document.querySelector('[data-login-shell]')?.classList.add('is-loading');
      const button = document.querySelector('[data-login-button]');
      if (button) {{
        button.disabled = true;
        button.querySelector('span').textContent = 'Opening...';
      }}
    }});
  </script>
</body>
</html>"""


def form_text(fields: dict[str, list[str]], name: str) -> str:
    return fields.get(name, [""])[0].strip()


def required_text(fields: dict[str, list[str]], name: str) -> str:
    value = form_text(fields, name)
    if not value:
        raise ValueError(f"{name.replace('_', ' ').title()} is required.")
    return value


def optional_int(fields: dict[str, list[str]], name: str) -> int | None:
    value = form_text(fields, name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name.replace('_', ' ').title()} must be a valid number.") from exc


def optional_query_int(query: dict[str, list[str]], name: str) -> int | None:
    value = query.get(name, [""])[0]
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def required_int(fields: dict[str, list[str]], name: str) -> int:
    value = optional_int(fields, name)
    if value is None:
        raise ValueError(f"{name.replace('_', ' ').title()} is required.")
    return value


def money_value(fields: dict[str, list[str]], name: str) -> float:
    value = form_text(fields, name)
    if not value:
        return 0.0
    try:
        amount = float(value)
    except ValueError as exc:
        raise ValueError(f"{name.replace('_', ' ').title()} must be a valid amount.") from exc
    if amount < 0:
        raise ValueError(f"{name.replace('_', ' ').title()} cannot be negative.")
    return amount


def render_dashboard(
    user: AuthenticatedUser,
    active_page: str,
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    active_page = unquote(active_page)
    permission_service = PermissionService()
    menu_html = []
    for section in MENU_SECTIONS:
        permitted_items = [
            item
            for item in section["items"]
            if permission_service.has_permission(user, PAGE_PERMISSIONS.get(item, "dashboard"))
        ]
        if not permitted_items:
            continue
        is_open = active_page in permitted_items
        open_attr = " open" if is_open else ""
        active_group = " active-group" if is_open else ""
        section_icon = menu_icon(section["title"])
        menu_html.append(
            f'<details class="menu-group{active_group}"{open_attr}>'
            f'<summary class="menu-section"><span class="menu-symbol">{section_icon}</span><span>{html.escape(section["title"])}</span></summary>'
            '<div class="menu-items">'
        )
        for item in permitted_items:
            active_class = " active" if item == active_page else ""
            item_icon = menu_icon(item)
            menu_html.append(
                f'<a class="menu-item{active_class}" href="/dashboard?page={quote(item)}"><span class="menu-item-symbol">{item_icon}</span><span>{html.escape(item)}</span></a>'
            )
        menu_html.append("</div></details>")

    page_query = dict(query or {})
    page_query["_user_id"] = [str(user.id)]
    content = render_page(active_page, message=message, error=error, query=page_query)
    pos_top_context = ""
    if active_page in {"POS", "New Sale", "Add Sale"}:
        today = __import__("datetime").date.today().isoformat()
        pos_top_context = f"""
        <div class="pos-top-context">
          <span class="pos-top-location"><small>Location</small><strong>Main Shop</strong></span>
          <span class="pos-top-date">{html.escape(today)}</span>
          <a href="/dashboard?page=Sales%20History">Recent Transactions</a>
        </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>POS Ultimate Inventory System</title>
  <style>{styles()}</style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand-card">
      <div class="brand-mark">PU</div>
      <div>
        <div class="brand">POS Ultimate</div>
        <div class="brand-sub">Inventory & Sales</div>
      </div>
    </div>
    <nav class="sidebar-nav">{''.join(menu_html)}</nav>
  </aside>
  <main class="app">
    <header class="topbar">
      <div>
        <h1>{html.escape(active_page)}</h1>
        <p>Signed in as {html.escape(user.full_name)} ({html.escape(user.role_name)})</p>
      </div>
      <div class="top-actions">
        {pos_top_context}
        <a class="top-icon-action" href="/dashboard?page=Backup" title="Backup" aria-label="Backup">{svg_icon("backup")}</a>
        <a class="top-icon-action" href="/dashboard?page=Business%20Settings" title="Settings" aria-label="Settings">{svg_icon("settings")}</a>
        <a class="top-icon-action top-icon-logout" href="/logout" title="Logout" aria-label="Logout">{svg_icon("logout")}</a>
      </div>
    </header>
    <section class="content">{content}</section>
  </main>
  <script>
    document.querySelectorAll('[data-contact-kind-form]').forEach((form) => {{
      const typeSelect = form.querySelector('[data-party-type]');
      const sync = () => {{
        const isBusiness = !typeSelect || typeSelect.value === 'business';
        form.querySelectorAll('[data-business-only]').forEach((element) => {{
          element.hidden = !isBusiness;
        }});
      }};
      if (typeSelect) {{
        typeSelect.addEventListener('change', sync);
      }}
      sync();
    }});
    document.querySelectorAll('[data-import-file-form]').forEach((form) => {{
      const fileInput = form.querySelector('[data-import-file]');
      const textArea = form.querySelector('[data-import-text]');
      if (!fileInput || !textArea) {{
        return;
      }}
      fileInput.addEventListener('change', () => {{
        const file = fileInput.files && fileInput.files[0];
        if (!file) {{
          return;
        }}
        const reader = new FileReader();
        reader.addEventListener('load', () => {{
          textArea.value = reader.result || '';
        }});
        reader.readAsText(file);
      }});
    }});
    document.querySelectorAll('[data-product-image-upload]').forEach((uploader) => {{
      const fileInput = uploader.querySelector('[data-product-image-file]');
      const pathInput = uploader.querySelector('[data-product-image-path]');
      const preview = uploader.querySelector('[data-product-image-preview]');
      const syncPreview = () => {{
        const value = pathInput && pathInput.value ? pathInput.value.trim() : '';
        if (!preview) {{
          return;
        }}
        if (value) {{
          preview.innerHTML = `<img src="${{value.replace(/"/g, '&quot;')}}" alt="">`;
        }} else {{
          preview.innerHTML = '<span>Image</span>';
        }}
      }};
      if (fileInput && pathInput) {{
        fileInput.addEventListener('change', () => {{
          const file = fileInput.files && fileInput.files[0];
          if (!file) {{
            return;
          }}
          const reader = new FileReader();
          reader.addEventListener('load', () => {{
            pathInput.value = reader.result || '';
            syncPreview();
          }});
          reader.readAsDataURL(file);
        }});
      }}
      if (pathInput) {{
        pathInput.addEventListener('input', syncPreview);
      }}
      syncPreview();
    }});
    document.querySelectorAll('[data-expense-form]').forEach((form) => {{
      const typeInputs = form.querySelectorAll('input[name="expense_type"]');
      const expenseOnly = form.querySelector('[data-expense-only]');
      const partyLabel = form.querySelector('[data-party-label]');
      const status = form.querySelector('select[name="status"]');
      const recurrence = form.querySelector('select[name="recurrence"]');
      const taxRate = form.querySelector('input[name="tax_rate"]');
      const taxMode = form.querySelector('select[name="tax_mode"]');
      const syncType = () => {{
        const selected = form.querySelector('input[name="expense_type"]:checked')?.value || 'expense';
        if (expenseOnly) expenseOnly.hidden = selected !== 'expense';
        if (partyLabel) partyLabel.textContent = selected === 'in' ? 'Received From' : 'Paid To';
        if (selected !== 'expense') {{
          if (status) status.value = 'paid';
          if (recurrence) recurrence.value = 'once';
          if (taxRate) taxRate.value = '0.00';
          if (taxMode) taxMode.value = 'exclusive';
        }}
      }};
      typeInputs.forEach((input) => input.addEventListener('change', syncType));
      syncType();

      const fileInput = form.querySelector('[data-expense-file]');
      const nameInput = form.querySelector('[data-expense-file-name]');
      const dataInput = form.querySelector('[data-expense-file-data]');
      const fileStatus = form.querySelector('[data-expense-file-status]');
      fileInput?.addEventListener('change', () => {{
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {{
          fileInput.value = '';
          if (fileStatus) fileStatus.textContent = 'File is larger than 2 MB.';
          return;
        }}
        const reader = new FileReader();
        reader.addEventListener('load', () => {{
          if (nameInput) nameInput.value = file.name;
          if (dataInput) dataInput.value = reader.result || '';
          if (fileStatus) fileStatus.textContent = `${{file.name}} (${{Math.ceil(file.size / 1024)}} KB)`;
        }});
        reader.readAsDataURL(file);
      }});
    }});
    document.querySelectorAll('.report-sheet').forEach((table) => {{
      table.querySelectorAll('thead th').forEach((heading, columnIndex) => {{
        if (heading.textContent.trim().toLowerCase() === 'action' || heading.textContent.trim().toLowerCase() === 'receipt') return;
        heading.classList.add('sortable-heading');
        heading.addEventListener('click', () => {{
          const body = table.querySelector('tbody');
          if (!body) return;
          const rows = Array.from(body.querySelectorAll('tr')).filter((row) => row.children.length > 1);
          const ascending = heading.dataset.direction !== 'asc';
          table.querySelectorAll('thead th').forEach((item) => {{
            if (item !== heading) delete item.dataset.direction;
          }});
          heading.dataset.direction = ascending ? 'asc' : 'desc';
          rows.sort((left, right) => {{
            const leftText = left.children[columnIndex]?.textContent.trim() || '';
            const rightText = right.children[columnIndex]?.textContent.trim() || '';
            const leftNumber = Number(leftText.replace(/,/g, ''));
            const rightNumber = Number(rightText.replace(/,/g, ''));
            const comparison = Number.isNaN(leftNumber) || Number.isNaN(rightNumber)
              ? leftText.localeCompare(rightText, undefined, {{numeric: true}})
              : leftNumber - rightNumber;
            return ascending ? comparison : -comparison;
          }});
          rows.forEach((row) => body.appendChild(row));
        }});
      }});
    }});
    document.querySelectorAll('[data-due-payment-form]').forEach((form) => {{
      const source = form.querySelector('[data-due-source]');
      const amount = form.querySelector('[data-due-amount]');
      const syncDue = () => {{
        const option = source?.options[source.selectedIndex];
        if (amount && option) {{
          amount.value = option.dataset.due || '0.00';
          amount.max = option.dataset.due || '';
        }}
      }};
      source?.addEventListener('change', syncDue);
      syncDue();
    }});
    document.querySelectorAll('[data-barcode-generate]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const field = button.closest('[data-barcode-field]')?.querySelector('[data-barcode-input]');
        if (!field) return;
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = 'Generating...';
        try {{
          const csrf = button.closest('form')?.querySelector('input[name="csrf_token"]')?.value || '';
          const response = await fetch('/barcodes/generate', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
            body: new URLSearchParams({{csrf_token: csrf}}).toString(),
          }});
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || 'Could not generate barcode.');
          field.value = result.barcode;
          field.dispatchEvent(new Event('input', {{bubbles: true}}));
        }} catch (error) {{
          alert(error.message || 'Could not generate barcode.');
        }} finally {{
          button.disabled = false;
          button.textContent = originalText;
        }}
      }});
    }});
    document.querySelectorAll('[data-sales-return]').forEach((workspace) => {{
      const invoiceSelect = workspace.querySelector('[data-return-invoice]');
      const itemRows = Array.from(workspace.querySelectorAll('[data-return-item]'));
      const emptyState = workspace.querySelector('[data-return-empty]');
      const summaryValues = Array.from(workspace.querySelectorAll('[data-return-sale-summary] strong'));
      const form = workspace.querySelector('[data-return-form]');
      const saleInput = form.querySelector('[data-return-sale-id]');
      const productInput = form.querySelector('[data-return-product-id]');
      const quantityInput = form.querySelector('[data-return-quantity]');
      const refundInput = form.querySelector('[data-return-refund]');
      const refundMethod = form.querySelector('[data-return-refund-method]');
      const conditionSelect = form.querySelector('[data-return-condition]');
      const stockInput = form.querySelector('[data-return-stock]');
      const selectedProduct = form.querySelector('[data-return-selected]');
      const refundTotal = form.querySelector('[data-return-refund-total]');
      let selectedPrice = 0;
      let selectedAvailable = 0;

      const money = (value) => Number(value || 0).toFixed(2);
      const syncRefund = () => {{
        const quantity = Math.min(Math.max(Number(quantityInput.value || 0), 0), selectedAvailable);
        if (selectedAvailable > 0 && Number(quantityInput.value || 0) > selectedAvailable) {{
          quantityInput.value = String(selectedAvailable);
        }}
        if (refundMethod.value === 'no_refund') {{
          refundInput.value = '0.00';
          refundInput.disabled = true;
        }} else {{
          refundInput.disabled = false;
          refundInput.value = money(quantity * selectedPrice);
        }}
        refundTotal.textContent = money(refundInput.value);
      }};

      invoiceSelect?.addEventListener('change', () => {{
        const saleId = invoiceSelect.value;
        const option = invoiceSelect.options[invoiceSelect.selectedIndex];
        let visible = 0;
        itemRows.forEach((row) => {{
          row.hidden = row.dataset.saleId !== saleId;
          if (!row.hidden) visible += 1;
        }});
        emptyState.hidden = visible > 0;
        if (summaryValues.length === 3) {{
          summaryValues[0].textContent = option?.dataset.invoice || '-';
          summaryValues[1].textContent = option?.dataset.customer || '-';
          summaryValues[2].textContent = option?.dataset.date || '-';
        }}
        saleInput.value = '';
        productInput.value = '';
        selectedAvailable = 0;
        selectedPrice = 0;
        selectedProduct.innerHTML = '<span>No product selected</span><strong>Select a product from the invoice.</strong>';
        syncRefund();
      }});
      workspace.querySelector('[data-return-items]')?.addEventListener('click', (event) => {{
        const button = event.target.closest('[data-return-select]');
        if (!button) return;
        saleInput.value = button.dataset.saleId || '';
        productInput.value = button.dataset.productId || '';
        selectedAvailable = Number(button.dataset.available || 0);
        selectedPrice = Number(button.dataset.price || 0);
        quantityInput.max = String(selectedAvailable);
        quantityInput.value = selectedAvailable > 0 ? '1' : '0';
        selectedProduct.innerHTML = '<span></span><strong></strong><small></small>';
        selectedProduct.querySelector('span').textContent = button.dataset.sku || '';
        selectedProduct.querySelector('strong').textContent = button.dataset.productName || '';
        selectedProduct.querySelector('small').textContent = `Available to return: ${{money(selectedAvailable)}} | Unit price: ${{money(selectedPrice)}}`;
        syncRefund();
      }});
      quantityInput?.addEventListener('input', syncRefund);
      refundInput?.addEventListener('input', () => {{
        const maximum = Number(quantityInput.value || 0) * selectedPrice;
        if (Number(refundInput.value || 0) > maximum) refundInput.value = money(maximum);
        refundTotal.textContent = money(refundInput.value);
      }});
      refundMethod?.addEventListener('change', syncRefund);
      conditionSelect?.addEventListener('change', () => {{
        const resellable = conditionSelect.value === 'resellable';
        stockInput.checked = resellable;
      }});
      form?.addEventListener('submit', (event) => {{
        if (!saleInput.value || !productInput.value) {{
          event.preventDefault();
          alert('Select an invoice product to return.');
        }}
      }});
      syncRefund();
    }});
    document.querySelectorAll('[data-register-close]').forEach((form) => {{
      const expected = Number(form.querySelector('[data-register-expected]')?.value || 0);
      const noteInputs = Array.from(form.querySelectorAll('[data-denomination-count]'));
      const coinsInput = form.querySelector('[data-denomination-coins]');
      const coinsTotal = form.querySelector('[data-denomination-coins-total]');
      const countedElement = form.querySelector('[data-register-counted]');
      const difference = form.querySelector('[data-register-difference]');
      const sync = () => {{
        let counted = 0;
        noteInputs.forEach((input) => {{
          const count = Math.max(Math.floor(Number(input.value || 0)), 0);
          const value = Number(input.dataset.denominationValue || 0);
          const total = count * value;
          input.value = String(count);
          const rowTotal = input.closest('.register-denomination-row')?.querySelector('[data-denomination-total]');
          if (rowTotal) rowTotal.textContent = total.toFixed(2);
          counted += total;
        }});
        const coinValue = Math.max(Number(coinsInput?.value || 0), 0);
        if (coinsTotal) coinsTotal.textContent = coinValue.toFixed(2);
        counted += coinValue;
        countedElement.textContent = counted.toFixed(2);
        const differenceValue = counted - expected;
        difference.textContent = differenceValue.toFixed(2);
        difference.classList.toggle('positive', differenceValue >= 0);
        difference.classList.toggle('negative', differenceValue < 0);
      }};
      [...noteInputs, coinsInput].forEach((input) => input?.addEventListener('input', sync));
      sync();
    }});
    document.querySelectorAll('[data-purchase-form]').forEach((form) => {{
      const items = new Map();
      const productSelect = form.querySelector('[data-purchase-product]');
      const quantityInput = form.querySelector('[data-purchase-quantity]');
      const priceInput = form.querySelector('[data-purchase-price]');
      const addButton = form.querySelector('[data-purchase-add]');
      const tableBody = form.querySelector('[data-purchase-items]');
      const hiddenContainer = form.querySelector('[data-purchase-hidden]');
      const discountInput = form.querySelector('input[name="discount"]');
      const taxInput = form.querySelector('input[name="tax"]');
      const paidInput = form.querySelector('input[name="paid_amount"]');
      const cashInput = form.querySelector('[data-purchase-cash]');
      const chequeInput = form.querySelector('[data-purchase-cheque]');
      const chequeNoInput = form.querySelector('[data-purchase-cheque-required]');
      const subtotalElement = form.querySelector('[data-purchase-subtotal]');
      const paidDisplay = form.querySelector('[data-purchase-paid-display]');
      const totalElement = form.querySelector('[data-purchase-total]');
      const dueElement = form.querySelector('[data-purchase-due]');
      const quickModal = form.querySelector('[data-purchase-product-modal]');
      const quickOpen = form.querySelector('[data-purchase-product-open]');
      const quickCloseButtons = Array.from(form.querySelectorAll('[data-purchase-product-close]'));
      const quickSave = form.querySelector('[data-purchase-product-save]');
      const quickError = form.querySelector('[data-quick-product-error]');
      const money = (value) => Number(value || 0).toFixed(2);
      const readMoney = (input) => Math.max(Number(input && input.value ? input.value : 0), 0);
      const readTextMoney = (element) => Math.max(Number(element?.textContent || 0), 0);
      const currentPurchaseTotal = () => {{
        let subtotal = 0;
        items.forEach((item) => subtotal += item.quantity * item.price);
        return Math.max(subtotal - readMoney(discountInput) + readMoney(taxInput), 0);
      }};
      const escapeHtml = (value) => String(value || '').replace(/[&<>"']/g, (character) => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }})[character]);

      const renderItems = () => {{
        tableBody.innerHTML = '';
        hiddenContainer.innerHTML = '';
        let subtotal = 0;
        if (!items.size) {{
          tableBody.innerHTML = '<tr><td colspan="6" class="empty">No products added.</td></tr>';
        }}
        items.forEach((item) => {{
          const lineTotal = item.quantity * item.price;
          subtotal += lineTotal;
          const row = document.createElement('tr');
          row.innerHTML = `
            <td>${{escapeHtml(item.name)}}</td>
            <td>${{escapeHtml(item.sku)}}</td>
            <td><input type="number" min="0.01" step="0.01" value="${{item.quantity}}" data-purchase-row-qty="${{item.id}}"></td>
            <td><input type="number" min="0" step="0.01" value="${{item.price}}" data-purchase-row-price="${{item.id}}"></td>
            <td class="numeric">${{money(lineTotal)}}</td>
            <td><button type="button" class="table-action danger-button" data-purchase-remove="${{item.id}}">Remove</button></td>`;
          tableBody.appendChild(row);
          [['product_ids', item.id], ['quantities', item.quantity], ['purchase_prices', item.price]].forEach(([name, value]) => {{
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            hiddenContainer.appendChild(input);
          }});
        }});
        const total = Math.max(subtotal - readMoney(discountInput) + readMoney(taxInput), 0);
        const paid = readMoney(cashInput) + readMoney(chequeInput);
        if (paidInput) paidInput.value = money(paid);
        if (chequeNoInput) chequeNoInput.required = readMoney(chequeInput) > 0;
        const due = Math.max(total - paid, 0);
        subtotalElement.textContent = money(subtotal);
        if (paidDisplay) paidDisplay.textContent = money(paid);
        totalElement.textContent = money(total);
        dueElement.textContent = money(due);
      }};

      productSelect?.addEventListener('change', () => {{
        const option = productSelect.options[productSelect.selectedIndex];
        if (option && priceInput) {{
          priceInput.value = option.dataset.price || '0.00';
        }}
      }});
      addButton?.addEventListener('click', () => {{
        const option = productSelect && productSelect.options[productSelect.selectedIndex];
        if (!option || !option.value) {{
          alert('Select a product.');
          return;
        }}
        const id = option.value;
        const quantity = Math.max(Number(quantityInput.value || 0), 0);
        const price = Math.max(Number(priceInput.value || 0), 0);
        if (quantity <= 0) {{
          alert('Quantity must be greater than zero.');
          return;
        }}
        const existing = items.get(id);
        if (existing) {{
          existing.quantity += quantity;
          existing.price = price;
        }} else {{
          items.set(id, {{
            id,
            name: option.dataset.name || option.textContent || '',
            sku: option.dataset.sku || '',
            quantity,
            price,
          }});
        }}
        productSelect.value = '';
        quantityInput.value = '1';
        priceInput.value = '0.00';
        renderItems();
      }});
      tableBody?.addEventListener('click', (event) => {{
        const target = event.target;
        if (target instanceof HTMLElement && target.dataset.purchaseRemove) {{
          items.delete(target.dataset.purchaseRemove);
          renderItems();
        }}
      }});
      tableBody?.addEventListener('input', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        const id = target.dataset.purchaseRowQty || target.dataset.purchaseRowPrice;
        const item = id ? items.get(id) : null;
        if (!item) return;
        if (target.dataset.purchaseRowQty) item.quantity = Math.max(Number(target.value || 0), 0.01);
        if (target.dataset.purchaseRowPrice) item.price = Math.max(Number(target.value || 0), 0);
        renderItems();
      }});
      [discountInput, taxInput, cashInput, chequeInput].forEach((input) => input && input.addEventListener('input', renderItems));
      const closeQuickModal = () => {{
        if (quickModal) quickModal.hidden = true;
        if (quickError) quickError.hidden = true;
      }};
      quickOpen?.addEventListener('click', () => {{
        if (quickModal) quickModal.hidden = false;
        form.querySelector('[data-quick-product-name]')?.focus();
      }});
      quickCloseButtons.forEach((button) => button.addEventListener('click', closeQuickModal));
      quickModal?.addEventListener('click', (event) => {{
        if (event.target === quickModal) closeQuickModal();
      }});
      quickSave?.addEventListener('click', async () => {{
        const field = (selector) => form.querySelector(selector);
        const payload = new URLSearchParams({{
          csrf_token: form.querySelector('input[name="csrf_token"]')?.value || '',
          name: field('[data-quick-product-name]')?.value.trim() || '',
          sku: field('[data-quick-product-sku]')?.value.trim() || '',
          barcode: field('[data-quick-product-barcode]')?.value.trim() || '',
          category_id: field('[data-quick-product-category]')?.value || '',
          brand_id: field('[data-quick-product-brand]')?.value || '',
          unit_id: field('[data-quick-product-unit]')?.value || '',
          quantity: field('[data-quick-product-quantity]')?.value || '0',
          purchase_price: field('[data-quick-product-purchase-price]')?.value || '0',
          selling_price: field('[data-quick-product-selling-price]')?.value || '0',
          alert_quantity: field('[data-quick-product-alert]')?.value || '0',
        }});
        quickSave.disabled = true;
        quickSave.textContent = 'Saving...';
        if (quickError) quickError.hidden = true;
        try {{
          const response = await fetch('/purchases/products/create', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
            body: payload.toString(),
          }});
          const result = await response.json();
          if (!response.ok || !result.ok) {{
            throw new Error(result.error || 'Could not create product.');
          }}
          const product = result.product;
          const option = document.createElement('option');
          option.value = String(product.id);
          option.textContent = `${{product.name}} (${{product.sku}})`;
          option.dataset.name = product.name;
          option.dataset.sku = product.sku;
          option.dataset.price = money(product.purchase_price);
          productSelect.appendChild(option);
          productSelect.value = option.value;
          items.set(option.value, {{
            id: option.value,
            name: product.name,
            sku: product.sku,
            quantity: Number(product.quantity),
            price: Number(product.purchase_price),
          }});
          quantityInput.value = '1';
          priceInput.value = money(product.purchase_price);
          renderItems();
          closeQuickModal();
          [
            '[data-quick-product-name]', '[data-quick-product-sku]', '[data-quick-product-barcode]'
          ].forEach((selector) => {{ const input = field(selector); if (input) input.value = ''; }});
          field('[data-quick-product-quantity]').value = '1';
          field('[data-quick-product-purchase-price]').value = '0.00';
          field('[data-quick-product-selling-price]').value = '0.00';
          field('[data-quick-product-alert]').value = '0.00';
        }} catch (error) {{
          if (quickError) {{
            quickError.textContent = error.message || 'Could not create product.';
            quickError.hidden = false;
          }}
        }} finally {{
          quickSave.disabled = false;
          quickSave.textContent = 'Save & Add To Purchase';
        }}
      }});
      form.addEventListener('submit', (event) => {{
        if (!items.size && productSelect?.value) {{
          addButton?.click();
        }}
        const paymentTotal = readMoney(cashInput) + readMoney(chequeInput);
        const purchaseTotal = currentPurchaseTotal() || readTextMoney(totalElement);
        if (paymentTotal > purchaseTotal) {{
          event.preventDefault();
          alert('Payment total cannot be greater than purchase total.');
          return;
        }}
        if (!items.size) {{
          event.preventDefault();
          alert('Add at least one product to the purchase.');
        }}
      }});
      renderItems();
    }});
    const openRoleEditor = (hash) => {{
      if (!hash || !hash.startsWith('#role-')) return;
      const target = document.querySelector(hash);
      if (!(target instanceof HTMLDetailsElement)) return;
      target.open = true;
      target.scrollIntoView({{behavior: 'smooth', block: 'start'}});
    }};
    document.querySelectorAll('a[href^="#role-"]').forEach((link) => {{
      link.addEventListener('click', () => {{
        window.setTimeout(() => openRoleEditor(link.getAttribute('href') || ''), 0);
      }});
    }});
    openRoleEditor(window.location.hash);
    window.addEventListener('hashchange', () => openRoleEditor(window.location.hash));
    document.querySelectorAll('[data-pos-form]').forEach((form) => {{
      const cart = new Map();
      const productButtons = Array.from(form.querySelectorAll('[data-pos-product]'));
      const search = form.querySelector('[data-pos-search]');
      const entryPanel = form.querySelector('[data-pos-entry-panel]');
      const entryToggle = form.querySelector('[data-pos-entry-toggle]');
      const metaPanel = form.querySelector('[data-pos-meta-panel]');
      const metaToggle = form.querySelector('[data-pos-meta-toggle]');
      const paymentPanel = form.querySelector('[data-pos-payment-panel]');
      const paymentToggle = form.querySelector('[data-pos-payment-toggle]');
      const cartContainer = form.querySelector('[data-pos-cart]');
      const hiddenContainer = form.querySelector('[data-pos-hidden]');
      const subtotalElement = form.querySelector('[data-pos-subtotal]');
      const itemCountElement = form.querySelector('[data-pos-items]');
      const totalElement = form.querySelector('[data-pos-total]');
      const balanceElement = form.querySelector('[data-pos-balance]');
      const discountInput = form.querySelector('[data-pos-discount]');
      const taxInput = form.querySelector('[data-pos-tax]');
      const paidInput = form.querySelector('[data-pos-paid]');
      const paymentSelect = form.querySelector('select[name="payment_method"]');
      const customerSelect = form.querySelector('select[name="customer_id"]');
      const saleStatusInput = form.querySelector('[data-pos-sale-status]');
      const multiplePayPanel = form.querySelector('[data-pos-multiple-pay-panel]');
      const multiplePayRows = form.querySelector('[data-pos-multiple-pay-rows]');
      const splitTotalElement = form.querySelector('[data-pos-split-total]');
      const splitRemainingElement = form.querySelector('[data-pos-split-remaining]');
      const multiplePayButton = form.querySelector('[data-pos-multiple-pay]');
      const multiplePayAddButton = form.querySelector('[data-pos-multiple-pay-add]');
      const cardModal = form.querySelector('[data-card-modal]');
      const cardHidden = form.querySelector('[data-card-hidden]');
      const cardFinalize = form.querySelector('[data-card-finalize]');
      const cardCancel = form.querySelector('[data-card-cancel]');
      const cardAmount = form.querySelector('[data-card-amount]');
      const visibleCount = form.querySelector('[data-pos-visible-count]');
      const productEmpty = form.querySelector('[data-pos-product-empty]');
      const categoryButtons = Array.from(form.querySelectorAll('[data-pos-category]'));
      const brandButtons = Array.from(form.querySelectorAll('[data-pos-brand]'));
      const drawerOpenButtons = Array.from(form.querySelectorAll('[data-pos-open-drawer]'));
      const drawerCloseButtons = Array.from(form.querySelectorAll('[data-pos-close-drawer]'));
      const drawerOverlay = form.querySelector('[data-pos-browser-overlay]');
      const drawers = Array.from(form.querySelectorAll('[data-pos-drawer]'));
      const featuredButton = form.querySelector('[data-pos-featured-filter]');
      let activeCategory = '';
      let activeBrand = '';

      entryToggle?.addEventListener('click', () => {{
        const willOpen = Boolean(entryPanel?.hidden);
        if (entryPanel) entryPanel.hidden = !willOpen;
        entryToggle.setAttribute('aria-expanded', String(willOpen));
        entryToggle.classList.toggle('active', willOpen);
        if (willOpen) window.setTimeout(() => search?.focus(), 0);
      }});
      metaToggle?.addEventListener('click', () => {{
        const willOpen = Boolean(metaPanel?.hidden);
        if (metaPanel) metaPanel.hidden = !willOpen;
        metaToggle.setAttribute('aria-expanded', String(willOpen));
        metaToggle.classList.toggle('active', willOpen);
        if (willOpen) window.setTimeout(() => metaPanel?.querySelector('input')?.focus(), 0);
      }});
      paymentToggle?.addEventListener('click', () => {{
        const willOpen = Boolean(paymentPanel?.hidden);
        if (paymentPanel) paymentPanel.hidden = !willOpen;
        paymentToggle.setAttribute('aria-expanded', String(willOpen));
        paymentToggle.classList.toggle('active', willOpen);
        if (willOpen) window.setTimeout(() => paymentPanel?.querySelector('select')?.focus(), 0);
      }});

      const money = (value) => Number(value || 0).toFixed(2);
      const readMoney = (input) => Math.max(Number(input && input.value ? input.value : 0), 0);
      const currentTotal = () => Number(totalElement?.textContent || 0);
      const splitTotal = () => Array.from(form.querySelectorAll('[data-pos-split-amount]')).reduce((total, input) => total + readMoney(input), 0);
      const cardReferenceValue = () => {{
        const invoice = form.querySelector('input[name="invoice_no"]')?.value || 'SALE';
        const compactInvoice = invoice.replace(/[^A-Za-z0-9]/g, '').slice(-10) || 'SALE';
        const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
        return `CARD-${{compactInvoice}}-${{stamp}}`;
      }};

      const updateSplitSummary = () => {{
        const total = currentTotal();
        const paid = splitTotal();
        if (splitTotalElement) splitTotalElement.textContent = money(paid);
        if (splitRemainingElement) splitRemainingElement.textContent = money(Math.max(total - paid, 0));
        if (paidInput && !multiplePayPanel?.hidden) paidInput.value = money(paid);
      }};

      const addSplitPaymentRow = (method = 'cash', amount = '') => {{
        if (!multiplePayRows) return;
        const row = document.createElement('div');
        row.className = 'pos-split-row';
        row.innerHTML = `
          <select name="payment_methods">${{multiplePayRows.dataset.methodOptions || '<option value="cash">Cash</option>'}}</select>
          <input type="number" name="payment_amounts" min="0" step="0.01" value="${{amount}}" placeholder="Amount" data-pos-split-amount>
          <input name="payment_notes" placeholder="Reference / note">
          <button type="button" data-pos-split-remove title="Remove payment">Remove</button>`;
        const select = row.querySelector('select');
        if (select && Array.from(select.options).some((option) => option.value === method)) select.value = method;
        multiplePayRows.appendChild(row);
        row.querySelector('[data-pos-split-amount]')?.addEventListener('input', () => {{
          updateSplitSummary();
          renderCart();
        }});
        row.querySelector('[data-pos-split-remove]')?.addEventListener('click', () => {{
          row.remove();
          updateSplitSummary();
          renderCart();
        }});
        updateSplitSummary();
      }};

      const clearCardHiddenPayment = () => {{
        if (cardHidden) cardHidden.innerHTML = '';
      }};

      const openCardModal = () => {{
        if (!cart.size) {{
          alert('Add at least one product to the cart.');
          return;
        }}
        if (saleStatusInput) saleStatusInput.value = 'final';
        renderCart();
        if (cardAmount) cardAmount.textContent = money(currentTotal());
        const referenceInput = form.querySelector('[data-card-reference]');
        const terminalInput = form.querySelector('[data-card-terminal]');
        if (referenceInput && !referenceInput.value.trim()) referenceInput.value = cardReferenceValue();
        if (terminalInput && !terminalInput.value.trim()) terminalInput.value = 'Main Counter Terminal';
        if (cardModal) cardModal.hidden = false;
        window.setTimeout(() => cardModal?.querySelector('[data-card-reference]')?.focus(), 0);
      }};

      const closeCardModal = () => {{
        if (cardModal) cardModal.hidden = true;
      }};

      const setHiddenCardPayment = () => {{
        if (!cardHidden) return;
        const reference = form.querySelector('[data-card-reference]')?.value.trim() || '';
        const last4 = form.querySelector('[data-card-last4]')?.value.trim() || '';
        const terminal = form.querySelector('[data-card-terminal]')?.value.trim() || '';
        const approval = form.querySelector('[data-card-approval]')?.value.trim() || '';
        const noteParts = [
          reference ? `Card Ref: ${{reference}}` : '',
          last4 ? `Last 4: ${{last4}}` : '',
          terminal ? `Terminal: ${{terminal}}` : '',
          approval ? `Approval: ${{approval}}` : '',
        ].filter(Boolean);
        cardHidden.innerHTML = '';
        [['payment_methods', 'card'], ['payment_amounts', money(currentTotal())], ['payment_notes', noteParts.join(' | ')]].forEach(([name, value]) => {{
          const input = document.createElement('input');
          input.type = 'hidden';
          input.name = name;
          input.value = value;
          cardHidden.appendChild(input);
        }});
      }};

      const addProduct = (button) => {{
        if (!button || button.disabled) {{
          return;
        }}
        const id = button.dataset.id;
        const existing = cart.get(id);
        const stock = Number(button.dataset.stock || 0);
        if (existing) {{
          existing.quantity = Math.min(existing.quantity + 1, stock);
        }} else {{
            cart.set(id, {{
              id,
            name: button.dataset.name || '',
            sku: button.dataset.sku || '',
            price: Number(button.dataset.price || 0),
              offerDiscount: Number(button.dataset.offerDiscount || 0),
              discount: 0,
              image: button.querySelector('.pos-product-image')?.innerHTML || '',
              stock,
              quantity: 1,
            }});
        }}
        renderCart();
      }};

      const renderCart = () => {{
        cartContainer.innerHTML = '';
        hiddenContainer.innerHTML = '';
        let subtotal = 0;
        let itemDiscountTotal = 0;
        let itemCount = 0;
        if (!cart.size) {{
          cartContainer.innerHTML = `
            <div class="pos-empty-cart">
              <i></i>
              <strong>Your cart is empty</strong>
              <span>Scan a barcode or select a product.</span>
            </div>`;
        }} else {{
          cartContainer.innerHTML = `
            <div class="pos-cart-header" aria-hidden="true">
              <span>Product</span>
              <span>Quantity</span>
              <span>Price Inc. Tax</span>
              <span>Discount / Offer</span>
              <span>Subtotal</span>
              <span></span>
            </div>`;
        }}
        cart.forEach((item) => {{
          itemCount += item.quantity;
          const lineSubtotal = item.quantity * item.price;
          if (Number(item.offerDiscount || 0) > 0) {{
            item.discount = Number(item.offerDiscount || 0) * item.quantity;
          }}
          item.discount = Math.min(Math.max(Number(item.discount || 0), 0), lineSubtotal);
          const lineTotal = Math.max(lineSubtotal - item.discount, 0);
          const offerUnitDiscount = Number(item.offerDiscount || 0);
          const effectiveUnitPrice = Math.max(item.price - offerUnitDiscount, 0);
          const priceControl = offerUnitDiscount > 0
            ? `<div class="pos-line-price-view"><del>${{money(item.price)}}</del><strong>${{money(effectiveUnitPrice)}}</strong></div>`
            : `<input class="pos-line-price" type="number" min="0" step="0.01" value="${{money(item.price)}}" data-pos-price="${{item.id}}">`;
          const discountControl = offerUnitDiscount > 0
            ? `<span class="pos-line-save">Save ${{money(item.discount)}}</span>`
            : `<input class="pos-line-discount" type="number" min="0" step="0.01" max="${{money(lineSubtotal)}}" value="${{money(item.discount)}}" data-pos-line-discount="${{item.id}}" title="Item discount or offer amount">`;
          itemDiscountTotal += item.discount;
          subtotal += lineTotal;
          const line = document.createElement('div');
          line.className = 'pos-cart-line';
          line.innerHTML = `
            <div class="pos-line-product">
              <span class="pos-line-image">${{item.image}}</span>
              <span class="pos-line-name">
                <strong>${{item.name}}</strong>
                <small>${{item.sku}} &middot; Stock ${{money(item.stock)}}</small>
              </span>
            </div>
            <div class="pos-qty-control">
              <button type="button" data-pos-minus="${{item.id}}">-</button>
              <input type="number" min="0.01" step="0.01" max="${{item.stock}}" value="${{item.quantity}}" data-pos-qty="${{item.id}}">
              <button type="button" data-pos-plus="${{item.id}}">+</button>
              <small>Pieces</small>
            </div>
            ${{priceControl}}
            ${{discountControl}}
            <strong class="pos-line-subtotal">${{money(lineTotal)}}</strong>
            <button type="button" class="pos-remove" data-pos-remove="${{item.id}}" title="Remove">Remove</button>`;
          cartContainer.appendChild(line);

          [['product_ids', item.id], ['quantities', item.quantity], ['unit_prices', item.price], ['item_discounts', item.discount]].forEach(([name, value]) => {{
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            hiddenContainer.appendChild(input);
          }});
        }});
        const total = Math.max(subtotal - readMoney(discountInput) + readMoney(taxInput), 0);
        const paid = multiplePayPanel && !multiplePayPanel.hidden ? splitTotal() : readMoney(paidInput);
        const discountSummary = form.querySelector('[data-pos-discount-summary]');
        if (discountSummary) discountSummary.textContent = money(itemDiscountTotal + readMoney(discountInput));
        if (itemCountElement) {{
          itemCountElement.textContent = money(itemCount);
        }}
        subtotalElement.textContent = money(subtotal);
        totalElement.textContent = money(total);
        balanceElement.textContent = paid >= total ? `Change ${{money(paid - total)}}` : `Due ${{money(total - paid)}}`;
        updateSplitSummary();
      }};

      const applyProductFilters = () => {{
        const term = search ? search.value.trim().toLowerCase() : '';
        let shown = 0;
        productButtons.forEach((button) => {{
          const matchesSearch = term === '' || (button.dataset.search || '').includes(term);
          const matchesCategory = activeCategory === '' || button.dataset.category === activeCategory;
          const matchesBrand = activeBrand === '' || button.dataset.brand === activeBrand;
          button.hidden = !(matchesSearch && matchesCategory && matchesBrand);
          if (!button.hidden) {{
            shown += 1;
          }}
        }});
        if (visibleCount) {{
          visibleCount.textContent = String(shown);
        }}
        if (productEmpty) {{
          productEmpty.hidden = shown !== 0;
        }}
      }};

      const selectFilter = (buttons, selected) => {{
        buttons.forEach((button) => button.classList.toggle('active', button === selected));
      }};

      const closeProductDrawer = () => {{
        drawers.forEach((drawer) => drawer.hidden = true);
        if (drawerOverlay) drawerOverlay.hidden = true;
        drawerOpenButtons.forEach((button) => {{
          button.classList.remove('active');
          button.setAttribute('aria-expanded', 'false');
        }});
      }};

      const openProductDrawer = (name) => {{
        drawers.forEach((drawer) => {{
          drawer.hidden = drawer.dataset.posDrawer !== name;
        }});
        if (drawerOverlay) drawerOverlay.hidden = false;
        drawerOpenButtons.forEach((button) => {{
          const active = button.dataset.posOpenDrawer === name;
          button.classList.toggle('active', active);
          button.setAttribute('aria-expanded', String(active));
        }});
      }};

      productButtons.forEach((button) => button.addEventListener('click', () => addProduct(button)));
      drawerOpenButtons.forEach((button) => button.addEventListener('click', () => {{
        const drawerName = button.dataset.posOpenDrawer || '';
        const targetDrawer = drawers.find((drawer) => drawer.dataset.posDrawer === drawerName);
        if (targetDrawer && !targetDrawer.hidden) {{
          closeProductDrawer();
        }} else {{
          openProductDrawer(drawerName);
        }}
      }}));
      drawerCloseButtons.forEach((button) => button.addEventListener('click', closeProductDrawer));
      drawerOverlay?.addEventListener('click', closeProductDrawer);
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') closeProductDrawer();
      }});
      featuredButton?.addEventListener('click', () => {{
        activeCategory = '';
        activeBrand = '';
        if (search) search.value = '';
        selectFilter(categoryButtons, categoryButtons.find((button) => (button.dataset.posCategory || '') === '') || categoryButtons[0]);
        selectFilter(brandButtons, brandButtons.find((button) => (button.dataset.posBrand || '') === '') || brandButtons[0]);
        drawerOpenButtons.forEach((button) => button.classList.remove('active'));
        featuredButton.classList.add('active');
        closeProductDrawer();
        applyProductFilters();
      }});
      categoryButtons.forEach((button) => button.addEventListener('click', () => {{
        activeCategory = button.dataset.posCategory || '';
        selectFilter(categoryButtons, button);
        drawerOpenButtons.forEach((item) => item.classList.toggle('active', item.dataset.posOpenDrawer === 'category'));
        featuredButton?.classList.remove('active');
        closeProductDrawer();
        applyProductFilters();
      }}));
      brandButtons.forEach((button) => button.addEventListener('click', () => {{
        activeBrand = button.dataset.posBrand || '';
        selectFilter(brandButtons, button);
        drawerOpenButtons.forEach((item) => item.classList.toggle('active', item.dataset.posOpenDrawer === 'brand'));
        featuredButton?.classList.remove('active');
        closeProductDrawer();
        applyProductFilters();
      }}));
      cartContainer.addEventListener('click', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) {{
          return;
        }}
        const removeId = target.dataset.posRemove;
        const minusId = target.dataset.posMinus;
        const plusId = target.dataset.posPlus;
        if (removeId) {{
          cart.delete(removeId);
        }}
        if (minusId && cart.has(minusId)) {{
          const item = cart.get(minusId);
          item.quantity -= 1;
          if (item.quantity <= 0) {{
            cart.delete(minusId);
          }}
        }}
        if (plusId && cart.has(plusId)) {{
          const item = cart.get(plusId);
          item.quantity = Math.min(item.quantity + 1, item.stock);
        }}
        renderCart();
      }});
      cartContainer.addEventListener('input', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLInputElement) || (!target.dataset.posQty && !target.dataset.posPrice && !target.dataset.posLineDiscount)) {{
          return;
        }}
        const item = cart.get(target.dataset.posQty || target.dataset.posPrice || target.dataset.posLineDiscount);
        if (!item) {{
          return;
        }}
        if (target.dataset.posQty) {{
          item.quantity = Math.min(Math.max(Number(target.value || 0), 0.01), item.stock);
        }}
        if (target.dataset.posPrice) {{
          item.price = Math.max(Number(target.value || 0), 0);
        }}
        if (target.dataset.posLineDiscount) {{
          item.discount = Math.max(Number(target.value || 0), 0);
        }}
        renderCart();
      }});
      [discountInput, taxInput, paidInput].forEach((input) => input && input.addEventListener('input', renderCart));
      multiplePayAddButton?.addEventListener('click', () => addSplitPaymentRow());
      multiplePayButton?.addEventListener('click', () => {{
        if (!cart.size) {{
          alert('Add at least one product to the cart.');
          return;
        }}
        if (saleStatusInput) saleStatusInput.value = 'final';
        if (multiplePayPanel) multiplePayPanel.hidden = false;
        if (multiplePayRows && !multiplePayRows.children.length) {{
          addSplitPaymentRow('cash', money(currentTotal()));
        }}
        updateSplitSummary();
      }});
      form.querySelectorAll('[data-pos-clear]').forEach((button) => button.addEventListener('click', () => {{
          cart.clear();
          if (discountInput) discountInput.value = '0.00';
          if (taxInput) taxInput.value = '0.00';
          if (paidInput) paidInput.value = '0.00';
          if (multiplePayRows) multiplePayRows.innerHTML = '';
          clearCardHiddenPayment();
          if (multiplePayPanel) multiplePayPanel.hidden = true;
          closeCardModal();
          renderCart();
        }}));
      form.querySelectorAll('[data-pos-payment]').forEach((button) => button.addEventListener('click', () => {{
        if (!cart.size) {{
          alert('Add at least one product to the cart.');
          return;
        }}
        if (saleStatusInput) saleStatusInput.value = 'final';
        const method = button.dataset.posPayment || 'cash';
        if (method === 'card') {{
          openCardModal();
          return;
        }}
        clearCardHiddenPayment();
        if (paymentSelect && Array.from(paymentSelect.options).some((option) => option.value === method)) {{
          paymentSelect.value = method;
        }}
        if (paidInput) {{
          paidInput.value = totalElement ? totalElement.textContent : '0.00';
        }}
        renderCart();
        form.requestSubmit();
      }}));
      cardCancel?.addEventListener('click', closeCardModal);
      cardModal?.addEventListener('click', (event) => {{
        if (event.target === cardModal) closeCardModal();
      }});
      cardFinalize?.addEventListener('click', () => {{
        const referenceInput = form.querySelector('[data-card-reference]');
        if (referenceInput && !referenceInput.value.trim()) {{
          referenceInput.focus();
          alert('Enter the card transaction reference.');
          return;
        }}
        if (paymentSelect && Array.from(paymentSelect.options).some((option) => option.value === 'card')) {{
          paymentSelect.value = 'card';
        }}
        if (paidInput) paidInput.value = money(currentTotal());
        setHiddenCardPayment();
        closeCardModal();
        renderCart();
        form.requestSubmit();
      }});
      form.querySelectorAll('[data-pos-credit]').forEach((button) => button.addEventListener('click', () => {{
        if (!cart.size) {{
          alert('Add at least one product to the cart.');
          return;
        }}
        if (customerSelect && !customerSelect.value) {{
          if (entryPanel) entryPanel.hidden = false;
          entryToggle?.setAttribute('aria-expanded', 'true');
          entryToggle?.classList.add('active');
          customerSelect.focus();
          alert('Select a customer before saving a credit sale.');
          return;
        }}
        if (saleStatusInput) saleStatusInput.value = 'final';
        if (paidInput) {{
          paidInput.value = '0.00';
        }}
        renderCart();
        form.requestSubmit();
      }}));
      form.querySelectorAll('[data-pos-document]').forEach((button) => button.addEventListener('click', () => {{
        if (!cart.size) {{
          alert('Add at least one product to the cart.');
          return;
        }}
        if (saleStatusInput) saleStatusInput.value = button.dataset.posDocument || 'draft';
        if (paidInput) paidInput.value = '0.00';
        renderCart();
        form.requestSubmit();
      }}));
      search?.addEventListener('input', applyProductFilters);
      search?.addEventListener('keydown', (event) => {{
        if (event.key !== 'Enter') {{
          return;
        }}
        event.preventDefault();
        const term = search.value.trim().toLowerCase();
        const exact = productButtons.find((button) => {{
          return !button.hidden && !button.disabled && (
            (button.dataset.barcode || '').toLowerCase() === term ||
            (button.dataset.sku || '').toLowerCase() === term
          );
        }});
        addProduct(exact || productButtons.find((button) => !button.hidden && !button.disabled));
        search.select();
      }});
      form.addEventListener('submit', (event) => {{
        if (!cart.size) {{
          event.preventDefault();
          alert('Add at least one product to the cart.');
          return;
        }}
        if (saleStatusInput && !saleStatusInput.value) saleStatusInput.value = 'final';
        if (multiplePayPanel && !multiplePayPanel.hidden) {{
          const total = currentTotal();
          const paid = splitTotal();
          if (paid > total) {{
            event.preventDefault();
            alert('Payment total cannot be greater than sale total.');
            return;
          }}
          if (paid <= 0) {{
            event.preventDefault();
            alert('Add at least one payment amount.');
            return;
          }}
          if (paid < total && customerSelect && !customerSelect.value) {{
            event.preventDefault();
            if (entryPanel) entryPanel.hidden = false;
            entryToggle?.setAttribute('aria-expanded', 'true');
            entryToggle?.classList.add('active');
            customerSelect.focus();
            alert('Select a customer before saving a due split payment sale.');
            return;
          }}
          if (paidInput) paidInput.value = money(paid);
        }}
      }});
      try {{
        const preload = form.dataset.posPreload ? JSON.parse(form.dataset.posPreload) : null;
        if (preload && Array.isArray(preload.items)) {{
          if (customerSelect && preload.customer_id) customerSelect.value = String(preload.customer_id);
          const invoiceInput = form.querySelector('input[name="invoice_no"]');
          const saleDateInput = form.querySelector('input[name="sale_date"]');
          if (invoiceInput && preload.invoice_no) invoiceInput.value = preload.invoice_no;
          if (saleDateInput && preload.sale_date) saleDateInput.value = preload.sale_date;
          if (discountInput) discountInput.value = money(preload.discount || 0);
          if (taxInput) taxInput.value = money(preload.tax || 0);
          preload.items.forEach((sourceItem) => {{
            const id = String(sourceItem.id || '');
            if (!id) return;
            const button = productButtons.find((candidate) => candidate.dataset.id === id);
            cart.set(id, {{
              id,
              name: sourceItem.name || button?.dataset.name || '',
              sku: sourceItem.sku || button?.dataset.sku || '',
              price: Number(sourceItem.price || button?.dataset.price || 0),
              offerDiscount: 0,
              discount: Number(sourceItem.discount || 0),
              image: button?.querySelector('.pos-product-image')?.innerHTML || '',
              stock: Number(button?.dataset.stock || sourceItem.quantity || 0),
              quantity: Number(sourceItem.quantity || 1),
            }});
          }});
          if (entryPanel) entryPanel.hidden = false;
          entryToggle?.setAttribute('aria-expanded', 'true');
          entryToggle?.classList.add('active');
          if (paymentPanel) paymentPanel.hidden = false;
          paymentToggle?.setAttribute('aria-expanded', 'true');
          paymentToggle?.classList.add('active');
        }}
      }} catch (error) {{
        console.warn('Could not preload sale document', error);
      }}
      applyProductFilters();
      renderCart();
    }});
  </script>
</body>
</html>"""


def render_dashboard_home() -> str:
    from datetime import date, timedelta

    repository = ProductRepository()
    contacts = ContactRepository()
    expenses = ExpenseRepository()
    purchases = PurchaseRepository()
    sales = SaleRepository()
    reports = ReportRepository()
    payments = PaymentRepository()
    stock_rows = StockRepository().stock_report()
    profit = reports.profit_loss_summary()
    cash = reports.cash_register_summary()
    pending_cheques = purchases.pending_cheque_summary()
    low_stock_count = sum(
        1 for row in stock_rows if row["alert_quantity"] > 0 and row["available_stock"] <= row["alert_quantity"]
    )
    recent_transactions = payments.list_transactions()[:6]

    today = date.today()
    period_specs = [
        ("today", "Today", today, today),
        ("week", "This Week", today - timedelta(days=today.weekday()), today),
        ("month", "This Month", today.replace(day=1), today),
    ]
    overview_data: dict[str, dict[str, float]] = {}
    overview_buttons: list[str] = []
    for key, label, start_date, end_date in period_specs:
        filters = {"date_from": start_date.isoformat(), "date_to": end_date.isoformat()}
        period_profit = reports.profit_loss_summary(filters)
        period_sales = sales.sales_history({**filters, "sale_status": "final"})
        overview_data[key] = {
            "sales": period_profit["net_sales"],
            "orders": float(len(period_sales)),
            "profit": period_profit["net_profit"],
            "expenses": period_profit["total_expenses"],
            "due": sum(float(row["due_amount"]) for row in period_sales),
            "units": sum(float(row["total_quantity"]) for row in period_sales),
        }
        overview_buttons.append(
            f'<button type="button" class="overview-period{" active" if key == "today" else ""}" '
            f'data-overview-period="{key}">{label}</button>'
        )

    week_start = today - timedelta(days=6)
    week_sales = sales.sales_history(
        {"date_from": week_start.isoformat(), "date_to": today.isoformat(), "sale_status": "final"}
    )
    sales_by_day = {week_start + timedelta(days=offset): 0.0 for offset in range(7)}
    for row in week_sales:
        try:
            sale_day = date.fromisoformat(str(row["sale_date"])[:10])
        except ValueError:
            continue
        if sale_day in sales_by_day:
            sales_by_day[sale_day] += float(row["total"])
    highest_day = max(sales_by_day.values(), default=0.0)
    overview_chart = "".join(
        f"""
        <div class="overview-bar-item">
          <span>{amount:.0f}</span>
          <i style="height:{max(8.0, amount / highest_day * 100) if highest_day else 8.0:.1f}%"></i>
          <small>{day.strftime('%a')}</small>
        </div>
        """
        for day, amount in sales_by_day.items()
    )
    current_overview = overview_data["today"]

    cards = [
        ("Sales", str(sales.sale_count()), "Completed final sales", "sales"),
        ("Purchases", str(purchases.purchase_count()), "Supplier purchase invoices", "purchase"),
        ("Pending Cheques", f'{pending_cheques["amount"]:.2f}', f'{pending_cheques["count"]} cheques waiting', "cash"),
        ("Products", str(repository.product_count()), f"{low_stock_count} low stock alerts", "product"),
        ("Net Profit", f"{profit['net_profit']:.2f}", "Sales minus purchases and expenses", "profit"),
    ]
    card_html = "".join(
        f"""
        <article class="dash-card">
          <div class="dash-card-top">
            <div class="dash-icon dash-icon-{icon_name}">{svg_icon(icon_name)}</div>
            <span>{html.escape(title)}</span>
          </div>
          <strong>{html.escape(value)}</strong>
          <p>{html.escape(hint)}</p>
        </article>
        """
        for title, value, hint, icon_name in cards
    )

    transaction_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{payment_type_badge(row["payment_type"])}</td>
          <td>{html.escape(row["reference_type"].replace('_', ' ').title())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
        </tr>
        """
        for row in recent_transactions
    )
    if not transaction_rows:
        transaction_rows = '<tr><td colspan="4" class="empty">No transactions yet.</td></tr>'

    stock_preview = sorted(stock_rows, key=lambda row: row["available_stock"])[:5]
    stock_rows_html = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td class="numeric">{row["available_stock"]:.2f}</td>
          <td>{stock_status(row["available_stock"], row["alert_quantity"])}</td>
        </tr>
        """
        for row in stock_preview
    )
    if not stock_rows_html:
        stock_rows_html = '<tr><td colspan="3" class="empty">No stock data yet.</td></tr>'

    return f"""
<section class="dashboard-hero">
  <div>
    <span class="hero-kicker">Operations Command Center</span>
    <h2>Business Dashboard</h2>
    <p>Live control surface for selling, purchasing, stock, expenses, payments, and reports.</p>
  </div>
  <div class="hero-balance">
    <span>Net Cash</span>
    <strong>{cash["net_cash"]:.2f}</strong>
    <small>Cash in {cash["cash_in"]:.2f} / cash out {cash["cash_out"]:.2f}</small>
  </div>
</section>
<section class="dashboard-overview" data-dashboard-overview data-overview-values='{html.escape(json.dumps(overview_data), quote=True)}'>
  <div class="overview-heading">
    <div>
      <span class="overview-kicker">Live business snapshot</span>
      <h3>Overview</h3>
      <p>Sales performance and items needing attention.</p>
    </div>
    <div class="overview-periods">{''.join(overview_buttons)}</div>
  </div>
  <div class="overview-grid">
    <div class="overview-summary">
      <div class="overview-stat overview-stat-primary">
        <span>Net Sales</span>
        <strong data-overview-value="sales">{current_overview['sales']:.2f}</strong>
        <small>Selected period</small>
      </div>
      <div class="overview-stat">
        <span>Orders</span>
        <strong data-overview-value="orders">{current_overview['orders']:.0f}</strong>
        <small>Final sales</small>
      </div>
      <div class="overview-stat">
        <span>Net Profit</span>
        <strong data-overview-value="profit">{current_overview['profit']:.2f}</strong>
        <small>After expenses</small>
      </div>
      <div class="overview-stat">
        <span>Expenses</span>
        <strong data-overview-value="expenses">{current_overview['expenses']:.2f}</strong>
        <small>Approved and paid</small>
      </div>
      <div class="overview-stat">
        <span>Amount Due</span>
        <strong data-overview-value="due">{current_overview['due']:.2f}</strong>
        <small>Customer balance</small>
      </div>
      <div class="overview-stat">
        <span>Units Sold</span>
        <strong data-overview-value="units">{current_overview['units']:.2f}</strong>
        <small>Product quantity</small>
      </div>
    </div>
    <div class="overview-trend">
      <div class="overview-trend-head">
        <div><span>Sales trend</span><strong>Last 7 days</strong></div>
        <small>{week_start.strftime('%d %b')} - {today.strftime('%d %b')}</small>
      </div>
      <div class="overview-bars">{overview_chart}</div>
    </div>
    <div class="overview-attention">
      <span>Needs attention</span>
      <a href="/dashboard?page=Stock%20Alert"><strong>{low_stock_count}</strong><small>Low stock products</small></a>
      <a href="/dashboard?page=Pending%20Cheques"><strong>{pending_cheques['count']}</strong><small>Pending cheques</small></a>
      <a href="/dashboard?page=Sales%20History"><strong data-overview-value="due">{current_overview['due']:.2f}</strong><small>Customer amount due</small></a>
    </div>
  </div>
</section>
<div class="dashboard-section-title">
  <div><h3>All-time records</h3><p>Lifetime totals across the complete system.</p></div>
</div>
<section class="dash-metrics">{card_html}</section>
<section class="dash-layout">
  <article class="dash-panel dash-panel-wide">
    <div class="panel-heading">
      <div>
        <h3>Fast Actions</h3>
        <p>Most-used workflows for counter and back-office work.</p>
      </div>
    </div>
    <div class="action-grid">
      {dashboard_action("POS", "New Sale", "sales", "Start checkout")}
      {dashboard_action("Sales History", "Sales History", "cash", "Today, week, month")}
      {dashboard_action("Products", "Products", "product", "Manage items")}
      {dashboard_action("Purchases", "Purchases", "purchase", "Receive stock")}
      {dashboard_action("Pending Cheques", "Pending Cheques", "cash", "Clear or bounce")}
      {dashboard_action("Stock", "Stock", "stock", "Check balance")}
      {dashboard_action("Backup", "Backup", "backup", "Protect data")}
    </div>
  </article>
  <article class="dash-panel">
    <div class="panel-heading">
      <div>
        <h3>Inventory Health</h3>
        <p>Lowest available stock first.</p>
      </div>
    </div>
    <table class="compact-table">
      <thead><tr><th>Product</th><th>Stock</th><th>Status</th></tr></thead>
      <tbody>{stock_rows_html}</tbody>
    </table>
  </article>
  <article class="dash-panel">
    <div class="panel-heading">
      <div>
        <h3>Recent Money Movement</h3>
        <p>Latest payment records.</p>
      </div>
    </div>
    <table class="compact-table">
      <thead><tr><th>Date</th><th>Type</th><th>Ref</th><th>Amount</th></tr></thead>
      <tbody>{transaction_rows}</tbody>
    </table>
  </article>
  <article class="dash-panel">
    <div class="panel-heading">
      <div>
        <h3>Workflow Coverage</h3>
        <p>Core modules completed in this build.</p>
      </div>
    </div>
    <div class="coverage-list">
      {coverage_item("Products", "Ready")}
      {coverage_item("Contacts", "Ready")}
      {coverage_item("Purchases", "Ready")}
      {coverage_item("Sales", "Ready")}
      {coverage_item("Stock", "Ready")}
      {coverage_item("Reports", "Ready")}
    </div>
  </article>
</section>
<script>
  (() => {{
    const overview = document.querySelector('[data-dashboard-overview]');
    if (!overview) return;
    const values = JSON.parse(overview.dataset.overviewValues || '{{}}');
    overview.querySelectorAll('[data-overview-period]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const period = values[button.dataset.overviewPeriod];
        if (!period) return;
        overview.querySelectorAll('[data-overview-period]').forEach((item) => item.classList.toggle('active', item === button));
        overview.querySelectorAll('[data-overview-value]').forEach((element) => {{
          const key = element.dataset.overviewValue;
          const value = Number(period[key] || 0);
          element.textContent = key === 'orders' ? value.toFixed(0) : value.toFixed(2);
          element.classList.remove('value-updated');
          void element.offsetWidth;
          element.classList.add('value-updated');
        }});
      }});
    }});
  }})();
</script>"""


def dashboard_action(page: str, label: str, icon_name: str, hint: str) -> str:
    return f"""
<a class="dash-action" href="/dashboard?page={quote(page)}">
  <span class="dash-action-icon dash-icon-{icon_name}">{svg_icon(icon_name)}</span>
  <strong>{html.escape(label)}</strong>
  <small>{html.escape(hint)}</small>
</a>"""


def coverage_item(label: str, value: str) -> str:
    return f"""
<div class="coverage-item">
  <span>{html.escape(label)}</span>
  <strong>{html.escape(value)}</strong>
</div>"""


def menu_icon(label: str) -> str:
    icon_by_label = {
        "Dashboard": "dashboard",
        "Sales": "sales",
        "POS": "pos",
        "Sales History": "history",
        "Returns": "return",
        "Cash Register": "cash",
        "Products": "product",
        "Stock": "stock",
        "Stock Adjustment": "adjust",
        "Product Setup": "setup",
        "Purchases": "purchase",
        "Pending Cheques": "cheque",
        "Purchase Returns": "return",
        "Suppliers": "supplier",
        "Customers": "customers",
        "Customer Groups": "groups",
        "Customer Payments": "payments",
        "Expenses": "expenses",
        "Expense Setup": "setup",
        "Reports": "reports",
        "Sales Summary": "reports",
        "Stock Summary": "stock",
        "Profit / Loss": "profit",
        "Payments": "payments",
        "Settings": "settings",
        "Business": "business",
        "Roles": "roles",
        "Users": "users",
        "Print / Receipt": "receipt",
        "Backup": "backup",
        "Add-ons": "addons",
        "WooCommerce": "store",
        "Manufacturing": "manufacturing",
        "Accounting": "accounting",
        "HRM / Essentials": "hrm",
        "CRM": "crm",
        "Restaurant / Kitchen": "restaurant",
        "SaaS / Super Admin": "saas",
        "API Connector": "api",
    }
    return svg_icon(icon_by_label.get(label, "product"))


def svg_icon(name: str) -> str:
    icons = {
        "dashboard": '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/></svg>',
        "sales": '<svg viewBox="0 0 24 24"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16v-5"/><path d="M12 16V8"/><path d="M16 16v-3"/></svg>',
        "pos": '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="10" rx="2"/><path d="M8 19h8"/><path d="M12 15v4"/><path d="M8 9h8"/></svg>',
        "search": '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M10.5 7.5v6"/><path d="M7.5 10.5h6"/></svg>',
        "history": '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v6l4 2"/></svg>',
        "return": '<svg viewBox="0 0 24 24"><path d="M9 7H5v4"/><path d="M5 11l5-5"/><path d="M5 11h10a4 4 0 0 1 0 8h-4"/></svg>',
        "purchase": '<svg viewBox="0 0 24 24"><path d="M6 7h15l-2 8H8L6 3H3"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/></svg>',
        "product": '<svg viewBox="0 0 24 24"><path d="M21 8l-9-5-9 5 9 5 9-5Z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/></svg>',
        "products": '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>',
        "brand": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4v16"/><path d="M8 8h5a3 3 0 0 1 0 6H8"/><path d="M8 14h6a3 3 0 0 1 0 6H8"/></svg>',
        "star": '<svg viewBox="0 0 24 24"><path d="M12 3l2.7 5.5 6.1.9-4.4 4.3 1 6.1L12 16.9 6.6 19.8l1-6.1-4.4-4.3 6.1-.9L12 3Z"/></svg>',
        "profit": '<svg viewBox="0 0 24 24"><path d="M4 17l6-6 4 4 6-8"/><path d="M14 7h6v6"/></svg>',
        "stock": '<svg viewBox="0 0 24 24"><path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/><path d="M7 6v12"/><path d="M17 6v12"/></svg>',
        "cash": '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 9v.01"/><path d="M18 15v.01"/></svg>',
        "cancel": '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9l6 6"/><path d="M15 9l-6 6"/></svg>',
        "draft": '<svg viewBox="0 0 24 24"><path d="M5 19h14"/><path d="M7 17l1-5 8-8 4 4-8 8-5 1Z"/><path d="M14 6l4 4"/></svg>',
        "quotation": '<svg viewBox="0 0 24 24"><path d="M5 19h14"/><path d="M7 17l1-5 8-8 4 4-8 8-5 1Z"/><path d="M14 6l4 4"/><path d="M6 7h5"/></svg>',
        "pause": '<svg viewBox="0 0 24 24"><rect x="7" y="5" width="4" height="14" rx="1"/><rect x="13" y="5" width="4" height="14" rx="1"/></svg>',
        "check": '<svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>',
        "card": '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/><path d="M7 15h3"/></svg>',
        "multi_pay": '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="14" height="10" rx="2"/><path d="M6 11h4"/><path d="M6 14h2"/><path d="M17 9h4v10H7v-2"/></svg>',
        "backup": '<svg viewBox="0 0 24 24"><path d="M12 3v10"/><path d="M8 9l4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
        "adjust": '<svg viewBox="0 0 24 24"><path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/><path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/></svg>',
        "setup": '<svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19 12h2"/><path d="M3 12h2"/><path d="M12 3v2"/><path d="M12 19v2"/><path d="M17 7l1.4-1.4"/><path d="M5.6 18.4L7 17"/><path d="M17 17l1.4 1.4"/><path d="M5.6 5.6L7 7"/></svg>',
        "cheque": '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h5"/><path d="M7 14h10"/><path d="M16 10h1"/></svg>',
        "supplier": '<svg viewBox="0 0 24 24"><path d="M3 16h18"/><path d="M5 16V8l7-4 7 4v8"/><path d="M9 16v-5h6v5"/></svg>',
        "customers": '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2"/><path d="M15 15a5 5 0 0 1 6 5"/></svg>',
        "groups": '<svg viewBox="0 0 24 24"><circle cx="7" cy="8" r="2"/><circle cx="17" cy="8" r="2"/><circle cx="12" cy="14" r="2"/><path d="M4 19a3 3 0 0 1 6 0"/><path d="M14 19a3 3 0 0 1 6 0"/></svg>',
        "payments": '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18"/><path d="M7 15h4"/></svg>',
        "expenses": '<svg viewBox="0 0 24 24"><path d="M12 3v18"/><path d="M17 7H9.5a3.5 3.5 0 0 0 0 7H14a3 3 0 0 1 0 6H6"/></svg>',
        "reports": '<svg viewBox="0 0 24 24"><path d="M5 19V5"/><path d="M5 19h14"/><path d="M9 16v-5"/><path d="M13 16V8"/><path d="M17 16v-3"/></svg>',
        "settings": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a8 8 0 0 0 .1-6"/><path d="M4.5 9a8 8 0 0 0 .1 6"/><path d="M7 4.8a8 8 0 0 1 5-1.8 8 8 0 0 1 5 1.8"/><path d="M17 19.2a8 8 0 0 1-10 0"/></svg>',
        "logout": '<svg viewBox="0 0 24 24"><path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4"/><path d="M14 8l4 4-4 4"/><path d="M9 12h9"/></svg>',
        "business": '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="1"/><path d="M8 8h2"/><path d="M14 8h2"/><path d="M8 12h2"/><path d="M14 12h2"/><path d="M10 20v-4h4v4"/></svg>',
        "roles": '<svg viewBox="0 0 24 24"><path d="M12 3l7 4v5c0 5-3 8-7 9-4-1-7-4-7-9V7l7-4Z"/><path d="M9 12l2 2 4-4"/></svg>',
        "users": '<svg viewBox="0 0 24 24"><circle cx="12" cy="7" r="3"/><path d="M5 21a7 7 0 0 1 14 0"/></svg>',
        "receipt": '<svg viewBox="0 0 24 24"><path d="M6 3h12v18l-2-1-2 1-2-1-2 1-2-1-2 1V3Z"/><path d="M9 8h6"/><path d="M9 12h6"/><path d="M9 16h4"/></svg>',
        "addons": '<svg viewBox="0 0 24 24"><path d="M8 3v4"/><path d="M16 3v4"/><path d="M7 7h10v4a5 5 0 0 1-10 0V7Z"/><path d="M12 16v5"/></svg>',
        "store": '<svg viewBox="0 0 24 24"><path d="M4 10h16l-1-5H5l-1 5Z"/><path d="M6 10v10h12V10"/><path d="M9 20v-5h6v5"/></svg>',
        "manufacturing": '<svg viewBox="0 0 24 24"><path d="M4 20V9l5 3V9l5 3V7h6v13H4Z"/><path d="M8 16h2"/><path d="M13 16h2"/></svg>',
        "accounting": '<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8"/><path d="M8 12h3"/><path d="M13 12h3"/><path d="M8 16h3"/><path d="M13 16h3"/></svg>',
        "hrm": '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M4 20a5 5 0 0 1 10 0"/><path d="M16 11l2 2 4-5"/></svg>',
        "crm": '<svg viewBox="0 0 24 24"><path d="M4 5h16v10H7l-3 3V5Z"/><circle cx="9" cy="10" r="1"/><circle cx="12" cy="10" r="1"/><circle cx="15" cy="10" r="1"/></svg>',
        "restaurant": '<svg viewBox="0 0 24 24"><path d="M7 3v8"/><path d="M5 3v8"/><path d="M9 3v8"/><path d="M5 11h4v10"/><path d="M16 3v18"/><path d="M16 3c3 2 3 7 0 9"/></svg>',
        "saas": '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8"/><path d="M8 13h4"/><path d="M14 17h2"/></svg>',
        "api": '<svg viewBox="0 0 24 24"><path d="M8 9l-4 3 4 3"/><path d="M16 9l4 3-4 3"/><path d="M14 5l-4 14"/></svg>',
    }
    return icons.get(name, icons["product"])


def render_page(
    active_page: str,
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    if active_page == "Dashboard":
        return render_dashboard_home()
    if active_page == "Customers":
        return render_customers_page(message=message, error=error, query=query)
    if active_page == "Suppliers":
        return render_suppliers_page(message=message, error=error, query=query)
    if active_page == "Customer Groups":
        return render_customer_groups(message=message, error=error, query=query)
    if active_page == "Import Contacts":
        return render_import_contacts(message=message, error=error)
    if active_page in {"Purchases", "List Purchases"}:
        return render_purchase_list(query=query, message=message, error=error)
    if active_page == "Add Purchase":
        return render_add_purchase(message=message, error=error)
    if active_page == "Pending Cheques":
        return render_pending_purchase_cheques(query=query, message=message, error=error)
    if active_page == "Purchase Order":
        return render_purchase_order(message=message, error=error)
    if active_page in {"Purchase Returns", "Purchase Return"}:
        return render_purchase_return(message=message, error=error)
    if active_page in {"New Sale", "POS", "Add Sale"}:
        return render_pos_sale(message=message, error=error, source_sale_id=optional_query_int(query, "source_sale_id"))
    if active_page in {"Sales History", "List Sales"}:
        return render_sales_list(query=query, message=message, error=error)
    if active_page in {"Returns", "Sales Return"}:
        return render_sales_return(message=message, error=error)
    if active_page == "Cash Register":
        return render_cash_register(query.get("_user_id", [None])[0], message=message, error=error)
    if active_page == "Drafts":
        return render_sales_document("Drafts", "draft", "Save incomplete sales without reducing stock.", message, error)
    if active_page == "Quotations":
        return render_sales_document("Quotations", "quotation", "Create customer quotations without stock movement.", message, error)
    if active_page == "Suspended Sales":
        return render_sales_document("Suspended Sales", "suspended", "Hold a POS sale temporarily without reducing stock.", message, error)
    if active_page == "Sales Orders":
        return render_sales_document("Sales Orders", "sales_order", "Create customer orders before final fulfillment.", message, error)
    if active_page == "Shipments":
        return render_shipments(message=message, error=error)
    if active_page in {"Expenses", "List Expenses"}:
        return render_expense_list(query=query, message=message, error=error)
    if active_page == "Expense Setup":
        return render_expense_setup()
    if active_page == "Add Expense":
        return render_add_expense(message=message, error=error)
    if active_page == "Expense Categories":
        return render_expense_categories(message=message, error=error)
    if active_page == "Expense Subcategories":
        return render_expense_categories(message=message, error=error, subcategories_only=True)
    if active_page == "Expense Payees":
        return render_expense_payees()
    if active_page == "Expense Budgets":
        return render_expense_budgets()
    if active_page == "Expense Controls":
        return render_expense_controls(message=message, error=error)
    if active_page == "Recurring Expenses":
        return render_recurring_expenses()
    if active_page == "Expense Refund":
        return render_expense_refund(message=message, error=error)
    if active_page in {"Accounts", "Payment Accounts"}:
        return render_payment_accounts(message=message, error=error)
    if active_page == "Customer Payments":
        return render_customer_payments(query=query, message=message, error=error)
    if active_page == "Supplier Payments":
        return render_supplier_payments(query=query, message=message, error=error)
    if active_page == "Transactions":
        return render_payment_transactions(message=message, error=error)
    if active_page == "Deposits":
        return render_deposits(message=message, error=error)
    if active_page == "Transfers":
        return render_transfers(message=message, error=error)
    if active_page in {"Sales Summary", "Sales Report"}:
        return render_sales_report(query)
    if active_page == "Purchase Report":
        return render_purchase_report(query)
    if active_page in {"Profit / Loss", "Profit / Loss Report"}:
        return render_profit_loss_report(query)
    if active_page == "Purchase & Sale Report":
        return render_purchase_sale_report()
    if active_page == "Tax Report":
        return render_tax_report()
    if active_page == "Supplier & Customer Report":
        return render_supplier_customer_report()
    if active_page == "Expense Report":
        return render_expense_report()
    if active_page in {"Payments", "Payment Report"}:
        return render_payment_report(query)
    if active_page == "Due Payment Report":
        return render_due_payment_report()
    if active_page == "Cash Register Report":
        return render_cash_register_report()
    if active_page == "Trending Products":
        return render_trending_products_report()
    if active_page == "Sales Representative Report":
        return render_sales_representative_report()
    if active_page in {"Business", "Business Settings"}:
        return render_business_settings(message=message, error=error)
    if active_page == "Business Locations":
        return render_business_locations(message=message, error=error)
    if active_page == "Print / Receipt":
        return render_print_receipt_settings(message=message, error=error)
    if active_page == "Invoice Settings":
        return render_invoice_settings(message=message, error=error)
    if active_page == "Barcode Settings":
        return render_barcode_settings(message=message, error=error)
    if active_page == "Tax Rates":
        return render_tax_rates(message=message, error=error)
    if active_page == "Payment Methods":
        return render_payment_methods(message=message, error=error)
    if active_page == "Printers":
        return render_printers(message=message, error=error)
    if active_page == "System Health":
        return render_system_health()
    if active_page == "Users":
        return render_users(message=message, error=error, query=query)
    if active_page == "Roles":
        return render_roles(message=message, error=error)
    if active_page == "Sales Commission Agents":
        return render_commission_agents(message=message, error=error)
    if active_page == "Backup":
        return render_backup(message=message, error=error)
    if active_page in {"Products", "List Products"}:
        return render_product_list(query=query, message=message, error=error)
    if active_page == "Add Product":
        return render_add_product(message=message, error=error)
    if active_page == "Edit Product":
        return render_edit_product(optional_query_int(query, "id"), message=message, error=error)
    if active_page == "Import Products":
        return render_import_products(message=message, error=error)
    if active_page == "Import Opening Stock":
        return render_import_opening_stock(message=message, error=error)
    if active_page == "Print Labels":
        return render_print_labels(query=query)
    if active_page == "Variations":
        return render_variations(message=message, error=error)
    if active_page == "Selling Price Groups":
        return render_selling_price_groups(message=message, error=error, query=query)
    if active_page == "Warranties":
        return render_warranties(message=message, error=error)
    if active_page == "Categories":
        return render_categories(message=message, error=error)
    if active_page == "Brands":
        return render_brands(message=message, error=error)
    if active_page == "Units":
        return render_lookup_page("Units", "unit", ProductRepository().list_units(), message, error)
    if active_page == "Stock Alert":
        return render_stock_alert_page()
    if active_page == "Stock Adjustment":
        return render_stock_adjustment(message=message, error=error)
    if active_page == "Stock Transfer":
        return render_stock_transfer(message=message, error=error)
    if active_page in {"Stock", "Stock Summary", "Stock Report"}:
        return render_stock_report(query)
    if active_page == "Low Stock Report":
        return render_low_stock_report()
    if active_page == "Stock Adjustment Report":
        return render_stock_adjustment_report()
    if active_page == "Stock Transfer Report":
        return render_stock_transfer_report()
    if active_page == "Product Stock History":
        product_id = optional_query_int(query, "product_id")
        return render_product_stock_history(product_id, query)
    if active_page == "Product Setup":
        return render_product_setup()
    addon_key = ADDON_PAGE_KEYS.get(active_page)
    if addon_key:
        return render_addon_page(addon_key, message=message, error=error, query=query)
    return render_placeholder(active_page)


def render_notice(message: str = "", error: str = "") -> str:
    if error:
        return f'<div class="error">{html.escape(error)}</div>'
    if message:
        return f'<div class="success">{html.escape(message)}</div>'
    return ""


def render_shortcut_hub(title: str, hint: str, links: list[tuple[str, str]]) -> str:
    cards = "".join(
        f"""
        <a class="dash-action" href="/dashboard?page={quote(page)}">
          <span class="dash-action-icon dash-icon-product">{svg_icon("product")}</span>
          <strong>{html.escape(page)}</strong>
          <small>{html.escape(description)}</small>
        </a>
        """
        for page, description in links
    )
    return f"""
<div class="page-title">
  <h2>{html.escape(title)}</h2>
  <p>{html.escape(hint)}</p>
</div>
<section class="action-grid">{cards}</section>"""


def render_product_setup() -> str:
    return render_shortcut_hub(
        "Product Setup",
        "Keep daily product work simple. Use these setup tools only when the catalog structure needs changes.",
        [
            ("Add Product", "Create a new product"),
            ("Categories", "Shop type templates, categories, and subcategories"),
            ("Brands", "Optional starter brands and brand records"),
            ("Units", "Pieces, boxes, kilograms, liters, and other units"),
            ("Variations", "Size, color, pack, and exact product variants"),
            ("Warranties", "Warranty terms used by products and brands"),
            ("Selling Price Groups", "Customer-specific price groups"),
            ("Import Products", "Bulk product import"),
            ("Import Opening Stock", "Bulk opening stock import"),
            ("Print Labels", "Barcode and product labels"),
            ("Stock Alert", "Products needing reorder"),
        ],
    )


def render_print_receipt_settings(message: str = "", error: str = "") -> str:
    return f"""
<div class="page-title">
  <h2>Print / Receipt</h2>
  <p>Manage invoice, receipt, barcode, printer, tax, and payment print settings from one place.</p>
</div>
{render_notice(message, error)}
<section class="action-grid">
  {settings_shortcut("Invoice Settings", "Invoice numbers, footer text, and terms")}
  {settings_shortcut("Printers", "Receipt, invoice, and barcode printer setup")}
  {settings_shortcut("Barcode Settings", "Label size, barcode prefix, and label contents")}
  {settings_shortcut("Tax Rates", "Tax rates used by products, sales, and purchases")}
  {settings_shortcut("Payment Methods", "Cash, card, bank transfer, wallet, and cheque methods")}
</section>"""


def settings_shortcut(page: str, description: str) -> str:
    return f"""
<a class="dash-action" href="/dashboard?page={quote(page)}">
  <span class="dash-action-icon dash-icon-stock">{svg_icon("stock")}</span>
  <strong>{html.escape(page)}</strong>
  <small>{html.escape(description)}</small>
</a>"""


def render_product_list(query: dict[str, list[str]] | None = None, message: str = "", error: str = "") -> str:
    query = query or {}
    repository = ProductRepository()
    products = repository.list_products()
    categories = repository.list_categories()
    brands = repository.list_brands()

    search = (query.get("search", [""])[0] or "").strip()
    category_id = optional_query_int(query, "category_id")
    brand_id = optional_query_int(query, "brand_id")
    status = (query.get("status", ["all"])[0] or "all").strip()
    stock = (query.get("stock", ["all"])[0] or "all").strip()
    view = (query.get("view", ["table"])[0] or "table").strip()
    sort = (query.get("sort", ["newest"])[0] or "newest").strip()

    total_count = len(products)
    active_count = sum(1 for row in products if row["is_active"])
    inactive_count = total_count - active_count
    low_stock_count = sum(1 for row in products if product_is_low_stock(row))

    filtered = filter_product_rows(products, search, category_id, brand_id, status, stock)
    filtered = sort_product_rows(filtered, sort)

    rows = "".join(render_product_table_row(row) for row in filtered)
    if not rows:
        rows = '<tr><td colspan="11" class="empty">No products match the selected filters.</td></tr>'

    cards = "".join(render_product_card(row) for row in filtered)
    if not cards:
        cards = '<p class="empty product-empty">No products match the selected filters.</p>'

    table_active = "active" if view != "grid" else ""
    grid_active = "active" if view == "grid" else ""
    product_table_style = "" if view != "grid" else ' style="display:none"'
    product_grid_style = "" if view == "grid" else ' style="display:none"'

    return f"""
<div class="page-title action-title product-title">
  <div>
    <span class="product-kicker">Product Control Center</span>
    <h2>Products</h2>
    <p>Manage product images, prices, barcode identity, stock status, labels, and POS readiness from one screen.</p>
  </div>
  <div class="product-title-actions">
    <a class="secondary-link" href="/dashboard?page=Import%20Products">Import</a>
    <a class="secondary-link" href="/dashboard?page=Print%20Labels">Labels</a>
    <a class="primary-link" href="/dashboard?page=Add%20Product">Add Product</a>
  </div>
</div>
{render_notice(message, error)}
<section class="product-stats">
  {product_metric("Total Products", str(total_count), "Master catalog")}
  {product_metric("Active", str(active_count), "Visible in sales")}
  {product_metric("Low Stock", str(low_stock_count), "Needs reorder")}
  {product_metric("Inactive", str(inactive_count), "Hidden from POS")}
</section>
<article class="panel product-filter-panel">
  <form method="get" action="/dashboard" class="product-filter-form">
    <input type="hidden" name="page" value="List Products">
    <input type="hidden" name="view" value="{html.escape(view)}">
    <label class="field product-search-field">
      <span>Search</span>
      <input name="search" value="{html.escape(search)}" placeholder="Name, SKU, or barcode">
    </label>
    {product_lookup_filter("Category", "category_id", categories, category_id)}
    {product_lookup_filter("Brand", "brand_id", brands, brand_id)}
    {product_choice_filter("Status", "status", (("all", "All"), ("active", "Active"), ("inactive", "Inactive")), status)}
    {product_choice_filter("Stock", "stock", (("all", "All"), ("low", "Low stock"), ("available", "Available")), stock)}
    {product_choice_filter("Sort", "sort", (("newest", "Newest"), ("name", "Name"), ("price_desc", "Price high"), ("low_stock", "Low stock")), sort)}
    <div class="product-filter-actions">
      <button type="submit">Apply</button>
      <a class="secondary-link" href="/dashboard?page=List%20Products">Reset</a>
    </div>
  </form>
</article>
<div class="product-viewbar">
  <div>
    <strong>{len(filtered)}</strong> products shown
  </div>
  <div class="segmented-control">
    <a class="{table_active}" href="{product_view_url(query, 'table')}">Table</a>
    <a class="{grid_active}" href="{product_view_url(query, 'grid')}">Grid</a>
  </div>
</div>
<article class="panel table-panel product-table-panel"{product_table_style}>
  <table class="product-table">
    <thead>
      <tr>
        <th class="col-product">Product</th>
        <th class="col-sku">SKU / Barcode</th>
        <th class="col-category">Category</th>
        <th class="col-brand">Brand</th>
        <th class="col-unit">Unit</th>
        <th class="col-stock">Stock</th>
        <th class="col-alert">Alert</th>
        <th class="col-purchase">Purchase</th>
        <th class="col-selling">Selling</th>
        <th class="col-status">Status</th>
        <th class="col-action">Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
<section class="product-card-grid"{product_grid_style}>{cards}</section>"""


def filter_product_rows(products: list, search: str, category_id: int | None, brand_id: int | None, status: str, stock: str) -> list:
    search_text = search.lower()
    filtered = []
    for row in products:
        if search_text:
            haystack = " ".join(
                str(row[key] or "")
                for key in ("name", "sku", "barcode", "category_name", "brand_name")
            ).lower()
            if search_text not in haystack:
                continue
        if category_id is not None and row["category_id"] != category_id:
            continue
        if brand_id is not None and row["brand_id"] != brand_id:
            continue
        if status == "active" and not row["is_active"]:
            continue
        if status == "inactive" and row["is_active"]:
            continue
        if stock == "low" and not product_is_low_stock(row):
            continue
        if stock == "available" and float(row["available_stock"] or 0) <= 0:
            continue
        filtered.append(row)
    return filtered


def sort_product_rows(products: list, sort: str) -> list:
    if sort == "name":
        return sorted(products, key=lambda row: (row["name"] or "").lower())
    if sort == "price_desc":
        return sorted(products, key=lambda row: float(row["selling_price"] or 0), reverse=True)
    if sort == "low_stock":
        return sorted(products, key=lambda row: (not product_is_low_stock(row), float(row["available_stock"] or 0)))
    return list(products)


def product_is_low_stock(row) -> bool:
    alert_quantity = float(row["alert_quantity"] or 0)
    return alert_quantity > 0 and float(row["available_stock"] or 0) <= alert_quantity


def product_offer_discount(row) -> float:
    selling_price = float(row["selling_price"] or 0)
    offer_price = float(row["offer_price"] or 0)
    if offer_price <= 0 or selling_price <= 0 or offer_price >= selling_price:
        return 0.0
    today = __import__("datetime").date.today().isoformat()
    start_date = str(row["offer_start_date"] or "").strip()
    end_date = str(row["offer_end_date"] or "").strip()
    if start_date and today < start_date:
        return 0.0
    if end_date and today > end_date:
        return 0.0
    return selling_price - offer_price


def product_offer_price(row) -> float:
    discount = product_offer_discount(row)
    return max(float(row["selling_price"] or 0) - discount, 0)


def product_metric(label: str, value: str, hint: str) -> str:
    return f"""
<div class="metric product-metric">
  <span>{html.escape(label)}</span>
  <strong>{html.escape(value)}</strong>
  <small>{html.escape(hint)}</small>
</div>"""


def product_lookup_filter(label: str, name: str, options: list, selected_id: int | None) -> str:
    option_html = [f'<option value="" {"selected" if selected_id is None else ""}>All</option>']
    option_html.extend(
        f'<option value="{item.id}" {"selected" if selected_id == item.id else ""}>{html.escape(item.name)}</option>'
        for item in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}">{''.join(option_html)}</select>
</label>"""


def product_choice_filter(label: str, name: str, options: tuple[tuple[str, str], ...], selected: str) -> str:
    option_html = "".join(
        f'<option value="{html.escape(value)}" {"selected" if selected == value else ""}>{html.escape(text)}</option>'
        for value, text in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}">{option_html}</select>
</label>"""


def product_view_url(query: dict[str, list[str]], view: str) -> str:
    params = {key: values[0] for key, values in query.items() if values}
    params["page"] = "List Products"
    params["view"] = view
    return "/dashboard?" + "&".join(f"{quote(str(key))}={quote(str(value))}" for key, value in params.items() if value != "")


def product_image_markup(row, class_name: str = "product-thumb") -> str:
    image_path = (row["image_path"] or "").strip()
    if image_path:
        return f'<img class="{class_name}" src="{html.escape(image_path, quote=True)}" alt="{html.escape(row["name"], quote=True)}">'
    initials = "".join(part[:1] for part in (row["name"] or "P").split()[:2]).upper() or "P"
    return f'<span class="{class_name} product-thumb-placeholder">{html.escape(initials)}</span>'


def render_product_table_row(row) -> str:
    stock_class = "danger" if product_is_low_stock(row) else "ok"
    stock_label = "Low" if product_is_low_stock(row) else "Ready"
    status_badge = '<span class="badge ok">Active</span>' if row["is_active"] else '<span class="badge danger">Inactive</span>'
    offer_discount = product_offer_discount(row)
    offer_note = f'<small class="table-note">Offer {product_offer_price(row):.2f} (-{offer_discount:.2f})</small>' if offer_discount > 0 else ""
    return f"""
<tr>
  <td class="product-name-col">
    <div class="product-cell">
      {product_image_markup(row)}
      <div>
        <strong>{html.escape(row["name"])}</strong>
        <small>{html.escape(row["tax_name"] or "No tax")} / {int(row["variant_count"] or 0)} variants</small>
      </div>
    </div>
  </td>
  <td class="product-sku-col"><strong>{html.escape(row["sku"])}</strong><small class="table-note">{html.escape(row["barcode"] or "No barcode")}</small></td>
  <td class="clip-cell">{html.escape(row["category_name"] or "Uncategorized")}</td>
  <td class="clip-cell">{html.escape(row["brand_name"] or "No brand")}</td>
  <td class="clip-cell">{html.escape(row["unit_name"] or "")}</td>
  <td><span class="badge {stock_class} compact-stock-badge">{stock_label}: {float(row["available_stock"] or 0):.2f}</span></td>
  <td class="numeric">{float(row["alert_quantity"] or 0):.2f}</td>
  <td class="numeric">{float(row["purchase_price"] or 0):.2f}</td>
  <td class="numeric selling-price">{float(row["selling_price"] or 0):.2f}{offer_note}</td>
  <td>{status_badge}</td>
  <td class="actions-cell product-actions-cell">
    <a class="table-link" href="/dashboard?page=Edit%20Product&id={row["id"]}">Edit</a>
    <a class="table-link" href="/dashboard?page=Product%20Stock%20History&product_id={row["id"]}">Stock</a>
    <a class="table-link" href="/dashboard?page=Print%20Labels&product_id={row["id"]}">Label</a>
    <form method="post" action="/products/deactivate" class="table-action">
      <input type="hidden" name="product_id" value="{row["id"]}">
      <button type="submit">Deactivate</button>
    </form>
  </td>
</tr>"""


def render_product_card(row) -> str:
    stock_class = "danger" if product_is_low_stock(row) else "ok"
    stock_label = "Low stock" if product_is_low_stock(row) else "Available"
    status_badge = '<span class="badge ok">Active</span>' if row["is_active"] else '<span class="badge danger">Inactive</span>'
    offer_discount = product_offer_discount(row)
    price_label = "Offer Price" if offer_discount > 0 else "Selling Price"
    price_value = product_offer_price(row) if offer_discount > 0 else float(row["selling_price"] or 0)
    offer_badge = f'<span class="badge danger">Save {offer_discount:.2f}</span>' if offer_discount > 0 else ""
    return f"""
<article class="product-card">
  <div class="product-card-image">{product_image_markup(row, "product-card-thumb")}</div>
  <div class="product-card-body">
    <div class="product-card-head">
      <div>
        <h3>{html.escape(row["name"])}</h3>
        <p>{html.escape(row["sku"])} / {html.escape(row["barcode"] or "No barcode")}</p>
      </div>
      {status_badge}
    </div>
    <div class="product-card-meta">
      <span>{html.escape(row["category_name"] or "Uncategorized")}</span>
      <span>{html.escape(row["brand_name"] or "No brand")}</span>
    </div>
    <div class="product-card-bottom">
      <div>
        <small>{price_label}</small>
        <strong>{price_value:.2f}</strong>
      </div>
      {offer_badge or f'<span class="badge {stock_class}">{stock_label}: {float(row["available_stock"] or 0):.2f}</span>'}
    </div>
    <p class="table-note">{int(row["variant_count"] or 0)} variants configured</p>
    <div class="product-card-actions">
      <a class="secondary-link" href="/dashboard?page=Product%20Stock%20History&product_id={row["id"]}">Stock</a>
      <a class="secondary-link" href="/dashboard?page=Print%20Labels&product_id={row["id"]}">Label</a>
      <a class="primary-link" href="/dashboard?page=Edit%20Product&id={row["id"]}">Edit</a>
    </div>
  </div>
</article>"""


def product_image_upload_field(value: str = "") -> str:
    preview = (
        f'<img src="{html.escape(value, quote=True)}" alt="">'
        if value
        else "<span>Image</span>"
    )
    return f"""
<section class="product-image-uploader" data-product-image-upload>
  <div class="product-upload-preview" data-product-image-preview>{preview}</div>
  <div class="product-upload-controls">
    <label class="field">
      <span>Upload Product Image</span>
      <input type="file" accept="image/*" data-product-image-file>
    </label>
    <label class="field">
      <span>Image URL / Path</span>
      <input name="image_path" value="{html.escape(value, quote=True)}" placeholder="Upload image or paste image URL" data-product-image-path>
    </label>
    <p class="hint">Use a clear square product photo. If no image is selected, the product list shows a clean placeholder.</p>
  </div>
</section>"""


def category_defaults_select(categories: list, selected_id: int | None = None) -> str:
    options = ['<option value="">Select Category</option>']
    for row in categories:
        selected = "selected" if selected_id == row["id"] else ""
        label = f'-- {row["name"]}' if row["parent_id"] else row["name"]
        options.append(
            f"""
            <option
              value="{row["id"]}"
              data-tax="{row["default_tax_rate_id"] or ""}"
              data-unit="{row["default_unit_id"] or ""}"
              data-warranty="{row["default_warranty_id"] or ""}"
              data-margin="{float(row["default_profit_margin"] or 0):.2f}"
              {selected}
            >{html.escape(label)}</option>
            """
        )
    return f"""
<label class="field">
  <span>Category</span>
  <select name="category_id" data-category-defaults>{"".join(options)}</select>
</label>"""


def category_defaults_script() -> str:
    return """
<script>
(() => {
  const category = document.querySelector('[data-category-defaults]');
  const form = category?.closest('form');
  if (!category || !form) return;
  const purchase = form.querySelector('[name="purchase_price"]');
  const selling = form.querySelector('[name="selling_price"]');
  const margin = form.querySelector('[name="profit_margin"]');
  const applyPrice = () => {
    const cost = Number(purchase?.value || 0);
    const percent = Number(margin?.value || 0);
    if (selling && cost > 0) selling.value = (cost * (1 + percent / 100)).toFixed(2);
  };
  category.addEventListener('change', () => {
    const option = category.options[category.selectedIndex];
    for (const [fieldName, dataName] of [['tax_rate_id', 'tax'], ['unit_id', 'unit'], ['warranty_id', 'warranty']]) {
      const field = form.querySelector(`[name="${fieldName}"]`);
      if (field && option.dataset[dataName]) field.value = option.dataset[dataName];
    }
    if (margin) margin.value = option.dataset.margin || '0.00';
    applyPrice();
  });
  purchase?.addEventListener('input', applyPrice);
  margin?.addEventListener('input', applyPrice);
})();
</script>"""


def brand_defaults_select(brands: list, selected_id: int | None = None) -> str:
    options = ['<option value="">Select Brand</option>']
    for row in brands:
        selected = "selected" if selected_id == row["id"] else ""
        options.append(
            f"""
            <option
              value="{row["id"]}"
              data-warranty="{row["default_warranty_id"] or ""}"
              data-margin="{float(row["default_profit_margin"] or 0):.2f}"
              {selected}
            >{html.escape(row["name"])}</option>
            """
        )
    return f"""
<label class="field">
  <span>Brand</span>
  <select name="brand_id" data-brand-defaults>{"".join(options)}</select>
</label>"""


def brand_defaults_script() -> str:
    return """
<script>
(() => {
  const brand = document.querySelector('[data-brand-defaults]');
  const form = brand?.closest('form');
  if (!brand || !form) return;
  const purchase = form.querySelector('[name="purchase_price"]');
  const selling = form.querySelector('[name="selling_price"]');
  const margin = form.querySelector('[name="profit_margin"]');
  const applyPrice = () => {
    const cost = Number(purchase?.value || 0);
    const percent = Number(margin?.value || 0);
    if (selling && cost > 0) selling.value = (cost * (1 + percent / 100)).toFixed(2);
  };
  brand.addEventListener('change', () => {
    const option = brand.options[brand.selectedIndex];
    const warranty = form.querySelector('[name="warranty_id"]');
    if (warranty && option.dataset.warranty) warranty.value = option.dataset.warranty;
    if (margin && Number(option.dataset.margin || 0) > 0) margin.value = option.dataset.margin;
    applyPrice();
  });
})();
</script>"""


def render_add_product(message: str = "", error: str = "") -> str:
    repository = ProductRepository()
    categories = repository.list_category_records(active_only=True)
    brands = repository.list_brand_records(active_only=True)
    units = repository.list_units()
    tax_rates = repository.list_tax_rates()
    warranties = repository.list_warranty_options()

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Add Product</h2>
    <p>Create the product master record used by purchases, stock, POS sales, and reports.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Products">List Products</a>
</div>
{render_notice(message, error)}
<article class="panel product-form-panel">
  <form class="product-form" method="post" action="/products/create">
    {product_image_upload_field()}
    <section class="product-form-section">
      <div class="section-heading">
        <span>01</span>
        <div><h4>Product Identity</h4><p>Name, barcode identity, category, brand, and unit.</p></div>
      </div>
      <div class="form-grid three-col">
        {text_input("Product Name", "name", required=True)}
        {text_input("SKU", "sku", required=True)}
        {automatic_barcode_input()}
        {category_defaults_select(categories)}
        {brand_defaults_select(brands)}
        {select_input("Unit", "unit_id", units)}
      </div>
    </section>
    <section class="product-form-section">
      <div class="section-heading">
        <span>02</span>
        <div><h4>Pricing And Stock</h4><p>Purchase cost, selling price, tax, stock alert, and POS status.</p></div>
      </div>
      <div class="form-grid three-col">
        {number_input("Purchase Price", "purchase_price", "0.00")}
        {number_input("Selling Price", "selling_price", "0.00")}
        {number_input("Profit Margin (%)", "profit_margin", "0.00")}
        {number_input("Offer Price", "offer_price", "0.00")}
        {date_input_optional("Offer Start Date", "offer_start_date", "")}
        {date_input_optional("Offer End Date", "offer_end_date", "")}
        {select_input("Tax Rate", "tax_rate_id", tax_rates)}
        {select_input("Warranty", "warranty_id", warranties)}
        {number_input("Alert Quantity", "alert_quantity", "0")}
        <label class="field">
          <span>Status</span>
          <select name="is_active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
          </select>
        </label>
      </div>
    </section>
    <div class="form-actions">
      <button type="submit">Save Product</button>
      <a href="/dashboard?page=List%20Products">Cancel</a>
    </div>
  </form>
</article>
{category_defaults_script()}
{brand_defaults_script()}"""


def render_edit_product(product_id: int | None, message: str = "", error: str = "") -> str:
    if product_id is None:
        return render_placeholder("Edit Product")
    product = ProductRepository().get_product(product_id)
    if product is None:
        return render_not_found_page("Product not found.")
    repository = ProductRepository()
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Edit Product</h2>
    <p>Update product master details.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Products">List Products</a>
</div>
{render_notice(message, error)}
<article class="panel product-form-panel">
  <form class="product-form" method="post" action="/products/update">
    <input type="hidden" name="product_id" value="{product["id"]}">
    {product_image_upload_field(product["image_path"] or "")}
    <section class="product-form-section">
      <div class="section-heading">
        <span>01</span>
        <div><h4>Product Identity</h4><p>Name, barcode identity, category, brand, and unit.</p></div>
      </div>
      <div class="form-grid three-col">
        {preset_text_input("Product Name", "name", product["name"], required=True)}
        {preset_text_input("SKU", "sku", product["sku"], required=True)}
        {automatic_barcode_input(product["barcode"] or "")}
        {select_input("Category", "category_id", repository.list_categories(), product["category_id"])}
        {select_input("Brand", "brand_id", repository.list_brands(), product["brand_id"])}
        {select_input("Unit", "unit_id", repository.list_units(), product["unit_id"])}
      </div>
    </section>
    <section class="product-form-section">
      <div class="section-heading">
        <span>02</span>
        <div><h4>Pricing And Stock</h4><p>Purchase cost, selling price, tax, stock alert, and POS status.</p></div>
      </div>
      <div class="form-grid three-col">
        {number_input("Purchase Price", "purchase_price", f'{product["purchase_price"]:.2f}')}
        {number_input("Selling Price", "selling_price", f'{product["selling_price"]:.2f}')}
        {number_input("Profit Margin (%)", "profit_margin", f'{product["profit_margin"]:.2f}')}
        {number_input("Offer Price", "offer_price", f'{float(product["offer_price"] or 0):.2f}')}
        {date_input_optional("Offer Start Date", "offer_start_date", product["offer_start_date"] or "")}
        {date_input_optional("Offer End Date", "offer_end_date", product["offer_end_date"] or "")}
        {select_input("Tax Rate", "tax_rate_id", repository.list_tax_rates(), product["tax_rate_id"])}
        {select_input("Warranty", "warranty_id", repository.list_warranty_options(), product["warranty_id"])}
        {number_input("Alert Quantity", "alert_quantity", f'{product["alert_quantity"]:.2f}')}
        <label class="field">
          <span>Status</span>
          <select name="is_active">
            <option value="1" {'selected' if product["is_active"] else ''}>Active</option>
            <option value="0" {'selected' if not product["is_active"] else ''}>Inactive</option>
          </select>
        </label>
      </div>
    </section>
    <div class="form-actions">
      <button type="submit">Update Product</button>
      <a href="/dashboard?page=List%20Products">Cancel</a>
    </div>
  </form>
</article>"""

def render_import_products(message: str = "", error: str = "") -> str:
    sample = "name,sku,barcode,image_path,purchase_price,selling_price,offer_price,offer_start_date,offer_end_date,profit_margin,alert_quantity\nImported Product,IMP-001,IMP-001,https://example.com/product.jpg,100,150,135,2026-06-30,2026-07-31,50,5"
    return render_csv_import_page(
        title="Import Products",
        hint="Paste product CSV data. Required columns: name, sku.",
        action="/products/import",
        sample=sample,
        message=message,
        error=error,
    )


def render_import_opening_stock(message: str = "", error: str = "") -> str:
    sample = "sku,quantity\nIMP-001,25"
    return render_csv_import_page(
        title="Import Opening Stock",
        hint="Paste opening stock CSV data. Required columns: sku, quantity. This creates opening_stock movements.",
        action="/products/opening-stock/import",
        sample=sample,
        message=message,
        error=error,
    )


def render_csv_import_page(title: str, hint: str, action: str, sample: str, message: str = "", error: str = "") -> str:
    return f"""
<div class="page-title">
  <h2>{html.escape(title)}</h2>
  <p>{html.escape(hint)}</p>
</div>
{render_notice(message, error)}
<article class="panel">
  <form method="post" action="{html.escape(action)}">
    <label class="field">
      <span>CSV Data</span>
      <textarea name="csv_text" rows="12">{html.escape(sample)}</textarea>
    </label>
    <button type="submit">{html.escape(title)}</button>
  </form>
</article>"""


def render_print_labels(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    products = ProductRepository().list_products()
    product_id = optional_query_int(query, "product_id")
    if product_id is not None:
        products = [row for row in products if row["id"] == product_id]
    selected_product = products[0] if product_id is not None and products else None
    labels = "".join(render_product_label(row) for row in products)
    if not labels:
        labels = '<p class="empty">No products available for labels.</p>'
    page_title = "Print Product Label" if selected_product else "Print Labels"
    page_hint = (
        f'Preview and print the label for {selected_product["name"]}.'
        if selected_product
        else "Preview product shelf labels before printing. Labels include product name, SKU, barcode text, and selling price."
    )
    return f"""
<div class="page-title action-title label-page-title">
  <div>
    <span class="product-kicker">Label Studio</span>
    <h2>{html.escape(page_title)}</h2>
    <p>{html.escape(page_hint)}</p>
  </div>
  <div class="product-title-actions">
    <a class="secondary-link" href="/dashboard?page=Print%20Labels">All Labels</a>
    <a class="secondary-link" href="/dashboard?page=List%20Products">Products</a>
    <button type="button" onclick="window.print()" class="print-button">Print Labels</button>
  </div>
</div>
<section class="label-toolbar">
  <article class="metric supplier-mini-metric"><span>Labels Ready</span><strong>{len(products)}</strong></article>
  <article class="metric supplier-mini-metric"><span>Format</span><strong>Sheet</strong></article>
  <article class="metric supplier-mini-metric"><span>Content</span><strong>SKU + Price</strong></article>
</section>
<article class="panel label-sheet-panel">
  <div class="label-grid">{labels}</div>
</article>"""


def render_product_label(row) -> str:
    code = row["barcode"] or row["sku"]
    bars = "".join(
        f'<span style="width:{2 + ((index + len(code)) % 4)}px"></span>'
        for index, _ in enumerate(str(code)[:22])
    )
    if not bars:
        bars = "<span></span><span></span><span></span>"
    return f"""
<article class="label-box">
  <div class="label-brand">POS Ultimate</div>
  <strong>{html.escape(row["name"])}</strong>
  <div class="label-meta">
    <span>SKU</span>
    <b>{html.escape(row["sku"])}</b>
  </div>
  <div class="label-bars" aria-hidden="true">{bars}</div>
  <div class="barcode-text">{html.escape(code)}</div>
  <div class="label-price">{row["selling_price"]:.2f}</div>
</article>"""


def render_variations(message: str = "", error: str = "") -> str:
    repository = ProductRepository()
    variations = repository.list_variations()
    variation_values = repository.list_variation_values()
    variants = repository.list_product_variants()
    products = repository.product_options()

    variation_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["name"])}</strong></td>
          <td>{html.escape(row["values_text"])}</td>
          <td>{status_badge(row["is_active"])}</td>
        </tr>
        """
        for row in variations
    ) or '<tr><td colspan="3" class="empty">No variation templates added yet.</td></tr>'
    value_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["variation_name"])}</td>
          <td>{html.escape(row["value_name"])}</td>
          <td>{status_badge(row["is_active"])}</td>
        </tr>
        """
        for row in variation_values
    ) or '<tr><td colspan="3" class="empty">No variation values added yet.</td></tr>'
    variant_rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["product_name"])}</strong>
            <p class="table-note">{html.escape(row["variation_summary"])}</p>
          </td>
          <td><strong>{html.escape(row["sku"])}</strong><p class="table-note">{html.escape(row["barcode"] or "No barcode")}</p></td>
          <td class="numeric">{float(row["available_stock"] or 0):.2f}</td>
          <td class="numeric">{float(row["purchase_price"] or 0):.2f}</td>
          <td class="numeric">{float(row["selling_price"] or 0):.2f}</td>
          <td>{status_badge(row["is_active"])}</td>
        </tr>
        """
        for row in variants
    ) or '<tr><td colspan="6" class="empty">No product variants added yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Variations</h2>
    <p>Create variation templates, then create exact product variants with their own SKU, barcode, price, and stock identity.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Products">List Products</a>
</div>
{render_notice(message, error)}
<section class="product-stats">
  {product_metric("Variation Templates", str(len(variations)), "Examples: Size, Color")}
  {product_metric("Variation Values", str(len(variation_values)), "Examples: Small, Red")}
  {product_metric("Product Variants", str(len(variants)), "Exact sellable items")}
  {product_metric("Products", str(len(products)), "Parent product records")}
</section>
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Variation Template</h3>
    <form method="post" action="/variations/create">
      {text_input("Variation Name", "name", True)}
      <label class="field wide-field">
        <span>Values</span>
        <textarea name="values_text" rows="4">Small, Medium, Large</textarea>
      </label>
      {status_select()}
      <button type="submit">Save Variation</button>
    </form>
  </article>
  <article class="panel">
    <h3>Add Product Variant</h3>
    <form method="post" action="/variants/create">
      <div class="form-grid two-col">
        {select_input("Product", "product_id", products)}
        {text_input("Variant SKU", "sku", True)}
        {text_input("Variant Barcode", "barcode")}
        {text_input("Variation Summary", "variation_summary", True)}
        {number_input("Purchase Price", "purchase_price", "0.00")}
        {number_input("Selling Price", "selling_price", "0.00")}
        {number_input("Alert Quantity", "alert_quantity", "0")}
        {status_select()}
      </div>
      <label class="field wide-field">
        <span>Option Mapping</span>
        <textarea name="option_values_text" rows="3" placeholder="Size: Medium, Color: Black"></textarea>
      </label>
      <label class="field wide-field">
        <span>Variant Image URL / Path</span>
        <input name="image_path" placeholder="Optional variant image">
      </label>
      <button type="submit">Save Variant</button>
    </form>
  </article>
</div>
<article class="panel table-panel">
  <h3>Product Variants</h3>
  <table>
    <thead><tr><th>Product / Variant</th><th>SKU / Barcode</th><th>Stock</th><th>Cost</th><th>Price</th><th>Status</th></tr></thead>
    <tbody>{variant_rows}</tbody>
  </table>
</article>
<div class="grid contacts-grid">
  <article class="panel table-panel">
    <h3>Variation Templates</h3>
    <table><thead><tr><th>Name</th><th>Values</th><th>Status</th></tr></thead><tbody>{variation_rows}</tbody></table>
  </article>
  <article class="panel table-panel">
    <h3>Variation Values</h3>
    <table><thead><tr><th>Variation</th><th>Value</th><th>Status</th></tr></thead><tbody>{value_rows}</tbody></table>
  </article>
</div>"""


def render_selling_price_groups(
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    groups = ProductRepository().list_price_groups()
    search = (query.get("price_group_search", [""])[0] or "").strip()
    status = (query.get("price_group_status", ["all"])[0] or "all").strip()
    filtered_groups = [
        row for row in groups
        if selling_price_group_matches_filter(row, search, status)
    ]
    active_count = sum(1 for row in groups if row["is_active"])
    rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["name"])}</strong>
            <p class="table-note">{html.escape(row["description"] or "No description")}</p>
          </td>
          <td>{status_badge(row["is_active"])}</td>
          <td class="actions-cell"><a class="table-link" href="#selling-price-group-{row["id"]}">Edit</a></td>
        </tr>
        """
        for row in filtered_groups
    )
    if not rows:
        rows = '<tr><td colspan="3" class="empty">No selling price groups match this filter.</td></tr>'
    edit_modals = "".join(render_selling_price_group_modal(row) for row in filtered_groups)

    return f"""
<div class="page-title action-title supplier-page-title">
  <div>
    <h2>Selling Price Groups</h2>
    <p>Create price group names for customer-specific pricing.</p>
  </div>
  <a class="primary-link" href="#add-selling-price-group-modal">Add Selling Price Group</a>
</div>
{render_notice(message, error)}
<article class="panel supplier-filter-panel">
  <form method="get" action="/dashboard" class="supplier-filter-form customer-group-filter-form">
    <input type="hidden" name="page" value="Selling Price Groups">
    <label class="field">
      <span>Search Selling Price Groups</span>
      <input type="search" name="price_group_search" value="{html.escape(search)}" placeholder="Search group name or description">
    </label>
    {selling_price_group_status_select(status)}
    <button type="submit">Search</button>
    <a class="secondary-link" href="/dashboard?page=Selling%20Price%20Groups">Clear</a>
  </form>
</article>
<section class="supplier-summary-row">
  <article class="metric supplier-mini-metric"><span>All Groups</span><strong>{len(groups)}</strong></article>
  <article class="metric supplier-mini-metric"><span>Active</span><strong>{active_count}</strong></article>
  <article class="metric supplier-mini-metric"><span>Matched</span><strong>{len(filtered_groups)}</strong></article>
</section>
<article class="panel table-panel supplier-table-panel">
  <div class="supplier-list-head">
    <div>
      <h3>All Selling Price Groups</h3>
      <p>Every selling price group with status and actions.</p>
    </div>
    <a class="primary-link" href="#add-selling-price-group-modal">Add Selling Price Group</a>
  </div>
  <table>
    <thead>
      <tr>
        <th>Selling Price Group</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{render_selling_price_group_modal()}
{edit_modals}"""


def render_selling_price_group_modal(row: sqlite3.Row | None = None) -> str:
    is_edit = row is not None
    modal_id = f'selling-price-group-{row["id"]}' if is_edit else "add-selling-price-group-modal"
    title = f'Edit {row["name"]}' if is_edit else "Add Selling Price Group"
    action = "/price-groups/update" if is_edit else "/price-groups/create"
    button = "Update Group" if is_edit else "Save Group"
    group_id = f'<input type="hidden" name="group_id" value="{row["id"]}">' if is_edit else ""
    name = "" if row is None else row["name"]
    description = "" if row is None else (row["description"] or "")
    is_active = 1 if row is None else row["is_active"]
    return f"""
<div id="{html.escape(modal_id)}" class="modal-screen supplier-modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Selling%20Price%20Groups" aria-label="Close"></a>
  <article class="modal-panel supplier-modal-panel">
    <div class="modal-head">
      <div>
        <span class="contact-chip">Price Group</span>
        <h3>{html.escape(title)}</h3>
        <p>Create a price group for customer-specific selling prices.</p>
      </div>
      <a class="modal-close" href="/dashboard?page=Selling%20Price%20Groups">Close</a>
    </div>
    <form method="post" action="{action}" class="supplier-form">
      {group_id}
      <section class="supplier-form-section">
        <div class="form-grid two-col">
          {preset_text_input("Selling Price Group Name", "name", name, required=True) if is_edit else text_input("Selling Price Group Name", "name", required=True)}
          <label class="field">
            <span>Status</span>
            <select name="is_active">
              <option value="1" {"selected" if is_active else ""}>Active</option>
              <option value="0" {"selected" if not is_active else ""}>Inactive</option>
            </select>
          </label>
        </div>
        <label class="field wide-field">
          <span>Description</span>
          <textarea name="description" rows="4">{html.escape(description)}</textarea>
        </label>
      </section>
      <div class="sticky-form-actions">
        <button type="submit">{html.escape(button)}</button>
        <a href="/dashboard?page=Selling%20Price%20Groups">Cancel</a>
      </div>
    </form>
  </article>
</div>"""


def selling_price_group_matches_filter(row: sqlite3.Row, search: str, status: str) -> bool:
    if search:
        haystack = f'{row["name"] or ""} {row["description"] or ""}'.lower()
        if search.lower() not in haystack:
            return False
    if status == "active" and not row["is_active"]:
        return False
    if status == "inactive" and row["is_active"]:
        return False
    return True


def selling_price_group_status_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All status"),
            ("active", "Active only"),
            ("inactive", "Inactive only"),
        )
    )
    return f"""
<label class="field">
  <span>Status</span>
  <select name="price_group_status">{options}</select>
</label>"""


def render_warranties(message: str = "", error: str = "") -> str:
    warranties = ProductRepository().list_warranties()
    rows = "".join(
        f"<tr><td>{html.escape(row['name'])}</td><td>{row['duration_value']} {html.escape(row['duration_unit'])}</td><td>{html.escape(row['description'] or '')}</td><td>{'Active' if row['is_active'] else 'Inactive'}</td></tr>"
        for row in warranties
    ) or '<tr><td colspan="4" class="empty">No warranties added yet.</td></tr>'
    return f"""
<div class="page-title"><h2>Warranties</h2><p>Manage warranty terms for products.</p></div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel">
    <h3>Add Warranty</h3>
    <form method="post" action="/warranties/create">
      <div class="form-grid two-col">
        {text_input("Warranty Name", "name", True)}
        {number_input("Duration", "duration_value", "12")}
        <label class="field"><span>Duration Unit</span><select name="duration_unit"><option value="days">Days</option><option value="months" selected>Months</option><option value="years">Years</option></select></label>
        {status_select()}
      </div>
      <label class="field wide-field"><span>Description</span><textarea name="description" rows="4"></textarea></label>
      <button type="submit">Save Warranty</button>
    </form>
  </article>
  <article class="panel table-panel"><h3>Warranty List</h3><table><thead><tr><th>Name</th><th>Duration</th><th>Description</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></article>
</div>"""


def render_simple_master_page(title: str, hint: str, action: str, fields: str, headers: str, rows: str, message: str = "", error: str = "") -> str:
    return f"""
<div class="page-title"><h2>{html.escape(title)}</h2><p>{html.escape(hint)}</p></div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel"><h3>Add</h3><form method="post" action="{html.escape(action)}">{fields}<button type="submit">Save</button></form></article>
  <article class="panel table-panel"><h3>Current Records</h3><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></article>
</div>"""


def render_categories(message: str = "", error: str = "") -> str:
    repository = ProductRepository()
    categories = repository.list_category_records()
    parent_options = repository.list_categories()
    tax_rates = repository.list_tax_rates()
    units = repository.list_units()
    warranties = repository.list_warranty_options()
    root_count = sum(1 for row in categories if row["parent_id"] is None)
    pos_count = sum(1 for row in categories if row["is_active"] and row["show_on_pos"])
    product_count = sum(int(row["product_count"] or 0) for row in categories)
    empty_guidance = (
        """
        <article class="panel category-empty-panel">
          <h3>No categories yet</h3>
          <p>Select a shop type to add a ready category structure, or create your own category manually below.</p>
        </article>
        """
        if not categories
        else ""
    )

    rows = "".join(render_category_row(row) for row in categories)
    if not rows:
        rows = '<tr><td colspan="8" class="empty">No categories added yet.</td></tr>'
    edit_modals = "".join(
        render_category_edit_modal(
            row,
            [option for option in parent_options if option.id != row["id"]],
            tax_rates,
            units,
            warranties,
        )
        for row in categories
    )

    return f"""
<div class="page-title action-title">
  <div>
    <span class="product-kicker">Catalog Structure</span>
    <h2>Categories</h2>
    <p>Build parent and subcategory groups with reusable defaults for products and the POS catalog.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Products">Products</a>
</div>
{render_notice(message, error)}
{empty_guidance}
{render_category_template_panel()}
<section class="product-stats">
  {product_metric("Categories", str(len(categories)), "Complete catalog tree")}
  {product_metric("Root Groups", str(root_count), "Top-level departments")}
  {product_metric("Visible In POS", str(pos_count), "Active cashier filters")}
  {product_metric("Assigned Products", str(product_count), "Direct category links")}
</section>
<article class="panel category-create-panel">
  <div class="supplier-list-head">
    <div><h3>Add Category</h3><p>Create a department, category, or subcategory for any shop type.</p></div>
  </div>
  <form method="post" action="/categories/create" class="product-form">
    {category_form_fields(None, parent_options, tax_rates, units, warranties)}
    <div class="form-actions"><button type="submit">Save Category</button></div>
  </form>
</article>
<article class="panel table-panel">
  <div class="supplier-list-head">
    <div><h3>Category Tree</h3><p>Subcategories are shown below their parent category.</p></div>
  </div>
  <table class="category-table">
    <thead>
      <tr><th>Category</th><th>Code</th><th>Parent</th><th>Products</th><th>Defaults</th><th>POS</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{edit_modals}"""


def render_category_template_panel() -> str:
    options = "".join(
        f'<option value="{html.escape(key)}">{html.escape(str(template["name"]))}</option>'
        for key, template in CATEGORY_TEMPLATES.items()
    )
    preview_cards = "".join(
        f"""
        <article class="category-template-card">
          <span style="background:{html.escape(str(template["color"]), quote=True)}"></span>
          <strong>{html.escape(str(template["name"]))}</strong>
          <small>{len(template["categories"])} root groups</small>
        </article>
        """
        for template in CATEGORY_TEMPLATES.values()
    )
    return f"""
<article class="panel category-template-panel">
  <div class="supplier-list-head">
    <div>
      <h3>Choose Shop Type</h3>
      <p>Use a starter category structure for the business, then edit anything you need.</p>
    </div>
  </div>
  <form method="post" action="/categories/template/apply" class="category-template-form">
    <label class="field">
      <span>Shop Type</span>
      <select name="template_key">{options}</select>
    </label>
    <button type="submit">Apply Categories</button>
  </form>
  <div class="category-template-grid">{preview_cards}</div>
</article>"""


def category_form_fields(
    category,
    parent_options: list,
    tax_rates: list,
    units: list,
    warranties: list,
) -> str:
    value = lambda key, default="": category[key] if category is not None and category[key] is not None else default
    active_checked = "checked" if category is None or category["is_active"] else ""
    pos_checked = "checked" if category is None or category["show_on_pos"] else ""
    parent_id = category["parent_id"] if category is not None else None
    tax_id = category["default_tax_rate_id"] if category is not None else None
    unit_id = category["default_unit_id"] if category is not None else None
    warranty_id = category["default_warranty_id"] if category is not None else None
    return f"""
<section class="product-form-section">
  <div class="section-heading"><span>01</span><div><h4>Identity And Hierarchy</h4><p>Name, parent group, code, visual identity, and POS order.</p></div></div>
  <div class="form-grid three-col">
    {preset_text_input("Category Name", "name", str(value("name")), required=True)}
    {select_input("Parent Category", "parent_id", parent_options, parent_id)}
    {preset_text_input("Category Code", "code", str(value("code")))}
    {preset_text_input("Image URL / Path", "image_path", str(value("image_path")))}
    <label class="field">
      <span>Display Color</span>
      <input type="color" name="color_hex" value="{html.escape(str(value("color_hex", "#0f766e")), quote=True)}">
    </label>
    <label class="field">
      <span>POS Display Order</span>
      <input type="number" name="display_order" min="0" step="1" value="{int(value("display_order", 0))}" required>
    </label>
  </div>
  <label class="field wide-field"><span>Description</span><textarea name="description" rows="3">{html.escape(str(value("description")))}</textarea></label>
</section>
<section class="product-form-section">
  <div class="section-heading"><span>02</span><div><h4>Product Defaults</h4><p>New products can inherit these values while remaining editable.</p></div></div>
  <div class="form-grid three-col">
    {select_input("Default Tax Rate", "default_tax_rate_id", tax_rates, tax_id)}
    {select_input("Default Unit", "default_unit_id", units, unit_id)}
    {select_input("Default Warranty", "default_warranty_id", warranties, warranty_id)}
    <label class="field">
      <span>Default Profit Margin (%)</span>
      <input type="number" name="default_profit_margin" min="0" step="0.01" value="{float(value("default_profit_margin", 0)):.2f}">
    </label>
  </div>
  <label class="field wide-field">
    <span>Category Attributes</span>
    <textarea name="attributes_text" rows="3" placeholder="Example: Size, Color, Material">{html.escape(str(value("attributes_text")))}</textarea>
  </label>
  <div class="form-grid two-col category-toggle-grid">
    <label class="choice-row"><input type="checkbox" name="show_on_pos" value="1" {pos_checked}> Show category on POS</label>
    <label class="choice-row"><input type="checkbox" name="is_active" value="1" {active_checked}> Category is active</label>
  </div>
</section>"""


def render_category_row(row) -> str:
    is_child = row["parent_id"] is not None
    prefix = '<span class="category-branch">↳</span> ' if is_child else ""
    defaults = " / ".join(
        value
        for value in (
            row["default_unit_name"] or "",
            row["default_tax_name"] or "",
            row["default_warranty_name"] or "",
        )
        if value
    ) or "Product-level defaults"
    pos_badge = (
        '<span class="badge ok">Visible</span>'
        if row["show_on_pos"] and row["is_active"]
        else '<span class="badge danger">Hidden</span>'
    )
    return f"""
<tr>
  <td>
    <div class="category-name-cell">
      <span class="category-color" style="background:{html.escape(row["color_hex"] or "#0f766e", quote=True)}"></span>
      <div><strong>{prefix}{html.escape(row["name"])}</strong><p class="table-note">{html.escape(row["description"] or "No description")}</p></div>
    </div>
  </td>
  <td><strong>{html.escape(row["code"] or "—")}</strong><p class="table-note">Order {int(row["display_order"] or 0)}</p></td>
  <td>{html.escape(row["parent_name"] or "Root category")}</td>
  <td class="numeric">{int(row["product_count"] or 0)}<p class="table-note">{int(row["child_count"] or 0)} subcategories</p></td>
  <td>{html.escape(defaults)}<p class="table-note">Margin {float(row["default_profit_margin"] or 0):.2f}%</p></td>
  <td>{pos_badge}</td>
  <td>{status_badge(row["is_active"])}</td>
  <td class="actions-cell">
    <a class="table-link" href="#category-{row["id"]}">Edit</a>
    <form method="post" action="/categories/deactivate" class="table-action">
      <input type="hidden" name="category_id" value="{row["id"]}">
      <button type="submit">Deactivate</button>
    </form>
  </td>
</tr>"""


def render_category_edit_modal(
    category,
    parent_options: list,
    tax_rates: list,
    units: list,
    warranties: list,
) -> str:
    return f"""
<section id="category-{category["id"]}" class="modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Categories" aria-label="Close category editor"></a>
  <article class="modal-panel contact-modal-panel">
    <div class="modal-head">
      <div><span class="product-kicker">Category Editor</span><h3>{html.escape(category["name"])}</h3><p>Update hierarchy, defaults, POS visibility, and category attributes.</p></div>
      <a class="modal-close" href="/dashboard?page=Categories">Close</a>
    </div>
    <form method="post" action="/categories/update" class="product-form">
      <input type="hidden" name="category_id" value="{category["id"]}">
      {category_form_fields(category, parent_options, tax_rates, units, warranties)}
      <div class="sticky-form-actions">
        <a href="/dashboard?page=Categories">Cancel</a>
        <button type="submit">Update Category</button>
      </div>
    </form>
  </article>
</section>"""


def render_brands(message: str = "", error: str = "") -> str:
    repository = ProductRepository()
    brands = repository.list_brand_records()
    warranties = repository.list_warranty_options()
    suppliers = repository.supplier_options()
    active_count = sum(1 for row in brands if row["is_active"])
    product_count = sum(int(row["product_count"] or 0) for row in brands)
    empty_guidance = (
        """
        <article class="panel category-empty-panel">
          <h3>No brands yet</h3>
          <p>Apply a starter brand list by shop type, or add only the brands this business actually sells.</p>
        </article>
        """
        if not brands
        else ""
    )
    rows = "".join(render_brand_row(row) for row in brands)
    if not rows:
        rows = '<tr><td colspan="8" class="empty">No brands added yet.</td></tr>'
    edit_modals = "".join(render_brand_edit_modal(row, warranties, suppliers) for row in brands)

    return f"""
<div class="page-title action-title">
  <div>
    <span class="product-kicker">Brand Library</span>
    <h2>Brands</h2>
    <p>Brands are optional. Use starter packs for common shops, then keep only the brands the business sells.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Products">Products</a>
</div>
{render_notice(message, error)}
{empty_guidance}
{render_brand_template_panel()}
<section class="product-stats">
  {product_metric("Brands", str(len(brands)), "Brand master records")}
  {product_metric("Active", str(active_count), "Available on products")}
  {product_metric("Assigned Products", str(product_count), "Direct brand links")}
  {product_metric("Templates", str(len(BRAND_TEMPLATES)), "Optional starter lists")}
</section>
<article class="panel category-create-panel">
  <div class="supplier-list-head">
    <div><h3>Add Brand</h3><p>Create a local, supplier, house, or international brand.</p></div>
  </div>
  <form method="post" action="/brands/create" class="product-form">
    {brand_form_fields(None, warranties, suppliers)}
    <div class="form-actions"><button type="submit">Save Brand</button></div>
  </form>
</article>
<article class="panel table-panel">
  <div class="supplier-list-head">
    <div><h3>Brand Records</h3><p>Manage brand identity, defaults, and product links.</p></div>
  </div>
  <table class="category-table">
    <thead>
      <tr><th>Brand</th><th>Code</th><th>Contact</th><th>Supplier</th><th>Products</th><th>Defaults</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{edit_modals}"""


def render_brand_template_panel() -> str:
    options = "".join(
        f'<option value="{html.escape(key)}">{html.escape(str(template["name"]))}</option>'
        for key, template in BRAND_TEMPLATES.items()
    )
    preview_cards = "".join(
        f"""
        <article class="category-template-card">
          <span style="background:#0f766e"></span>
          <strong>{html.escape(str(template["name"]))}</strong>
          <small>{len(template["brands"])} starter brands</small>
        </article>
        """
        for template in BRAND_TEMPLATES.values()
    )
    return f"""
<article class="panel category-template-panel">
  <div class="supplier-list-head">
    <div>
      <h3>Choose Shop Type Brands</h3>
      <p>Apply a starter brand list only when this business needs it. Duplicates are skipped.</p>
    </div>
  </div>
  <form method="post" action="/brands/template/apply" class="category-template-form">
    <label class="field">
      <span>Shop Type</span>
      <select name="template_key">{options}</select>
    </label>
    <button type="submit">Apply Brands</button>
  </form>
  <div class="category-template-grid">{preview_cards}</div>
</article>"""


def brand_form_fields(brand, warranties: list, suppliers: list) -> str:
    value = lambda key, default="": brand[key] if brand is not None and brand[key] is not None else default
    active_checked = "checked" if brand is None or brand["is_active"] else ""
    warranty_id = brand["default_warranty_id"] if brand is not None else None
    supplier_id = brand["supplier_id"] if brand is not None else None
    return f"""
<section class="product-form-section">
  <div class="section-heading"><span>01</span><div><h4>Brand Identity</h4><p>Name, code, logo, website, and description.</p></div></div>
  <div class="form-grid three-col">
    {preset_text_input("Brand Name", "name", str(value("name")), required=True)}
    {preset_text_input("Brand Code", "code", str(value("code")))}
    {preset_text_input("Logo URL / Path", "logo_path", str(value("logo_path")))}
    {preset_text_input("Website", "website", str(value("website")))}
    {preset_text_input("Country", "country", str(value("country")))}
    <label class="choice-row"><input type="checkbox" name="is_active" value="1" {active_checked}> Brand is active</label>
  </div>
  <label class="field wide-field"><span>Description</span><textarea name="description" rows="3">{html.escape(str(value("description")))}</textarea></label>
</section>
<section class="product-form-section">
  <div class="section-heading"><span>02</span><div><h4>Contact And Defaults</h4><p>Optional supplier/contact details and product defaults.</p></div></div>
  <div class="form-grid three-col">
    {preset_text_input("Contact Person", "contact_person", str(value("contact_person")))}
    {preset_text_input("Phone", "phone", str(value("phone")))}
    {preset_text_input("Email", "email", str(value("email")))}
    {select_input("Linked Supplier", "supplier_id", suppliers, supplier_id)}
    {select_input("Default Warranty", "default_warranty_id", warranties, warranty_id)}
    <label class="field">
      <span>Default Profit Margin (%)</span>
      <input type="number" name="default_profit_margin" min="0" step="0.01" value="{float(value("default_profit_margin", 0)):.2f}">
    </label>
  </div>
</section>"""


def render_brand_row(row) -> str:
    logo = (
        f'<img class="product-thumb" src="{html.escape(row["logo_path"], quote=True)}" alt="{html.escape(row["name"], quote=True)}">'
        if row["logo_path"]
        else f'<span class="product-thumb product-thumb-placeholder">{html.escape((row["name"] or "B")[:2].upper())}</span>'
    )
    contact = " / ".join(value for value in (row["contact_person"] or "", row["phone"] or "", row["email"] or "") if value) or "No contact"
    defaults = " / ".join(value for value in (row["default_warranty_name"] or "",) if value) or "Product-level defaults"
    return f"""
<tr>
  <td>
    <div class="product-cell">
      {logo}
      <div><strong>{html.escape(row["name"])}</strong><p class="table-note">{html.escape(row["description"] or "No description")}</p></div>
    </div>
  </td>
  <td><strong>{html.escape(row["code"] or "—")}</strong><p class="table-note">{html.escape(row["country"] or "")}</p></td>
  <td>{html.escape(contact)}</td>
  <td>{html.escape(row["supplier_name"] or "Not linked")}</td>
  <td class="numeric">{int(row["product_count"] or 0)}</td>
  <td>{html.escape(defaults)}<p class="table-note">Margin {float(row["default_profit_margin"] or 0):.2f}%</p></td>
  <td>{status_badge(row["is_active"])}</td>
  <td class="actions-cell">
    <a class="table-link" href="#brand-{row["id"]}">Edit</a>
    <form method="post" action="/brands/deactivate" class="table-action">
      <input type="hidden" name="brand_id" value="{row["id"]}">
      <button type="submit">Deactivate</button>
    </form>
  </td>
</tr>"""


def render_brand_edit_modal(brand, warranties: list, suppliers: list) -> str:
    return f"""
<section id="brand-{brand["id"]}" class="modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Brands" aria-label="Close brand editor"></a>
  <article class="modal-panel contact-modal-panel">
    <div class="modal-head">
      <div><span class="product-kicker">Brand Editor</span><h3>{html.escape(brand["name"])}</h3><p>Update brand identity, contact details, and defaults.</p></div>
      <a class="modal-close" href="/dashboard?page=Brands">Close</a>
    </div>
    <form method="post" action="/brands/update" class="product-form">
      <input type="hidden" name="brand_id" value="{brand["id"]}">
      {brand_form_fields(brand, warranties, suppliers)}
      <div class="sticky-form-actions">
        <a href="/dashboard?page=Brands">Cancel</a>
        <button type="submit">Update Brand</button>
      </div>
    </form>
  </article>
</section>"""


def render_lookup_page(
    title: str,
    lookup_type: str,
    items: list,
    message: str = "",
    error: str = "",
) -> str:
    short_name_field = ""
    if lookup_type == "unit":
        short_name_field = text_input("Short Name", "short_name", required=True)

    rows = "".join(f"<tr><td>{html.escape(item.name)}</td><td>Active</td></tr>" for item in items)
    if not rows:
        rows = '<tr><td colspan="2" class="empty">No records added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>{html.escape(title)}</h2>
  <p>Manage product lookup data used by the product master form.</p>
</div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel">
    <h3>Add {html.escape(title[:-1] if title.endswith('s') else title)}</h3>
    <form method="post" action="/lookups/create">
      <input type="hidden" name="lookup_type" value="{html.escape(lookup_type)}">
      {text_input("Name", "name", required=True)}
      {short_name_field}
      <button type="submit">Save</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Current Records</h3>
    <table>
      <thead><tr><th>Name</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_stock_alert_page() -> str:
    products = ReportRepository().low_stock_report()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["sku"])}</td>
          <td class="numeric">{row["available_stock"]:.2f} {html.escape(row["unit_name"])}</td>
          <td class="numeric">{row["alert_quantity"]:.2f}</td>
          <td>{stock_status_badge(row["available_stock"], row["alert_quantity"])}</td>
          <td>
            <div class="inline-actions">
              <a class="table-link" href="/dashboard?page=Product%20Stock%20History&product_id={row["id"]}">History</a>
              <a class="table-link" href="/dashboard?page=Add%20Purchase">Reorder</a>
            </div>
          </td>
        </tr>
        """
        for row in products
    )
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No low-stock products found.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Stock Alert</h2>
    <p>Products at or below alert quantity based on live stock movements.</p>
  </div>
  <a class="primary-link" href="/dashboard?page=Add%20Purchase">Add Purchase</a>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Product</th><th>SKU</th><th>Available</th><th>Alert Qty</th><th>Status</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_stock_adjustment(message: str = "", error: str = "") -> str:
    repository = StockOperationRepository()
    products = ProductRepository().product_options()
    locations = repository.location_options()
    today = __import__("datetime").date.today().isoformat()
    adjustments = repository.list_adjustments()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["adjustment_date"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td>{html.escape(row["location_name"] or "")}</td>
          <td>{html.escape(row["adjustment_type"].title())}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td>{html.escape(row["reason"] or "")}</td>
        </tr>
        """
        for row in adjustments
    )
    if not rows:
        rows = '<tr><td colspan="7" class="empty">No stock adjustments added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Stock Adjustment</h2>
  <p>Increase or decrease stock manually for damaged, lost, found, or corrected quantities.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Adjustment</h3>
    <form method="post" action="/stock-adjustments/create">
      <div class="form-grid two-col">
        {select_input("Product", "product_id", products)}
        {select_input("Location", "location_id", locations)}
        {date_input("Adjustment Date", "adjustment_date", today)}
        <label class="field"><span>Type</span><select name="adjustment_type"><option value="increase">Increase</option><option value="decrease">Decrease</option></select></label>
        {number_input("Quantity", "quantity", "1")}
      </div>
      <label class="field wide-field"><span>Reason</span><textarea name="reason" rows="4"></textarea></label>
      <button type="submit">Save Adjustment</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Adjustment History</h3>
    <table>
      <thead><tr><th>Date</th><th>Product</th><th>SKU</th><th>Location</th><th>Type</th><th>Qty</th><th>Reason</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_stock_transfer(message: str = "", error: str = "") -> str:
    repository = StockOperationRepository()
    products = ProductRepository().product_options()
    locations = repository.location_options()
    today = __import__("datetime").date.today().isoformat()
    transfers = repository.list_transfers()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["transfer_date"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td>{html.escape(row["from_location_name"])}</td>
          <td>{html.escape(row["to_location_name"])}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in transfers
    )
    if not rows:
        rows = '<tr><td colspan="7" class="empty">No stock transfers added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Stock Transfer</h2>
  <p>Move stock from one business location to another. Transfer creates one stock-out and one stock-in movement.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Transfer</h3>
    <form method="post" action="/stock-transfers/create">
      <div class="form-grid two-col">
        {select_input("Product", "product_id", products)}
        {select_input("From Location", "from_location_id", locations)}
        {select_input("To Location", "to_location_id", locations)}
        {date_input("Transfer Date", "transfer_date", today)}
        {number_input("Quantity", "quantity", "1")}
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="4"></textarea></label>
      <button type="submit">Save Transfer</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Transfer History</h3>
    <table>
      <thead><tr><th>Date</th><th>Product</th><th>SKU</th><th>From</th><th>To</th><th>Qty</th><th>Note</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_stock_report(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    rows_data = ReportRepository().stock_report(filters)
    products = ProductRepository()
    categories = products.list_categories()
    brands = products.list_brands()
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations()
        if row["is_active"]
    ]
    available_total = sum(float(row["available_stock"]) for row in rows_data)
    purchase_value = sum(float(row["available_stock"]) * float(row["purchase_price"]) for row in rows_data)
    selling_value = sum(float(row["available_stock"]) * float(row["selling_price"]) for row in rows_data)
    low_count = sum(1 for row in rows_data if float(row["available_stock"]) <= float(row["alert_quantity"]))
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["sku"])}</td>
          <td>{html.escape(row["barcode"] or "")}</td>
          <td>{html.escape(row["category_name"])}</td>
          <td>{html.escape(row["brand_name"])}</td>
          <td>{html.escape(row["unit_name"])}</td>
          <td class="numeric">{row["quantity_in"]:.2f}</td>
          <td class="numeric">{row["quantity_out"]:.2f}</td>
          <td class="numeric">{row["available_stock"]:.2f}</td>
          <td class="numeric">{row["alert_quantity"]:.2f}</td>
          <td class="numeric">{float(row["available_stock"]) * float(row["purchase_price"]):.2f}</td>
          <td class="numeric">{float(row["available_stock"]) * float(row["selling_price"]):.2f}</td>
          <td class="numeric">{float(row["available_stock"]) * (float(row["selling_price"]) - float(row["purchase_price"])):.2f}</td>
          <td>{stock_status(row["available_stock"], row["alert_quantity"])}</td>
          <td><a class="table-link" href="/dashboard?page=Product%20Stock%20History&product_id={row["id"]}">History</a></td>
        </tr>
        """
        for row in rows_data
    )
    if not rows:
        rows = '<tr><td colspan="15" class="empty">No stock rows match the filters.</td></tr>'

    return f"""
{report_page_header("Stock Report", "Inventory quantities, values, alerts, and movement totals.", "stock", filters)}
{render_money_cards([("Available Units", available_total), ("Purchase Value", purchase_value), ("Selling Value", selling_value), ("Low Stock Items", float(low_count))])}
{report_filter_panel("Stock Report", filters, f'''
  {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
  {select_input("Category", "category_id", categories, query_selected_int(filters, "category_id"))}
  {select_input("Brand", "brand_id", brands, query_selected_int(filters, "brand_id"))}
  {simple_select("Stock Status", "stock_status", [("", "All Stock"), ("low", "Low Stock"), ("out", "Out of Stock")], filters["stock_status"])}
''')}
<article class="panel table-panel report-sheet-panel">
  <div class="report-sheet-scroll"><table class="report-sheet">
    <thead>
      <tr>
        <th>Product</th>
        <th>SKU</th>
        <th>Barcode</th>
        <th>Category</th>
        <th>Brand</th>
        <th>Unit</th>
        <th>Stock In</th>
        <th>Stock Out</th>
        <th>Available</th>
        <th>Alert Qty</th>
        <th>Purchase Value</th>
        <th>Selling Value</th>
        <th>Potential Profit</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def render_product_stock_history(
    product_id: int | None = None,
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    products = ProductRepository().product_options()
    movements = StockRepository().movement_history(product_id, filters)
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations()
        if row["is_active"]
    ]
    total_in = sum(float(row["quantity_in"]) for row in movements)
    total_out = sum(float(row["quantity_out"]) for row in movements)
    opening_balance = 0.0
    current_balance = 0.0
    current_value = 0.0
    if movements:
        oldest_by_key: dict[tuple[object, object, object], dict[str, object]] = {}
        latest_by_key: dict[tuple[object, object, object], dict[str, object]] = {}
        for row in reversed(movements):
            key = (row["product_id"], row["variant_id"], row["location_id"])
            oldest_by_key.setdefault(key, row)
            latest_by_key[key] = row
        opening_balance = sum(
            float(row["running_balance"]) - float(row["quantity_in"]) + float(row["quantity_out"])
            for row in oldest_by_key.values()
        )
        current_balance = sum(float(row["running_balance"]) for row in latest_by_key.values())
        current_value = sum(float(row["stock_value"]) for row in latest_by_key.values())

    rows = "".join(
        f"""
        <tr class="{"negative-stock-row" if float(row["running_balance"]) < 0 else ""}">
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["variant_sku"] or row["product_sku"])}</td>
          <td>{html.escape(row["variant_barcode"] or row["product_barcode"] or "")}</td>
          <td>{html.escape(row["variation_name"])}</td>
          <td>{html.escape(row["location_name"])}</td>
          <td>{html.escape(row["movement_type"].replace('_', ' ').title())}</td>
          <td>{stock_reference_link(row)}</td>
          <td class="numeric">{row["quantity_in"]:.2f}</td>
          <td class="numeric">{row["quantity_out"]:.2f}</td>
          <td class="numeric">{float(row["running_balance"]):.2f}</td>
          <td class="numeric">{float(row["unit_cost"]):.2f}</td>
          <td class="numeric">{float(row["stock_value"]):.2f}</td>
          <td>System</td>
          <td class="clip-cell" title="{html.escape(row["note"] or "", quote=True)}">{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in movements
    )
    if not rows:
        rows = '<tr><td colspan="15" class="empty">No stock movements match the selected filters.</td></tr>'

    export_params = {key: value for key, value in filters.items() if value}
    if product_id:
        export_params["product_id"] = str(product_id)

    return f"""
<div class="page-title action-title report-title">
  <div>
    <h2>Product Stock History</h2>
    <p>Excel-style audit trail with movement source, running balance, cost, and stock value.</p>
  </div>
  <div class="quick-actions">
    <a href="/stock-history/export.csv?{urlencode(export_params)}">Export Excel CSV</a>
    <button type="button" onclick="window.print()">Print / PDF</button>
    <a class="secondary-link" href="/dashboard?page=Stock%20Report">Stock Report</a>
  </div>
</div>
{render_money_cards([
    ("Opening Stock", opening_balance),
    ("Stock In", total_in),
    ("Stock Out", total_out),
    ("Closing Stock", current_balance),
    ("Current Stock Value", current_value),
])}
<article class="panel report-filter-panel">
  <div class="report-presets">
    {stock_history_preset_links(product_id)}
    <a href="/dashboard?{urlencode({"page": "Product Stock History", **({"product_id": product_id} if product_id else {})})}">All Time</a>
  </div>
  <form method="get" action="/dashboard" class="report-filter-grid">
    <input type="hidden" name="page" value="Product Stock History">
    {preset_text_input("Search", "search", filters["search"])}
    {date_input_optional("From", "date_from", filters["date_from"])}
    {date_input_optional("To", "date_to", filters["date_to"])}
    {select_input("Product", "product_id", products, product_id)}
    {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
    {simple_select("Movement", "movement_type", stock_movement_options(), filters["movement_type"])}
    {simple_select("Reference", "reference_type", stock_reference_options(), filters["reference_type"])}
    <div class="expense-filter-actions">
      <button type="submit">Apply</button>
      <a class="secondary-link" href="/dashboard?page=Product%20Stock%20History">Clear</a>
    </div>
  </form>
</article>
<article class="panel table-panel report-sheet-panel">
  <div class="report-sheet-scroll"><table class="report-sheet stock-history-sheet">
    <thead>
      <tr>
        <th>Date & Time</th>
        <th>Product</th>
        <th>SKU</th>
        <th>Barcode</th>
        <th>Variation</th>
        <th>Location</th>
        <th>Movement</th>
        <th>Reference</th>
        <th>Qty In</th>
        <th>Qty Out</th>
        <th>Running Balance</th>
        <th>Unit Cost</th>
        <th>Stock Value</th>
        <th>User</th>
        <th>Note</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def stock_status(available_stock: float, alert_quantity: float) -> str:
    if alert_quantity > 0 and available_stock <= alert_quantity:
        return '<span class="badge danger">Low Stock</span>'
    return '<span class="badge ok">OK</span>'


def stock_movement_options() -> list[tuple[str, str]]:
    return [
        ("", "All Movements"),
        ("opening_stock", "Opening Stock"),
        ("purchase", "Purchase"),
        ("purchase_return", "Purchase Return"),
        ("sale", "Sale"),
        ("sale_return", "Sales Return"),
        ("stock_adjustment", "Stock Adjustment"),
        ("stock_transfer_in", "Transfer In"),
        ("stock_transfer_out", "Transfer Out"),
    ]


def stock_reference_options() -> list[tuple[str, str]]:
    return [
        ("", "All References"),
        ("opening_stock", "Opening Stock"),
        ("purchase", "Purchase"),
        ("purchase_return", "Purchase Return"),
        ("sale", "Sale"),
        ("sale_return", "Sales Return"),
        ("stock_adjustment", "Stock Adjustment"),
        ("stock_transfer", "Stock Transfer"),
    ]


def stock_reference_link(row: dict[str, object]) -> str:
    label = html.escape(str(row["reference_label"] or ""))
    reference_type = row["reference_type"]
    reference_id = row["reference_id"]
    if not reference_id:
        return label
    if reference_type == "sale":
        return f'<a class="table-link" href="/sales/invoice?id={reference_id}">{label}</a>'
    if reference_type == "purchase":
        return f'<a class="table-link" href="/purchases/detail?id={reference_id}">{label}</a>'
    page_map = {
        "purchase_return": "Purchase Return",
        "sale_return": "Sales Return",
        "stock_adjustment": "Stock Adjustment",
        "stock_transfer": "Stock Transfer",
    }
    page = page_map.get(str(reference_type))
    if page:
        return f'<a class="table-link" href="/dashboard?page={quote(page)}">{label}</a>'
    return label


def stock_history_preset_links(product_id: int | None) -> str:
    from datetime import date, timedelta

    today = date.today()
    presets = [
        ("Today", today, today),
        ("Yesterday", today - timedelta(days=1), today - timedelta(days=1)),
        ("This Week", today - timedelta(days=today.weekday()), today),
        ("This Month", today.replace(day=1), today),
    ]
    return "".join(
        f'<a href="/dashboard?{urlencode({"page": "Product Stock History", "date_from": start.isoformat(), "date_to": end.isoformat(), **({"product_id": product_id} if product_id else {})})}">{label}</a>'
        for label, start, end in presets
    )


def stock_status_badge(available_stock: float, alert_quantity: float) -> str:
    return stock_status(available_stock, alert_quantity)


def status_badge(is_active: int) -> str:
    if is_active:
        return '<span class="badge ok">Active</span>'
    return '<span class="badge danger">Inactive</span>'


def render_contacts_page(contact_title: str, contact_type: str, message: str = "", error: str = "") -> str:
    repository = ContactRepository()
    contacts = repository.list_contacts(contact_type)
    active_count = sum(1 for row in contacts if row["is_active"])
    total_balance = sum(float(row["opening_balance"] or 0) for row in contacts)
    total_credit = sum(float(row["credit_limit"] or 0) for row in contacts)
    is_supplier = contact_type == "supplier"
    business_total_key = "purchase_total" if is_supplier else "sale_total"
    business_due_key = "purchase_due" if is_supplier else "sale_due"
    business_count_key = "purchase_count" if is_supplier else "sale_count"
    total_business = sum(float(row[business_total_key] or 0) for row in contacts)
    total_due = sum(float(row[business_due_key] or 0) for row in contacts)
    third_column_label = "Purchases" if is_supplier else "Group"
    balance_label = "Supplier Opening" if is_supplier else "Opening Balance"
    credit_label = "Supplier Credit Limit" if is_supplier else "Credit Limit"
    primary_due_label = "Payable Due" if is_supplier else "Receivable Due"

    rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["name"])}</strong>
            <p class="table-note">{html.escape(row["business_name"] or row["contact_code"] or "No business profile")}</p>
          </td>
          <td>
            {html.escape(row["phone"] or "")}
            <p class="table-note">{html.escape(row["email"] or "")}</p>
          </td>
          <td>{supplier_purchase_summary(row) if is_supplier else html.escape(row["customer_group_name"] or row["payment_terms"] or "")}</td>
          <td class="numeric">{row["opening_balance"]:.2f}</td>
          <td class="numeric">{row["credit_limit"]:.2f}</td>
          <td class="numeric">{row[business_due_key]:.2f}</td>
          <td>{status_badge(row["is_active"])}</td>
          <td class="actions-cell">
            <a class="table-link" href="#contact-{row["id"]}">Edit</a>
            <a class="table-link" href="/contacts/ledger?type={contact_type}&id={row["id"]}">Ledger</a>
            {f'<a class="table-link" href="/dashboard?page=Add%20Purchase">Add Purchase</a>' if is_supplier else ""}
            <form method="post" action="/contacts/deactivate" class="table-action">
              <input type="hidden" name="contact_type" value="{contact_type}">
              <input type="hidden" name="contact_id" value="{row["id"]}">
              <button type="submit">Deactivate</button>
            </form>
          </td>
        </tr>
        """
        for row in contacts
    )
    if not rows:
        rows = f'<tr><td colspan="8" class="empty">No {html.escape(contact_title.lower())} added yet.</td></tr>'

    page_hint = (
        "Customer records are used by POS sales, invoices, payments, ledgers, and reports."
        if not is_supplier
        else "Supplier records are used by purchases, purchase returns, payable balances, ledgers, and reports."
    )
    singular = contact_title[:-1]
    edit_cards = "".join(render_contact_edit_card(row, contact_type, credit_label) for row in contacts)
    supplier_actions = (
        """
        <div class="quick-actions supplier-actions">
          <a href="/dashboard?page=Add%20Purchase">Add Purchase</a>
          <a href="/dashboard?page=Purchase%20Order">Purchase Order</a>
          <a href="/dashboard?page=Purchase%20Return">Purchase Return</a>
          <a href="/dashboard?page=Purchase%20Report">Purchase Report</a>
        </div>
        """
        if is_supplier
        else ""
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>{html.escape(contact_title)}</h2>
    <p>{html.escape(page_hint)} Keep only clean supplier profile, contact, payment, and account details here.</p>
  </div>
  <a class="primary-link" href="#add-contact-modal">Add New {html.escape(singular)}</a>
</div>
{render_notice(message, error)}
{supplier_actions}
<section class="contact-stats">
  <article class="metric contact-metric"><span>Total {html.escape(contact_title)}</span><strong>{len(contacts)}</strong></article>
  <article class="metric contact-metric"><span>Active</span><strong>{active_count}</strong></article>
  <article class="metric contact-metric"><span>{html.escape(primary_due_label)}</span><strong>{total_due:.2f}</strong></article>
  <article class="metric contact-metric"><span>{'Total Purchases' if is_supplier else 'Total Sales'}</span><strong>{total_business:.2f}</strong></article>
</section>
<div id="add-contact-modal" class="modal-screen">
  <a class="modal-backdrop" href="/dashboard?page={quote(contact_title)}" aria-label="Close"></a>
  <article class="modal-panel contact-modal-panel">
    <div class="modal-head">
      <div>
        <span class="contact-chip">New Profile</span>
        <h3>Add New {html.escape(singular)}</h3>
        <p>Capture business details, payment controls, and responsible contact persons.</p>
      </div>
      <a class="modal-close" href="/dashboard?page={quote(contact_title)}">Close</a>
    </div>
    <form method="post" action="/contacts/create" class="contact-form">
      {contact_form_fields(contact_type, credit_label)}
      <div class="sticky-form-actions">
        <button type="submit">Save {html.escape(singular)}</button>
        <a href="/dashboard?page={quote(contact_title)}">Cancel</a>
      </div>
    </form>
  </article>
</div>
<article class="panel table-panel contact-table-panel">
    <h3>{html.escape(contact_title)} List</h3>
    <table>
      <thead>
        <tr>
          <th>Profile</th>
          <th>Contact</th>
          <th>{html.escape(third_column_label)}</th>
          <th>{html.escape(balance_label)}</th>
          <th>Credit Limit</th>
          <th>{html.escape(primary_due_label)}</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
<div class="contact-edit-grid">
  {edit_cards}
</div>"""


def supplier_purchase_summary(row: sqlite3.Row) -> str:
    if row["purchase_count"]:
        return f"""
        <strong>{row["purchase_count"]} invoices</strong>
        <p class="table-note">Total {row["purchase_total"]:.2f}</p>
        """
    terms = row["payment_terms"] or "No purchases yet"
    return html.escape(terms)


def render_customers_page(
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    customers = ContactRepository().list_contacts("customer")
    search = (query.get("customer_search", [""])[0] or "").strip()
    status = (query.get("customer_status", ["all"])[0] or "all").strip()
    due_filter = (query.get("customer_due", ["all"])[0] or "all").strip()

    filtered_customers = [
        row for row in customers
        if customer_matches_filter(row, search, status, due_filter)
    ]
    active_count = sum(1 for row in customers if row["is_active"])
    total_due = sum(float(row["sale_due"] or 0) for row in customers)

    rows = "".join(render_customer_row(row) for row in filtered_customers)
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No customers match this filter.</td></tr>'
    edit_modals = "".join(render_customer_modal(row) for row in filtered_customers)

    return f"""
<div class="page-title action-title supplier-page-title">
  <div>
    <h2>Customers</h2>
    <p>Simple customer profiles for sales, due balances, and contact details.</p>
  </div>
  <a class="primary-link" href="#add-customer-modal">Add Customer</a>
</div>
{render_notice(message, error)}
<article class="panel supplier-filter-panel">
  <form method="get" action="/dashboard" class="supplier-filter-form">
    <input type="hidden" name="page" value="Customers">
    <label class="field">
      <span>Filter Customers</span>
      <input type="search" name="customer_search" value="{html.escape(search)}" placeholder="Search name, phone, email, or business">
    </label>
    {customer_status_select(status)}
    {customer_due_select(due_filter)}
    <button type="submit">Filter</button>
    <a class="secondary-link" href="/dashboard?page=Customers">Clear</a>
  </form>
</article>
<section class="supplier-summary-row">
  <article class="metric supplier-mini-metric"><span>All Customers</span><strong>{len(customers)}</strong></article>
  <article class="metric supplier-mini-metric"><span>Active</span><strong>{active_count}</strong></article>
  <article class="metric supplier-mini-metric"><span>Receivable Due</span><strong>{total_due:.2f}</strong></article>
</section>
<article class="panel table-panel supplier-table-panel">
  <div class="supplier-list-head">
    <div>
      <h3>All your Customers</h3>
      <p>Clean customer list with sales and due balance at a glance.</p>
    </div>
    <a class="primary-link" href="#add-customer-modal">Add Customer</a>
  </div>
  <table>
    <thead>
      <tr>
        <th>Customer</th>
        <th>Contact</th>
        <th>Sales</th>
        <th>Receivable Due</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{render_customer_modal()}
{edit_modals}"""


def customer_matches_filter(row: sqlite3.Row, search: str, status: str, due_filter: str) -> bool:
    if search:
        haystack = " ".join(
            str(row[key] or "")
            for key in ("name", "business_name", "contact_code", "phone", "email", "address")
        ).lower()
        if search.lower() not in haystack:
            return False
    if status == "active" and not row["is_active"]:
        return False
    if status == "inactive" and row["is_active"]:
        return False
    due_amount = float(row["sale_due"] or 0)
    if due_filter == "due" and due_amount <= 0:
        return False
    if due_filter == "no_due" and due_amount > 0:
        return False
    return True


def render_customer_row(row: sqlite3.Row) -> str:
    business_line = row["business_name"] or row["contact_code"] or "Customer profile"
    sale_text = f'{row["sale_count"]} invoices' if row["sale_count"] else "No sales"
    party_type = party_type_label(row["supplier_type"])
    return f"""
<tr>
  <td>
    <strong>{html.escape(row["name"])}</strong>
    <p class="table-note">{html.escape(party_type)} / {html.escape(contact_role_label(row["contact_type"]))} / {html.escape(business_line)}</p>
  </td>
  <td>
    {html.escape(row["phone"] or "-")}
    <p class="table-note">{html.escape(row["email"] or row["address"] or "")}</p>
  </td>
  <td>
    <strong>{html.escape(sale_text)}</strong>
    <p class="table-note">Total {row["sale_total"]:.2f}</p>
  </td>
  <td class="numeric">{row["sale_due"]:.2f}</td>
  <td>{status_badge(row["is_active"])}</td>
  <td class="actions-cell">
    <a class="table-link" href="#customer-{row["id"]}">Edit</a>
    <a class="table-link" href="/contacts/ledger?type=customer&id={row["id"]}">Ledger</a>
  </td>
</tr>"""


def render_customer_modal(row: sqlite3.Row | None = None) -> str:
    is_edit = row is not None
    modal_id = f'customer-{row["id"]}' if is_edit else "add-customer-modal"
    title = f'Edit {row["name"]}' if is_edit else "Add Customer"
    action = "/contacts/update" if is_edit else "/contacts/create"
    button = "Update Customer" if is_edit else "Save Customer"
    return f"""
<div id="{html.escape(modal_id)}" class="modal-screen supplier-modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Customers" aria-label="Close"></a>
  <article class="modal-panel supplier-modal-panel">
    <div class="modal-head">
      <div>
        <span class="contact-chip">Customer</span>
        <h3>{html.escape(title)}</h3>
        <p>Only the details needed to sell, receive payments, and contact this customer.</p>
      </div>
      <a class="modal-close" href="/dashboard?page=Customers">Close</a>
    </div>
    <form method="post" action="{action}" class="supplier-form contact-kind-form" data-contact-kind-form>
      {customer_form_fields(row)}
      <div class="sticky-form-actions">
        <button type="submit">{html.escape(button)}</button>
        <a href="/dashboard?page=Customers">Cancel</a>
      </div>
    </form>
  </article>
</div>"""


def customer_form_fields(row: sqlite3.Row | None = None) -> str:
    contact_id = f'<input type="hidden" name="contact_id" value="{row["id"]}">' if row else ""
    value = lambda key: "" if row is None else (row[key] or "")
    numeric_value = lambda key: "0.00" if row is None else f'{row[key]:.2f}'
    credit_days = "0" if row is None else str(row["credit_days"] or 0)
    selected_role = value("contact_type") or "customer"
    selected_party = value("supplier_type") or "individual"
    return f"""
{contact_id}
<input type="hidden" name="return_page" value="Customers">
<section class="supplier-form-section">
  <div class="section-heading">
    <span>01</span>
    <div><h4>Contact Details</h4><p>Main details used for sales and communication.</p></div>
  </div>
  {contact_role_options(selected_role)}
  <div class="form-grid two-col">
    {party_type_select(selected_party)}
    {preset_text_input("Customer Name", "name", value("name"), required=True) if row else text_input("Customer Name", "name", required=True)}
    {business_only_field(preset_text_input("Business Name", "business_name", value("business_name")))}
    {preset_text_input("Phone", "phone", value("phone"))}
    {preset_text_input("Email", "email", value("email"))}
  </div>
  <label class="field wide-field">
    <span>Address</span>
    <textarea name="address" rows="3">{html.escape(value("address"))}</textarea>
  </label>
</section>
<section class="supplier-form-section">
  <div class="section-heading">
    <span>02</span>
    <div><h4>More Information</h4><p>Account and payment settings for this customer.</p></div>
  </div>
  <div class="form-grid three-col">
    {preset_text_input("Contact Code", "contact_code", value("contact_code"))}
    {business_only_field(preset_text_input("Tax Number", "tax_number", value("tax_number")))}
    {payment_terms_select(value("payment_terms"))}
    {preset_number_input("Credit Days", "credit_days", credit_days)}
    {preset_number_input("Opening Balance", "opening_balance", numeric_value("opening_balance"))}
    {preset_number_input("Credit Limit", "credit_limit", numeric_value("credit_limit"))}
    {contact_status_select(1 if row is None else row["is_active"])}
  </div>
  <label class="field wide-field">
    <span>Notes</span>
    <textarea name="notes" rows="3">{html.escape(value("notes"))}</textarea>
  </label>
</section>
<section class="supplier-form-section business-only-section" data-business-only>
  <div class="section-heading">
    <span>03</span>
    <div><h4>Contact Person</h4><p>The main person responsible for purchases or accounts.</p></div>
  </div>
  <div class="form-grid two-col">
    {preset_text_input("Person Name", "contact_person_1_name", value("contact_person_1_name"))}
    {preset_text_input("Designation", "contact_person_1_designation", value("contact_person_1_designation"))}
    {preset_text_input("Person Phone", "contact_person_1_phone", value("contact_person_1_phone"))}
    {preset_text_input("Person Email", "contact_person_1_email", value("contact_person_1_email"))}
  </div>
</section>"""


def render_suppliers_page(
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    suppliers = ContactRepository().list_contacts("supplier")
    search = (query.get("supplier_search", [""])[0] or "").strip()
    status = (query.get("supplier_status", ["all"])[0] or "all").strip()
    due_filter = (query.get("supplier_due", ["all"])[0] or "all").strip()

    filtered_suppliers = [
        row for row in suppliers
        if supplier_matches_filter(row, search, status, due_filter)
    ]
    active_count = sum(1 for row in suppliers if row["is_active"])
    total_due = sum(float(row["purchase_due"] or 0) for row in suppliers)

    rows = "".join(render_supplier_row(row) for row in filtered_suppliers)
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No suppliers match this filter.</td></tr>'

    edit_modals = "".join(render_supplier_modal(row) for row in filtered_suppliers)

    return f"""
<div class="page-title action-title supplier-page-title">
  <div>
    <h2>Suppliers</h2>
    <p>Keep supplier details simple: contact, account information, and the main person to call.</p>
  </div>
  <a class="primary-link" href="#add-supplier-modal">Add Supplier</a>
</div>
{render_notice(message, error)}
<article class="panel supplier-filter-panel">
  <form method="get" action="/dashboard" class="supplier-filter-form">
    <input type="hidden" name="page" value="Suppliers">
    <label class="field">
      <span>Filter Suppliers</span>
      <input type="search" name="supplier_search" value="{html.escape(search)}" placeholder="Search name, phone, email, or business">
    </label>
    {supplier_status_select(status)}
    {supplier_due_select(due_filter)}
    <button type="submit">Filter</button>
    <a class="secondary-link" href="/dashboard?page=Suppliers">Clear</a>
  </form>
</article>
<section class="supplier-summary-row">
  <article class="metric supplier-mini-metric"><span>All Suppliers</span><strong>{len(suppliers)}</strong></article>
  <article class="metric supplier-mini-metric"><span>Active</span><strong>{active_count}</strong></article>
  <article class="metric supplier-mini-metric"><span>Payable Due</span><strong>{total_due:.2f}</strong></article>
</section>
<article class="panel table-panel supplier-table-panel">
  <div class="supplier-list-head">
    <div>
      <h3>All your Suppliers</h3>
      <p>Clean supplier list with purchase and due balance at a glance.</p>
    </div>
    <a class="primary-link" href="#add-supplier-modal">Add Supplier</a>
  </div>
  <table>
    <thead>
      <tr>
        <th>Supplier</th>
        <th>Contact</th>
        <th>Purchases</th>
        <th>Payable Due</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{render_supplier_modal()}
{edit_modals}"""


def supplier_matches_filter(row: sqlite3.Row, search: str, status: str, due_filter: str) -> bool:
    if search:
        haystack = " ".join(
            str(row[key] or "")
            for key in ("name", "business_name", "contact_code", "phone", "email", "address")
        ).lower()
        if search.lower() not in haystack:
            return False
    if status == "active" and not row["is_active"]:
        return False
    if status == "inactive" and row["is_active"]:
        return False
    due_amount = float(row["purchase_due"] or 0)
    if due_filter == "due" and due_amount <= 0:
        return False
    if due_filter == "no_due" and due_amount > 0:
        return False
    return True


def render_supplier_row(row: sqlite3.Row) -> str:
    business_line = row["business_name"] or row["contact_code"] or "Supplier profile"
    purchase_text = f'{row["purchase_count"]} invoices' if row["purchase_count"] else "No purchases"
    supplier_type = party_type_label(row["supplier_type"])
    return f"""
<tr>
  <td>
    <strong>{html.escape(row["name"])}</strong>
    <p class="table-note">{html.escape(supplier_type)} · {html.escape(business_line)}</p>
  </td>
  <td>
    {html.escape(row["phone"] or "-")}
    <p class="table-note">{html.escape(row["email"] or row["address"] or "")}</p>
  </td>
  <td>
    <strong>{html.escape(purchase_text)}</strong>
    <p class="table-note">Total {row["purchase_total"]:.2f}</p>
  </td>
  <td class="numeric">{row["purchase_due"]:.2f}</td>
  <td>{status_badge(row["is_active"])}</td>
  <td class="actions-cell">
    <a class="table-link" href="#supplier-{row["id"]}">Edit</a>
    <a class="table-link" href="/contacts/ledger?type=supplier&id={row["id"]}">Ledger</a>
  </td>
</tr>"""


def render_supplier_modal(row: sqlite3.Row | None = None) -> str:
    is_edit = row is not None
    modal_id = f'supplier-{row["id"]}' if is_edit else "add-supplier-modal"
    title = f'Edit {row["name"]}' if is_edit else "Add Supplier"
    action = "/contacts/update" if is_edit else "/contacts/create"
    button = "Update Supplier" if is_edit else "Save Supplier"
    return f"""
<div id="{html.escape(modal_id)}" class="modal-screen supplier-modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Suppliers" aria-label="Close"></a>
  <article class="modal-panel supplier-modal-panel">
    <div class="modal-head">
      <div>
        <span class="contact-chip">Supplier</span>
        <h3>{html.escape(title)}</h3>
        <p>Only the details needed to buy, pay, and contact this supplier.</p>
      </div>
      <a class="modal-close" href="/dashboard?page=Suppliers">Close</a>
    </div>
    <form method="post" action="{action}" class="supplier-form contact-kind-form" data-contact-kind-form>
      {supplier_form_fields(row)}
      <div class="sticky-form-actions">
        <button type="submit">{html.escape(button)}</button>
        <a href="/dashboard?page=Suppliers">Cancel</a>
      </div>
    </form>
  </article>
</div>"""


def supplier_form_fields(row: sqlite3.Row | None = None) -> str:
    contact_id = f'<input type="hidden" name="contact_id" value="{row["id"]}">' if row else ""
    value = lambda key: "" if row is None else (row[key] or "")
    numeric_value = lambda key: "0.00" if row is None else f'{row[key]:.2f}'
    credit_days = "0" if row is None else str(row["credit_days"] or 0)
    return f"""
{contact_id}
<input type="hidden" name="return_page" value="Suppliers">
<section class="supplier-form-section">
  <div class="section-heading">
    <span>01</span>
    <div><h4>Contact Details</h4><p>Main details used when purchasing and calling the supplier.</p></div>
  </div>
  {contact_role_options(value("contact_type") or "supplier")}
  <div class="form-grid two-col">
    {preset_text_input("Supplier Name", "name", value("name"), required=True) if row else text_input("Supplier Name", "name", required=True)}
    {party_type_select(value("supplier_type") or "business")}
    {business_only_field(preset_text_input("Business Name", "business_name", value("business_name")))}
    {preset_text_input("Phone", "phone", value("phone"))}
    {preset_text_input("Email", "email", value("email"))}
  </div>
  <label class="field wide-field">
    <span>Address</span>
    <textarea name="address" rows="3">{html.escape(value("address"))}</textarea>
  </label>
</section>
<section class="supplier-form-section">
  <div class="section-heading">
    <span>02</span>
    <div><h4>More Information</h4><p>Account, tax, and payment settings for this supplier.</p></div>
  </div>
  <div class="form-grid three-col">
    {preset_text_input("Supplier Code", "contact_code", value("contact_code"))}
    {business_only_field(preset_text_input("Tax Number", "tax_number", value("tax_number")))}
    {payment_terms_select(value("payment_terms"))}
    {preset_number_input("Credit Days", "credit_days", credit_days)}
    {preset_number_input("Opening Balance", "opening_balance", numeric_value("opening_balance"))}
    {preset_number_input("Credit Limit", "credit_limit", numeric_value("credit_limit"))}
    {contact_status_select(1 if row is None else row["is_active"])}
  </div>
  <label class="field wide-field">
    <span>Notes</span>
    <textarea name="notes" rows="3">{html.escape(value("notes"))}</textarea>
  </label>
</section>
<section class="supplier-form-section business-only-section" data-business-only>
  <div class="section-heading">
    <span>03</span>
    <div><h4>Contact Person</h4><p>The main person responsible for orders, delivery, or accounts.</p></div>
  </div>
  <div class="form-grid two-col">
    {preset_text_input("Person Name", "contact_person_1_name", value("contact_person_1_name"))}
    {preset_text_input("Designation", "contact_person_1_designation", value("contact_person_1_designation"))}
    {preset_text_input("Person Phone", "contact_person_1_phone", value("contact_person_1_phone"))}
    {preset_text_input("Person Email", "contact_person_1_email", value("contact_person_1_email"))}
  </div>
</section>"""


def party_type_select(selected: str) -> str:
    selected = selected if selected in {"individual", "business"} else "business"
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("individual", "Individual"),
            ("business", "Business"),
        )
    )
    return f"""
<label class="field">
  <span>Individual / Business</span>
  <select name="supplier_type" data-party-type>{options}</select>
</label>"""


def contact_role_options(selected: str) -> str:
    selected = selected if selected in {"customer", "supplier", "both"} else "customer"
    options = "".join(
        f"""
        <label class="choice-row">
          <input type="radio" name="contact_type" value="{value}" {"checked" if selected == value else ""}>
          <span>{label}</span>
        </label>
        """
        for value, label in (
            ("customer", "Customer"),
            ("supplier", "Supplier"),
            ("both", "Both Customer and Supplier"),
        )
    )
    return f"""
<div class="role-choice-block">
  <span>Contact Type</span>
  <div class="role-choice-list">{options}</div>
</div>"""


def business_only_field(field_html: str) -> str:
    return f'<div data-business-only>{field_html}</div>'


def party_type_label(value: str) -> str:
    return "Individual" if value == "individual" else "Business"


def contact_role_label(value: str) -> str:
    labels = {
        "customer": "Customer",
        "supplier": "Supplier",
        "both": "Customer and Supplier",
    }
    return labels.get(value, "Customer")


def customer_status_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All status"),
            ("active", "Active only"),
            ("inactive", "Inactive only"),
        )
    )
    return f"""
<label class="field">
  <span>Status</span>
  <select name="customer_status">{options}</select>
</label>"""


def customer_due_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All balances"),
            ("due", "With due"),
            ("no_due", "No due"),
        )
    )
    return f"""
<label class="field">
  <span>Balance</span>
  <select name="customer_due">{options}</select>
</label>"""


def supplier_status_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All status"),
            ("active", "Active only"),
            ("inactive", "Inactive only"),
        )
    )
    return f"""
<label class="field">
  <span>Status</span>
  <select name="supplier_status">{options}</select>
</label>"""


def supplier_due_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All balances"),
            ("due", "With due"),
            ("no_due", "No due"),
        )
    )
    return f"""
<label class="field">
  <span>Balance</span>
  <select name="supplier_due">{options}</select>
</label>"""


def contact_form_fields(contact_type: str, credit_label: str, row: sqlite3.Row | None = None) -> str:
    contact_id = f'<input type="hidden" name="contact_id" value="{row["id"]}">' if row else ""
    group_field = ""
    if contact_type == "customer":
        selected_group = row["customer_group_id"] if row else None
        group_field = select_input("Customer Group", "customer_group_id", ContactRepository().customer_group_options(), selected_group)

    value = lambda key: "" if row is None else (row[key] or "")
    numeric_value = lambda key: "0.00" if row is None else f'{row[key]:.2f}'
    credit_days = "0" if row is None else str(row["credit_days"] or 0)
    return f"""
{contact_id}
<input type="hidden" name="contact_type" value="{html.escape(contact_type)}">
<section class="contact-form-section">
  <div class="section-heading">
    <span>01</span>
    <div><h4>Business Profile</h4><p>Main identity, tax, and communication details.</p></div>
  </div>
  <div class="form-grid three-col">
    {preset_text_input("Name", "name", value("name"), required=True) if row else text_input("Name", "name", required=True)}
    {preset_text_input("Business Name", "business_name", value("business_name"))}
    {preset_text_input("Contact Code", "contact_code", value("contact_code"))}
    {preset_text_input("Tax Number", "tax_number", value("tax_number"))}
    {preset_text_input("Phone", "phone", value("phone"))}
    {preset_text_input("Alternate Phone", "alternate_phone", value("alternate_phone"))}
    {preset_text_input("Email", "email", value("email"))}
    {preset_text_input("Website", "website", value("website"))}
    {group_field}
  </div>
</section>
<section class="contact-form-section">
  <div class="section-heading">
    <span>02</span>
    <div><h4>Payment And Credit</h4><p>Opening balance, credit limits, and payment terms.</p></div>
  </div>
  <div class="form-grid three-col">
    {preset_number_input("Opening Balance", "opening_balance", numeric_value("opening_balance"))}
    {preset_number_input(credit_label, "credit_limit", numeric_value("credit_limit"))}
    {preset_number_input("Credit Days", "credit_days", credit_days)}
    {payment_terms_select(value("payment_terms"))}
    {contact_status_select(1 if row is None else row["is_active"])}
  </div>
</section>
<section class="contact-form-section">
  <div class="section-heading">
    <span>03</span>
    <div><h4>Address</h4><p>Location fields for delivery, billing, and reports.</p></div>
  </div>
  <div class="form-grid three-col">
    {preset_text_input("City", "city", value("city"))}
    {preset_text_input("State / Province", "state", value("state"))}
    {preset_text_input("Country", "country", value("country"))}
    {preset_text_input("Postal Code", "postal_code", value("postal_code"))}
  </div>
  <label class="field wide-field">
    <span>Address</span>
    <textarea name="address" rows="3">{html.escape(value("address"))}</textarea>
  </label>
</section>
<section class="contact-form-section">
  <div class="section-heading">
    <span>04</span>
    <div><h4>Contact Persons</h4><p>Primary, secondary, and additional people for this contact.</p></div>
  </div>
  <div class="contact-person-grid">
    {contact_person_block(1, row)}
    {contact_person_block(2, row)}
    {contact_person_block(3, row)}
  </div>
</section>
<section class="contact-form-section">
  <div class="section-heading">
    <span>05</span>
    <div><h4>Notes</h4><p>Internal notes for purchasing, sales, delivery, and account teams.</p></div>
  </div>
  <label class="field">
    <span>Notes</span>
    <textarea name="notes" rows="3">{html.escape(value("notes"))}</textarea>
  </label>
</section>"""


def contact_person_block(index: int, row: sqlite3.Row | None = None) -> str:
    prefix = f"contact_person_{index}"
    value = lambda key: "" if row is None else (row[f"{prefix}_{key}"] or "")
    return f"""
<div class="contact-person-card">
  <h5>Contact Person {index}</h5>
  {preset_text_input("Name", f"{prefix}_name", value("name"))}
  {preset_text_input("Designation", f"{prefix}_designation", value("designation"))}
  {preset_text_input("Phone", f"{prefix}_phone", value("phone"))}
  {preset_text_input("Email", f"{prefix}_email", value("email"))}
</div>"""


def render_contact_edit_card(row: sqlite3.Row, contact_type: str, credit_label: str) -> str:
    return f"""
<article class="panel contact-edit-card" id="contact-{row["id"]}">
  <form method="post" action="/contacts/update" class="contact-form">
    <div class="contact-card-head">
      <div>
        <span class="contact-chip">{html.escape(row["contact_code"] or row["payment_terms"] or "Profile")}</span>
        <h3>{html.escape(row["name"])}</h3>
        <p>{html.escape(row["business_name"] or row["email"] or "Edit this full contact profile.")}</p>
      </div>
      <button type="submit">Update</button>
    </div>
    {contact_form_fields(contact_type, credit_label, row)}
  </form>
</article>"""


def contact_person_summary(row: sqlite3.Row) -> str:
    people = [
        row["contact_person_1_name"],
        row["contact_person_2_name"],
        row["contact_person_3_name"],
    ]
    count = sum(1 for person in people if person)
    if count == 0:
        return '<span class="badge">None</span>'
    return f'<span class="badge role-badge">{count} people</span>'


def payment_terms_select(selected: str = "") -> str:
    options = "".join(
        f'<option value="{html.escape(value)}" {"selected" if selected == value else ""}>{html.escape(label)}</option>'
        for value, label in (
            ("", "Select terms"),
            ("Cash", "Cash"),
            ("Net 7", "Net 7"),
            ("Net 15", "Net 15"),
            ("Net 30", "Net 30"),
            ("Net 45", "Net 45"),
            ("Custom", "Custom"),
        )
    )
    return f"""
<label class="field">
  <span>Payment Terms</span>
  <select name="payment_terms">{options}</select>
</label>"""


def contact_status_select(selected: int) -> str:
    return f"""
<label class="field">
  <span>Status</span>
  <select name="is_active">
    <option value="1" {"selected" if selected else ""}>Active</option>
    <option value="0" {"selected" if not selected else ""}>Inactive</option>
  </select>
</label>"""


def render_customer_groups(
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    groups = ContactRepository().list_customer_groups()
    search = (query.get("group_search", [""])[0] or "").strip()
    status = (query.get("group_status", ["all"])[0] or "all").strip()
    filtered_groups = [
        row for row in groups
        if customer_group_matches_filter(row, search, status)
    ]
    active_count = sum(1 for row in groups if row["is_active"])
    rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["name"])}</strong>
            <p class="table-note">{html.escape(row["note"] or "No note")}</p>
          </td>
          <td class="numeric">{row["price_discount_percent"]:.2f}%</td>
          <td class="numeric">{row["customer_count"]}</td>
          <td>{status_badge(row["is_active"])}</td>
          <td class="actions-cell"><a class="table-link" href="#customer-group-{row["id"]}">Edit</a></td>
        </tr>
        """
        for row in filtered_groups
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No customer groups match this filter.</td></tr>'
    edit_modals = "".join(render_customer_group_modal(row) for row in filtered_groups)

    return f"""
<div class="page-title action-title supplier-page-title">
  <div>
    <h2>Customer Groups</h2>
    <p>Group customers for pricing, discounts, reports, and credit policy.</p>
  </div>
  <a class="primary-link" href="#add-customer-group-modal">Add Customer Group</a>
</div>
{render_notice(message, error)}
<article class="panel supplier-filter-panel">
  <form method="get" action="/dashboard" class="supplier-filter-form customer-group-filter-form">
    <input type="hidden" name="page" value="Customer Groups">
    <label class="field">
      <span>Search Customer Groups</span>
      <input type="search" name="group_search" value="{html.escape(search)}" placeholder="Search group name or note">
    </label>
    {customer_group_status_select(status)}
    <button type="submit">Search</button>
    <a class="secondary-link" href="/dashboard?page=Customer%20Groups">Clear</a>
  </form>
</article>
<section class="supplier-summary-row">
  <article class="metric supplier-mini-metric"><span>All Groups</span><strong>{len(groups)}</strong></article>
  <article class="metric supplier-mini-metric"><span>Active</span><strong>{active_count}</strong></article>
  <article class="metric supplier-mini-metric"><span>Matched</span><strong>{len(filtered_groups)}</strong></article>
</section>
<article class="panel table-panel supplier-table-panel">
  <div class="supplier-list-head">
    <div>
      <h3>All Customer Groups</h3>
      <p>Every customer group with discount, customer count, and active status.</p>
    </div>
    <a class="primary-link" href="#add-customer-group-modal">Add Customer Group</a>
  </div>
  <table>
    <thead>
      <tr>
        <th>Group</th>
        <th>Calculation Percentage (%)</th>
        <th>Customers</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>
{render_customer_group_modal()}
{edit_modals}"""


def render_customer_group_modal(row: sqlite3.Row | None = None) -> str:
    is_edit = row is not None
    modal_id = f'customer-group-{row["id"]}' if is_edit else "add-customer-group-modal"
    title = f'Edit {row["name"]}' if is_edit else "Add Customer Group"
    action = "/customer-groups/update" if is_edit else "/customer-groups/create"
    button = "Update Group" if is_edit else "Save Group"
    group_id = f'<input type="hidden" name="group_id" value="{row["id"]}">' if is_edit else ""
    name = "" if row is None else row["name"]
    discount = "0.00" if row is None else f'{row["price_discount_percent"]:.2f}'
    note = "" if row is None else (row["note"] or "")
    is_active = 1 if row is None else row["is_active"]
    return f"""
<div id="{html.escape(modal_id)}" class="modal-screen supplier-modal-screen">
  <a class="modal-backdrop" href="/dashboard?page=Customer%20Groups" aria-label="Close"></a>
  <article class="modal-panel supplier-modal-panel">
    <div class="modal-head">
      <div>
        <span class="contact-chip">Group</span>
        <h3>{html.escape(title)}</h3>
        <p>Create a pricing or discount group for customers.</p>
      </div>
      <a class="modal-close" href="/dashboard?page=Customer%20Groups">Close</a>
    </div>
    <form method="post" action="{action}" class="supplier-form">
      {group_id}
      <section class="supplier-form-section">
        <div class="form-grid two-col">
          {preset_text_input("Customer Group Name", "name", name, required=True) if is_edit else text_input("Customer Group Name", "name", required=True)}
          {number_input("Calculation Percentage (%)", "price_discount_percent", discount)}
          <label class="field">
            <span>Status</span>
            <select name="is_active">
              <option value="1" {"selected" if is_active else ""}>Active</option>
              <option value="0" {"selected" if not is_active else ""}>Inactive</option>
            </select>
          </label>
        </div>
        <label class="field wide-field">
          <span>Note</span>
          <textarea name="note" rows="4">{html.escape(note)}</textarea>
        </label>
      </section>
      <div class="sticky-form-actions">
        <button type="submit">{html.escape(button)}</button>
        <a href="/dashboard?page=Customer%20Groups">Cancel</a>
      </div>
    </form>
  </article>
</div>"""


def customer_group_matches_filter(row: sqlite3.Row, search: str, status: str) -> bool:
    if search:
        haystack = f'{row["name"] or ""} {row["note"] or ""}'.lower()
        if search.lower() not in haystack:
            return False
    if status == "active" and not row["is_active"]:
        return False
    if status == "inactive" and row["is_active"]:
        return False
    return True


def customer_group_status_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("all", "All status"),
            ("active", "Active only"),
            ("inactive", "Inactive only"),
        )
    )
    return f"""
<label class="field">
  <span>Status</span>
  <select name="group_status">{options}</select>
</label>"""


def render_import_contacts(message: str = "", error: str = "") -> str:
    sample = (
        "type,supplier_type,name,business_name,contact_code,tax_number,phone,alternate_phone,email,website,address,city,state,country,postal_code,payment_terms,credit_days,opening_balance,credit_limit,contact_person_1_name,contact_person_1_designation,contact_person_1_phone,contact_person_1_email,notes,is_active\n"
        "customer,individual,John Customer,,CUS-001,,0771234567,,john@example.com,,Colombo 03,Colombo,Western,Sri Lanka,00300,Net 15,15,0,5000,,,,,Regular retail customer,active\n"
        "supplier,business,ABC Supplier,ABC Trading Pvt Ltd,SUP-001,VAT123,0111234567,0117654321,abc@example.com,https://abc.example,Kandy Road,Kandy,Central,Sri Lanka,20000,Net 30,30,1000,0,Nimal Perera,Accounts Manager,0711111111,nimal@abc.example,Main dry goods supplier,active\n"
        "both,business,Sunil Stores,Sunil Stores,SUN-001,,0715556666,,sunil@example.com,,Galle Road,Galle,Southern,Sri Lanka,80000,Cash,0,0,10000,Sunil Silva,Owner,0715556666,sunil@example.com,Can buy and sell,active"
    )
    return f"""
<div class="page-title action-title supplier-page-title">
  <div>
    <h2>Import Contacts</h2>
    <p>Paste CSV rows to import customers, suppliers, or contacts that are both. Required columns: type, name.</p>
  </div>
  <div class="top-actions">
    <a href="/dashboard?page=Customers">Customers</a>
    <a href="/dashboard?page=Suppliers">Suppliers</a>
  </div>
</div>
{render_notice(message, error)}
<article class="panel supplier-table-panel">
  <form method="post" action="/contacts/import" class="import-contact-form" data-import-file-form>
    <section class="import-section">
      <div class="section-heading">
        <span>01</span>
        <div><h4>File To Import</h4><p>Select a CSV file, or paste CSV data into the box below.</p></div>
      </div>
      <label class="field">
        <span>Choose CSV File</span>
        <input type="file" accept=".csv,text/csv" data-import-file>
      </label>
      <label class="field wide-field">
        <span>CSV Data</span>
        <textarea name="csv_text" rows="10" data-import-text>{html.escape(sample)}</textarea>
      </label>
    </section>
    <section class="import-section">
      <div class="section-heading">
        <span>02</span>
        <div><h4>Instructions</h4><p>Use the column names exactly as shown. Required columns are type and name.</p></div>
      </div>
      {import_contact_instruction_table()}
    </section>
    <div class="form-actions">
      <button type="submit">Import Contacts</button>
      <a href="/dashboard?page=Customers">Customers</a>
      <a href="/dashboard?page=Suppliers">Suppliers</a>
    </div>
  </form>
</article>"""


def import_contact_instruction_table() -> str:
    columns = (
        ("type", "Required. customer, supplier, or both."),
        ("supplier_type", "Optional. individual or business."),
        ("name", "Required. Customer or supplier display name."),
        ("business_name", "Optional. Company or shop name."),
        ("contact_code", "Optional. Internal contact code."),
        ("tax_number", "Optional. VAT/GST/tax number."),
        ("phone", "Optional. Main phone number."),
        ("alternate_phone", "Optional. Second phone number."),
        ("email", "Optional. Email address."),
        ("website", "Optional. Website URL."),
        ("address", "Optional. Street address."),
        ("city", "Optional. City."),
        ("state", "Optional. State or province."),
        ("country", "Optional. Country."),
        ("postal_code", "Optional. Postal code."),
        ("payment_terms", "Optional. Cash, Net 7, Net 15, Net 30, etc."),
        ("credit_days", "Optional. Number of credit days."),
        ("opening_balance", "Optional. Starting balance."),
        ("credit_limit", "Optional. Allowed credit limit."),
        ("contact_person_1_name", "Optional. Main contact person."),
        ("contact_person_1_designation", "Optional. Person role."),
        ("contact_person_1_phone", "Optional. Person phone."),
        ("contact_person_1_email", "Optional. Person email."),
        ("notes", "Optional. Internal notes."),
        ("is_active", "Optional. active/inactive, yes/no, true/false, or 1/0."),
    )
    rows = "".join(
        f"<tr><td><code>{html.escape(name)}</code></td><td>{html.escape(description)}</td></tr>"
        for name, description in columns
    )
    return f"""
<div class="table-panel import-instruction-table">
  <table>
    <thead><tr><th>Column</th><th>Use</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def render_contact_ledger(contact_type: str, contact_id: int) -> str:
    repository = ContactRepository()
    if contact_type == "supplier":
        rows_data = repository.supplier_ledger(contact_id)
        title = "Supplier Ledger"
        back_page = "Suppliers"
    else:
        rows_data = repository.customer_ledger(contact_id)
        title = "Customer Ledger"
        back_page = "Customers"

    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["entry_date"])}</td>
          <td>{html.escape(row["reference"])}</td>
          <td class="numeric">{row["total"]:.2f}</td>
          <td class="numeric">{row["paid_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
        </tr>
        """
        for row in rows_data
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No ledger entries found.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>{styles()}</style></head>
<body>
  <main class="content">
    <div class="page-title action-title">
      <div>
        <h2>{html.escape(title)}</h2>
        <p>Invoice totals, paid amounts, and due balances for this contact.</p>
      </div>
      <a class="secondary-link" href="/dashboard?page={quote(back_page)}">Back</a>
    </div>
    <article class="panel table-panel">
      <table>
        <thead><tr><th>Date</th><th>Reference</th><th>Total</th><th>Paid</th><th>Due</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </article>
  </main>
</body>
</html>"""


def purchase_payment_flow(row: sqlite3.Row) -> str:
    cleared = float(row["cleared_amount"] or 0)
    pending_cheque = float(row["pending_cheque_amount"] or 0)
    due = float(row["due_amount"] or 0)
    parts = []
    if cleared > 0:
        parts.append(f"Cleared {cleared:.2f}")
    if pending_cheque > 0:
        parts.append(f"Cheque pending {pending_cheque:.2f}")
    if due > 0:
        parts.append(f"Due {due:.2f}")
    if not parts:
        parts.append("No payment")
    return " | ".join(parts)


def render_purchase_list(
    query: dict[str, list[str]] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    query = query or {}
    supplier_id = optional_query_int(query, "supplier_id")
    product_id = optional_query_int(query, "product_id")
    start_date = (query.get("start_date", [""])[0] or "").strip()
    end_date = (query.get("end_date", [""])[0] or "").strip()
    purchases = PurchaseRepository().list_purchases(supplier_id, product_id, start_date, end_date)
    suppliers = ContactRepository().supplier_options()
    products = ProductRepository().product_options()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["purchase_date"])}</td>
          <td>{html.escape(row["supplier_name"] or "")}</td>
          <td class="numeric">{row["item_count"]}</td>
          <td class="numeric">{row["total_quantity"]:.2f}</td>
          <td class="numeric">{row["total"]:.2f}</td>
          <td class="numeric">{row["paid_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
          <td>{html.escape(row["payment_status"].title())}</td>
          <td>{html.escape(purchase_payment_flow(row))}</td>
          <td><a class="table-link" href="/purchases/detail?id={row["id"]}">All Details</a></td>
        </tr>
        """
        for row in purchases
    )
    if not rows:
        rows = '<tr><td colspan="11" class="empty">No purchases match the selected filters.</td></tr>'

    supplier_options = '<option value="">All Suppliers</option>' + "".join(
        f'<option value="{item.id}" {"selected" if item.id == supplier_id else ""}>{html.escape(item.name)}</option>'
        for item in suppliers
    )
    product_options = '<option value="">All Products</option>' + "".join(
        f'<option value="{item.id}" {"selected" if item.id == product_id else ""}>{html.escape(item.name)}</option>'
        for item in products
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>List Purchases</h2>
    <p>Saved purchase invoices. Each purchase adds stock through stock movements.</p>
  </div>
  <a class="primary-link" href="/dashboard?page=Add%20Purchase">Add Purchase</a>
</div>
{render_notice(message, error)}
<article class="panel purchase-filter-panel">
  <form method="get" action="/dashboard" class="purchase-filter-form">
    <input type="hidden" name="page" value="List Purchases">
    <label class="field"><span>Supplier</span><select name="supplier_id">{supplier_options}</select></label>
    <label class="field"><span>Product</span><select name="product_id">{product_options}</select></label>
    {date_input("From", "start_date", start_date)}
    {date_input("To", "end_date", end_date)}
    <button type="submit">Filter</button>
    <a class="secondary-link" href="/dashboard?page=List%20Purchases">Clear</a>
  </form>
</article>
<article class="panel table-panel">
  <table>
    <thead>
      <tr>
        <th>Invoice</th>
        <th>Date</th>
        <th>Supplier</th>
        <th>Items</th>
        <th>Qty</th>
        <th>Total</th>
        <th>Paid</th>
        <th>Due</th>
        <th>Status</th>
        <th>Payment Flow</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_add_purchase(message: str = "", error: str = "") -> str:
    product_repository = ProductRepository()
    suppliers = ContactRepository().supplier_options()
    products = [row for row in product_repository.list_products() if row["is_active"]]
    categories = product_repository.list_categories()
    brands = product_repository.list_brands()
    units = product_repository.list_units()
    payment_methods = SettingsRepository().list_payment_methods()
    default_invoice = "PO-" + __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")
    today = __import__("datetime").date.today().isoformat()
    product_hint = ""
    if not products:
        product_hint = '<div class="error">Add at least one product before creating a purchase.</div>'
    product_options = '<option value="">Select product</option>' + "".join(
        f'<option value="{row["id"]}" data-name="{html.escape(row["name"], quote=True)}" '
        f'data-sku="{html.escape(row["sku"], quote=True)}" '
        f'data-price="{float(row["purchase_price"] or 0):.2f}">'
        f'{html.escape(row["name"])} ({html.escape(row["sku"])})</option>'
        for row in products
    )
    quick_category_options = '<option value="">No category</option>' + "".join(
        f'<option value="{item.id}">{html.escape(item.name)}</option>' for item in categories
    )
    quick_brand_options = '<option value="">No brand</option>' + "".join(
        f'<option value="{item.id}">{html.escape(item.name)}</option>' for item in brands
    )
    quick_unit_options = '<option value="">No unit</option>' + "".join(
        f'<option value="{item.id}">{html.escape(item.name)}</option>' for item in units
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Add Purchase</h2>
    <p>Create a supplier purchase and increase product stock in one transaction.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Purchases">List Purchases</a>
</div>
{render_notice(message, error)}
{product_hint}
<article class="panel">
  <form class="product-form purchase-builder" method="post" action="/purchases/create" data-purchase-form>
    <div class="form-grid three-col">
      {select_input("Supplier", "supplier_id", suppliers)}
      {preset_text_input("Invoice No", "invoice_no", default_invoice, required=True)}
      {date_input("Purchase Date", "purchase_date", today)}
    </div>
    <section class="purchase-item-entry">
      <div class="purchase-product-picker">
        <label class="field">
          <span>Product</span>
          <select name="product_id" data-purchase-product>{product_options}</select>
        </label>
        <button type="button" class="purchase-new-product-button" data-purchase-product-open>+ New Product</button>
      </div>
      <label class="field"><span>Quantity</span><input name="quantity" type="number" min="0.01" step="0.01" value="1" data-purchase-quantity></label>
      <label class="field"><span>Purchase Price</span><input name="purchase_price" type="number" min="0" step="0.01" value="0.00" data-purchase-price></label>
      <button type="button" data-purchase-add>Add Item</button>
    </section>
    <div class="purchase-items-table table-panel">
      <table>
        <thead><tr><th>Product</th><th>SKU</th><th>Quantity</th><th>Price</th><th>Line Total</th><th></th></tr></thead>
        <tbody data-purchase-items><tr><td colspan="6" class="empty">No products added.</td></tr></tbody>
      </table>
    </div>
    <div data-purchase-hidden></div>
    <div class="form-grid three-col purchase-summary-fields">
      {number_input("Discount", "discount", "0.00")}
      {number_input("Tax", "tax", "0.00")}
      <input type="hidden" name="paid_amount" value="0.00" data-purchase-paid-total>
      <div class="purchase-summary">
        <span>Subtotal</span><strong data-purchase-subtotal>0.00</strong>
        <span>Paid</span><strong data-purchase-paid-display>0.00</strong>
        <span>Total</span><strong data-purchase-total>0.00</strong>
        <span>Due</span><strong data-purchase-due>0.00</strong>
      </div>
    </div>
    <section class="purchase-payment-box">
      <div class="purchase-payment-head">
        <div>
          <span>Split Payment</span>
          <strong>Cash + Cheque</strong>
        </div>
        <p>Cash is posted immediately. Cheque stays pending until it is cleared.</p>
      </div>
      <div class="form-grid three-col">
        <label class="field"><span>Cash / Bank Amount</span><input name="cash_amount" type="number" min="0" step="0.01" value="0.00" data-purchase-cash></label>
        {payment_method_select("Cash / Bank Method", "cash_method", payment_methods)}
        <label class="field"><span>Cheque Amount</span><input name="cheque_amount" type="number" min="0" step="0.01" value="0.00" data-purchase-cheque></label>
        <label class="field"><span>Cheque No</span><input name="cheque_no" data-purchase-cheque-required></label>
        {date_input("Cheque Date", "cheque_date", today)}
        <label class="field"><span>Bank Name</span><input name="cheque_bank"></label>
      </div>
      <label class="field wide-field"><span>Cheque Note</span><textarea name="cheque_note" rows="2" placeholder="Example: supplier cheque, next month clearing"></textarea></label>
    </section>
    <div class="form-actions">
      <button type="submit">Save Purchase</button>
      <a href="/dashboard?page=List%20Purchases">Cancel</a>
    </div>
    <div class="purchase-quick-modal" data-purchase-product-modal hidden>
      <div class="purchase-quick-dialog" role="dialog" aria-modal="true" aria-labelledby="quick-product-title">
        <div class="purchase-quick-head">
          <div><span>Purchase Setup</span><h3 id="quick-product-title">New Product</h3></div>
          <button type="button" class="modal-close" data-purchase-product-close title="Close">×</button>
        </div>
        <div class="purchase-quick-grid">
          <label class="field"><span>Product Name</span><input data-quick-product-name></label>
          <label class="field"><span>SKU</span><input data-quick-product-sku></label>
          {automatic_barcode_input(input_attributes="data-quick-product-barcode")}
          <label class="field"><span>Category</span><select data-quick-product-category>{quick_category_options}</select></label>
          <label class="field"><span>Brand</span><select data-quick-product-brand>{quick_brand_options}</select></label>
          <label class="field"><span>Unit</span><select data-quick-product-unit>{quick_unit_options}</select></label>
          <label class="field"><span>Purchase Quantity</span><input type="number" min="0.01" step="0.01" value="1" data-quick-product-quantity></label>
          <label class="field"><span>Purchase Price</span><input type="number" min="0" step="0.01" value="0.00" data-quick-product-purchase-price></label>
          <label class="field"><span>Selling Price</span><input type="number" min="0" step="0.01" value="0.00" data-quick-product-selling-price></label>
          <label class="field"><span>Stock Alert Qty</span><input type="number" min="0" step="0.01" value="0.00" data-quick-product-alert></label>
        </div>
        <p class="purchase-quick-error" data-quick-product-error hidden></p>
        <div class="purchase-quick-actions">
          <button type="button" class="secondary-button" data-purchase-product-close>Cancel</button>
          <button type="button" data-purchase-product-save>Save & Add To Purchase</button>
        </div>
      </div>
    </div>
  </form>
</article>"""


def render_pending_purchase_cheques(
    query: dict[str, list[str]] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    query = query or {}
    status = (query.get("status", ["pending"])[0] or "").strip()
    rows_data = PurchaseRepository().list_purchase_cheques(status)
    today = __import__("datetime").date.today().isoformat()
    total_amount = sum(float(row["amount"] or 0) for row in rows_data)
    pending_amount = sum(float(row["amount"] or 0) for row in rows_data if row["status"] == "pending")
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["supplier_name"])}</td>
          <td>{html.escape(row["purchase_date"])}</td>
          <td>{html.escape(row["cheque_no"] or "")}</td>
          <td>{html.escape(row["cheque_date"] or "")}</td>
          <td>{html.escape(row["bank_name"] or "")}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["status"].replace("_", " ").title())}</td>
          <td>{html.escape(row["cleared_at"] or row["bounced_at"] or "")}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td>
            {pending_cheque_actions(row, today)}
          </td>
        </tr>
        """
        for row in rows_data
    )
    if not rows:
        rows = '<tr><td colspan="11" class="empty">No cheque records found.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Pending Cheques</h2>
    <p>Excel-style purchase cheque control. Clear cheques only when bank/payment is actually completed.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=Add%20Purchase">Add Purchase</a>
</div>
{render_notice(message, error)}
{render_money_cards([("Cheque Total", total_amount), ("Pending Amount", pending_amount), ("Rows", float(len(rows_data)))])}
<article class="panel purchase-filter-panel">
  <form method="get" action="/dashboard" class="purchase-filter-form">
    <input type="hidden" name="page" value="Pending Cheques">
    {simple_select("Status", "status", [("", "All"), ("pending", "Pending"), ("cleared", "Cleared"), ("bounced", "Bounced")], status)}
    <button type="submit">Filter</button>
    <a class="secondary-link" href="/dashboard?page=Pending%20Cheques">Pending Only</a>
  </form>
</article>
<article class="panel table-panel report-sheet">
  <table>
    <thead>
      <tr>
        <th>Invoice</th><th>Supplier</th><th>Purchase Date</th><th>Cheque No</th><th>Cheque Date</th>
        <th>Bank</th><th>Amount</th><th>Status</th><th>Closed Date</th><th>Note</th><th>Action</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def pending_cheque_actions(row: sqlite3.Row, today: str) -> str:
    if row["status"] != "pending":
        return f'<a class="table-link" href="/purchases/detail?id={row["purchase_id"]}">Details</a>'
    return f"""
<div class="inline-actions">
  <form method="post" action="/purchase-cheques/status" class="table-action">
    <input type="hidden" name="payment_id" value="{row["id"]}">
    <input type="hidden" name="status" value="cleared">
    <input type="hidden" name="action_date" value="{html.escape(today)}">
    <button type="submit">Mark Cleared</button>
  </form>
  <form method="post" action="/purchase-cheques/status" class="table-action">
    <input type="hidden" name="payment_id" value="{row["id"]}">
    <input type="hidden" name="status" value="bounced">
    <input type="hidden" name="action_date" value="{html.escape(today)}">
    <button type="submit">Bounced</button>
  </form>
  <a class="table-link" href="/purchases/detail?id={row["purchase_id"]}">Details</a>
</div>"""


def purchase_payment_line_action(row: sqlite3.Row, purchase_id: int, today: str) -> str:
    if row["payment_type"] != "cheque" or row["status"] != "pending":
        return ""
    detail_url = f"/purchases/detail?id={purchase_id}"
    return f"""
<div class="inline-actions">
  <form method="post" action="/purchase-cheques/status" class="table-action">
    <input type="hidden" name="payment_id" value="{row["id"]}">
    <input type="hidden" name="status" value="cleared">
    <input type="hidden" name="action_date" value="{html.escape(today)}">
    <input type="hidden" name="return_to" value="{html.escape(detail_url)}">
    <button type="submit">Clear</button>
  </form>
  <form method="post" action="/purchase-cheques/status" class="table-action">
    <input type="hidden" name="payment_id" value="{row["id"]}">
    <input type="hidden" name="status" value="bounced">
    <input type="hidden" name="action_date" value="{html.escape(today)}">
    <input type="hidden" name="return_to" value="{html.escape(detail_url)}">
    <button type="submit">Bounce</button>
  </form>
</div>"""


def render_purchase_detail(purchase_id: int) -> str:
    purchase, items, payments = PurchaseRepository().get_purchase_detail(purchase_id)
    if purchase is None:
        return render_not_found_page("Purchase invoice not found.")
    settings = SettingsRepository().get_business_settings()
    today = __import__("datetime").date.today().isoformat()
    payment_method = (purchase["payment_method"] or "Not paid").replace("_", " ").title()
    supplier_contact = " ".join(
        value for value in (purchase["supplier_phone"] or "", purchase["supplier_email"] or "") if value
    )
    total_quantity = sum(float(item["quantity"] or 0) for item in items)
    payment_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_type"].replace("_", " ").title())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{html.escape(row["cheque_no"] or "")}</td>
          <td>{html.escape(row["cheque_date"] or "")}</td>
          <td>{html.escape(row["bank_name"] or "")}</td>
          <td>{html.escape(row["status"].replace("_", " ").title())}</td>
          <td>{purchase_payment_line_action(row, purchase_id, today)}</td>
        </tr>
        """
        for row in payments
    ) or '<tr><td colspan="8" class="empty">No payment lines found.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Purchase Details {html.escape(purchase["invoice_no"])}</title>
  <style>{styles()}</style>
</head>
<body class="purchase-detail-body">
  <main class="purchase-detail-page">
    <div class="purchase-detail-toolbar">
      <div>
        <span>Purchase Record</span>
        <h1>{html.escape(purchase["invoice_no"])}</h1>
        <p>{html.escape(purchase["supplier_name"])} | {html.escape(purchase["purchase_date"])}</p>
      </div>
      <div class="purchase-detail-actions">
        <a class="secondary-link" href="/dashboard?page=List%20Purchases">Back</a>
        <button type="button" onclick="window.print()">Print</button>
      </div>
    </div>
    <section class="purchase-detail-metrics">
      <article><span>Product Lines</span><strong>{len(items)}</strong></article>
      <article><span>Total Quantity</span><strong>{total_quantity:.2f}</strong></article>
      <article><span>Grand Total</span><strong>{html.escape(settings["currency_symbol"])} {purchase["total"]:.2f}</strong></article>
      <article><span>Paid</span><strong>{html.escape(settings["currency_symbol"])} {purchase["paid_amount"]:.2f}</strong></article>
      <article><span>Due</span><strong>{html.escape(settings["currency_symbol"])} {purchase["due_amount"]:.2f}</strong></article>
    </section>
    <section class="purchase-detail-summary">
      <div>
        <span>Supplier</span>
        <strong>{html.escape(purchase["supplier_name"])}</strong>
        <small>{html.escape(supplier_contact)}</small>
        <small>{html.escape(purchase["supplier_address"] or "")}</small>
      </div>
      <div>
        <span>Purchase Information</span>
        <strong>{html.escape(purchase["invoice_no"])}</strong>
        <small>Date: {html.escape(purchase["purchase_date"])}</small>
        <small>Location: {html.escape(purchase["location_name"])}</small>
      </div>
      <div><span>Payment Method</span><strong>{html.escape(payment_method)}</strong></div>
      <div><span>Payment Status</span><strong>{html.escape(purchase["payment_status"].title())}</strong></div>
      <div><span>Recorded</span><strong>{html.escape(purchase["created_at"])}</strong></div>
    </section>
    <section class="purchase-detail-table">
      <div class="purchase-detail-section-head">
        <h2>Purchased Items</h2>
        <span>{len(items)} lines | {total_quantity:.2f} total quantity</span>
      </div>
      <table>
        <thead>
          <tr><th>#</th><th>Product</th><th>SKU</th><th>Barcode</th><th>Quantity</th><th>Unit Cost</th><th>Line Total</th><th>Stock Status</th></tr>
        </thead>
        <tbody>{''.join(
            f'<tr><td>{index}</td><td>{html.escape(item["product_name"])}</td>'
            f'<td>{html.escape(item["product_sku"])}</td><td>{html.escape(item["product_barcode"] or "")}</td>'
            f'<td class="numeric">{item["quantity"]:.2f} {html.escape(item["unit_name"])}</td>'
            f'<td class="numeric">{item["purchase_price"]:.2f}</td>'
            f'<td class="numeric">{item["line_total"]:.2f}</td><td>Received</td></tr>'
            for index, item in enumerate(items, 1)
        ) or '<tr><td colspan="8" class="empty">No purchase items found.</td></tr>'}</tbody>
        <tfoot>
          <tr><th colspan="4">Totals</th><th class="numeric">{total_quantity:.2f}</th><th></th><th class="numeric">{purchase["subtotal"]:.2f}</th><th></th></tr>
        </tfoot>
      </table>
    </section>
    <section class="purchase-payment-detail">
      <div class="purchase-detail-section-head"><h2>Payment Summary</h2></div>
      <div class="purchase-payment-grid">
        <div><span>Subtotal</span><strong>{html.escape(settings["currency_symbol"])} {purchase["subtotal"]:.2f}</strong></div>
        <div><span>Discount</span><strong>{html.escape(settings["currency_symbol"])} {purchase["discount"]:.2f}</strong></div>
        <div><span>Tax</span><strong>{html.escape(settings["currency_symbol"])} {purchase["tax"]:.2f}</strong></div>
        <div class="total"><span>Grand Total</span><strong>{html.escape(settings["currency_symbol"])} {purchase["total"]:.2f}</strong></div>
        <div><span>Paid Amount</span><strong>{html.escape(settings["currency_symbol"])} {purchase["paid_amount"]:.2f}</strong></div>
        <div class="due"><span>Due Amount</span><strong>{html.escape(settings["currency_symbol"])} {purchase["due_amount"]:.2f}</strong></div>
      </div>
    </section>
    <section class="purchase-detail-table">
      <div class="purchase-detail-section-head"><h2>Payment Lines</h2><span>Cash, bank, and cheque history</span></div>
      <table>
        <thead><tr><th>Type</th><th>Amount</th><th>Payment Date</th><th>Cheque No</th><th>Cheque Date</th><th>Bank</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>{payment_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def render_purchase_order(message: str = "", error: str = "") -> str:
    repository = PurchaseOrderRepository()
    orders = repository.list_orders()
    suppliers = ContactRepository().supplier_options()
    products = ProductRepository().product_options()
    default_order_no = "PO-ORDER-" + __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")
    today = __import__("datetime").date.today().isoformat()

    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["order_no"])}</td>
          <td>{html.escape(row["order_date"])}</td>
          <td>{html.escape(row["expected_date"] or "")}</td>
          <td>{html.escape(row["supplier_name"] or "")}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td class="numeric">{row["subtotal"]:.2f}</td>
          <td>{html.escape(row["status"].replace('_', ' ').title())}</td>
        </tr>
        """
        for row in orders
    )
    if not rows:
        rows = '<tr><td colspan="9" class="empty">No purchase orders added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Purchase Order</h2>
  <p>Create supplier orders without changing stock. Stock increases only when an actual purchase is added.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Purchase Order</h3>
    <form method="post" action="/purchase-orders/create">
      <div class="form-grid two-col">
        {select_input("Supplier", "supplier_id", suppliers)}
        {preset_text_input("Order No", "order_no", default_order_no, required=True)}
        {date_input("Order Date", "order_date", today)}
        {date_input("Expected Date", "expected_date", today)}
        {select_input("Product", "product_id", products)}
        {number_input("Quantity", "quantity", "1")}
        {number_input("Purchase Price", "purchase_price", "0.00")}
        <label class="field">
          <span>Status</span>
          <select name="status">
            <option value="ordered">Ordered</option>
            <option value="partial">Partial</option>
            <option value="received">Received</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
      </div>
      <label class="field wide-field">
        <span>Note</span>
        <textarea name="note" rows="4"></textarea>
      </label>
      <button type="submit">Save Purchase Order</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Order List</h3>
    <table>
      <thead>
        <tr>
          <th>Order No</th>
          <th>Order Date</th>
          <th>Expected</th>
          <th>Supplier</th>
          <th>Product</th>
          <th>SKU</th>
          <th>Qty</th>
          <th>Subtotal</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_purchase_return(message: str = "", error: str = "") -> str:
    repository = PurchaseReturnRepository()
    purchase_products = repository.purchase_product_options()
    returns = repository.list_returns()
    today = __import__("datetime").date.today().isoformat()

    return_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["return_date"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["supplier_name"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td class="numeric">{row["refund_amount"]:.2f}</td>
          <td>{html.escape(row["refund_method"].replace("_", " ").title())}</td>
          <td>{html.escape(row["reason"].replace("_", " ").title())}</td>
          <td>{"Stock Reduced" if row["return_to_stock"] else "No Stock Change"}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in returns
    )
    if not return_rows:
        return_rows = '<tr><td colspan="11" class="empty">No purchase returns added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Purchase Return</h2>
  <p>Return purchased products to suppliers, record supplier refunds, and reduce stock.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Purchase Return</h3>
    <form method="post" action="/purchase-return/create">
      <div class="form-grid two-col">
        {purchase_product_select("Purchase / Product", "purchase_product", purchase_products)}
        {date_input("Return Date", "return_date", today)}
        {number_input("Return Quantity", "quantity", "1")}
        {number_input("Refund Amount", "refund_amount", "0.00")}
        {simple_select("Reason", "reason", [
            ("damaged", "Damaged"), ("wrong_item", "Wrong Item"), ("expired", "Expired"),
            ("excess_stock", "Excess Stock"), ("price_issue", "Price Issue"), ("other", "Other")
        ], "damaged")}
        {simple_select("Item Condition", "item_condition", [
            ("resellable", "Resellable"), ("damaged", "Damaged"), ("expired", "Expired"), ("scrap", "Scrap")
        ], "resellable")}
        {simple_select("Refund Method", "refund_method", [
            ("cash", "Cash Received"), ("bank_transfer", "Bank Transfer"), ("card", "Card Refund"),
            ("supplier_credit", "Supplier Credit"), ("exchange", "Exchange"), ("no_refund", "No Refund")
        ], "cash")}
      </div>
      <label class="field checkbox-field">
        <input type="checkbox" name="reduce_stock" value="1" checked>
        <span>Reduce stock because goods are leaving the shop</span>
      </label>
      <label class="field wide-field">
        <span>Note</span>
        <textarea name="note" rows="4"></textarea>
      </label>
      <button type="submit">Save Return</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Return History</h3>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Invoice</th>
          <th>Supplier</th>
          <th>Product</th>
          <th>SKU</th>
          <th>Qty</th>
          <th>Refund</th>
          <th>Method</th>
          <th>Reason</th>
          <th>Stock</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>{return_rows}</tbody>
    </table>
  </article>
</div>"""


def render_sales_list(query: dict[str, list[str]] | None = None, message: str = "", error: str = "") -> str:
    query = query or {}
    filters = sales_history_filters(query)
    sales = SaleRepository().sales_history(filters)
    final_sales = [row for row in sales if row["sale_status"] == "final"]
    gross_sales = sum(float(row["total"]) for row in final_sales)
    returns = sum(float(row["return_amount"]) for row in final_sales)
    net_sales = gross_sales - returns
    paid_sales = sum(float(row["paid_amount"]) for row in final_sales)
    due_sales = sum(float(row["due_amount"]) for row in final_sales)
    cost = sum(float(row["cost_of_goods"]) for row in final_sales)
    gross_profit = net_sales - cost
    customers = ContactRepository().customer_options()
    products_repository = ProductRepository()
    products = products_repository.product_options()
    categories = products_repository.list_categories()
    brands = products_repository.list_brands()
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations() if row["is_active"]
    ]
    payment_methods = [
        ("", "All Methods"),
        *[(row["method_key"], row["name"]) for row in SettingsRepository().list_payment_methods() if row["is_active"]],
    ]
    rows = "".join(
        f"""
        <tr class="{"non-final-sale-row" if row["sale_status"] != "final" else ""}">
          <td>{html.escape(row["created_at"])}</td>
          <td><a class="table-link" href="/sales/invoice?id={row["id"]}">{html.escape(row["invoice_no"])}</a></td>
          <td>{html.escape(row["customer_name"])}</td>
          <td>{html.escape(row["customer_phone"])}</td>
          <td>{html.escape(row["location_name"])}</td>
          <td>System</td>
          <td>Not assigned</td>
          <td class="clip-cell" title="{html.escape(row["product_names"], quote=True)}">{html.escape(row["product_names"])}</td>
          <td class="numeric">{row["item_count"]}</td>
          <td class="numeric">{row["total_quantity"]:.2f}</td>
          <td class="numeric">{row["subtotal"]:.2f}</td>
          <td class="numeric">{row["discount"]:.2f}</td>
          <td class="numeric">{row["tax"]:.2f}</td>
          <td class="numeric">{float(row["return_amount"]) if row["sale_status"] == "final" else 0:.2f}</td>
          <td class="numeric">{float(row["total"]) - (float(row["return_amount"]) if row["sale_status"] == "final" else 0):.2f}</td>
          <td class="numeric">{float(row["cost_of_goods"]) if row["sale_status"] == "final" else 0:.2f}</td>
          <td class="numeric">{float(row["total"]) - float(row["return_amount"]) - float(row["cost_of_goods"]) if row["sale_status"] == "final" else 0:.2f}</td>
          <td class="numeric">{row["paid_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
          <td>{html.escape((row["payment_methods"] or "").replace("_", " ").title())}</td>
          <td>{transaction_status_badge(row["payment_status"])}</td>
          <td>{sale_status_badge(row["sale_status"])}</td>
          <td class="sales-history-actions">
            <a class="table-link" href="/sales/invoice?id={row["id"]}">Invoice</a>
            <a class="table-link" href="/sales/receipt?id={row["id"]}&type=pos">Receipt</a>
            {'<a class="table-link" href="/dashboard?page=Sales%20Return">Return</a>' if row["sale_status"] == "final" else ""}
            {'<a class="table-link" href="/dashboard?page=Shipments">Shipment</a>' if row["sale_status"] == "final" else ""}
          </td>
        </tr>
        """
        for row in sales
    )
    if not rows:
        rows = '<tr><td colspan="23" class="empty">No sales match the selected filters.</td></tr>'

    export_params = {key: value for key, value in filters.items() if value}

    return f"""
<div class="page-title action-title report-title">
  <div>
    <h2>Sales History</h2>
    <p>Invoice-level Excel register for daily sales operations and audit.</p>
  </div>
  <div class="quick-actions">
    <a href="/sales-history/export.csv?{urlencode(export_params)}">Export Excel CSV</a>
    <button type="button" onclick="window.print()">Print / PDF</button>
    <a class="primary-link" href="/dashboard?page=POS">New Sale</a>
  </div>
</div>
{render_notice(message, error)}
{render_money_cards([("Net Sales", net_sales), ("Returns", returns), ("Gross Profit", gross_profit), ("Due", due_sales)])}
<article class="panel report-filter-panel">
  <div class="report-presets">{sales_history_preset_links()}<a href="/dashboard?page=Sales%20History">All Time</a></div>
  <form method="get" action="/dashboard" class="sales-history-filter-grid">
    <input type="hidden" name="page" value="Sales History">
    {preset_text_input("Search", "search", filters["search"])}
    {date_input_optional("From", "date_from", filters["date_from"])}
    {date_input_optional("To", "date_to", filters["date_to"])}
    {select_input("Customer", "customer_id", customers, query_selected_int(filters, "customer_id"))}
    {select_input("Product", "product_id", products, query_selected_int(filters, "product_id"))}
    {select_input("Category", "category_id", categories, query_selected_int(filters, "category_id"))}
    {select_input("Brand", "brand_id", brands, query_selected_int(filters, "brand_id"))}
    {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
    {simple_select("Sale Status", "sale_status", [("", "All Documents"), ("final", "Final"), ("draft", "Draft"), ("quotation", "Quotation"), ("suspended", "Suspended"), ("sales_order", "Sales Order")], filters["sale_status"])}
    {simple_select("Payment", "payment_status", [("", "All Payments"), ("paid", "Paid"), ("partial", "Partial"), ("due", "Due")], filters["payment_status"])}
    {simple_select("Method", "payment_method", payment_methods, filters["payment_method"])}
    <div class="expense-filter-actions"><button type="submit">Apply</button><a class="secondary-link" href="/dashboard?page=Sales%20History">Clear</a></div>
  </form>
</article>
<article class="panel table-panel report-sheet-panel">
  <div class="sheet-meta"><strong>{len(sales)} rows</strong><span>Final sales totals: Paid {paid_sales:.2f} / Due {due_sales:.2f}</span></div>
  <div class="report-sheet-scroll"><table class="report-sheet sales-history-sheet">
    <thead>
      <tr>
        <th>Date & Time</th>
        <th>Invoice</th>
        <th>Customer</th>
        <th>Phone</th>
        <th>Location</th>
        <th>Cashier</th>
        <th>Sales Rep</th>
        <th>Products</th>
        <th>Items</th>
        <th>Qty</th>
        <th>Subtotal</th>
        <th>Discount</th>
        <th>Tax</th>
        <th>Returns</th>
        <th>Net Total</th>
        <th>COGS</th>
        <th>Gross Profit</th>
        <th>Paid</th>
        <th>Due</th>
        <th>Method</th>
        <th>Payment</th>
        <th>Sale Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def sales_period_range(period: str, query: dict[str, list[str]]) -> tuple[str, str]:
    datetime_module = __import__("datetime")
    today = datetime_module.date.today()
    if period == "yesterday":
        day = today - datetime_module.timedelta(days=1)
        return day.isoformat(), day.isoformat()
    if period == "week":
        start = today - datetime_module.timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    if period == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    if period == "custom":
        start_date = (query.get("start_date", [today.isoformat()])[0] or today.isoformat()).strip()
        end_date = (query.get("end_date", [today.isoformat()])[0] or today.isoformat()).strip()
        return start_date, end_date
    return today.isoformat(), today.isoformat()


def sales_history_filters(query: dict[str, list[str]]) -> dict[str, str]:
    keys = (
        "search", "date_from", "date_to", "customer_id", "product_id",
        "category_id", "brand_id", "location_id", "sale_status",
        "payment_status", "payment_method",
    )
    return {key: query.get(key, [""])[0] for key in keys}


def sales_history_preset_links() -> str:
    from datetime import date, timedelta

    today = date.today()
    presets = [
        ("Today", today, today),
        ("Yesterday", today - timedelta(days=1), today - timedelta(days=1)),
        ("This Week", today - timedelta(days=today.weekday()), today),
        ("This Month", today.replace(day=1), today),
    ]
    return "".join(
        f'<a href="/dashboard?{urlencode({"page": "Sales History", "date_from": start.isoformat(), "date_to": end.isoformat()})}">{label}</a>'
        for label, start, end in presets
    )


def sale_status_badge(status: str) -> str:
    classes = {
        "final": "ok",
        "draft": "",
        "quotation": "",
        "suspended": "danger",
        "sales_order": "",
        "cancelled": "danger",
    }
    class_name = classes.get(status, "")
    class_attr = f" {class_name}" if class_name else ""
    return f'<span class="badge{class_attr}">{html.escape(status.replace("_", " ").title())}</span>'


def date_in_range(value: str, start_date: str, end_date: str) -> bool:
    return start_date <= (value or "")[:10] <= end_date


def sales_period_select(selected: str) -> str:
    options = "".join(
        f'<option value="{value}" {"selected" if selected == value else ""}>{label}</option>'
        for value, label in (
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("week", "This Week"),
            ("month", "This Month"),
            ("custom", "Custom Range"),
        )
    )
    return f"""
<label class="field">
  <span>Period</span>
  <select name="period">{options}</select>
</label>"""


def render_pos_sale(message: str = "", error: str = "", source_sale_id: int | None = None) -> str:
    customers = ContactRepository().customer_options()
    products = [row for row in ProductRepository().list_products() if row["is_active"]]
    payment_methods = SettingsRepository().list_payment_methods()
    default_invoice = "INV-" + __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")
    today = __import__("datetime").date.today().isoformat()
    source_sale, source_items = (None, [])
    if source_sale_id:
        source_sale, source_items = SaleRepository().get_sale_invoice(source_sale_id)
        if source_sale and source_sale["sale_status"] != "final":
            default_invoice = str(source_sale["invoice_no"])
            today = str(source_sale["sale_date"])
        else:
            source_sale_id = None
            source_sale, source_items = (None, [])
    product_hint = ""
    if not products:
        product_hint = '<div class="error">Add at least one product before creating a sale.</div>'
    product_tiles = "".join(render_pos_product_tile(row) for row in products)
    categories = sorted({str(row["category_name"] or "").strip() for row in products if row["category_name"]})
    brands = sorted({str(row["brand_name"] or "").strip() for row in products if row["brand_name"]})
    category_filters = "".join(
        f'<button type="button" class="pos-drawer-tile" data-pos-category="{html.escape(name, quote=True)}">'
        f"<span>{html.escape(name)}</span></button>"
        for name in categories
    )
    brand_filters = "".join(
        f'<button type="button" class="pos-drawer-tile" data-pos-brand="{html.escape(name, quote=True)}">'
        f"<span>{html.escape(name)}</span></button>"
        for name in brands
    )
    split_method_options = "".join(
        f'<option value="{html.escape(row["method_key"], quote=True)}">{html.escape(row["name"])}</option>'
        for row in payment_methods
        if row["is_active"]
    ) or '<option value="cash">Cash</option>'
    preload = {}
    if source_sale and source_items:
        preload = {
            "source_sale_id": source_sale_id,
            "customer_id": source_sale["customer_id"],
            "invoice_no": source_sale["invoice_no"],
            "sale_date": source_sale["sale_date"],
            "discount": float(source_sale["discount"] or 0),
            "tax": float(source_sale["tax"] or 0),
            "items": [
                {
                    "id": int(row["product_id"]),
                    "name": row["product_name"],
                    "sku": row["product_sku"],
                    "price": float(row["unit_price"] or 0),
                    "discount": float(row["discount"] or 0),
                    "quantity": float(row["quantity"] or 0),
                }
                for row in source_items
            ],
        }
    preload_attr = html.escape(json.dumps(preload), quote=True)
    source_input = f'<input type="hidden" name="source_sale_id" value="{source_sale_id}">' if source_sale_id else ""
    source_notice = (
        f'<div class="success">Loaded {html.escape(str(source_sale["sale_status"]).replace("_", " ").title())} {html.escape(str(source_sale["invoice_no"]))}. Collect payment and complete as final sale.</div>'
        if source_sale
        else ""
    )

    return f"""
{render_notice(message, error)}
{source_notice}
{product_hint}
<form class="pos-shell" method="post" action="/sales/create" data-pos-form data-pos-preload="{preload_attr}">
  <input type="hidden" name="sale_status" value="final" data-pos-sale-status>
  {source_input}
  <section class="pos-cart-panel">
    <div class="pos-cart-entry-row" data-pos-entry-panel hidden>
      <div class="pos-customer-bar">
        {select_input("Customer", "customer_id", customers)}
        <a class="pos-icon-link" href="/dashboard?page=Customers" title="Add or manage customers">+</a>
      </div>
      <div class="pos-cart-search">
        <label class="field pos-search">
          <span>Scan Or Search Product</span>
          <input type="search" data-pos-search placeholder="Product name / SKU / barcode">
        </label>
      </div>
    </div>
    <div class="pos-ticket-head">
      <div>
        <span>Current Sale</span>
        <strong>{html.escape(default_invoice)}</strong>
      </div>
      <div class="pos-ticket-actions">
        <button type="button" class="pos-entry-toggle" data-pos-entry-toggle aria-expanded="false" title="Open customer and product search" aria-label="Open customer and product search">{svg_icon("search")}</button>
        <button type="button" class="pos-entry-toggle" data-pos-meta-toggle aria-expanded="false" title="Open invoice number and sale date" aria-label="Open invoice number and sale date">{svg_icon("receipt")}</button>
        <button type="button" class="pos-entry-toggle" data-pos-payment-toggle aria-expanded="false" title="Open payment method and receipt type" aria-label="Open payment method and receipt type">{svg_icon("card")}</button>
        <button type="button" class="pos-clear-button" data-pos-clear>Clear Cart</button>
      </div>
    </div>
    <div class="pos-meta pos-sale-meta" data-pos-meta-panel hidden>
      {preset_text_input("Invoice No", "invoice_no", default_invoice, required=True)}
      {date_input("Sale Date", "sale_date", today)}
    </div>
    <div class="pos-cart-lines" data-pos-cart>
      <div class="pos-empty-cart">
        <i></i>
        <strong>Your cart is empty</strong>
        <span>Scan a barcode or select a product.</span>
      </div>
    </div>
    <div data-pos-hidden></div>
    <div class="pos-totals pos-checkout-strip">
      <div class="pos-total-cell"><span>Items</span><strong data-pos-items>0.00</strong></div>
      <div class="pos-total-cell"><span>Subtotal</span><strong data-pos-subtotal>0.00</strong></div>
      <label class="pos-total-cell pos-total-input"><span>Bill Discount</span><input type="number" step="0.01" min="0" name="discount" value="0.00" data-pos-discount><small>Total Disc. <b data-pos-discount-summary>0.00</b></small></label>
      <label class="pos-total-cell pos-total-input"><span>Order Tax</span><input type="number" step="0.01" min="0" name="tax" value="0.00" data-pos-tax></label>
      <div class="pos-total-cell"><span>Shipping</span><strong>0.00</strong></div>
      <label class="pos-total-cell pos-total-input"><span>Paid</span><input type="number" step="0.01" min="0" name="paid_amount" value="0.00" data-pos-paid></label>
      <div class="pos-total-cell"><span>Change / Due</span><strong data-pos-balance>0.00</strong></div>
      <div class="pos-grand-total"><span>Total Payable</span><strong data-pos-total>0.00</strong></div>
    </div>
    <div class="pos-payment-row" data-pos-payment-panel hidden>
      {payment_method_select("Payment Method", "payment_method", payment_methods)}
      <label class="field">
        <span>Receipt Type</span>
        <select name="receipt_type">
          <option value="invoice">Standard Invoice</option>
          <option value="pos" selected>POS Receipt</option>
          <option value="gift">Gift Receipt</option>
          <option value="delivery">Delivery Note</option>
          <option value="tax">Tax Invoice</option>
        </select>
      </label>
    </div>
    <div class="pos-multiple-pay-panel" data-pos-multiple-pay-panel hidden>
      <div class="pos-multiple-pay-head">
        <div><strong>Multiple Pay</strong><span>Split this sale across cash, card, bank, or other methods.</span></div>
        <button type="button" data-pos-multiple-pay-add>+ Add Payment</button>
      </div>
      <div class="pos-multiple-pay-rows" data-pos-multiple-pay-rows data-method-options="{html.escape(split_method_options, quote=True)}"></div>
      <div class="pos-multiple-pay-summary">
        <span>Split Total <strong data-pos-split-total>0.00</strong></span>
        <span>Remaining <strong data-pos-split-remaining>0.00</strong></span>
        <button type="submit">Complete Split Payment</button>
      </div>
    </div>
    <div data-card-hidden></div>
    <div class="pos-card-modal" data-card-modal hidden>
      <div class="pos-card-dialog">
        <div class="pos-card-head">
          <div>
            <span>Card Payment</span>
            <h3>Card Transaction Details</h3>
          </div>
          <strong>Rs. <b data-card-amount>0.00</b></strong>
        </div>
        <div class="form-grid two-col">
          <label class="field">
            <span>Transaction Ref / RRN</span>
            <input data-card-reference placeholder="Auto internal ref or bank RRN" autocomplete="off">
          </label>
          <label class="field">
            <span>Card Last 4</span>
            <input data-card-last4 maxlength="4" placeholder="1234" autocomplete="off">
          </label>
          <label class="field">
            <span>Terminal / Device</span>
            <input data-card-terminal placeholder="Main Counter Terminal">
          </label>
          <label class="field">
            <span>Approval Code (Optional)</span>
            <input data-card-approval placeholder="From card slip if available">
          </label>
        </div>
        <p class="pos-card-help">Ref and terminal are auto-filled for manual terminals. Replace the ref with the bank RRN from the card slip when available.</p>
        <div class="pos-card-actions">
          <button type="button" class="secondary-link" data-card-cancel>Cancel</button>
          <button type="button" data-card-finalize>Finalize Payment & Print</button>
        </div>
      </div>
    </div>
  </section>
  <section class="pos-catalog">
    <div class="pos-catalog-head">
      <div>
        <span class="pos-kicker">Product Browser</span>
        <h3>Select Products</h3>
      </div>
      <div class="pos-count"><strong data-pos-visible-count>{len(products)}</strong><span>products</span></div>
    </div>
    <div class="pos-browser-tabs">
      <button type="button" class="pos-browser-tab active" data-pos-open-drawer="category">
        <span class="pos-browser-tab-icon">{svg_icon("products")}</span>
        <span>Category</span>
        <strong data-pos-category-count>{len(categories) + 1}</strong>
      </button>
      <button type="button" class="pos-browser-tab" data-pos-open-drawer="brand">
        <span class="pos-browser-tab-icon">{svg_icon("brand")}</span>
        <span>Brands</span>
        <strong data-pos-brand-count>{len(brands) + 1}</strong>
      </button>
      <button type="button" class="pos-browser-tab" data-pos-featured-filter>
        <span class="pos-browser-tab-icon">{svg_icon("star")}</span>
        <span>Featured Products</span>
      </button>
    </div>
    <div class="pos-product-grid" data-pos-products>
      {product_tiles}
    </div>
    <div class="pos-product-empty" data-pos-product-empty hidden>No products match this filter.</div>
    <div class="pos-browser-overlay" data-pos-browser-overlay hidden></div>
    <aside class="pos-browser-drawer" data-pos-drawer="category" hidden>
      <div class="pos-browser-drawer-head">
        <div><h3>Category</h3><span>{len(categories) + 1} Category</span></div>
        <button type="button" data-pos-close-drawer aria-label="Close category drawer">x</button>
      </div>
      <div class="pos-drawer-grid" data-pos-category-filters>
        <button type="button" class="pos-drawer-tile active" data-pos-category=""><span>All Categories</span></button>
        {category_filters}
      </div>
    </aside>
    <aside class="pos-browser-drawer" data-pos-drawer="brand" hidden>
      <div class="pos-browser-drawer-head">
        <div><h3>Brands</h3><span>{len(brands) + 1} Brands</span></div>
        <button type="button" data-pos-close-drawer aria-label="Close brands drawer">x</button>
      </div>
      <div class="pos-drawer-grid" data-pos-brand-filters>
        <button type="button" class="pos-drawer-tile active" data-pos-brand=""><span>All Brands</span></button>
        {brand_filters}
      </div>
    </aside>
  </section>
  <footer class="pos-action-bar">
    <button type="button" class="pos-action pos-action-cancel pos-action-wide" data-pos-clear><span class="pos-action-icon">{svg_icon("cancel")}</span><span>Cancel</span></button>
    <span class="pos-action-divider" aria-hidden="true"></span>
    <button type="button" class="pos-action pos-action-compact pos-action-draft" data-pos-document="draft"><span class="pos-action-icon">{svg_icon("draft")}</span><span>Draft</span></button>
    <button type="button" class="pos-action pos-action-compact pos-action-quote" data-pos-document="quotation"><span class="pos-action-icon">{svg_icon("quotation")}</span><span>Quotation</span></button>
    <button type="button" class="pos-action pos-action-compact pos-action-suspend" data-pos-document="suspended"><span class="pos-action-icon">{svg_icon("pause")}</span><span>Suspend</span></button>
    <button type="button" class="pos-action pos-action-compact pos-action-credit" data-pos-credit><span class="pos-action-icon">{svg_icon("check")}</span><span>Credit Sale</span></button>
    <button type="button" class="pos-action pos-action-compact pos-action-pay" data-pos-payment="card"><span class="pos-action-icon">{svg_icon("card")}</span><span>Card</span></button>
    <button type="button" class="pos-action pos-action-complete pos-action-wide" data-pos-multiple-pay><span class="pos-action-icon">{svg_icon("multi_pay")}</span><span>Multiple Pay</span></button>
    <button type="button" class="pos-action pos-action-cash pos-action-wide" data-pos-payment="cash"><span class="pos-action-icon">{svg_icon("cash")}</span><span>Cash</span></button>
  </footer>
</form>"""


def render_pos_product_tile(row) -> str:
    stock = float(row["available_stock"] or 0)
    disabled = " disabled" if stock <= 0 else ""
    stock_badge = "danger" if stock <= 0 or product_is_low_stock(row) else "ok"
    searchable = " ".join(str(row[key] or "") for key in ("name", "sku", "barcode", "category_name", "brand_name")).lower()
    selling_price = float(row["selling_price"] or 0)
    offer_discount = product_offer_discount(row)
    offer_price = product_offer_price(row)
    price_html = (
        f'<b>{offer_price:.2f}</b><small class="pos-offer-note"><del>{selling_price:.2f}</del> Save {offer_discount:.2f}</small>'
        if offer_discount > 0
        else f'<b>{selling_price:.2f}</b>'
    )
    return f"""
<button type="button" class="pos-product-tile"{disabled}
  data-pos-product
  data-id="{row["id"]}"
  data-name="{html.escape(row["name"], quote=True)}"
  data-sku="{html.escape(row["sku"], quote=True)}"
  data-barcode="{html.escape(row["barcode"] or "", quote=True)}"
  data-price="{selling_price:.2f}"
  data-offer-discount="{offer_discount:.2f}"
  data-stock="{stock:.2f}"
  data-category="{html.escape(row["category_name"] or "", quote=True)}"
  data-brand="{html.escape(row["brand_name"] or "", quote=True)}"
  data-search="{html.escape(searchable, quote=True)}">
  <span class="pos-product-image">{product_image_markup(row, "product-card-thumb")}</span>
  <span class="pos-product-info">
    <strong>{html.escape(row["name"])}</strong>
    <small>{html.escape(row["sku"])} / {html.escape(row["barcode"] or "No barcode")}</small>
  </span>
  <span class="pos-product-foot">
    <span class="pos-price-stack">{price_html}</span>
    <em class="badge {stock_badge}">Stock {stock:.2f}</em>
  </span>
</button>"""


def render_sales_return(message: str = "", error: str = "") -> str:
    repository = SalesReturnRepository()
    returnable_items = repository.returnable_sale_items()
    returns = repository.list_returns()
    today = __import__("datetime").date.today().isoformat()
    invoice_records: dict[int, dict[str, str]] = {}
    for row in returnable_items:
        invoice_records[int(row["sale_id"])] = {
            "invoice_no": row["invoice_no"],
            "sale_date": row["sale_date"],
            "customer_name": row["customer_name"],
        }
    invoice_options = '<option value="">Select invoice</option>' + "".join(
        f'<option value="{sale_id}" data-invoice="{html.escape(record["invoice_no"], quote=True)}" '
        f'data-date="{html.escape(record["sale_date"], quote=True)}" '
        f'data-customer="{html.escape(record["customer_name"], quote=True)}">'
        f'{html.escape(record["invoice_no"])} | '
        f'{html.escape(record["sale_date"])} | {html.escape(record["customer_name"])}</option>'
        for sale_id, record in invoice_records.items()
    )
    item_rows = "".join(
        f"""
        <tr data-return-item data-sale-id="{row["sale_id"]}" hidden>
          <td><strong>{html.escape(row["product_name"])}</strong><small>{html.escape(row["product_sku"])} | {html.escape(row["product_barcode"] or "No barcode")}</small></td>
          <td class="numeric">{row["sold_quantity"]:.2f}</td>
          <td class="numeric">{row["returned_quantity"]:.2f}</td>
          <td class="numeric"><strong>{row["remaining_quantity"]:.2f}</strong></td>
          <td class="numeric">{row["unit_price"]:.2f}</td>
          <td><button type="button" class="secondary-button" data-return-select
            data-sale-id="{row["sale_id"]}" data-product-id="{row["product_id"]}"
            data-product-name="{html.escape(row["product_name"], quote=True)}"
            data-sku="{html.escape(row["product_sku"], quote=True)}"
            data-available="{row["remaining_quantity"]:.2f}" data-price="{row["unit_price"]:.2f}">Return</button></td>
        </tr>
        """
        for row in returnable_items
    ) or '<tr><td colspan="6" class="empty">No returnable sold products found.</td></tr>'
    history_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["return_date"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["customer_name"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td class="numeric">{row["refund_amount"]:.2f}</td>
          <td>{html.escape(row["refund_method"].replace("_", " ").title())}</td>
          <td>{html.escape(row["reason"].replace("_", " ").title())}</td>
          <td>{"Yes" if row["return_to_stock"] else "No"}</td>
          <td><a class="table-link" href="/sales-return/receipt?id={row["id"]}">Receipt</a></td>
        </tr>
        """
        for row in returns
    )
    if not history_rows:
        history_rows = '<tr><td colspan="10" class="empty">No sales returns added yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Sales Return</h2>
    <p>Find the invoice, select an item, choose the refund method, and control whether stock is restored.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=Sales%20History">Sales History</a>
</div>
{render_notice(message, error)}
<section class="sales-return-workspace" data-sales-return>
  <article class="panel return-invoice-panel">
    <div class="return-step-head"><span>01</span><div><h3>Find Sale</h3><p>Select the original invoice to load its returnable products.</p></div></div>
    <label class="field return-invoice-search">
      <span>Invoice / Customer / Date</span>
      <select data-return-invoice>{invoice_options}</select>
    </label>
    <div class="return-sale-summary" data-return-sale-summary>
      <div><span>Invoice</span><strong>-</strong></div>
      <div><span>Customer</span><strong>-</strong></div>
      <div><span>Sale Date</span><strong>-</strong></div>
    </div>
    <div class="return-items-table">
      <table>
        <thead><tr><th>Product</th><th>Sold</th><th>Returned</th><th>Available</th><th>Price</th><th></th></tr></thead>
        <tbody data-return-items>{item_rows}</tbody>
      </table>
      <div class="return-empty-state" data-return-empty>Select an invoice to view products.</div>
    </div>
  </article>
  <article class="panel return-editor-panel">
    <div class="return-step-head"><span>02</span><div><h3>Return Details</h3><p>Review quantity, item condition, stock, and refund.</p></div></div>
    <form method="post" action="/sales-return/create" data-return-form>
      <input type="hidden" name="sale_id" data-return-sale-id>
      <input type="hidden" name="product_id" data-return-product-id>
      <div class="return-selected-product" data-return-selected>
        <span>No product selected</span><strong>Select a product from the invoice.</strong>
      </div>
      <div class="form-grid two-col">
        {date_input("Return Date", "return_date", today)}
        <label class="field"><span>Return Quantity</span><input name="quantity" type="number" min="0.01" step="0.01" value="1" data-return-quantity required></label>
        <label class="field"><span>Reason</span><select name="reason" required>
          <option value="damaged">Damaged</option><option value="wrong_item">Wrong Item</option>
          <option value="changed_mind">Customer Changed Mind</option><option value="expired">Expired</option>
          <option value="defective">Defective</option><option value="other">Other</option>
        </select></label>
        <label class="field"><span>Item Condition</span><select name="item_condition" data-return-condition>
          <option value="resellable">Resellable</option><option value="damaged">Damaged</option>
          <option value="opened">Opened / Used</option><option value="expired">Expired</option>
        </select></label>
        <label class="field"><span>Refund Method</span><select name="refund_method" data-return-refund-method>
          <option value="cash">Cash Refund</option><option value="card">Card Refund</option>
          <option value="bank_transfer">Bank Transfer</option><option value="store_credit">Store Credit</option>
          <option value="exchange">Exchange</option><option value="no_refund">No Refund</option>
        </select></label>
        <label class="field"><span>Refund Amount</span><input name="refund_amount" type="number" min="0" step="0.01" value="0.00" data-return-refund required></label>
      </div>
      <label class="return-stock-toggle">
        <input type="checkbox" name="return_to_stock" value="1" checked data-return-stock>
        <span><strong>Return to stock</strong><small>Enable only when the item can be sold or reused.</small></span>
      </label>
      <label class="field wide-field"><span>Internal Note</span><textarea name="note" rows="3" placeholder="Optional return notes"></textarea></label>
      <div class="return-refund-total"><span>Refund Total</span><strong data-return-refund-total>0.00</strong></div>
      <button type="submit" class="return-confirm-button">Confirm Return</button>
    </form>
  </article>
</section>
<article class="panel table-panel return-history-panel">
  <div class="return-step-head"><span>03</span><div><h3>Return History</h3><p>Refund, reason, and stock outcome for completed returns.</p></div></div>
  <div class="return-history-scroll">
    <table>
      <thead>
        <tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Product</th><th>Qty</th><th>Refund</th><th>Method</th><th>Reason</th><th>Stock</th><th></th></tr>
      </thead>
      <tbody>{history_rows}</tbody>
    </table>
  </div>
</article>"""


def render_sales_document(title: str, status: str, hint: str, message: str = "", error: str = "") -> str:
    repository = SaleRepository()
    documents = repository.list_sales_by_status(status)
    customers = ContactRepository().customer_options()
    products = ProductRepository().product_options()
    today = __import__("datetime").date.today().isoformat()
    prefix = {
        "draft": "DRAFT",
        "quotation": "QUOTE",
        "suspended": "SUSP",
        "sales_order": "SO",
    }[status]
    default_no = prefix + "-" + __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")

    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["sale_date"])}</td>
          <td>{html.escape(row["customer_name"] or "")}</td>
          <td class="numeric">{row["total"]:.2f}</td>
          <td>{html.escape(row["payment_status"].title())}</td>
          <td>{html.escape(row["sale_status"].replace('_', ' ').title())}</td>
          <td><a class="table-link" href="/dashboard?page=POS&source_sale_id={row["id"]}">Open In POS</a></td>
        </tr>
        """
        for row in documents
    )
    if not rows:
        rows = '<tr><td colspan="7" class="empty">No records found.</td></tr>'

    return f"""
<div class="page-title">
  <h2>{html.escape(title)}</h2>
  <p>{html.escape(hint)}</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add {html.escape(title[:-1] if title.endswith('s') else title)}</h3>
    <form method="post" action="/sales-document/create">
      <input type="hidden" name="sale_status" value="{html.escape(status)}">
      <div class="form-grid two-col">
        {select_input("Customer", "customer_id", customers)}
        {preset_text_input("Document No", "invoice_no", default_no, required=True)}
        {date_input("Date", "sale_date", today)}
        {select_input("Product", "product_id", products)}
        {number_input("Quantity", "quantity", "1")}
        {number_input("Unit Price", "unit_price", "0.00")}
        {number_input("Discount", "discount", "0.00")}
        {number_input("Tax", "tax", "0.00")}
      </div>
      <button type="submit">Save</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>List</h3>
    <table>
      <thead><tr><th>No</th><th>Date</th><th>Customer</th><th>Total</th><th>Payment</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_shipments(message: str = "", error: str = "") -> str:
    repository = ShipmentRepository()
    shipments = repository.list_shipments()
    sales = repository.sale_options()
    today = __import__("datetime").date.today().isoformat()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["shipment_date"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["courier"] or "")}</td>
          <td>{html.escape(row["tracking_no"] or "")}</td>
          <td>{html.escape(row["status"].replace('_', ' ').title())}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in shipments
    )
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No shipments added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Shipments</h2>
  <p>Track delivery details for final sales.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Shipment</h3>
    <form method="post" action="/shipments/create">
      <div class="form-grid two-col">
        {select_input("Sale", "sale_id", sales)}
        {date_input("Shipment Date", "shipment_date", today)}
        {text_input("Courier", "courier")}
        {text_input("Tracking No", "tracking_no")}
        <label class="field">
          <span>Status</span>
          <select name="status">
            <option value="pending">Pending</option>
            <option value="packed">Packed</option>
            <option value="shipped">Shipped</option>
            <option value="delivered">Delivered</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
      </div>
      <label class="field wide-field">
        <span>Note</span>
        <textarea name="note" rows="4"></textarea>
      </label>
      <button type="submit">Save Shipment</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Shipment List</h3>
    <table>
      <thead><tr><th>Date</th><th>Invoice</th><th>Courier</th><th>Tracking</th><th>Status</th><th>Note</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_cash_register(user_id_value: str | None, message: str = "", error: str = "") -> str:
    repository = CashRegisterRepository()
    user_id = int(user_id_value or "0")
    open_register = repository.current_open_register(user_id) if user_id else None
    registers = repository.list_registers()
    locations = [row for row in SettingsRepository().list_locations() if row["is_active"]]
    location_options = "".join(
        f'<option value="{row["id"]}">{html.escape(row["name"])}</option>' for row in locations
    )

    if open_register is None:
        current_panel = f"""
<section class="register-open-state">
  <article class="panel register-open-card">
    <div class="register-state-icon">CR</div>
    <div>
      <span class="register-kicker">Start Shift</span>
      <h3>Open Cash Register</h3>
      <p>Count the drawer cash before accepting cash transactions.</p>
    </div>
    <form method="post" action="/cash-register/open" class="register-open-form">
      <label class="field"><span>Location</span><select name="location_id" required>{location_options}</select></label>
      {number_input("Opening Cash", "opening_cash", "0.00")}
      <button type="submit">Open Register</button>
    </form>
  </article>
</section>"""
    else:
        summary = repository.register_summary(open_register)
        transactions = repository.register_transactions(open_register)
        transaction_rows = "".join(
            f"""
            <tr>
              <td>{html.escape(row["created_at"])}</td>
              <td>{cash_register_reference_label(row["reference_type"])}</td>
              <td>{payment_type_badge(row["payment_type"])}</td>
              <td>{html.escape(row["note"] or "")}</td>
              <td class="numeric {'positive' if row["payment_type"] == 'in' else 'negative'}">
                {'+' if row["payment_type"] == 'in' else '-'}{row["amount"]:.2f}
              </td>
            </tr>
            """
            for row in transactions
        ) or '<tr><td colspan="5" class="empty">No cash transactions in this shift.</td></tr>'
        current_panel = f"""
<section class="register-live">
  <header class="register-live-head">
    <div>
      <span class="register-status-dot">Open</span>
      <h3>Register #{open_register["id"]}</h3>
      <p>{html.escape(open_register["user_name"])} | {html.escape(open_register["location_name"] or "")} | Opened {html.escape(open_register["opened_at"])}</p>
    </div>
    <a class="secondary-link" href="/cash-register/receipt?id={open_register["id"]}">Shift Report</a>
  </header>
  <div class="register-metrics">
    {register_metric("Opening Cash", open_register["opening_cash"], "Drawer start")}
    {register_metric("Cash Sales", summary["cash_sales"], "Cash sale collections", "positive")}
    {register_metric("Other Cash In", summary["other_cash_in"], "Deposits and adjustments", "positive")}
    {register_metric("Cash Out", summary["cash_out"], "Purchases, expenses, refunds", "negative")}
    {register_metric("Expected Cash", summary["expected_cash"], f'{int(summary["transaction_count"])} transactions', "primary")}
  </div>
  <div class="register-main-grid">
    <article class="panel register-ledger">
      <div class="register-section-head"><div><h3>Shift Transactions</h3><p>Cash method transactions only. Card and bank payments are excluded.</p></div></div>
      <div class="register-ledger-scroll">
        <table><thead><tr><th>Time</th><th>Source</th><th>Direction</th><th>Note</th><th>Amount</th></tr></thead><tbody>{transaction_rows}</tbody></table>
      </div>
    </article>
    <aside class="register-side-stack">
      <article class="panel">
        <div class="register-section-head"><div><h3>Manual Movement</h3><p>Record drawer cash added or removed.</p></div></div>
        <form method="post" action="/cash-register/movement" class="register-movement-form">
          <input type="hidden" name="register_id" value="{open_register["id"]}">
          <label class="field"><span>Type</span><select name="movement_type"><option value="in">Cash In</option><option value="out">Cash Out</option></select></label>
          {number_input("Amount", "amount", "0.00")}
          <label class="field"><span>Reason</span><input name="reason" placeholder="Petty cash, float, bank deposit..." required></label>
          <button type="submit">Save Movement</button>
        </form>
      </article>
      <article class="panel register-close-card">
        <div class="register-section-head"><div><h3>Close Shift</h3><p>Count actual drawer cash and review the difference.</p></div></div>
        <form method="post" action="/cash-register/close" class="close-register-form" data-register-close>
          <input type="hidden" name="register_id" value="{open_register["id"]}">
          <input type="hidden" value="{summary["expected_cash"]:.2f}" data-register-expected>
          <div class="register-denominations">
            <div class="register-denomination-head"><span>Note</span><span>Count</span><span>Total</span></div>
            {''.join(register_denomination_row(value) for value in CASH_DENOMINATIONS)}
            <label class="register-coins-row">
              <span>Coins Total</span>
              <input type="number" name="coins_total" min="0" step="0.01" value="0.00" data-denomination-coins>
              <strong data-denomination-coins-total>0.00</strong>
            </label>
          </div>
          <div class="register-counted-total"><span>Counted Cash</span><strong data-register-counted>0.00</strong></div>
          <div class="register-difference"><span>Difference</span><strong data-register-difference>0.00</strong></div>
          <label class="field"><span>Closing Note</span><textarea name="closing_note" rows="3" placeholder="Explain shortage, excess, or handover note"></textarea></label>
          <label class="register-approval"><input type="checkbox" name="manager_approved" value="1"><span>Manager reviewed and approved</span></label>
          <button type="submit" class="register-close-button">Close Register</button>
        </form>
      </article>
    </aside>
  </div>
</section>"""

    rows = ""
    for register in registers:
        summary = repository.register_summary(register)
        approval_action = ""
        if register["status"] == "closed" and (register["approval_status"] or "pending") == "pending":
            approval_action = f"""
            <form method="post" action="/cash-register/approve" class="table-action">
              <input type="hidden" name="register_id" value="{register["id"]}">
              <button type="submit">Approve</button>
            </form>"""
        rows += f"""
        <tr>
          <td>{html.escape(register["opened_at"])}</td>
          <td>{html.escape(register["closed_at"] or "")}</td>
          <td>{html.escape(register["user_name"])}</td>
          <td>{html.escape(register["location_name"] or "")}</td>
          <td class="numeric">{register["opening_cash"]:.2f}</td>
          <td class="numeric">{summary["cash_in"]:.2f}</td>
          <td class="numeric">{summary["cash_out"]:.2f}</td>
          <td class="numeric">{summary["expected_cash"]:.2f}</td>
          <td class="numeric">{(register["closing_cash"] or 0):.2f}</td>
          <td class="numeric {'positive' if summary["difference"] >= 0 else 'negative'}">{summary["difference"]:.2f}</td>
          <td>{html.escape((register["approval_status"] or "pending").title())}</td>
          <td>{html.escape(register["status"].title())}</td>
          <td><div class="inline-actions"><a class="table-link" href="/cash-register/receipt?id={register["id"]}">Z Report</a>{approval_action}</div></td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="13" class="empty">No cash register sessions found.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div><h2>Cash Register</h2><p>Manage cashier shifts, drawer cash, cash movements, and closing reconciliation.</p></div>
  <a class="secondary-link" href="/dashboard?page=Cash%20Register%20Report">Cash Report</a>
</div>
{render_notice(message, error)}
{current_panel}
<article class="panel table-panel register-history">
  <div class="register-section-head"><div><h3>Shift History</h3><p>Opening, expected, counted, difference, approval, and printable Z report.</p></div></div>
  <table>
    <thead>
      <tr>
        <th>Opened</th>
        <th>Closed</th>
        <th>Cashier</th>
        <th>Location</th>
        <th>Opening</th>
        <th>Cash In</th>
        <th>Cash Out</th>
        <th>Expected</th>
        <th>Closing</th>
        <th>Difference</th>
        <th>Approval</th>
        <th>Status</th>
        <th>Report</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def register_metric(label: str, amount: float, hint: str, tone: str = "") -> str:
    return f"""
<article class="register-metric {html.escape(tone)}">
  <span>{html.escape(label)}</span>
  <strong>{float(amount):.2f}</strong>
  <small>{html.escape(hint)}</small>
</article>"""


def register_denomination_row(value: int) -> str:
    return f"""
<label class="register-denomination-row">
  <span>Rs. {value}</span>
  <input type="number" name="denomination_{value}" min="0" step="1" value="0"
    data-denomination-count data-denomination-value="{value}">
  <strong data-denomination-total>0.00</strong>
</label>"""


def cash_register_reference_label(reference_type: str) -> str:
    labels = {
        "sale": "Cash Sale",
        "deposit": "Deposit",
        "customer_payment": "Customer Payment",
        "purchase": "Purchase",
        "expense": "Expense",
        "sale_return": "Sales Return",
        "purchase_return": "Purchase Return",
        "expense_refund": "Expense Refund",
        "cash_register_adjustment": "Manual Movement",
    }
    return html.escape(labels.get(reference_type, reference_type.replace("_", " ").title()))


def expense_filters_from_query(query: dict[str, list[str]]) -> dict[str, str]:
    return {
        key: query.get(key, [""])[0]
        for key in (
            "search",
            "date_from",
            "date_to",
            "expense_type",
            "status",
            "category_id",
            "account_id",
            "location_id",
            "sort",
            "direction",
        )
    }


def expense_type_label(expense_type: str) -> str:
    return {"expense": "Expense", "in": "Cash In", "out": "Cash Out"}.get(
        expense_type, expense_type.title()
    )


def render_expense_list(
    query: dict[str, list[str]] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    query = query or {}
    repository = ExpenseRepository()
    filters = expense_filters_from_query(query)
    expenses = repository.list_expenses(filters)
    summary = repository.summary(filters)
    categories = repository.category_options()
    accounts = repository.account_options()
    locations = repository.location_options()

    def sort_link(label: str, key: str) -> str:
        next_direction = "asc"
        marker = ""
        if filters["sort"] == key:
            next_direction = "desc" if filters["direction"] == "asc" else "asc"
            marker = " ↑" if filters["direction"] == "asc" else " ↓"
        params = {key_: value for key_, value in filters.items() if value}
        params.update({"page": "List Expenses", "sort": key, "direction": next_direction})
        return f'<a class="sheet-sort" href="/dashboard?{urlencode(params)}">{label}{marker}</a>'

    rows = "".join(
        f"""
        <tr>
          <td class="sheet-select"><input type="checkbox" aria-label="Select transaction"></td>
          <td>{html.escape(row["expense_date"])}</td>
          <td>{html.escape(row["expense_time"] or "")}</td>
          <td><strong>{html.escape(row["reference_no"] or f'#{row["id"]}')}</strong></td>
          <td>{expense_type_badge(row["expense_type"])}</td>
          <td>{html.escape(row["category_name"] or "Uncategorized")}</td>
          <td>{html.escape(row["account_name"] or "")}</td>
          <td>{html.escape(row["party_name"] or "")}</td>
          <td>{html.escape(str(row["payment_method"]).replace("_", " ").title())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td class="numeric">{float(row["tax_amount"] or 0):.2f}</td>
          <td>{transaction_status_badge(row["status"])}</td>
          <td>{html.escape(row["location_name"] or "")}</td>
          <td class="clip-cell" title="{html.escape(row["note"] or "", quote=True)}">{html.escape(row["note"] or "")}</td>
          <td>{'<a class="table-link" href="/expenses/attachment?id=' + str(row["id"]) + '">Open</a>' if row["attachment_data"] else ""}</td>
          <td class="expense-row-actions">
            <form method="post" action="/expenses/duplicate">
              <input type="hidden" name="expense_id" value="{row["id"]}">
              <button type="submit" title="Duplicate">Copy</button>
            </form>
            {expense_status_actions(row)}
            <button type="button" onclick="window.print()" title="Print list">Print</button>
          </td>
        </tr>
        """
        for row in expenses
    )
    if not rows:
        rows = '<tr><td colspan="16" class="empty">No transactions match the selected filters.</td></tr>'

    filter_params = {key: value for key, value in filters.items() if value}
    export_url = "/expenses/export.csv"
    if filter_params:
        export_url += "?" + urlencode(filter_params)

    return f"""
<div class="page-title action-title expense-list-title">
  <div>
    <h2>Expense Transactions</h2>
    <p>Spreadsheet view for expenses and cash movements.</p>
  </div>
  <div class="quick-actions">
    <a href="{export_url}">Export Excel CSV</a>
    <button type="button" onclick="window.print()">Print / PDF</button>
    <a class="primary-link" href="/dashboard?page=Add%20Expense">Add Transaction</a>
  </div>
</div>
{render_notice(message, error)}
{render_money_cards([
    ("Expenses", summary["expense"]),
    ("Cash In", summary["cash_in"]),
    ("Cash Out", summary["cash_out"]),
    ("Net Cash", summary["net_cash"]),
])}
<article class="panel expense-filter-panel">
  <form method="get" action="/dashboard" class="expense-filter-grid">
    <input type="hidden" name="page" value="List Expenses">
    {preset_text_input("Search", "search", filters["search"])}
    {date_input_optional("From", "date_from", filters["date_from"])}
    {date_input_optional("To", "date_to", filters["date_to"])}
    {simple_select("Type", "expense_type", [
        ("", "All Types"), ("expense", "Expense"), ("in", "Cash In"), ("out", "Cash Out")
    ], filters["expense_type"])}
    {simple_select("Status", "status", [
        ("", "All Statuses"), ("draft", "Draft"), ("pending", "Pending"),
        ("approved", "Approved"), ("paid", "Paid"), ("cancelled", "Cancelled")
    ], filters["status"])}
    {select_input("Category", "category_id", categories, int(filters["category_id"]) if filters["category_id"].isdigit() else None)}
    {select_input("Account", "account_id", accounts, int(filters["account_id"]) if filters["account_id"].isdigit() else None)}
    {select_input("Location", "location_id", locations, int(filters["location_id"]) if filters["location_id"].isdigit() else None)}
    <div class="expense-filter-actions">
      <button type="submit">Apply</button>
      <a class="secondary-link" href="/dashboard?page=List%20Expenses">Clear</a>
    </div>
  </form>
</article>
<article class="panel table-panel expense-sheet-panel">
  <div class="sheet-meta"><strong>{len(expenses)} rows</strong><span>Click column headings to sort</span></div>
  <div class="expense-sheet-scroll">
  <table class="expense-sheet">
    <thead>
      <tr>
        <th class="sheet-select"><input type="checkbox" aria-label="Select all"></th>
        <th>{sort_link("Date", "date")}</th>
        <th>Time</th>
        <th>Reference</th>
        <th>{sort_link("Type", "type")}</th>
        <th>{sort_link("Category", "category")}</th>
        <th>{sort_link("Account", "account")}</th>
        <th>Paid To / From</th>
        <th>Method</th>
        <th>{sort_link("Amount", "amount")}</th>
        <th>Tax</th>
        <th>{sort_link("Status", "status")}</th>
        <th>Location</th>
        <th>Description</th>
        <th>File</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</article>"""


def render_add_expense(message: str = "", error: str = "") -> str:
    repository = ExpenseRepository()
    categories = repository.category_options()
    accounts = repository.account_options()
    locations = repository.location_options()
    parties = repository.party_options()
    settings = repository.get_settings()
    payment_methods = SettingsRepository().list_payment_methods()
    now = __import__("datetime").datetime.now()
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    party_options = "".join(
        f'<option value="{html.escape(name, quote=True)}"></option>' for name in parties
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Add Transaction</h2>
    <p>Record an expense, cash receipt, or cash withdrawal with complete supporting details.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=List%20Expenses">List Expenses</a>
</div>
{render_notice(message, error)}
<article class="panel expense-entry-panel">
  <form class="product-form" method="post" action="/expenses/create" data-expense-form>
    <section class="expense-form-section">
      <h3>Transaction</h3>
      <div class="expense-type-control" role="group" aria-label="Transaction type">
        <label><input type="radio" name="expense_type" value="expense" checked><span>Expense</span></label>
        <label><input type="radio" name="expense_type" value="in"><span>Cash In</span></label>
        <label><input type="radio" name="expense_type" value="out"><span>Cash Out</span></label>
      </div>
    </section>
    <section class="expense-form-section">
      <h3>Basic Details</h3>
      <div class="form-grid three-col">
      {date_input("Expense Date", "expense_date", today)}
      {time_input("Time", "expense_time", current_time)}
      {preset_text_input("Reference (auto if blank)", "reference_no", "")}
      {select_input("Category", "category_id", categories)}
      {select_input("Payment Account", "account_id", accounts, int(settings["default_account_id"] or 1))}
      {select_input("Business Location", "location_id", locations, int(settings["default_location_id"] or 1))}
      {number_input("Amount", "amount", "0.00")}
      {payment_method_select("Payment Method", "payment_method", payment_methods)}
      <label class="field">
        <span data-party-label>Paid To</span>
        <input name="party_name" list="expense-parties" placeholder="Person, supplier, owner, or customer">
        <datalist id="expense-parties">{party_options}</datalist>
      </label>
      </div>
    </section>
    <section class="expense-form-section" data-expense-only>
      <h3>Tax & Approval</h3>
      <div class="form-grid three-col">
        {number_input("Tax Rate %", "tax_rate", "0.00")}
        {simple_select("Tax Mode", "tax_mode", [
            ("exclusive", "Tax Exclusive"), ("inclusive", "Tax Inclusive")
        ], "exclusive")}
        {simple_select("Status", "status", [
            ("paid", "Paid"), ("draft", "Draft"), ("pending", "Pending Approval"),
            ("approved", "Approved")
        ], "paid")}
        {simple_select("Recurring", "recurrence", [
            ("once", "One Time"), ("daily", "Daily"), ("weekly", "Weekly"),
            ("monthly", "Monthly"), ("yearly", "Yearly")
        ], "once")}
      </div>
    </section>
    <section class="expense-form-section">
      <h3>Evidence & Description</h3>
      <div class="expense-attachment" data-expense-attachment>
        <label class="field">
          <span>Receipt / Invoice / Image / PDF</span>
          <input type="file" accept="image/*,.pdf,application/pdf" data-expense-file>
        </label>
        <input type="hidden" name="attachment_name" data-expense-file-name>
        <input type="hidden" name="attachment_data" data-expense-file-data>
        <small data-expense-file-status>No file selected. Maximum 2 MB.</small>
      </div>
      <label class="field wide-field">
        <span>Description / Note</span>
        <textarea name="note" rows="4" required placeholder="Explain the business purpose or reason for this cash movement"></textarea>
      </label>
    </section>
    <div class="form-actions">
      <button type="submit">Save Transaction</button>
      <a href="/dashboard?page=List%20Expenses">Cancel</a>
    </div>
  </form>
</article>"""


def render_expense_categories(
    message: str = "",
    error: str = "",
    subcategories_only: bool = False,
) -> str:
    repository = ExpenseRepository()
    categories = repository.list_categories()
    parent_options = [
        LookupItem(id=row["id"], name=row["name"])
        for row in categories
        if row["parent_id"] is None and row["is_active"]
    ]
    visible_categories = [
        row for row in categories if not subcategories_only or row["parent_id"] is not None
    ]
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["parent_name"] or "")}</td>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(expense_type_label(row["transaction_type"]) if row["transaction_type"] != "all" else "All")}</td>
          <td class="numeric">{row["monthly_budget"]:.2f}</td>
          <td>{"Required" if row["requires_attachment"] else "Optional"}</td>
          <td>{"Active" if row["is_active"] else "Inactive"}</td>
        </tr>
        """
        for row in visible_categories
    )
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No expense categories added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>{"Expense Subcategories" if subcategories_only else "Expense Categories"}</h2>
  <p>{"Create and review child categories under each main expense category." if subcategories_only else "Create parent categories, subcategories, budgets, and transaction-specific choices."}</p>
</div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel">
    <h3>Add Category</h3>
    <form method="post" action="/expense-categories/create">
      <div class="form-grid two-col">
        {text_input("Name", "name", required=True)}
        {select_input("Parent Category", "parent_id", parent_options)}
        {simple_select("Available For", "transaction_type", [
            ("all", "All Types"), ("expense", "Expense"), ("in", "Cash In"), ("out", "Cash Out")
        ], "all")}
        {number_input("Monthly Budget", "monthly_budget", "0.00")}
        <label class="field checkbox-field">
          <input type="checkbox" name="requires_attachment" value="1">
          <span>Require attachment</span>
        </label>
      </div>
      <button type="submit">Save Category</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Current Categories</h3>
    <table>
      <thead><tr><th>Parent</th><th>Category</th><th>Type</th><th>Budget</th><th>Attachment</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_expense_setup() -> str:
    return render_shortcut_hub(
        "Expense Setup",
        "Keep daily expense entry simple. Use these setup tools when transaction rules or supporting records need changes.",
        [
            ("Add Expense", "Create an expense, cash-in, or cash-out transaction"),
            ("Expense Categories", "Main categories for expenses and cash movements"),
            ("Expense Subcategories", "Child categories grouped under a main category"),
            ("Payment Accounts", "Cash register, petty cash, bank, card, and wallet accounts"),
            ("Payment Methods", "Cash, card, transfer, cheque, and mobile payment methods"),
            ("Expense Payees", "Suppliers, employees, owners, customers, and other parties"),
            ("Tax Rates", "Tax rates available for expense transactions"),
            ("Expense Budgets", "Monthly category budgets and spending limits"),
            ("Expense Controls", "Defaults, references, approvals, and attachment rules"),
            ("Recurring Expenses", "Daily, weekly, monthly, and yearly transactions"),
            ("Expense Refund", "Record money returned against an expense"),
            ("List Expenses", "Open the spreadsheet transaction register"),
        ],
    )


def render_expense_controls(message: str = "", error: str = "") -> str:
    repository = ExpenseRepository()
    settings = repository.get_settings()
    accounts = repository.account_options()
    locations = repository.location_options()
    categories = repository.list_categories()
    methods = SettingsRepository().list_payment_methods()
    budget_total = sum(float(row["monthly_budget"]) for row in categories)
    active_methods = sum(1 for row in methods if row["is_active"])
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Expense Controls</h2>
    <p>Transaction defaults, reference numbering, approvals, and evidence rules.</p>
  </div>
  <div class="quick-actions">
    <a href="/dashboard?page=Expense%20Setup">Expense Setup</a>
    <a href="/dashboard?page=Expense%20Categories">Categories</a>
  </div>
</div>
{render_notice(message, error)}
{render_money_cards([
    ("Categories", float(len(categories))),
    ("Monthly Budgets", budget_total),
    ("Payment Accounts", float(len(accounts))),
    ("Payment Methods", float(active_methods)),
])}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Transaction Defaults</h3>
    <form method="post" action="/expense-settings/update">
      <div class="form-grid two-col">
        {select_input("Default Account", "default_account_id", accounts, settings["default_account_id"])}
        {select_input("Default Location", "default_location_id", locations, settings["default_location_id"])}
        {preset_text_input("Reference Prefix", "reference_prefix", settings["reference_prefix"], required=True)}
        {number_input("Approval Required Above", "approval_limit", str(settings["approval_limit"]))}
        {number_input("Attachment Required Above", "require_attachment_over", str(settings["require_attachment_over"]))}
      </div>
      <button type="submit">Save Expense Settings</button>
    </form>
  </article>
  <article class="panel">
    <h3>Control Rules</h3>
    <div class="setup-rule-list">
      <div><strong>Approval</strong><span>Transactions above {settings["approval_limit"]:.2f} move to Pending.</span></div>
      <div><strong>Attachments</strong><span>Evidence required above {settings["require_attachment_over"]:.2f}.</span></div>
      <div><strong>Expense</strong><span>Affects profit/loss and reduces the selected account.</span></div>
      <div><strong>Cash In / Out</strong><span>Only changes the selected account balance.</span></div>
      <div><strong>Refund</strong><span>Reduces the linked expense and returns money to its account.</span></div>
    </div>
  </article>
</div>"""


def render_expense_payees() -> str:
    names = ExpenseRepository().party_options()
    rows = "".join(
        f"<tr><td>{index}</td><td>{html.escape(name)}</td><td>Active contact</td></tr>"
        for index, name in enumerate(names, start=1)
    ) or '<tr><td colspan="3" class="empty">No payees or payers found.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Expense Payees</h2>
    <p>Contacts available in the Paid To and Received From fields.</p>
  </div>
  <div class="quick-actions">
    <a href="/dashboard?page=Expense%20Setup">Expense Setup</a>
    <a class="primary-link" href="/dashboard?page=Customers">Manage Contacts</a>
  </div>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>#</th><th>Payee / Payer</th><th>Source</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_expense_budgets() -> str:
    categories = ExpenseRepository().list_categories()
    budget_rows = [row for row in categories if float(row["monthly_budget"]) > 0]
    total = sum(float(row["monthly_budget"]) for row in budget_rows)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["parent_name"] or "")}</td>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(expense_type_label(row["transaction_type"]) if row["transaction_type"] != "all" else "All Types")}</td>
          <td class="numeric">{row["monthly_budget"]:.2f}</td>
        </tr>
        """
        for row in budget_rows
    ) or '<tr><td colspan="4" class="empty">No category budgets configured.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Expense Budgets</h2>
    <p>Monthly limits configured against expense categories.</p>
  </div>
  <div class="quick-actions">
    <a href="/dashboard?page=Expense%20Setup">Expense Setup</a>
    <a class="primary-link" href="/dashboard?page=Expense%20Categories">Manage Budgets</a>
  </div>
</div>
{render_money_cards([("Monthly Budget", total), ("Budgeted Categories", float(len(budget_rows)))])}
<article class="panel table-panel">
  <table>
    <thead><tr><th>Parent</th><th>Category</th><th>Type</th><th>Monthly Budget</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_recurring_expenses() -> str:
    rows_data = [
        row
        for row in ExpenseRepository().list_expenses()
        if row["recurrence"] != "once" and row["status"] != "cancelled"
    ]
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["reference_no"] or f'#{row["id"]}')}</td>
          <td>{html.escape(expense_type_label(row["expense_type"]))}</td>
          <td>{html.escape(row["category_name"] or "Uncategorized")}</td>
          <td>{html.escape(row["party_name"] or "")}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(str(row["recurrence"]).title())}</td>
          <td>{transaction_status_badge(row["status"])}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="7" class="empty">No recurring transactions configured.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div>
    <h2>Recurring Expenses</h2>
    <p>Transactions marked for daily, weekly, monthly, or yearly repetition.</p>
  </div>
  <div class="quick-actions">
    <a href="/dashboard?page=Expense%20Setup">Expense Setup</a>
    <a class="primary-link" href="/dashboard?page=Add%20Expense">Add Transaction</a>
  </div>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Reference</th><th>Type</th><th>Category</th><th>Party</th><th>Amount</th><th>Frequency</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_expense_refund(message: str = "", error: str = "") -> str:
    repository = ExpenseRepository()
    expenses = repository.expense_options()
    refunds = repository.list_refunds()
    today = __import__("datetime").date.today().isoformat()

    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["refund_date"])}</td>
          <td>{html.escape(row["expense_date"])}</td>
          <td>{html.escape(row["category_name"] or "")}</td>
          <td class="numeric">{row["expense_amount"]:.2f}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in refunds
    )
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No expense refunds added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Expense Refund</h2>
  <p>Record money returned against an expense. Refunds are saved as cash-in payment transactions.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Refund</h3>
    <form method="post" action="/expense-refunds/create">
      <div class="form-grid two-col">
        {select_input("Expense", "expense_id", expenses)}
        {date_input("Refund Date", "refund_date", today)}
        {number_input("Refund Amount", "amount", "0.00")}
      </div>
      <label class="field wide-field">
        <span>Note</span>
        <textarea name="note" rows="4"></textarea>
      </label>
      <button type="submit">Save Refund</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Refund History</h3>
    <table>
      <thead>
        <tr>
          <th>Refund Date</th>
          <th>Expense Date</th>
          <th>Category</th>
          <th>Expense Amount</th>
          <th>Refund</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_payment_accounts(message: str = "", error: str = "") -> str:
    accounts = PaymentRepository().list_accounts()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["account_type"].replace('_', ' ').title())}</td>
          <td class="numeric">{row["opening_balance"]:.2f}</td>
          <td class="numeric">{row["current_balance"]:.2f}</td>
          <td>{'Active' if row["is_active"] else 'Inactive'}</td>
        </tr>
        """
        for row in accounts
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No payment accounts found.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Accounts</h2>
    <p>Account balances are calculated from opening balance plus payment transactions.</p>
  </div>
  <a class="primary-link" href="/dashboard?page=Deposits">Add Deposit</a>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Account</h3>
    <form method="post" action="/accounts/create">
      <div class="form-grid two-col">
        {text_input("Account Name", "name", required=True)}
        <label class="field">
          <span>Type</span>
          <select name="account_type">
            <option value="cash">Cash</option>
            <option value="bank">Bank</option>
            <option value="card">Card</option>
            <option value="wallet">Wallet</option>
          </select>
        </label>
        {number_input("Opening Balance", "opening_balance", "0.00")}
        {status_select()}
      </div>
      <button type="submit">Save Account</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Account List</h3>
    <table>
      <thead>
        <tr>
          <th>Account</th>
          <th>Type</th>
          <th>Opening Balance</th>
          <th>Current Balance</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_payment_transactions(message: str = "", error: str = "") -> str:
    transactions = PaymentRepository().list_transactions()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{html.escape(row["account_name"] or "")}</td>
          <td>{payment_type_badge(row["payment_type"])}</td>
          <td>{html.escape(row["reference_type"].replace('_', ' ').title())} #{row["reference_id"]}</td>
          <td>{html.escape(row["method"].replace('_', ' ').title())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td><a class="table-link" href="/payments/receipt?id={row["id"]}">Receipt</a></td>
        </tr>
        """
        for row in transactions
    )
    if not rows:
        rows = '<tr><td colspan="8" class="empty">No payment transactions found.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Transactions</h2>
    <p>Cash-in and cash-out records from sales, purchases, expenses, and deposits.</p>
  </div>
  <a class="primary-link" href="/dashboard?page=Deposits">Add Deposit</a>
</div>
{render_notice(message, error)}
<article class="panel table-panel">
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Account</th>
        <th>Type</th>
        <th>Reference</th>
        <th>Method</th>
        <th>Amount</th>
        <th>Note</th>
        <th>Print</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def due_sale_options(rows: list[sqlite3.Row], selected_id: int | None = None) -> str:
    if not rows:
        return '<option value="">No customer due invoices</option>'
    options = ['<option value="">Select due sale invoice</option>']
    for row in rows:
        label = (
            f"{row['invoice_no']} - {row['customer_name']} - "
            f"Due {float(row['due_amount'] or 0):.2f}"
        )
        options.append(
            f'<option value="{row["id"]}" data-due="{float(row["due_amount"] or 0):.2f}" {"selected" if selected_id == row["id"] else ""}>'
            f"{html.escape(label)}</option>"
        )
    return "".join(options)


def due_purchase_options(rows: list[sqlite3.Row], selected_id: int | None = None) -> str:
    if not rows:
        return '<option value="">No supplier due purchases</option>'
    options = ['<option value="">Select due purchase invoice</option>']
    for row in rows:
        label = (
            f"{row['invoice_no']} - {row['supplier_name']} - "
            f"Due {float(row['due_amount'] or 0):.2f}"
        )
        options.append(
            f'<option value="{row["id"]}" data-due="{float(row["due_amount"] or 0):.2f}" {"selected" if selected_id == row["id"] else ""}>'
            f"{html.escape(label)}</option>"
        )
    return "".join(options)


def account_select(label: str, name: str, accounts: list[sqlite3.Row]) -> str:
    options = "".join(
        f'<option value="{row["id"]}">{html.escape(row["name"])}</option>'
        for row in accounts
    )
    if not options:
        options = '<option value="">No active account</option>'
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}" required>{options}</select>
</label>"""


def render_customer_payments(
    query: dict[str, list[str]] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    query = query or {}
    repository = PaymentRepository()
    due_sales = repository.customer_due_sales()
    history = repository.customer_payment_history()
    accounts = repository.account_options()
    methods = SettingsRepository().list_payment_methods()
    today = __import__("datetime").date.today().isoformat()
    selected_sale_id = optional_query_int(query, "sale_id")
    due_total = sum(float(row["due_amount"] or 0) for row in due_sales)
    received_total = sum(float(row["amount"] or 0) for row in history)
    due_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["sale_date"])}</td>
          <td><a class="table-link" href="/sales/invoice?id={row["id"]}">{html.escape(row["invoice_no"])}</a></td>
          <td>{html.escape(row["customer_name"])}</td>
          <td>{html.escape(row["customer_phone"] or "")}</td>
          <td class="numeric">{float(row["total"] or 0):.2f}</td>
          <td class="numeric">{float(row["paid_amount"] or 0):.2f}</td>
          <td class="numeric">{float(row["due_amount"] or 0):.2f}</td>
          <td>{transaction_status_badge(row["payment_status"])}</td>
          <td><a class="table-link" href="/dashboard?{urlencode({"page": "Customer Payments", "sale_id": row["id"]})}">Receive</a></td>
        </tr>
        """
        for row in due_sales
    ) or '<tr><td colspan="9" class="empty">No customer due invoices.</td></tr>'
    history_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["customer_name"] or "Walk-in Customer")}</td>
          <td>{html.escape(row["account_name"] or "")}</td>
          <td>{html.escape(row["method"].replace("_", " ").title())}</td>
          <td class="numeric">{float(row["amount"] or 0):.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td><a class="table-link" href="/payments/receipt?id={row["id"]}">Receipt</a></td>
        </tr>
        """
        for row in history
    ) or '<tr><td colspan="8" class="empty">No customer payment history.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div><h2>Customer Payments</h2><p>Receive money against credit sales and close customer due invoices.</p></div>
  <a class="secondary-link" href="/dashboard?page=Due%20Payment%20Report">Due Report</a>
</div>
{render_notice(message, error)}
{render_money_cards([("Customer Due", due_total), ("Due Invoices", float(len(due_sales))), ("Recent Received", received_total)])}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Receive Customer Payment</h3>
    <form method="post" action="/customer-payments/create" data-due-payment-form>
      <div class="form-grid two-col">
        <label class="field wide-field">
          <span>Sale Invoice</span>
          <select name="sale_id" required data-due-source>{due_sale_options(due_sales, selected_sale_id)}</select>
        </label>
        {date_input("Payment Date", "payment_date", today)}
        {account_select("Deposit Account", "account_id", accounts)}
        {payment_method_select("Method", "method", methods)}
        <label class="field">
          <span>Amount</span>
          <input name="amount" type="number" step="0.01" min="0.01" value="0.00" required data-due-amount>
        </label>
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <button type="submit">Save Customer Payment</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Open Customer Due</h3>
    <table><thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Phone</th><th>Total</th><th>Paid</th><th>Due</th><th>Status</th><th>Action</th></tr></thead><tbody>{due_rows}</tbody></table>
  </article>
</div>
<article class="panel table-panel">
  <h3>Customer Payment History</h3>
  <table><thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Account</th><th>Method</th><th>Amount</th><th>Note</th><th>Receipt</th></tr></thead><tbody>{history_rows}</tbody></table>
</article>"""


def render_supplier_payments(
    query: dict[str, list[str]] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    query = query or {}
    repository = PaymentRepository()
    due_purchases = repository.supplier_due_purchases()
    history = repository.supplier_payment_history()
    accounts = repository.account_options()
    methods = SettingsRepository().list_payment_methods()
    today = __import__("datetime").date.today().isoformat()
    selected_purchase_id = optional_query_int(query, "purchase_id")
    due_total = sum(float(row["due_amount"] or 0) for row in due_purchases)
    paid_total = sum(float(row["amount"] or 0) for row in history)
    due_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["purchase_date"])}</td>
          <td><a class="table-link" href="/purchases/detail?id={row["id"]}">{html.escape(row["invoice_no"])}</a></td>
          <td>{html.escape(row["supplier_name"])}</td>
          <td>{html.escape(row["supplier_phone"] or "")}</td>
          <td class="numeric">{float(row["total"] or 0):.2f}</td>
          <td class="numeric">{float(row["paid_amount"] or 0):.2f}</td>
          <td class="numeric">{float(row["due_amount"] or 0):.2f}</td>
          <td>{transaction_status_badge(row["payment_status"])}</td>
          <td><a class="table-link" href="/dashboard?{urlencode({"page": "Supplier Payments", "purchase_id": row["id"]})}">Pay</a></td>
        </tr>
        """
        for row in due_purchases
    ) or '<tr><td colspan="9" class="empty">No supplier due purchases.</td></tr>'
    history_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["supplier_name"] or "No Supplier")}</td>
          <td>{html.escape(row["account_name"] or "")}</td>
          <td>{html.escape(row["method"].replace("_", " ").title())}</td>
          <td class="numeric">{float(row["amount"] or 0):.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td><a class="table-link" href="/payments/receipt?id={row["id"]}">Receipt</a></td>
        </tr>
        """
        for row in history
    ) or '<tr><td colspan="8" class="empty">No supplier payment history.</td></tr>'
    return f"""
<div class="page-title action-title">
  <div><h2>Supplier Payments</h2><p>Pay supplier purchase dues and close purchase balances.</p></div>
  <a class="secondary-link" href="/dashboard?page=Due%20Payment%20Report">Due Report</a>
</div>
{render_notice(message, error)}
{render_money_cards([("Supplier Due", due_total), ("Due Purchases", float(len(due_purchases))), ("Recent Paid", paid_total)])}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Pay Supplier Due</h3>
    <form method="post" action="/supplier-payments/create" data-due-payment-form>
      <div class="form-grid two-col">
        <label class="field wide-field">
          <span>Purchase Invoice</span>
          <select name="purchase_id" required data-due-source>{due_purchase_options(due_purchases, selected_purchase_id)}</select>
        </label>
        {date_input("Payment Date", "payment_date", today)}
        {account_select("Pay From Account", "account_id", accounts)}
        {payment_method_select("Method", "method", methods)}
        <label class="field">
          <span>Amount</span>
          <input name="amount" type="number" step="0.01" min="0.01" value="0.00" required data-due-amount>
        </label>
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <button type="submit">Save Supplier Payment</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Open Supplier Due</h3>
    <table><thead><tr><th>Date</th><th>Invoice</th><th>Supplier</th><th>Phone</th><th>Total</th><th>Paid</th><th>Due</th><th>Status</th><th>Action</th></tr></thead><tbody>{due_rows}</tbody></table>
  </article>
</div>
<article class="panel table-panel">
  <h3>Supplier Payment History</h3>
  <table><thead><tr><th>Date</th><th>Invoice</th><th>Supplier</th><th>Account</th><th>Method</th><th>Amount</th><th>Note</th><th>Receipt</th></tr></thead><tbody>{history_rows}</tbody></table>
</article>"""


def render_deposits(message: str = "", error: str = "") -> str:
    accounts = PaymentRepository().account_options()
    payment_methods = SettingsRepository().list_payment_methods()
    today = __import__("datetime").date.today().isoformat()
    account_options = [type("Option", (), {"id": row["id"], "name": row["name"]}) for row in accounts]

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Deposits</h2>
    <p>Add money into a payment account, usually the cash register or bank account.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=Transactions">Transactions</a>
</div>
{render_notice(message, error)}
<article class="panel">
  <form class="product-form" method="post" action="/deposits/create">
    <div class="form-grid two-col">
      {select_input("Account", "account_id", account_options)}
      {date_input("Deposit Date", "payment_date", today)}
      {number_input("Amount", "amount", "0.00")}
      {payment_method_select("Method", "method", payment_methods)}
    </div>
    <label class="field wide-field">
      <span>Note</span>
      <textarea name="note" rows="4"></textarea>
    </label>
    <div class="form-actions">
      <button type="submit">Save Deposit</button>
      <a href="/dashboard?page=Accounts">Cancel</a>
    </div>
  </form>
</article>"""


def render_transfers(message: str = "", error: str = "") -> str:
    repository = PaymentRepository()
    accounts = repository.account_options()
    transfers = repository.list_transfers()
    account_options = [type("Option", (), {"id": row["id"], "name": row["name"]}) for row in accounts]
    today = __import__("datetime").date.today().isoformat()

    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["transfer_date"])}</td>
          <td>{html.escape(row["from_account_name"])}</td>
          <td>{html.escape(row["to_account_name"])}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in transfers
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No transfers added yet.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Transfers</h2>
  <p>Move money between payment accounts. Transfers create paired cash-out and cash-in transactions.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Transfer</h3>
    <form method="post" action="/transfers/create">
      <div class="form-grid two-col">
        {select_input("From Account", "from_account_id", account_options)}
        {select_input("To Account", "to_account_id", account_options)}
        {date_input("Transfer Date", "transfer_date", today)}
        {number_input("Amount", "amount", "0.00")}
      </div>
      <label class="field wide-field">
        <span>Note</span>
        <textarea name="note" rows="4"></textarea>
      </label>
      <button type="submit">Save Transfer</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Transfer History</h3>
    <table>
      <thead><tr><th>Date</th><th>From</th><th>To</th><th>Amount</th><th>Note</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def payment_type_badge(payment_type: str) -> str:
    if payment_type == "in":
        return '<span class="badge ok">IN</span>'
    return '<span class="badge danger">OUT</span>'


def expense_type_badge(expense_type: str) -> str:
    if expense_type == "expense":
        return '<span class="badge">EXPENSE</span>'
    return payment_type_badge(expense_type)


def transaction_status_badge(status: str) -> str:
    classes = {
        "paid": "ok",
        "approved": "ok",
        "partial": "",
        "due": "danger",
        "pending": "danger",
        "cancelled": "danger",
        "draft": "",
    }
    class_name = classes.get(status, "")
    class_attr = f" {class_name}" if class_name else ""
    return f'<span class="badge{class_attr}">{html.escape(status.title())}</span>'


def expense_status_actions(row: sqlite3.Row) -> str:
    if row["status"] == "cancelled":
        return ""
    target = "approved" if row["status"] in {"draft", "pending"} else "cancelled"
    label = "Approve" if target == "approved" else "Cancel"
    return f"""
    <form method="post" action="/expenses/status">
      <input type="hidden" name="expense_id" value="{row["id"]}">
      <input type="hidden" name="status" value="{target}">
      <button type="submit">{label}</button>
    </form>"""


def render_attachment(row: sqlite3.Row) -> str:
    source = html.escape(row["attachment_data"], quote=True)
    filename = html.escape(row["attachment_name"] or "Attachment")
    is_pdf = str(row["attachment_data"]).startswith("data:application/pdf")
    preview = (
        f'<iframe src="{source}" title="{filename}"></iframe>'
        if is_pdf
        else f'<img src="{source}" alt="{filename}">'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{filename}</title>
  <style>
    body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; background: #f1f5f9; }}
    header {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }}
    img, iframe {{ display: block; width: 100%; min-height: 80vh; object-fit: contain; border: 1px solid #cbd5e1; background: white; }}
    button {{ padding: 9px 14px; }}
  </style>
</head>
<body>
  <header><strong>{filename}</strong><button onclick="window.print()">Print / Save PDF</button></header>
  {preview}
</body>
</html>"""


def report_filters_from_query(query: dict[str, list[str]]) -> dict[str, str]:
    keys = (
        "search", "date_from", "date_to", "location_id", "payment_status",
        "category_id", "brand_id", "stock_status", "account_id",
        "payment_type", "method", "reference_type", "movement_type",
        "supplier_id", "product_id", "cheque_status",
    )
    return {key: query.get(key, [""])[0] for key in keys}


def query_selected_int(filters: dict[str, str], key: str) -> int | None:
    value = filters.get(key, "")
    return int(value) if value.isdigit() else None


def report_page_header(
    title: str,
    hint: str,
    report_type: str,
    filters: dict[str, str],
) -> str:
    export_params = {key: value for key, value in filters.items() if value}
    export_params["report"] = report_type
    return f"""
<div class="page-title action-title report-title">
  <div><h2>{html.escape(title)}</h2><p>{html.escape(hint)}</p></div>
  <div class="quick-actions">
    <a href="/reports/export.csv?{urlencode(export_params)}">Export Excel CSV</a>
    <button type="button" onclick="window.print()">Print / PDF</button>
  </div>
</div>"""


def report_filter_panel(
    page: str,
    filters: dict[str, str],
    extra_fields: str = "",
) -> str:
    from datetime import date, timedelta

    today = date.today()
    month_start = today.replace(day=1)
    presets = [
        ("Today", today, today),
        ("Yesterday", today - timedelta(days=1), today - timedelta(days=1)),
        ("This Week", today - timedelta(days=today.weekday()), today),
        ("This Month", month_start, today),
    ]
    preset_links = "".join(
        f'<a href="/dashboard?{urlencode({"page": page, "date_from": start.isoformat(), "date_to": end.isoformat()})}">{label}</a>'
        for label, start, end in presets
    )
    return f"""
<article class="panel report-filter-panel">
  <div class="report-presets">{preset_links}<a href="/dashboard?page={quote(page)}">All Time</a></div>
  <form method="get" action="/dashboard" class="report-filter-grid">
    <input type="hidden" name="page" value="{html.escape(page, quote=True)}">
    {preset_text_input("Search", "search", filters["search"])}
    {date_input_optional("From", "date_from", filters["date_from"])}
    {date_input_optional("To", "date_to", filters["date_to"])}
    {extra_fields}
    <div class="expense-filter-actions">
      <button type="submit">Apply</button>
      <a class="secondary-link" href="/dashboard?page={quote(page)}">Clear</a>
    </div>
  </form>
</article>"""


def render_sales_report(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    rows_data = ReportRepository().sales_report(filters)
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations()
        if row["is_active"]
    ]
    total = sum(float(row["total"]) for row in rows_data)
    returns = sum(float(row["return_amount"]) for row in rows_data)
    net_sales = total - returns
    cogs = sum(float(row["cost_of_goods"]) for row in rows_data)
    gross_profit = net_sales - cogs
    paid = sum(float(row["paid_amount"]) for row in rows_data)
    due = sum(float(row["due_amount"]) for row in rows_data)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["sale_date"])}</td>
          <td><a class="table-link" href="/sales/invoice?id={row["id"]}">{html.escape(row["invoice_no"])}</a></td>
          <td>{html.escape(row["customer_name"])}</td>
          <td>{html.escape(row["location_name"])}</td>
          <td>{html.escape(row["payment_status"].title())}</td>
          <td class="numeric">{row["subtotal"]:.2f}</td>
          <td class="numeric">{row["discount"]:.2f}</td>
          <td class="numeric">{row["tax"]:.2f}</td>
          <td class="numeric">{row["return_amount"]:.2f}</td>
          <td class="numeric">{float(row["total"]) - float(row["return_amount"]):.2f}</td>
          <td class="numeric">{row["cost_of_goods"]:.2f}</td>
          <td class="numeric">{float(row["total"]) - float(row["return_amount"]) - float(row["cost_of_goods"]):.2f}</td>
          <td class="numeric">{row["paid_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="14" class="empty">No sales match the filters.</td></tr>'
    return f"""
{report_page_header("Sales Report", "Final sales, returns, cost, profit, collections, and due balances.", "sales", filters)}
{render_money_cards([("Net Sales", net_sales), ("Gross Profit", gross_profit), ("Paid", paid), ("Due", due)])}
{report_filter_panel("Sales Report", filters, f'''
  {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
  {simple_select("Payment Status", "payment_status", [("", "All Payments"), ("paid", "Paid"), ("partial", "Partial"), ("due", "Due")], filters["payment_status"])}
''')}
<article class="panel table-panel report-sheet-panel">
  <div class="report-sheet-scroll"><table class="report-sheet">
    <thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Location</th><th>Payment</th><th>Subtotal</th><th>Discount</th><th>Tax</th><th>Returns</th><th>Net Sales</th><th>COGS</th><th>Gross Profit</th><th>Paid</th><th>Due</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def render_purchase_report(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    rows_data = ReportRepository().purchase_report(filters)
    purchase_totals: dict[int, tuple[float, float, float, float]] = {}
    for row in rows_data:
        purchase_totals[int(row["purchase_id"])] = (
            float(row["total"] or 0),
            float(row["paid_amount"] or 0),
            float(row["due_amount"] or 0),
            float(row["pending_cheque_amount"] or 0),
        )
    total = sum(values[0] for values in purchase_totals.values())
    paid = sum(values[1] for values in purchase_totals.values())
    due = sum(values[2] for values in purchase_totals.values())
    pending_cheque = sum(values[3] for values in purchase_totals.values())
    total_quantity = sum(float(row["quantity"] or 0) for row in rows_data)
    suppliers = ContactRepository().supplier_options()
    products = ProductRepository().product_options()
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations()
        if row["is_active"]
    ]
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["purchase_date"])}</td>
          <td><a class="table-link" href="/purchases/detail?id={row["purchase_id"]}">{html.escape(row["invoice_no"])}</a></td>
          <td>{html.escape(row["supplier_name"])}</td>
          <td>{html.escape(row["location_name"])}</td>
          <td>{html.escape(row["product_name"] or "")}</td>
          <td>{html.escape(row["product_sku"] or "")}</td>
          <td>{html.escape(row["product_barcode"] or "")}</td>
          <td class="numeric">{float(row["quantity"] or 0):.2f} {html.escape(row["unit_name"] or "")}</td>
          <td class="numeric">{float(row["purchase_price"] or 0):.2f}</td>
          <td class="numeric">{float(row["line_total"] or 0):.2f}</td>
          <td class="numeric">{float(row["total"] or 0):.2f}</td>
          <td class="numeric">{float(row["paid_amount"] or 0):.2f}</td>
          <td class="numeric">{float(row["due_amount"] or 0):.2f}</td>
          <td>{transaction_status_badge(row["payment_status"])}</td>
          <td>{html.escape((row["payment_methods"] or "").replace("_", " ").title() or "-")}</td>
          <td class="numeric">{float(row["cleared_amount"] or 0):.2f}</td>
          <td class="numeric">{float(row["pending_cheque_amount"] or 0):.2f}</td>
          <td>{html.escape(row["cheque_numbers"] or "-")}</td>
          <td>{html.escape((row["cheque_statuses"] or "-").replace(",", ", ").title())}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="19" class="empty">No purchases match the filters.</td></tr>'
    return f"""
{report_page_header("Purchase Report", "Supplier purchase history by product, quantity, payment split, due balance, and cheque status.", "purchase", filters)}
{render_money_cards([("Purchase Total", total), ("Total Qty", total_quantity), ("Paid", paid), ("Due", due), ("Pending Cheques", pending_cheque)])}
{report_filter_panel("Purchase Report", filters, f'''
  {select_input("Supplier", "supplier_id", suppliers, query_selected_int(filters, "supplier_id"))}
  {select_input("Product", "product_id", products, query_selected_int(filters, "product_id"))}
  {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
  {simple_select("Payment Status", "payment_status", [("", "All Payments"), ("paid", "Paid"), ("partial", "Partial"), ("due", "Due"), ("cheque_pending", "Cheque Pending")], filters["payment_status"])}
  {simple_select("Cheque Status", "cheque_status", [("", "All Cheques"), ("pending", "Pending"), ("cleared", "Cleared"), ("bounced", "Bounced")], filters["cheque_status"])}
''')}
<article class="panel table-panel report-sheet-panel">
  <div class="report-sheet-scroll"><table class="report-sheet">
    <thead><tr><th>Date</th><th>Invoice</th><th>Supplier</th><th>Location</th><th>Product</th><th>SKU</th><th>Barcode</th><th>Qty</th><th>Unit Cost</th><th>Line Total</th><th>Invoice Total</th><th>Paid</th><th>Due</th><th>Payment</th><th>Methods</th><th>Cleared</th><th>Pending Cheque</th><th>Cheque No</th><th>Cheque Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def render_profit_loss_report(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    summary = ReportRepository().profit_loss_summary(filters)
    locations = [
        LookupItem(id=row["id"], name=row["name"])
        for row in SettingsRepository().list_locations()
        if row["is_active"]
    ]
    cards = [
        ("Net Sales", summary["net_sales"]),
        ("Gross Profit", summary["gross_profit"]),
        ("Operating Expenses", summary["total_expenses"]),
        ("Net Profit", summary["net_profit"]),
    ]
    return f"""
{report_page_header("Profit / Loss Report", "Net sales minus cost of goods and approved operating expenses.", "profit", filters)}
{render_money_cards(cards)}
{report_filter_panel("Profit / Loss Report", filters, f'''
  {select_input("Location", "location_id", locations, query_selected_int(filters, "location_id"))}
''')}
<article class="panel table-panel">
  <table>
    <tbody>
      {report_row("Gross Sales", summary["gross_sales"])}
      {report_row("Sales Returns", -summary["sales_returns"])}
      {report_row("Net Sales", summary["net_sales"])}
      {report_row("Cost of Goods Sold", -summary["cost_of_goods"])}
      {report_row("Gross Profit", summary["gross_profit"])}
      {report_row("Operating Expenses", -summary["total_expenses"])}
      {report_row("Net Profit", summary["net_profit"])}
      {report_row("Profit Margin %", summary["profit_margin"])}
      {report_row("Cash In - Non Profit", summary["cash_in"])}
      {report_row("Cash Out - Non Profit", -summary["cash_out"])}
    </tbody>
  </table>
</article>"""


def render_purchase_sale_report() -> str:
    summary = ReportRepository().purchase_sale_summary()
    rows = [
        ("Sales Total", summary["sales_total"]),
        ("Sales Paid", summary["sales_paid"]),
        ("Sales Due", summary["sales_due"]),
        ("Purchase Total", summary["purchase_total"]),
        ("Purchase Paid", summary["purchase_paid"]),
        ("Purchase Due", summary["purchase_due"]),
    ]
    return f"""
<div class="page-title">
  <h2>Purchase & Sale Report</h2>
  <p>Summary of sales and purchases with paid and due balances.</p>
</div>
{render_money_cards(rows[:4])}
<article class="panel table-panel">
  <table>
    <tbody>{''.join(report_row(label, amount) for label, amount in rows)}</tbody>
  </table>
</article>"""


def render_tax_report() -> str:
    data = ReportRepository().tax_report()
    summary = data["summary"]
    tax_rows = list(data["sales"]) + list(data["purchases"])
    tax_rows.sort(key=lambda row: row["entry_date"], reverse=True)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["entry_date"])}</td>
          <td>{html.escape(row["source"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td class="numeric">{row["total"]:.2f}</td>
          <td class="numeric">{row["tax"]:.2f}</td>
        </tr>
        """
        for row in tax_rows
    ) or '<tr><td colspan="5" class="empty">No taxable sales or purchases found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Tax Report</h2>
  <p>Sales tax collected, purchase tax paid, and the net tax position.</p>
</div>
{render_money_cards([("Sales Tax", summary["sales_tax"]), ("Purchase Tax", summary["purchase_tax"]), ("Net Tax", summary["net_tax"])])}
<article class="panel table-panel">
  <table>
    <thead><tr><th>Date</th><th>Source</th><th>Invoice</th><th>Total</th><th>Tax</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_supplier_customer_report() -> str:
    rows_data = ReportRepository().supplier_customer_report()
    total = sum(float(row["total_amount"]) for row in rows_data)
    due = sum(float(row["due_amount"]) for row in rows_data)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["contact_type"].title())}</td>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["phone"] or "")}</td>
          <td>{html.escape(row["email"] or "")}</td>
          <td class="numeric">{row["document_count"]}</td>
          <td class="numeric">{row["total_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
          <td>{status_badge(row["is_active"])}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="8" class="empty">No suppliers or customers found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Supplier & Customer Report</h2>
  <p>Contact summary with document counts, total business value, and due balances.</p>
</div>
{render_money_cards([("Total Value", total), ("Total Due", due), ("Contacts", float(len(rows_data)))])}
<article class="panel table-panel">
  <table>
    <thead><tr><th>Type</th><th>Name</th><th>Phone</th><th>Email</th><th>Documents</th><th>Total</th><th>Due</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_expense_report() -> str:
    rows_data = ReportRepository().expense_by_category()
    total = sum(float(row["total_amount"]) for row in rows_data)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["category_name"])}</td>
          <td class="numeric">{row["expense_count"]}</td>
          <td class="numeric">{row["total_amount"]:.2f}</td>
        </tr>
        """
        for row in rows_data
    )
    if not rows:
        rows = '<tr><td colspan="3" class="empty">No expenses found.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Expense Report</h2>
  <p>Expenses grouped by category.</p>
</div>
{render_money_cards([("Total Expenses", total)])}
<article class="panel table-panel">
  <table>
    <thead><tr><th>Category</th><th>Count</th><th>Total</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_payment_report(query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    filters = report_filters_from_query(query)
    rows_data = ReportRepository().payment_report(filters)
    accounts = PaymentRepository().account_options()
    methods = SettingsRepository().list_payment_methods()
    method_options = [("", "All Methods")] + [
        (row["method_key"], row["name"]) for row in methods if row["is_active"]
    ]
    cash_in = sum(float(row["amount"]) for row in rows_data if row["payment_type"] == "in")
    cash_out = sum(float(row["amount"]) for row in rows_data if row["payment_type"] == "out")
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["payment_date"])}</td>
          <td>{payment_type_badge(row["payment_type"])}</td>
          <td>{html.escape(row["reference_type"].replace('_', ' ').title())} #{row["reference_id"]}</td>
          <td>{html.escape(row["account_name"])}</td>
          <td>{html.escape(row["method"].replace('_', ' ').title())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td><a class="table-link" href="/payments/receipt?id={row["id"]}">Receipt</a></td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="8" class="empty">No payments match the filters.</td></tr>'
    return f"""
{report_page_header("Payment Report", "Money in and out across accounts, methods, and business sources.", "payment", filters)}
{render_money_cards([("Cash In", cash_in), ("Cash Out", cash_out), ("Net", cash_in - cash_out)])}
{report_filter_panel("Payment Report", filters, f'''
  {select_input("Account", "account_id", [LookupItem(id=row["id"], name=row["name"]) for row in accounts], query_selected_int(filters, "account_id"))}
  {simple_select("Direction", "payment_type", [("", "In & Out"), ("in", "Cash In"), ("out", "Cash Out")], filters["payment_type"])}
  {simple_select("Method", "method", method_options, filters["method"])}
  {simple_select("Source", "reference_type", [("", "All Sources"), ("sale", "Sales"), ("purchase", "Purchases"), ("expense", "Expenses"), ("expense_refund", "Expense Refunds"), ("deposit", "Deposits"), ("transfer", "Transfers")], filters["reference_type"])}
''')}
<article class="panel table-panel report-sheet-panel">
  <div class="report-sheet-scroll"><table class="report-sheet">
    <thead><tr><th>Date</th><th>Type</th><th>Reference</th><th>Account</th><th>Method</th><th>Amount</th><th>Note</th><th>Receipt</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</article>"""


def render_due_payment_report() -> str:
    rows_data = ReportRepository().due_payment_report()
    due = sum(float(row["due_amount"]) for row in rows_data)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["entry_date"])}</td>
          <td>{html.escape(row["source"])}</td>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["party_name"])}</td>
          <td class="numeric">{row["total"]:.2f}</td>
          <td class="numeric">{row["paid_amount"]:.2f}</td>
          <td class="numeric">{row["due_amount"]:.2f}</td>
          <td>{due_payment_action(row)}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="8" class="empty">No due payments found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Due Payment Report</h2>
  <p>Outstanding customer receivables and supplier payables with direct settlement actions.</p>
</div>
{render_money_cards([("Total Due", due), ("Due Documents", float(len(rows_data)))])}
<article class="panel table-panel">
  <table>
    <thead><tr><th>Date</th><th>Source</th><th>Invoice</th><th>Customer / Supplier</th><th>Total</th><th>Paid</th><th>Due</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def due_payment_action(row: sqlite3.Row) -> str:
    if row["source"] == "Sale":
        url = "/dashboard?" + urlencode({"page": "Customer Payments", "sale_id": row["source_id"]})
        return f'<a class="table-link" href="{url}">Receive</a>'
    url = "/dashboard?" + urlencode({"page": "Supplier Payments", "purchase_id": row["source_id"]})
    return f'<a class="table-link" href="{url}">Pay</a>'


def render_cash_register_report() -> str:
    summary = ReportRepository().cash_register_summary()
    rows = [
        ("Cash In", summary["cash_in"]),
        ("Cash Out", -summary["cash_out"]),
        ("Net Cash", summary["net_cash"]),
    ]
    return f"""
<div class="page-title">
  <h2>Cash Register Report</h2>
  <p>Cash movement summary from payment transactions.</p>
</div>
{render_money_cards([("Cash In", summary["cash_in"]), ("Cash Out", summary["cash_out"]), ("Net Cash", summary["net_cash"])])}
<article class="panel table-panel">
  <table>
    <tbody>{''.join(report_row(label, amount) for label, amount in rows)}</tbody>
  </table>
</article>"""


def render_trending_products_report() -> str:
    rows_data = ReportRepository().trending_products()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["sku"])}</td>
          <td class="numeric">{row["quantity_sold"]:.2f}</td>
          <td class="numeric">{row["sale_count"]}</td>
          <td class="numeric">{row["sales_amount"]:.2f}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="5" class="empty">No sold products found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Trending Products</h2>
  <p>Top selling products ranked by quantity sold and sales amount.</p>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Product</th><th>SKU</th><th>Qty Sold</th><th>Sales</th><th>Amount</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_sales_representative_report() -> str:
    rows_data = ReportRepository().sales_representative_report()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["phone"] or "")}</td>
          <td>{html.escape(row["email"] or "")}</td>
          <td class="numeric">{row["commission_rate"]:.2f}%</td>
          <td>{status_badge(row["is_active"])}</td>
          <td>{html.escape(row["created_at"])}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="6" class="empty">No sales commission agents found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Sales Representative Report</h2>
  <p>Sales commission agents and their configured commission rates.</p>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Commission</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_low_stock_report() -> str:
    rows_data = ReportRepository().low_stock_report()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["sku"])}</td>
          <td class="numeric">{row["available_stock"]:.2f} {html.escape(row["unit_name"])}</td>
          <td class="numeric">{row["alert_quantity"]:.2f}</td>
          <td>{stock_status_badge(row["available_stock"], row["alert_quantity"])}</td>
          <td>
            <div class="inline-actions">
              <a class="table-link" href="/dashboard?page=Product%20Stock%20History&product_id={row["id"]}">History</a>
              <a class="table-link" href="/dashboard?page=Add%20Purchase">Reorder</a>
            </div>
          </td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="6" class="empty">No low stock products found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Low Stock Report</h2>
  <p>Products where available stock is at or below the alert quantity.</p>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Product</th><th>SKU</th><th>Available</th><th>Alert Qty</th><th>Status</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_stock_adjustment_report() -> str:
    rows_data = ReportRepository().stock_adjustment_report()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["adjustment_date"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td>{html.escape(row["location_name"])}</td>
          <td>{html.escape(row["adjustment_type"].title())}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td>{html.escape(row["reason"] or "")}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="7" class="empty">No stock adjustments found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Stock Adjustment Report</h2>
  <p>Manual stock increases and decreases by product and location.</p>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Date</th><th>Product</th><th>SKU</th><th>Location</th><th>Type</th><th>Qty</th><th>Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_stock_transfer_report() -> str:
    rows_data = ReportRepository().stock_transfer_report()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["transfer_date"])}</td>
          <td>{html.escape(row["product_name"])}</td>
          <td>{html.escape(row["product_sku"])}</td>
          <td>{html.escape(row["from_location_name"])}</td>
          <td>{html.escape(row["to_location_name"])}</td>
          <td class="numeric">{row["quantity"]:.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="7" class="empty">No stock transfers found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Stock Transfer Report</h2>
  <p>Stock moved between business locations.</p>
</div>
<article class="panel table-panel">
  <table>
    <thead><tr><th>Date</th><th>Product</th><th>SKU</th><th>From</th><th>To</th><th>Qty</th><th>Note</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_money_cards(cards: list[tuple[str, float]]) -> str:
    return '<div class="metrics">' + "".join(
        f'<article class="metric"><span>{html.escape(label)}</span><strong>{amount:.2f}</strong></article>'
        for label, amount in cards
    ) + "</div>"


def report_row(label: str, amount: float) -> str:
    amount_class = "positive" if amount >= 0 else "negative"
    return f"""
<tr>
  <th>{html.escape(label)}</th>
  <td class="numeric {amount_class}">{amount:.2f}</td>
</tr>"""


def render_sale_invoice(sale_id: int) -> str:
    sale, items = SaleRepository().get_sale_invoice(sale_id)
    if sale is None:
        return render_not_found_page("Sale invoice not found.")

    settings = SettingsRepository().get_business_settings()
    item_discount_total = sum(float(item["discount"] or 0) for item in items)
    total_discount = item_discount_total + float(sale["discount"] or 0)
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(item["product_name"])}</td>
          <td>{html.escape(item["product_sku"])}</td>
          <td class="numeric">{item["quantity"]:.2f}</td>
          <td class="numeric">{item["unit_price"]:.2f}</td>
          <td class="numeric">{item["discount"]:.2f}</td>
          <td class="numeric">{item["tax"]:.2f}</td>
          <td class="numeric">{item["line_total"]:.2f}</td>
        </tr>
        """
        for item in items
    )
    if not rows:
        rows = '<tr><td colspan="7" class="empty">No sale items found.</td></tr>'

    customer_name = sale["customer_name"] or "Walk-in Customer"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invoice {html.escape(sale["invoice_no"])}</title>
  <style>{styles()}{invoice_styles()}</style>
</head>
<body class="invoice-body">
  <main class="invoice-sheet">
    <div class="invoice-actions">
      <a class="secondary-link" href="/dashboard?page=List%20Sales">Back to Sales</a>
      <a class="secondary-link" href="/sales/receipt?id={sale_id}&type=pos">POS Receipt</a>
      <a class="secondary-link" href="/sales/receipt?id={sale_id}&type=duplicate">Duplicate</a>
      <a class="secondary-link" href="/sales/receipt?id={sale_id}&type=gift">Gift</a>
      <a class="secondary-link" href="/sales/receipt?id={sale_id}&type=delivery">Delivery Note</a>
      <a class="secondary-link" href="/sales/receipt?id={sale_id}&type=tax">Tax Invoice</a>
      <button type="button" onclick="window.print()">Print</button>
    </div>
    <header class="invoice-header">
      <div>
        <h1>{html.escape(settings["business_name"])}</h1>
        <p>{html.escape(settings["address"] or "")}</p>
        <p>{html.escape(settings["phone"] or "")} {html.escape(settings["email"] or "")}</p>
        <p>{'Tax No: ' + html.escape(settings["tax_number"]) if settings["tax_number"] else ''}</p>
      </div>
      <div class="invoice-meta">
        <h2>Invoice</h2>
        <p><strong>No:</strong> {html.escape(sale["invoice_no"])}</p>
        <p><strong>Date:</strong> {html.escape(sale["sale_date"])}</p>
        <p><strong>Status:</strong> {html.escape(sale["payment_status"].title())}</p>
      </div>
    </header>
    <section class="invoice-customer">
      <h3>Bill To</h3>
      <p><strong>{html.escape(customer_name)}</strong></p>
      <p>{html.escape(sale["customer_phone"] or "")} {html.escape(sale["customer_email"] or "")}</p>
      <p>{html.escape(sale["customer_address"] or "")}</p>
    </section>
    <section class="invoice-table table-panel">
      <table>
        <thead>
          <tr>
            <th>Product</th>
            <th>SKU</th>
            <th>Qty</th>
            <th>Unit Price</th>
            <th>Discount</th>
            <th>Tax</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    <section class="invoice-totals">
      <table>
        <tbody>
          {invoice_total_row("Subtotal", sale["subtotal"], settings["currency_symbol"])}
          {invoice_total_row("Discount", total_discount, settings["currency_symbol"])}
          {invoice_total_row("Tax", sale["tax"], settings["currency_symbol"])}
          {invoice_total_row("Total", sale["total"], settings["currency_symbol"])}
          {invoice_total_row("Paid", sale["paid_amount"], settings["currency_symbol"])}
          {invoice_total_row("Due", sale["due_amount"], settings["currency_symbol"])}
        </tbody>
      </table>
    </section>
    <footer class="invoice-footer">
      <p>Thank you for your business.</p>
    </footer>
  </main>
</body>
</html>"""


SALE_RECEIPT_TYPES = {
    "pos": ("POS Receipt", "Counter sale receipt", True, True),
    "duplicate": ("Duplicate Receipt", "Duplicate copy", True, True),
    "gift": ("Gift Receipt", "Gift copy - prices hidden", False, False),
    "delivery": ("Delivery Note", "Delivery copy - prices hidden", False, False),
    "tax": ("Tax Invoice", "Tax receipt", True, True),
}


def render_sale_receipt(sale_id: int, receipt_type: str) -> str:
    sale, items = SaleRepository().get_sale_invoice(sale_id)
    if sale is None:
        return render_not_found_page("Sale receipt not found.")
    title, subtitle, show_prices, show_totals = SALE_RECEIPT_TYPES.get(receipt_type, SALE_RECEIPT_TYPES["pos"])
    settings = SettingsRepository().get_business_settings()
    item_discount_total = sum(float(item["discount"] or 0) for item in items)
    total_discount = item_discount_total + float(sale["discount"] or 0)
    rows = "".join(render_receipt_sale_item(item, show_prices, settings["currency_symbol"]) for item in items)
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No sale items found.</td></tr>'
    totals = ""
    if show_totals:
        totals = f"""
        <section class="receipt-totals">
          {receipt_total_row("Subtotal", sale["subtotal"], settings["currency_symbol"])}
          {receipt_total_row("Discount", total_discount, settings["currency_symbol"])}
          {receipt_total_row("Tax", sale["tax"], settings["currency_symbol"])}
          {receipt_total_row("Total", sale["total"], settings["currency_symbol"])}
          {receipt_total_row("Paid", sale["paid_amount"], settings["currency_symbol"])}
          {receipt_total_row("Due", sale["due_amount"], settings["currency_symbol"])}
        </section>
        """
    customer_name = sale["customer_name"] or "Walk-in Customer"
    table_header = (
        "<tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>"
        if show_prices
        else "<tr><th>Item</th><th>SKU</th><th>Qty</th></tr>"
    )
    return render_print_document(
        page_title=f"{title} {sale['invoice_no']}",
        body=f"""
        <main class="receipt-roll">
          <header class="receipt-head">
            <h1>{html.escape(settings["business_name"])}</h1>
            <p>{html.escape(settings["address"] or "")}</p>
            <p>{html.escape(settings["phone"] or "")}</p>
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(subtitle)}</p>
          </header>
          <section class="receipt-meta">
            <div><span>No</span><strong>{html.escape(sale["invoice_no"])}</strong></div>
            <div><span>Date</span><strong>{html.escape(sale["sale_date"])}</strong></div>
            <div><span>Customer</span><strong>{html.escape(customer_name)}</strong></div>
            <div><span>Status</span><strong>{html.escape(sale["payment_status"].title())}</strong></div>
          </section>
          <table class="receipt-table">
            <thead>{table_header}</thead>
            <tbody>{rows}</tbody>
          </table>
          {totals}
          <footer class="receipt-footer">
            <p>{html.escape(SettingsRepository().get_invoice_settings()["receipt_footer"] or "Thank you for your business.")}</p>
          </footer>
        </main>
        """,
        extra_styles=receipt_styles(),
    )


def render_receipt_sale_item(item, show_prices: bool, currency: str) -> str:
    if show_prices:
        quantity = float(item["quantity"] or 0)
        discount = float(item["discount"] or 0)
        unit_price = float(item["unit_price"] or 0)
        line_total = float(item["line_total"] or 0)
        effective_unit_price = line_total / quantity if quantity > 0 else unit_price
        price_cell = (
            f'<span class="receipt-price-stack"><del>{unit_price:.2f}</del><strong>{effective_unit_price:.2f}</strong></span>'
            if discount > 0 and effective_unit_price < unit_price
            else f"{unit_price:.2f}"
        )
        return f"""
        <tr>
          <td>{html.escape(item["product_name"])}<small>{html.escape(item["product_sku"])}</small></td>
          <td class="numeric">{item["quantity"]:.2f}</td>
          <td class="numeric">{price_cell}</td>
          <td class="numeric">{item["line_total"]:.2f}</td>
        </tr>
        """
    return f"""
    <tr>
      <td>{html.escape(item["product_name"])}</td>
      <td>{html.escape(item["product_sku"])}</td>
      <td class="numeric">{item["quantity"]:.2f}</td>
    </tr>
    """


def render_payment_receipt(payment_id: int) -> str:
    payment = PaymentRepository().get_transaction_receipt(payment_id)
    if payment is None:
        return render_not_found_page("Payment receipt not found.")
    settings = SettingsRepository().get_business_settings()
    direction = "Received" if payment["payment_type"] == "in" else "Paid Out"
    return render_simple_receipt(
        title="Payment Receipt",
        subtitle=direction,
        rows=[
            ("Receipt No", f"PAY-{payment['id']}"),
            ("Date", payment["payment_date"]),
            ("Account", payment["account_name"] or ""),
            ("Reference", f"{payment['reference_type'].replace('_', ' ').title()} #{payment['reference_id']}"),
            ("Method", payment["method"].replace("_", " ").title()),
            ("Amount", f"{settings['currency_symbol']} {payment['amount']:.2f}"),
            ("Note", payment["note"] or ""),
        ],
    )


def render_sales_return_receipt(return_id: int) -> str:
    sale_return = SalesReturnRepository().get_return_receipt(return_id)
    if sale_return is None:
        return render_not_found_page("Sales return receipt not found.")
    settings = SettingsRepository().get_business_settings()
    return render_simple_receipt(
        title="Sales Return Receipt",
        subtitle="Refund / credit note",
        rows=[
            ("Return No", f"SR-{sale_return['id']}"),
            ("Date", sale_return["return_date"]),
            ("Invoice", sale_return["invoice_no"]),
            ("Customer", sale_return["customer_name"] or "Walk-in Customer"),
            ("Product", sale_return["product_name"]),
            ("SKU", sale_return["product_sku"]),
            ("Quantity", f"{sale_return['quantity']:.2f}"),
            ("Refund", f"{settings['currency_symbol']} {sale_return['refund_amount']:.2f}"),
            ("Refund Method", sale_return["refund_method"].replace("_", " ").title()),
            ("Reason", sale_return["reason"].replace("_", " ").title()),
            ("Condition", sale_return["item_condition"].replace("_", " ").title()),
            ("Returned To Stock", "Yes" if sale_return["return_to_stock"] else "No"),
            ("Note", sale_return["note"] or ""),
        ],
    )


def render_cash_register_receipt(register_id: int) -> str:
    repository = CashRegisterRepository()
    register = repository.get_register(register_id)
    if register is None:
        return render_not_found_page("Cash register receipt not found.")
    settings = SettingsRepository().get_business_settings()
    summary = repository.register_summary(register)
    denomination_breakdown = repository.denomination_breakdown(register)
    denomination_notes = denomination_breakdown["notes"]
    denomination_rows = "".join(
        f"""
        <tr>
          <td>Rs. {denomination}</td>
          <td class="numeric">{int(denomination_notes.get(str(denomination), 0) or 0)}</td>
          <td class="numeric">{denomination * int(denomination_notes.get(str(denomination), 0) or 0):.2f}</td>
        </tr>"""
        for denomination in CASH_DENOMINATIONS
    )
    denomination_rows += f"""
        <tr><td>Coins</td><td></td><td class="numeric">{float(denomination_breakdown["coins_total"]):.2f}</td></tr>
        <tr><th>Counted Cash</th><th></th><th class="numeric">{float(denomination_breakdown["counted_cash"]):.2f}</th></tr>
    """
    transactions = repository.register_transactions(register)
    transaction_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"][11:16] if len(row["created_at"]) >= 16 else row["created_at"])}</td>
          <td>{cash_register_reference_label(row["reference_type"])}</td>
          <td>{html.escape(row["payment_type"].upper())}</td>
          <td class="numeric">{row["amount"]:.2f}</td>
        </tr>"""
        for row in transactions
    ) or '<tr><td colspan="4">No cash transactions</td></tr>'
    return render_print_document(
        page_title=f"Register Z Report REG-{register['id']}",
        body=f"""
        <main class="receipt-roll">
          <header class="receipt-head">
            <h1>{html.escape(settings["business_name"])}</h1>
            <h2>Cash Register Z Report</h2>
            <p>REG-{register["id"]} | {html.escape(register["status"].title())}</p>
          </header>
          <section class="receipt-meta receipt-meta-stack">
            {receipt_info_row("Cashier", register["user_name"])}
            {receipt_info_row("Location", register["location_name"] or "")}
            {receipt_info_row("Opened", register["opened_at"])}
            {receipt_info_row("Closed", register["closed_at"] or "Open")}
            {receipt_info_row("Opening", f'{settings["currency_symbol"]} {register["opening_cash"]:.2f}')}
            {receipt_info_row("Cash Sales", f'{settings["currency_symbol"]} {summary["cash_sales"]:.2f}')}
            {receipt_info_row("Other Cash In", f'{settings["currency_symbol"]} {summary["other_cash_in"]:.2f}')}
            {receipt_info_row("Cash Out", f'{settings["currency_symbol"]} {summary["cash_out"]:.2f}')}
            {receipt_info_row("Expected", f'{settings["currency_symbol"]} {summary["expected_cash"]:.2f}')}
            {receipt_info_row("Counted", f'{settings["currency_symbol"]} {float(register["closing_cash"] or 0):.2f}')}
            {receipt_info_row("Difference", f'{settings["currency_symbol"]} {summary["difference"]:.2f}')}
            {receipt_info_row("Approval", (register["approval_status"] or "pending").title())}
          </section>
          <table class="receipt-table">
            <thead><tr><th>Denomination</th><th>Count</th><th>Total</th></tr></thead>
            <tbody>{denomination_rows}</tbody>
          </table>
          <table class="receipt-table">
            <thead><tr><th>Time</th><th>Source</th><th>Type</th><th>Amount</th></tr></thead>
            <tbody>{transaction_rows}</tbody>
          </table>
          <footer class="receipt-footer"><p>{html.escape(register["closing_note"] or "End of shift report")}</p></footer>
        </main>
        """,
        extra_styles=receipt_styles(),
    )


def receipt_info_row(label: str, value: object) -> str:
    return f"<div><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"


def render_simple_receipt(title: str, subtitle: str, rows: list[tuple[str, object]]) -> str:
    settings = SettingsRepository().get_business_settings()
    row_html = "".join(
        f"<div><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in rows
        if value is not None and str(value) != ""
    )
    return render_print_document(
        page_title=title,
        body=f"""
        <main class="receipt-roll">
          <div class="invoice-actions"><button type="button" onclick="window.print()">Print</button></div>
          <header class="receipt-head">
            <h1>{html.escape(settings["business_name"])}</h1>
            <p>{html.escape(settings["address"] or "")}</p>
            <p>{html.escape(settings["phone"] or "")}</p>
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(subtitle)}</p>
          </header>
          <section class="receipt-meta receipt-meta-stack">{row_html}</section>
          <footer class="receipt-footer"><p>{html.escape(SettingsRepository().get_invoice_settings()["receipt_footer"] or "Thank you.")}</p></footer>
        </main>
        """,
        extra_styles=receipt_styles(),
    )


def render_print_document(page_title: str, body: str, extra_styles: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(page_title)}</title>
  <style>{styles()}{invoice_styles()}{extra_styles}</style>
</head>
<body class="invoice-body">
  {body}
</body>
</html>"""


def receipt_total_row(label: str, amount: float, currency: str) -> str:
    return f"<div><span>{html.escape(label)}</span><strong>{html.escape(currency)} {amount:.2f}</strong></div>"


def render_not_found_page(message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Not Found</title><style>{styles()}</style></head>
<body><main class="content"><article class="panel"><h1>Not Found</h1><p>{html.escape(message)}</p></article></main></body>
</html>"""


def invoice_total_row(label: str, amount: float, currency: str) -> str:
    return f"""
<tr>
  <th>{html.escape(label)}</th>
  <td class="numeric">{html.escape(currency)} {amount:.2f}</td>
</tr>"""


def render_business_settings(message: str = "", error: str = "") -> str:
    settings = SettingsRepository().get_business_settings()
    return f"""
<div class="page-title">
  <h2>Business Settings</h2>
  <p>Business profile used by reports, invoices, receipts, and future print layouts.</p>
</div>
{render_notice(message, error)}
<article class="panel">
  <form class="product-form" method="post" action="/settings/business/update">
    <div class="form-grid two-col">
      {preset_text_input("Business Name", "business_name", settings["business_name"] or "", required=True)}
      {preset_text_input("Currency Symbol", "currency_symbol", settings["currency_symbol"] or "", required=True)}
      {preset_text_input("Tax Number", "tax_number", settings["tax_number"] or "")}
      {preset_text_input("Phone", "phone", settings["phone"] or "")}
      {preset_text_input("Email", "email", settings["email"] or "")}
    </div>
    <label class="field wide-field">
      <span>Address</span>
      <textarea name="address" rows="4">{html.escape(settings["address"] or "")}</textarea>
    </label>
    <div class="form-actions">
      <button type="submit">Save Settings</button>
      <a href="/dashboard">Cancel</a>
    </div>
  </form>
</article>"""


def render_business_locations(message: str = "", error: str = "") -> str:
    locations = SettingsRepository().list_locations()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["phone"] or "")}</td>
          <td>{html.escape(row["address"] or "")}</td>
          <td>{'Active' if row["is_active"] else 'Inactive'}</td>
        </tr>
        """
        for row in locations
    )
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No business locations found.</td></tr>'

    return f"""
<div class="page-title">
  <h2>Business Locations</h2>
  <p>Manage shop, branch, warehouse, or outlet locations used by purchases, sales, and stock.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Location</h3>
    <form method="post" action="/settings/locations/create">
      <div class="form-grid two-col">
        {text_input("Location Name", "name", required=True)}
        {text_input("Phone", "phone")}
        <label class="field">
          <span>Status</span>
          <select name="is_active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
          </select>
        </label>
      </div>
      <label class="field wide-field">
        <span>Address</span>
        <textarea name="address" rows="4"></textarea>
      </label>
      <button type="submit">Save Location</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Locations</h3>
    <table>
      <thead><tr><th>Name</th><th>Phone</th><th>Address</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_invoice_settings(message: str = "", error: str = "") -> str:
    settings = SettingsRepository().get_invoice_settings()
    return f"""
<div class="page-title">
  <h2>Invoice Settings</h2>
  <p>Control invoice numbering, receipt footer text, terms, and printed invoice options.</p>
</div>
{render_notice(message, error)}
<article class="panel">
  <form class="product-form" method="post" action="/settings/invoice/update">
    <div class="form-grid two-col">
      {preset_text_input("Invoice Prefix", "invoice_prefix", settings["invoice_prefix"], required=True)}
      {number_input("Next Invoice Number", "next_invoice_number", str(settings["next_invoice_number"]))}
      <label class="field">
        <span>Show Tax</span>
        <select name="show_tax">
          <option value="1" {"selected" if settings["show_tax"] else ""}>Yes</option>
          <option value="0" {"selected" if not settings["show_tax"] else ""}>No</option>
        </select>
      </label>
      <label class="field">
        <span>Show Logo</span>
        <select name="show_logo">
          <option value="0" {"selected" if not settings["show_logo"] else ""}>No</option>
          <option value="1" {"selected" if settings["show_logo"] else ""}>Yes</option>
        </select>
      </label>
    </div>
    <label class="field wide-field">
      <span>Receipt Footer</span>
      <textarea name="receipt_footer" rows="3">{html.escape(settings["receipt_footer"] or "")}</textarea>
    </label>
    <label class="field wide-field">
      <span>Terms and Conditions</span>
      <textarea name="terms" rows="4">{html.escape(settings["terms"] or "")}</textarea>
    </label>
    <button type="submit">Save Invoice Settings</button>
  </form>
</article>"""


def render_barcode_settings(message: str = "", error: str = "") -> str:
    settings = SettingsRepository().get_barcode_settings()
    return f"""
<div class="page-title">
  <h2>Barcode Settings</h2>
  <p>Set barcode prefix and label print defaults for product labels.</p>
</div>
{render_notice(message, error)}
<article class="panel">
  <form class="product-form" method="post" action="/settings/barcode/update">
    <div class="form-grid two-col">
      {preset_text_input("Barcode Prefix", "barcode_prefix", settings["barcode_prefix"], required=True)}
      {number_input("Next Barcode Number", "next_barcode_number", str(settings["next_barcode_number"]))}
      {number_input("Label Width mm", "label_width", f'{settings["label_width"]:.2f}')}
      {number_input("Label Height mm", "label_height", f'{settings["label_height"]:.2f}')}
      {number_input("Copies Per Product", "copies_per_product", str(settings["copies_per_product"]))}
      <label class="field">
        <span>Show Price</span>
        <select name="show_price">
          <option value="1" {"selected" if settings["show_price"] else ""}>Yes</option>
          <option value="0" {"selected" if not settings["show_price"] else ""}>No</option>
        </select>
      </label>
      <label class="field">
        <span>Show Product Name</span>
        <select name="show_product_name">
          <option value="1" {"selected" if settings["show_product_name"] else ""}>Yes</option>
          <option value="0" {"selected" if not settings["show_product_name"] else ""}>No</option>
        </select>
      </label>
    </div>
    <button type="submit">Save Barcode Settings</button>
  </form>
</article>"""


def render_tax_rates(message: str = "", error: str = "") -> str:
    rows_data = SettingsRepository().list_tax_rates()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td class="numeric">{row["rate"]:.2f}%</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="2" class="empty">No tax rates found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Tax Rates</h2>
  <p>Create tax rates used by products, purchases, sales, and tax reports.</p>
</div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel">
    <h3>Add Tax Rate</h3>
    <form method="post" action="/settings/tax-rates/create">
      {text_input("Name", "name", required=True)}
      {number_input("Rate %", "rate", "0.00")}
      <button type="submit">Save Tax Rate</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Tax Rates</h3>
    <table>
      <thead><tr><th>Name</th><th>Rate</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_payment_methods(message: str = "", error: str = "") -> str:
    rows_data = SettingsRepository().list_payment_methods()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["method_key"])}</td>
          <td>{status_badge(row["is_active"])}</td>
          <td>{html.escape(row["created_at"])}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="4" class="empty">No payment methods found.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Payment Methods</h2>
  <p>Manage payment method labels used in sale, purchase, deposit, and transaction forms.</p>
</div>
{render_notice(message, error)}
<div class="grid">
  <article class="panel">
    <h3>Add Payment Method</h3>
    <form method="post" action="/settings/payment-methods/create">
      {text_input("Name", "name", required=True)}
      {text_input("Method Key", "method_key", required=True)}
      {status_select()}
      <button type="submit">Save Payment Method</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Payment Methods</h3>
    <table>
      <thead><tr><th>Name</th><th>Key</th><th>Status</th><th>Created</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_printers(message: str = "", error: str = "") -> str:
    rows_data = SettingsRepository().list_printers()
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["printer_type"].title())}</td>
          <td>{html.escape(row["connection_type"].title())}</td>
          <td>{html.escape(row["paper_width"])}</td>
          <td>{html.escape(row["device_name"] or "")}</td>
          <td>{"Yes" if row["is_default"] else "No"}</td>
          <td>{status_badge(row["is_active"])}</td>
        </tr>
        """
        for row in rows_data
    ) or '<tr><td colspan="7" class="empty">No printers configured.</td></tr>'
    return f"""
<div class="page-title">
  <h2>Printers</h2>
  <p>Configure receipt, invoice, and barcode printer names for future print workflows.</p>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Add Printer</h3>
    <form method="post" action="/settings/printers/create">
      <div class="form-grid two-col">
        {text_input("Printer Name", "name", required=True)}
        {text_input("Device Name", "device_name")}
        <label class="field">
          <span>Printer Type</span>
          <select name="printer_type">
            <option value="receipt">Receipt</option>
            <option value="invoice">Invoice</option>
            <option value="barcode">Barcode</option>
          </select>
        </label>
        <label class="field">
          <span>Connection</span>
          <select name="connection_type">
            <option value="windows">Windows Printer</option>
            <option value="usb">USB</option>
            <option value="network">Network</option>
          </select>
        </label>
        <label class="field">
          <span>Paper Width</span>
          <select name="paper_width">
            <option value="80mm">80mm</option>
            <option value="58mm">58mm</option>
            <option value="A4">A4</option>
            <option value="Label">Label</option>
          </select>
        </label>
        <label class="field">
          <span>Default</span>
          <select name="is_default">
            <option value="0">No</option>
            <option value="1">Yes</option>
          </select>
        </label>
        {status_select()}
      </div>
      <button type="submit">Save Printer</button>
    </form>
  </article>
  <article class="panel table-panel">
    <h3>Printer List</h3>
    <table>
      <thead><tr><th>Name</th><th>Type</th><th>Connection</th><th>Paper</th><th>Device</th><th>Default</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>"""


def render_system_health() -> str:
    health = SettingsRepository().system_health()
    rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in [
            ("Database Integrity", str(health["integrity"])),
            ("Database Size", f'{health["database_size_bytes"] / 1024:.2f} KB'),
            ("Products", str(health["products"])),
            ("Sales", str(health["sales"])),
            ("Purchases", str(health["purchases"])),
            ("Users", str(health["users"])),
        ]
    )
    return f"""
<div class="page-title">
  <h2>System Health</h2>
  <p>Read-only database health and record count summary.</p>
</div>
<article class="panel table-panel">
  <table>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_users(
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    repository = UserRepository()
    query = query or {}
    current_user_id = optional_query_int(query, "_user_id")
    users = repository.list_users()
    roles = repository.role_options()
    total_users = len(users)
    active_users = sum(1 for row in users if row["is_active"])
    custom_access = sum(1 for row in users if row["permissions_text"])
    role_count = len(roles)
    rows = ""
    for row in users:
        action = ""
        if row["is_active"] and row["id"] != current_user_id:
            action = f"""
            <form method="post" action="/users/deactivate" class="table-action">
              <input type="hidden" name="user_id" value="{row["id"]}">
              <button type="submit">Deactivate</button>
            </form>"""
        rows += f"""
        <tr>
          <td>{html.escape(row["username"])}</td>
          <td>
            <strong>{html.escape(row["full_name"])}</strong>
            <p class="table-note">{html.escape(row["phone"] or "")} {html.escape(row["email"] or "")}</p>
          </td>
          <td>{html.escape(row["role_name"])}</td>
          <td>
            <strong>{html.escape(row["department"] or "General")}</strong>
            <p class="table-note">{html.escape(row["designation"] or "")}</p>
          </td>
          <td>{html.escape(row["permissions_text"] or "Role defaults")}</td>
          <td class="numeric">{row["sales_commission_rate"]:.2f}%</td>
          <td>{status_badge(row["is_active"])}</td>
          <td>{html.escape(row["created_at"])}</td>
          <td>{action}</td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="9" class="empty">No users found.</td></tr>'

    permissions_html = "".join(
        f"""
        <label class="check-card">
          <input type="checkbox" name="permissions" value="{html.escape(value)}">
          <span>{html.escape(label)}</span>
        </label>
        """
        for label, value in ROLE_PERMISSION_OPTIONS
    )
    role_options_html = "".join(
        f'<option value="{item.id}">{html.escape(item.name)}</option>'
        for item in roles
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Users</h2>
    <p>Manage staff logins with role-first access. Keep daily user setup simple, open advanced details only when needed.</p>
  </div>
  <a class="secondary-link" href="/dashboard?page=Roles">Setup Roles</a>
  <a class="primary-link" href="#add-user-form">Add User</a>
</div>
{render_notice(message, error)}
<section class="user-overview">
  <article><span>Total Users</span><strong>{total_users}</strong></article>
  <article><span>Active Users</span><strong>{active_users}</strong></article>
  <article><span>Roles</span><strong>{role_count}</strong></article>
  <article><span>Custom Access</span><strong>{custom_access}</strong></article>
</section>
<article class="panel table-panel user-list-panel">
  <div class="panel-heading">
    <div>
      <h3>Staff List</h3>
      <p>Start here. Add staff only after the right role exists.</p>
    </div>
    <a class="secondary-link" href="#add-user-form">Add Staff</a>
  </div>
  <table>
    <thead><tr><th>Username</th><th>Profile</th><th>Role</th><th>HRM</th><th>Permissions</th><th>Commission</th><th>Status</th><th>Created</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>
<article class="panel user-form-panel" id="add-user-form">
  <div class="user-form-head">
    <div>
      <span>Staff Setup</span>
      <h3>Add Staff Login</h3>
      <p>Create the login first. Extra access, HRM, bank, and payroll are optional.</p>
    </div>
    <a class="secondary-link" href="/dashboard?page=Roles">Manage Roles</a>
  </div>
  <form method="post" action="/users/create" class="product-form">
    <section class="staff-core-form">
      <div class="form-grid three-col">
        {text_input("Username", "username", required=True)}
        {password_input("Password", "password", required=True)}
        {text_input("Full Name", "full_name", required=True)}
        <label class="field">
          <span>Role</span>
          <select name="role_id" required>{role_options_html}</select>
        </label>
        {text_input("Phone", "phone")}
        <label class="field">
          <span>Status</span>
          <select name="is_active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
          </select>
        </label>
      </div>
    </section>
    <div class="staff-advanced">
      <details>
        <summary><span>Extra Permissions</span><small>Optional access beyond selected role</small></summary>
        <div class="permission-grid">{permissions_html}</div>
      </details>
      <details>
        <summary><span>Contact Details</span><small>Email, address, emergency contact</small></summary>
        <div class="form-grid two-col">
          {text_input("Email", "email")}
          {text_input("Emergency Contact", "emergency_contact")}
        </div>
        <label class="field wide-field">
          <span>Address</span>
          <textarea name="address" rows="3"></textarea>
        </label>
      </details>
      <details>
        <summary><span>Sales Settings</span><small>Commission and monthly target</small></summary>
        <div class="form-grid two-col">
          {number_input("Commission Rate %", "sales_commission_rate", "0.00")}
          {number_input("Monthly Sales Target", "sales_target", "0.00")}
        </div>
      </details>
      <details>
        <summary><span>HRM Details</span><small>Department, designation, joining date</small></summary>
        <div class="form-grid two-col">
          {text_input("Employee No", "employee_no")}
          {text_input("Department", "department")}
          {text_input("Designation", "designation")}
          {date_input_optional("Joining Date", "joining_date", "")}
          <label class="field">
            <span>Employment Type</span>
            <select name="employment_type">
              <option value="">Select type</option>
              <option value="Full Time">Full Time</option>
              <option value="Part Time">Part Time</option>
              <option value="Contract">Contract</option>
              <option value="Temporary">Temporary</option>
            </select>
          </label>
        </div>
      </details>
      <details>
        <summary><span>Bank Details</span><small>Salary payment account information</small></summary>
        <div class="form-grid two-col">
          {text_input("Bank Name", "bank_name")}
          {text_input("Account Name", "bank_account_name")}
          {text_input("Account Number", "bank_account_number")}
          {text_input("Branch", "bank_branch")}
        </div>
      </details>
      <details>
        <summary><span>Payroll</span><small>Salary defaults for future payroll runs</small></summary>
        <div class="form-grid two-col">
          {number_input("Basic Salary", "basic_salary", "0.00")}
          <label class="field">
            <span>Pay Frequency</span>
            <select name="pay_frequency">
              <option value="">Select frequency</option>
              <option value="Monthly">Monthly</option>
              <option value="Weekly">Weekly</option>
              <option value="Daily">Daily</option>
            </select>
          </label>
          {number_input("Allowances", "allowances", "0.00")}
          {number_input("Deductions", "deductions", "0.00")}
        </div>
      </details>
    </div>
    <div class="sticky-form-actions">
      <button type="submit">Save User</button>
      <a href="/dashboard?page=Users">Reset</a>
    </div>
  </form>
</article>"""


def render_roles(message: str = "", error: str = "") -> str:
    repository = UserRepository()
    roles = repository.list_roles()
    user_counts = repository.role_user_counts()
    total_assignments = sum(user_counts.values())
    editable_count = len(roles)
    rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["name"])}</strong>
            <p class="table-note">{user_counts.get(row["id"], 0)} assigned users</p>
          </td>
          <td>{html.escape(row["description"] or "No description")}</td>
          <td>{permission_badges(row["permissions_text"])}</td>
          <td>{html.escape(row["created_at"])}</td>
          <td><a class="table-link" href="#role-{row["id"]}">Open Edit</a></td>
        </tr>
        """
        for row in roles
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No roles found.</td></tr>'

    role_cards = "".join(render_role_edit_card(row, user_counts.get(row["id"], 0)) for row in roles)

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Roles</h2>
    <p>Set staff access profiles first, then assign users to the right role.</p>
  </div>
  <a class="primary-link" href="#add-role-form">Add Role</a>
</div>
{render_notice(message, error)}
<div class="role-stats">
  <article class="metric role-metric"><span>Total Roles</span><strong>{editable_count}</strong></article>
  <article class="metric role-metric"><span>Assigned Users</span><strong>{total_assignments}</strong></article>
  <article class="metric role-metric"><span>Permission Areas</span><strong>{len(ROLE_PERMISSION_OPTIONS)}</strong></article>
  <article class="metric role-metric"><span>Mode</span><strong>Edit</strong></article>
</div>
<article class="panel table-panel role-table-panel">
  <div class="panel-heading">
    <div>
      <h3>Role List</h3>
      <p>Review access profiles and open only the role you need to edit.</p>
    </div>
    <a class="secondary-link" href="#add-role-form">Add Role</a>
  </div>
  <table>
    <thead><tr><th>Role</th><th>Description</th><th>Permissions</th><th>Created</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>
<div class="role-workflow">
  <article class="panel role-create-panel" id="add-role-form">
    <div class="panel-heading">
      <div>
        <h3>Add Role</h3>
        <p>Create the profile name first. Open permissions only when custom access is needed.</p>
      </div>
    </div>
    <form method="post" action="/roles/create" class="role-form">
      <div class="form-grid two-col">
        {text_input("Role Name", "name", required=True)}
        <label class="field">
          <span>Description</span>
          <textarea name="description" rows="3"></textarea>
        </label>
      </div>
      <details class="role-permission-details">
        <summary><span>Permissions</span><small>Select modules for this role</small></summary>
        <div class="permission-grid role-permission-grid">{role_permission_cards()}</div>
      </details>
      <div class="form-actions">
        <button type="submit">Save Role</button>
      </div>
    </form>
  </article>
  <section class="role-edit-stack">
    <div class="panel-heading">
      <div>
        <h3>Edit Roles</h3>
        <p>Each role stays closed until you need to change it.</p>
      </div>
    </div>
    {role_cards}
  </section>
</div>"""


def render_role_edit_card(row: sqlite3.Row, user_count: int) -> str:
    permissions = permissions_set(row["permissions_text"])
    permission_cards = role_permission_cards(permissions)
    return f"""
<details class="role-edit-card" id="role-{row["id"]}">
  <summary>
    <span>{html.escape(row["name"])}</span>
    <small>{user_count} assigned users</small>
  </summary>
  <form method="post" action="/roles/update" class="role-form">
    <input type="hidden" name="role_id" value="{row["id"]}">
    <div class="role-card-head">
      <div>
        <span class="role-chip">{user_count} users</span>
        <h3>{html.escape(row["name"])}</h3>
        <p>{html.escape(row["description"] or "Update this role profile and its access scope.")}</p>
      </div>
      <button type="submit">Update</button>
    </div>
    <div class="form-grid two-col">
      {preset_text_input("Role Name", "name", row["name"], required=True)}
      <label class="field">
        <span>Description</span>
        <textarea name="description" rows="3">{html.escape(row["description"] or "")}</textarea>
      </label>
    </div>
    <details class="role-permission-details" open>
      <summary><span>Permissions</span><small>Update module access</small></summary>
      <div class="permission-grid role-permission-grid">{permission_cards}</div>
    </details>
  </form>
</details>"""


def permissions_set(permissions_text: str | None) -> set[str]:
    if not permissions_text:
        return set()
    return {item.strip() for item in permissions_text.split(",") if item.strip()}


def normalise_permissions(values: list[str]) -> str:
    allowed = {value for _, value in ROLE_PERMISSION_OPTIONS}
    selected = sorted({value.strip() for value in values if value.strip() in allowed})
    return ", ".join(selected)


def role_permission_cards(selected: set[str] | None = None) -> str:
    selected = selected or set()
    return "".join(
        f"""
        <label class="check-card permission-card">
          <input type="checkbox" name="permissions" value="{html.escape(value)}" {"checked" if value in selected else ""}>
          <span>{html.escape(label)}</span>
        </label>
        """
        for label, value in ROLE_PERMISSION_OPTIONS
    )


def permission_badges(permissions_text: str | None) -> str:
    permissions = permissions_set(permissions_text)
    if not permissions:
        return '<span class="badge">No custom access</span>'

    label_lookup = {value: label for label, value in ROLE_PERMISSION_OPTIONS}
    visible = sorted(label_lookup.get(permission, permission) for permission in permissions)
    badges = "".join(f'<span class="badge role-badge">{html.escape(label)}</span>' for label in visible[:4])
    if len(visible) > 4:
        badges += f'<span class="badge role-badge">+{len(visible) - 4} more</span>'
    return f'<div class="role-badges">{badges}</div>'


def render_commission_agents(message: str = "", error: str = "") -> str:
    agents = CommissionAgentRepository().list_agents()
    active_count = sum(1 for row in agents if row["is_active"])
    total_target = sum(float(row["sales_target"] or 0) for row in agents)
    average_rate = (sum(float(row["commission_rate"] or 0) for row in agents) / len(agents)) if agents else 0
    rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["name"])}</strong>
            <p class="table-note">{html.escape(row["agent_code"] or "No code")} · {html.escape(row["territory"] or "No territory")}</p>
          </td>
          <td>
            {html.escape(row["phone"] or "")}
            <p class="table-note">{html.escape(row["email"] or "")}</p>
          </td>
          <td class="numeric">{row["commission_rate"]:.2f}%</td>
          <td class="numeric">{row["sales_target"]:.2f}</td>
          <td>{status_badge(row["is_active"])}</td>
          <td>{html.escape(row["created_at"])}</td>
          <td><a class="table-link" href="#agent-{row["id"]}">Edit</a></td>
        </tr>
        """
        for row in agents
    )
    if not rows:
        rows = '<tr><td colspan="7" class="empty">No sales commission agents added yet.</td></tr>'

    edit_cards = "".join(render_commission_agent_edit_card(row) for row in agents)

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Sales Commission Agents</h2>
    <p>Manage agent profiles, commission rates, sales targets, payout details, and active selling territories.</p>
  </div>
  <a class="primary-link" href="#add-agent-form">Add Agent</a>
</div>
{render_notice(message, error)}
<section class="agent-stats">
  <article class="metric agent-metric"><span>Total Agents</span><strong>{len(agents)}</strong></article>
  <article class="metric agent-metric"><span>Active Agents</span><strong>{active_count}</strong></article>
  <article class="metric agent-metric"><span>Avg. Commission</span><strong>{average_rate:.2f}%</strong></article>
  <article class="metric agent-metric"><span>Monthly Target</span><strong>{total_target:.2f}</strong></article>
</section>
<div class="agent-layout">
  <article class="panel agent-create-panel" id="add-agent-form">
    <div class="panel-heading">
      <div>
        <h3>Add Agent</h3>
        <p>Create a complete sales commission profile with payout and territory details.</p>
      </div>
    </div>
    <form method="post" action="/commission-agents/create" class="agent-form">
      <div class="form-grid two-col">
        {text_input("Name", "name", required=True)}
        {text_input("Agent Code", "agent_code")}
        {text_input("Phone", "phone")}
        {text_input("Email", "email")}
        {number_input("Commission Rate %", "commission_rate", "0.00")}
        {number_input("Monthly Sales Target", "sales_target", "0.00")}
        {text_input("Territory", "territory")}
        {commission_payout_select()}
        {text_input("Payable Account", "payable_account")}
        {agent_status_select(1)}
      </div>
      <label class="field wide-field">
        <span>Address</span>
        <textarea name="address" rows="3"></textarea>
      </label>
      <label class="field wide-field">
        <span>Notes</span>
        <textarea name="notes" rows="3"></textarea>
      </label>
      <div class="form-actions">
        <button type="submit">Save Agent</button>
      </div>
    </form>
  </article>
  <article class="panel table-panel agent-table-panel">
    <h3>Agent List</h3>
    <table>
      <thead>
        <tr>
          <th>Agent</th>
          <th>Contact</th>
          <th>Commission</th>
          <th>Target</th>
          <th>Status</th>
          <th>Created</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </article>
</div>
<div class="agent-edit-grid">
  {edit_cards}
</div>"""


def render_commission_agent_edit_card(row: sqlite3.Row) -> str:
    return f"""
<article class="panel agent-edit-card" id="agent-{row["id"]}">
  <form method="post" action="/commission-agents/update" class="agent-form">
    <input type="hidden" name="agent_id" value="{row["id"]}">
    <div class="agent-card-head">
      <div>
        <span class="agent-chip">{html.escape(row["territory"] or "General")}</span>
        <h3>{html.escape(row["name"])}</h3>
        <p>{html.escape(row["agent_code"] or "No agent code")} · {row["commission_rate"]:.2f}% commission · {row["sales_target"]:.2f} target</p>
      </div>
      <button type="submit">Update</button>
    </div>
    <div class="form-grid two-col">
      {preset_text_input("Name", "name", row["name"], required=True)}
      {preset_text_input("Agent Code", "agent_code", row["agent_code"] or "")}
      {preset_text_input("Phone", "phone", row["phone"] or "")}
      {preset_text_input("Email", "email", row["email"] or "")}
      {preset_number_input("Commission Rate %", "commission_rate", f'{row["commission_rate"]:.2f}')}
      {preset_number_input("Monthly Sales Target", "sales_target", f'{row["sales_target"]:.2f}')}
      {preset_text_input("Territory", "territory", row["territory"] or "")}
      {commission_payout_select(row["payout_frequency"] or "")}
      {preset_text_input("Payable Account", "payable_account", row["payable_account"] or "")}
      {agent_status_select(row["is_active"])}
    </div>
    <label class="field wide-field">
      <span>Address</span>
      <textarea name="address" rows="3">{html.escape(row["address"] or "")}</textarea>
    </label>
    <label class="field wide-field">
      <span>Notes</span>
      <textarea name="notes" rows="3">{html.escape(row["notes"] or "")}</textarea>
    </label>
  </form>
</article>"""


def preset_number_input(label: str, name: str, value: str) -> str:
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="number" min="0" step="0.01" value="{html.escape(value)}">
</label>"""


def commission_payout_select(selected: str = "") -> str:
    options = "".join(
        f'<option value="{html.escape(value)}" {"selected" if selected == value else ""}>{html.escape(label)}</option>'
        for value, label in (
            ("", "Select frequency"),
            ("Per Sale", "Per Sale"),
            ("Weekly", "Weekly"),
            ("Monthly", "Monthly"),
            ("Quarterly", "Quarterly"),
        )
    )
    return f"""
<label class="field">
  <span>Payout Frequency</span>
  <select name="payout_frequency">{options}</select>
</label>"""


def agent_status_select(selected: int) -> str:
    return f"""
<label class="field">
  <span>Status</span>
  <select name="is_active">
    <option value="1" {"selected" if selected else ""}>Active</option>
    <option value="0" {"selected" if not selected else ""}>Inactive</option>
  </select>
</label>"""


def render_backup(message: str = "", error: str = "") -> str:
    service = BackupService()
    service.apply_retention()
    settings = service.get_settings()
    backups = service.list_backups()
    schedule_options = "".join(
        f'<option value="{value}" {"selected" if settings.schedule == value else ""}>{label}</option>'
        for value, label in (("daily", "Daily"), ("weekly", "Weekly"))
    )
    enabled_checked = "checked" if settings.enabled else ""
    last_run = settings.last_run_at.replace("T", " ") if settings.last_run_at else "Not run yet"
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(backup.name)}</td>
          <td>{backup.modified_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
          <td class="numeric">{backup.size_bytes / 1024:.2f} KB</td>
          <td>{status_label("complete") if backup.integrity == "ok" else status_label("attention")} {html.escape(backup.integrity)}</td>
          <td class="actions-cell">
            <form method="post" action="/backup/verify" class="table-action">
              <input type="hidden" name="backup_name" value="{html.escape(backup.name, quote=True)}">
              <button type="submit">Verify</button>
            </form>
            <form method="post" action="/backup/restore" class="table-action restore-action">
              <input type="hidden" name="backup_name" value="{html.escape(backup.name, quote=True)}">
              <input name="restore_confirmation" placeholder="Type RESTORE">
              <button type="submit">Restore</button>
            </form>
          </td>
        </tr>
        """
        for backup in backups
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No backups created yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Backup</h2>
    <p>Create, verify, schedule, retain, and restore SQLite database backups.</p>
  </div>
  <form method="post" action="/backup/create" class="inline-action">
    <button type="submit">Create Backup</button>
  </form>
</div>
{render_notice(message, error)}
<div class="grid contacts-grid">
  <article class="panel">
    <h3>Scheduled Backup</h3>
    <p class="muted-copy">Runs automatically when the system is opened after the selected interval.</p>
    <form method="post" action="/backup/settings">
      <div class="form-grid two-col">
        <label class="field checkbox-field">
          <input type="checkbox" name="enabled" value="1" {enabled_checked}>
          <span>Enable scheduled backup</span>
        </label>
        <label class="field">
          <span>Schedule</span>
          <select name="schedule">{schedule_options}</select>
        </label>
        <label class="field">
          <span>Keep Latest Backups</span>
          <input name="retention_count" type="number" min="1" value="{settings.retention_count}">
        </label>
        <label class="field">
          <span>Last Scheduled Run</span>
          <input value="{html.escape(last_run, quote=True)}" readonly>
        </label>
      </div>
      <button type="submit">Save Backup Settings</button>
    </form>
  </article>
  <article class="panel">
    <h3>Restore Safety</h3>
    <p class="muted-copy">Restore only accepts verified backups. Before restore, the current database is backed up automatically.</p>
    <div class="setup-list">
      <div><strong>1</strong><span>Click Verify and confirm integrity is ok.</span></div>
      <div><strong>2</strong><span>Type RESTORE beside the backup file.</span></div>
      <div><strong>3</strong><span>The system creates a safety backup, then replaces the database.</span></div>
    </div>
  </article>
</div>
<article class="panel table-panel">
  <h3>Backup Files</h3>
  <table>
    <thead><tr><th>File Name</th><th>Created</th><th>Size</th><th>Integrity</th><th>Actions</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</article>"""


def render_woocommerce_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "woocommerce"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual Setup"),
            ("api", "REST API"),
            ("webhook", "Webhook"),
            ("file_import", "CSV / File Import"),
        )
    )
    capabilities = (
        ("Connection", "Store URL, API keys, and status check.", "01"),
        ("Products", "SKU/barcode matching, categories, brands, images, variations.", "02"),
        ("Orders", "Import online orders into POS sales/order history.", "03"),
        ("Stock", "Keep POS and WooCommerce stock aligned after sales and purchases.", "04"),
        ("Customers", "Bring customer phone, email, and address into POS contacts.", "05"),
        ("Conflicts", "Resolve duplicate SKU, price, stock, and missing category problems.", "06"),
    )
    workflow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in capabilities
    )
    mapping_rows = "".join(
        f"""
        <tr>
          <td>{source}</td>
          <td>{target}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for source, target, rule, status in (
            ("WooCommerce SKU", "POS SKU / Barcode", "Exact match first", '<span class="badge ok">Required</span>'),
            ("WooCommerce Category", "POS Category", "Create or map before product sync", '<span class="badge">Setup</span>'),
            ("Online Order", "POS Sale / Sales Order", "Import by order status", '<span class="badge">Planned</span>'),
            ("Payment Method", "POS Payment Method", "COD/card/bank transfer mapping", '<span class="badge">Setup</span>'),
            ("Stock Quantity", "POS Stock Balance", "POS is stock master after setup", '<span class="badge ok">Recommended</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", True),
            ("complete", "Complete", False),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No WooCommerce work items yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No WooCommerce checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>WooCommerce</h2>
    <p>Connect online store products, stock, orders, customers, and payment status with POS.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="woocommerce">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Connection</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>{html.escape(module["endpoint_url"] or "Store URL not set")}</small></article>
  <article><span>Pending Setup</span><strong>{summary["pending"]}</strong><small>Items waiting</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Being prepared</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready items</small></article>
</section>
<section class="woo-workflow">{workflow_cards}</section>
<section class="woo-layout">
  <article class="panel woo-connection-panel">
    <div class="panel-heading">
      <div>
        <h3>Connection Setup</h3>
        <p>Use the WooCommerce store URL and API key label. Keep actual secrets outside screenshots.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="woocommerce">
      <div class="form-grid two-col">
        <label class="field">
          <span>Status</span>
          <select name="is_enabled">
            <option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option>
            <option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option>
          </select>
        </label>
        <label class="field">
          <span>Sync Method</span>
          <select name="connection_mode">{mode_options}</select>
        </label>
        {preset_text_input("Store URL", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("API Key Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field">
        <span>Setup Notes</span>
        <textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea>
      </label>
      <p class="form-hint">Credential format: add lines like consumer_key=ck_xxx and consumer_secret=cs_xxx. You can also put ck_xxx:cs_xxx in API Key Label.</p>
      <div class="form-actions"><button type="submit">Save Connection</button></div>
    </form>
  </article>
  <article class="panel woo-action-panel">
    <div class="panel-heading">
      <div>
        <h3>WooCommerce Actions</h3>
        <p>Run these actions only after saving the store URL and API credentials.</p>
      </div>
    </div>
    <div class="woo-action-list">
      <form method="post" action="/woocommerce/test"><button type="submit">Test Connection</button><span>Check store URL and API authentication.</span></form>
      <form method="post" action="/woocommerce/import-products"><button type="submit">Import Products</button><span>Create/update POS products by WooCommerce SKU.</span></form>
      <form method="post" action="/woocommerce/import-customers"><button type="submit">Import Customers</button><span>Create/update customers by email or phone.</span></form>
      <form method="post" action="/woocommerce/import-orders"><button type="submit">Import Orders</button><span>Bring processing/completed orders into POS sales.</span></form>
      <form method="post" action="/woocommerce/push-stock"><button type="submit">Push Stock</button><span>Update WooCommerce stock from POS mapped products.</span></form>
    </div>
  </article>
</section>
<article class="panel woo-sync-plan">
  <div class="panel-heading">
    <div>
      <h3>Sync Plan</h3>
      <p>Operational order for a clean first setup.</p>
    </div>
  </div>
  <ol class="woo-steps">
    <li><strong>Connect store</strong><span>Save URL, key label, and run check.</span></li>
    <li><strong>Map categories and payment methods</strong><span>Avoid duplicate products and wrong payments.</span></li>
    <li><strong>Import or push products</strong><span>Match by SKU/barcode before creating new items.</span></li>
    <li><strong>Sync orders</strong><span>Bring processing orders into POS for fulfilment.</span></li>
    <li><strong>Reconcile stock</strong><span>Review mismatch report before going live.</span></li>
  </ol>
</article>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Mapping Rules</h3><p>These are the A-Z decisions needed before live sync.</p></div></div>
  <table>
    <thead><tr><th>WooCommerce Field</th><th>POS Field</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{mapping_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add Sync Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="woocommerce">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel woo-conflict-panel">
    <h3>Conflict Checks</h3>
    <div class="coverage-list">
      {coverage_item("Duplicate SKU", "Review")}
      {coverage_item("Stock mismatch", "Review")}
      {coverage_item("Missing category", "Map")}
      {coverage_item("Payment mismatch", "Map")}
      {coverage_item("Failed order import", "Retry")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>WooCommerce Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>Sync History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_manufacturing_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "manufacturing"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual Production"),
            ("api", "Machine / API"),
            ("webhook", "Production Events"),
            ("file_import", "CSV / Batch Import"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("BOM / Recipe", "Define raw materials, quantities, expected output, and wastage.", "01"),
            ("Production Order", "Plan what to manufacture, quantity, location, and dates.", "02"),
            ("Raw Material Issue", "Consume ingredients/components and reduce raw stock.", "03"),
            ("Finished Goods", "Receive produced quantity and increase finished product stock.", "04"),
            ("Wastage", "Record damaged, scrap, by-product, and production loss.", "05"),
            ("Costing & History", "Calculate unit cost and review production records.", "06"),
        )
    )
    process_rows = "".join(
        f"""
        <tr>
          <td>{step}</td>
          <td>{stock_effect}</td>
          <td>{cost_effect}</td>
          <td>{status}</td>
        </tr>
        """
        for step, stock_effect, cost_effect, status in (
            ("Create BOM", "No stock change", "Estimated cost only", '<span class="badge ok">Setup</span>'),
            ("Start Production Order", "Reserve planned raw materials", "Planned production cost", '<span class="badge">Planned</span>'),
            ("Issue Raw Materials", "Raw material stock decreases", "Actual raw material cost", '<span class="badge danger">Stock Out</span>'),
            ("Receive Finished Goods", "Finished product stock increases", "Final cost per unit", '<span class="badge ok">Stock In</span>'),
            ("Record Wastage", "Wastage/scrap tracked", "Adds to production cost", '<span class="badge">Review</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", True),
            ("complete", "Complete", False),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No manufacturing tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No manufacturing checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Manufacturing</h2>
    <p>Plan recipes, consume raw materials, receive finished goods, track wastage, and calculate production cost.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="manufacturing">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>Production control method</small></article>
  <article><span>BOM Setup</span><strong>{summary["pending"]}</strong><small>Pending tasks</small></article>
  <article><span>Production</span><strong>{summary["in_progress"]}</strong><small>In progress tasks</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready items</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Manufacturing Setup</h3>
        <p>Enable production control and choose how production entries are captured.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="manufacturing">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>Production Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Production Endpoint / File Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Batch / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save Manufacturing Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Production Flow</h3>
        <p>Correct order for stock and costing accuracy.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Create BOM / Recipe</strong><span>Finished item, raw materials, qty, output, wastage.</span></li>
      <li><strong>Create Production Order</strong><span>Planned qty, location, dates, and operator.</span></li>
      <li><strong>Issue Raw Materials</strong><span>Reduce raw stock only when production starts.</span></li>
      <li><strong>Receive Finished Goods</strong><span>Increase finished product stock after production.</span></li>
      <li><strong>Close And Cost</strong><span>Apply labour, overhead, wastage, and final unit cost.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Stock And Cost Rules</h3><p>Manufacturing must change stock only at the correct operation point.</p></div></div>
  <table>
    <thead><tr><th>Step</th><th>Stock Effect</th><th>Cost Effect</th><th>Status</th></tr></thead>
    <tbody>{process_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add Manufacturing Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="manufacturing">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>Production Controls</h3>
    <div class="coverage-list">
      {coverage_item("BOM / Recipe", "Setup")}
      {coverage_item("Production Orders", "Plan")}
      {coverage_item("Raw Issue", "Stock Out")}
      {coverage_item("Finished Goods", "Stock In")}
      {coverage_item("Wastage", "Cost")}
      {coverage_item("History", "Excel")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>Manufacturing Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>Production Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_accounting_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "accounting"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual Accounting"),
            ("api", "Accounting API"),
            ("webhook", "Journal Events"),
            ("file_import", "CSV / Excel Export"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Chart of Accounts", "Map cash, bank, sales, purchases, tax, receivable, payable.", "01"),
            ("Journals", "Review sales, purchases, expenses, payments, returns, and stock journals.", "02"),
            ("Ledgers", "Customer, supplier, cash, bank, expense, and tax ledger views.", "03"),
            ("AR / AP", "Customer receivable, supplier payable, aging, and follow-up.", "04"),
            ("Tax & P/L", "Sales tax, purchase tax, net tax, gross profit, net profit.", "05"),
            ("Trial Balance", "Debit/credit balance and accountant export history.", "06"),
        )
    )
    account_rows = "".join(
        f"""
        <tr>
          <td>{account}</td>
          <td>{source}</td>
          <td>{posting}</td>
          <td>{status}</td>
        </tr>
        """
        for account, source, posting, status in (
            ("Cash / Bank", "Payments, deposits, transfers", "Debit cash-in, credit cash-out", '<span class="badge ok">Core</span>'),
            ("Sales Income", "POS sales and invoices", "Credit sales income", '<span class="badge ok">Core</span>'),
            ("COGS / Purchases", "Purchases and stock cost", "Debit cost / purchase account", '<span class="badge">Map</span>'),
            ("Expense Accounts", "Expense module", "Debit selected expense head", '<span class="badge">Map</span>'),
            ("Tax Payable", "Sales tax minus purchase tax", "Net tax summary by period", '<span class="badge">Tax</span>'),
            ("Receivable / Payable", "Customer due / supplier due", "Aging and balance follow-up", '<span class="badge danger">Control</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", True),
            ("complete", "Complete", False),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No accounting tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No accounting checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Accounting</h2>
    <p>Build accountant-ready journals, ledgers, receivables, payables, tax summaries, and export controls.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="accounting">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>Accounting handoff method</small></article>
  <article><span>Pending Setup</span><strong>{summary["pending"]}</strong><small>Mapping tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Journal setup</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Accounting Setup</h3>
        <p>Choose how accounting records are prepared and exported.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="accounting">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>Accounting Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Export Endpoint / Folder", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Accountant / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save Accounting Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Accounting Flow</h3>
        <p>Correct order for clean books and accountant handoff.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Map accounts</strong><span>Cash, bank, sales, purchase, expense, tax, receivable, payable.</span></li>
      <li><strong>Generate journals</strong><span>Sales, purchase, expense, payment, return, stock adjustment.</span></li>
      <li><strong>Review ledgers</strong><span>Customer, supplier, cash, bank, tax, and expense ledgers.</span></li>
      <li><strong>Close period</strong><span>Tax, profit/loss, receivable/payable aging, trial balance.</span></li>
      <li><strong>Export</strong><span>Excel/CSV accountant handoff with history and audit trail.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Chart Of Accounts Mapping</h3><p>Every POS transaction needs a clean accounting destination.</p></div></div>
  <table>
    <thead><tr><th>Account</th><th>POS Source</th><th>Posting Rule</th><th>Status</th></tr></thead>
    <tbody>{account_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add Accounting Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="accounting">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>Accounting Controls</h3>
    <div class="coverage-list">
      {coverage_item("Chart of Accounts", "Map")}
      {coverage_item("Journal Entries", "Review")}
      {coverage_item("Ledgers", "Excel")}
      {coverage_item("Receivable / Payable", "Aging")}
      {coverage_item("Tax Summary", "Period")}
      {coverage_item("Trial Balance", "Check")}
      {coverage_item("Export History", "Audit")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>Accounting Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>Accounting Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_hrm_essentials_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "hrm_essentials"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual HRM"),
            ("api", "Attendance API"),
            ("webhook", "Attendance Events"),
            ("file_import", "CSV / Excel Import"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Staff Profiles", "Employee identity, department, designation, contacts, emergency details.", "01"),
            ("Roles And Access", "Login, role assignment, permissions, active/inactive staff.", "02"),
            ("Attendance", "Daily check-in, check-out, late, absent, leave, and overtime.", "03"),
            ("Leave", "Leave request, type, approval status, and balance.", "04"),
            ("Payroll", "Basic salary, allowances, deductions, overtime, commission, payslip.", "05"),
            ("Reports", "Staff, attendance, leave, payroll, and commission Excel sheets.", "06"),
        )
    )
    rules_rows = "".join(
        f"""
        <tr>
          <td>{area}</td>
          <td>{source}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for area, source, rule, status in (
            ("Staff Profile", "Users module", "User record is HR staff master", '<span class="badge ok">Core</span>'),
            ("Access", "Roles module", "Role controls menus and actions", '<span class="badge ok">Core</span>'),
            ("Attendance", "Manual / device import", "One daily record per staff", '<span class="badge">Setup</span>'),
            ("Leave", "Request / approval", "Approved leave affects attendance", '<span class="badge">Approval</span>'),
            ("Payroll", "Salary + attendance", "Net salary = earnings - deductions", '<span class="badge">Period</span>'),
            ("Commission", "Sales target/rate", "Commission calculated from sales performance", '<span class="badge">Sales</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", True),
            ("complete", "Complete", False),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No HRM tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No HRM checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>HRM / Essentials</h2>
    <p>Manage staff profiles, access, attendance, leave, payroll, commission, documents, and HRM reports.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="hrm_essentials">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>HRM capture method</small></article>
  <article><span>Pending Setup</span><strong>{summary["pending"]}</strong><small>HRM setup tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Active tasks</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>HRM Setup</h3>
        <p>Choose how attendance and HRM records are managed.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="hrm_essentials">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>HRM Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Attendance Endpoint / File Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Device / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save HRM Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>HRM Flow</h3>
        <p>Correct order for staff operations.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Create staff profile</strong><span>Use Users page as employee master.</span></li>
      <li><strong>Assign role and access</strong><span>Set menu permissions through Roles.</span></li>
      <li><strong>Record attendance</strong><span>Daily check-in/out, late, absent, leave, overtime.</span></li>
      <li><strong>Approve leave</strong><span>Leave affects attendance and payroll.</span></li>
      <li><strong>Run payroll</strong><span>Salary, allowances, deductions, commission, payslip.</span></li>
      <li><strong>Export reports</strong><span>Staff, attendance, leave, payroll, commission.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>HRM Control Rules</h3><p>Clear staff setup avoids payroll and access mistakes.</p></div></div>
  <table>
    <thead><tr><th>Area</th><th>Source</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{rules_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add HRM Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="hrm_essentials">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>HRM Controls</h3>
    <div class="coverage-list">
      {coverage_item("Staff Profiles", "Users")}
      {coverage_item("Roles And Access", "Roles")}
      {coverage_item("Attendance", "Daily")}
      {coverage_item("Leave", "Approval")}
      {coverage_item("Payroll", "Period")}
      {coverage_item("Commission", "Sales")}
      {coverage_item("Documents", "Files")}
      {coverage_item("Reports", "Excel")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>HRM Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>HRM Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_hrm_essentials_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    active_tab = (query.get("tab", ["staff"])[0] or "staff").lower()
    tabs = (
        ("staff", "Staff"),
        ("attendance", "Attendance"),
        ("leave", "Leave"),
        ("payroll", "Payroll"),
        ("documents", "Documents"),
        ("reports", "Reports"),
        ("setup", "Setup"),
    )
    valid_tabs = {key for key, _ in tabs}
    if active_tab not in valid_tabs:
        active_tab = "staff"

    hrm = HRMRepository()
    staff = hrm.list_staff()
    staff_options = hrm.staff_options()
    attendance_rows = hrm.list_attendance()
    leave_rows = hrm.list_leaves()
    payroll_rows = hrm.list_payroll()
    document_rows = hrm.list_documents()
    hrm_summary = hrm.summary()
    sync_logs = repository.list_sync_logs("hrm_essentials", limit=12)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'

    def tab_link(tab_key: str, label: str) -> str:
        active = " active" if tab_key == active_tab else ""
        return f'<a class="hrm-tab{active}" href="/dashboard?page=HRM%20%2F%20Essentials&tab={html.escape(tab_key)}">{html.escape(label)}</a>'

    tab_nav = "".join(tab_link(key, label) for key, label in tabs)
    staff_options_html = "".join(
        f'<option value="{item.id}">{html.escape(item.name)}</option>'
        for item in staff_options
    )
    if not staff_options_html:
        staff_options_html = '<option value="">No active staff</option>'

    staff_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["full_name"])}</strong><p class="table-note">{html.escape(row["username"])}</p></td>
          <td>{html.escape(row["role_name"])}</td>
          <td>{html.escape(row["department"] or "")}</td>
          <td>{html.escape(row["designation"] or "")}</td>
          <td class="numeric">{float(row["basic_salary"] or 0):.2f}</td>
          <td>{'<span class="badge ok">Active</span>' if row["is_active"] else '<span class="badge danger">Inactive</span>'}</td>
        </tr>
        """
        for row in staff
    ) or '<tr><td colspan="6" class="empty">No staff added yet. Add staff from Users page.</td></tr>'

    attendance_table_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["attendance_date"])}</td>
          <td>{html.escape(row["full_name"])}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["check_in"] or "")}</td>
          <td>{html.escape(row["check_out"] or "")}</td>
          <td class="numeric">{float(row["overtime_hours"] or 0):.2f}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in attendance_rows
    ) or '<tr><td colspan="7" class="empty">No attendance records yet.</td></tr>'

    leave_table_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["full_name"])}</td>
          <td>{html.escape(row["leave_type"].replace("_", " ").title())}</td>
          <td>{html.escape(row["date_from"])} to {html.escape(row["date_to"])}</td>
          <td class="numeric">{float(row["days"] or 0):.2f}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["reason"] or "")}</td>
          <td class="actions-cell">
            <form method="post" action="/hrm/leave/status" class="table-action"><input type="hidden" name="leave_id" value="{row["id"]}"><input type="hidden" name="status" value="approved"><button type="submit">Approve</button></form>
            <form method="post" action="/hrm/leave/status" class="table-action"><input type="hidden" name="leave_id" value="{row["id"]}"><input type="hidden" name="status" value="rejected"><button type="submit">Reject</button></form>
          </td>
        </tr>
        """
        for row in leave_rows
    ) or '<tr><td colspan="7" class="empty">No leave requests yet.</td></tr>'

    payroll_table_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["pay_period"])}</td>
          <td>{html.escape(row["full_name"])}</td>
          <td class="numeric">{float(row["basic_salary"] or 0):.2f}</td>
          <td class="numeric">{float(row["allowances"] or 0):.2f}</td>
          <td class="numeric">{float(row["commission_amount"] or 0):.2f}</td>
          <td class="numeric">{float(row["deductions"] or 0):.2f}</td>
          <td class="numeric"><strong>{float(row["net_salary"] or 0):.2f}</strong></td>
          <td>{status_label(row["payment_status"])}</td>
        </tr>
        """
        for row in payroll_rows
    ) or '<tr><td colspan="8" class="empty">No payroll records yet.</td></tr>'

    document_table_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["full_name"])}</td>
          <td>{html.escape(row["document_type"])}</td>
          <td>{html.escape(row["document_no"] or "")}</td>
          <td>{html.escape(row["expiry_date"] or "")}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["note"] or "")}</td>
        </tr>
        """
        for row in document_rows
    ) or '<tr><td colspan="6" class="empty">No documents recorded yet.</td></tr>'

    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No HRM checks logged yet.</td></tr>'

    content_by_tab = {
        "staff": f"""
<article class="panel table-panel">
  <div class="panel-heading"><div><h3>Staff Master</h3><p>Staff records come from Users. Add or edit staff details from the Users page.</p></div><a class="secondary-link" href="/dashboard?page=Users">Open Users</a></div>
  <table><thead><tr><th>Staff</th><th>Role</th><th>Department</th><th>Designation</th><th>Basic Salary</th><th>Status</th></tr></thead><tbody>{staff_rows}</tbody></table>
</article>""",
        "attendance": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Mark Attendance</h3>
    <form class="product-form" method="post" action="/hrm/attendance/save">
      <div class="form-grid two-col">
        <label class="field"><span>Staff</span><select name="user_id" required>{staff_options_html}</select></label>
        {date_input_optional("Date", "attendance_date", __import__("datetime").date.today().isoformat())}
        <label class="field"><span>Status</span><select name="status"><option value="present">Present</option><option value="late">Late</option><option value="half_day">Half Day</option><option value="absent">Absent</option><option value="leave">Leave</option></select></label>
        {text_input("Check In", "check_in")}
        {text_input("Check Out", "check_out")}
        {number_input("Overtime Hours", "overtime_hours", "0")}
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Attendance</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Attendance Sheet</h3><table><thead><tr><th>Date</th><th>Staff</th><th>Status</th><th>In</th><th>Out</th><th>OT</th><th>Note</th></tr></thead><tbody>{attendance_table_rows}</tbody></table></article>
</section>""",
        "leave": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Add Leave Request</h3>
    <form class="product-form" method="post" action="/hrm/leave/create">
      <div class="form-grid two-col">
        <label class="field"><span>Staff</span><select name="user_id" required>{staff_options_html}</select></label>
        <label class="field"><span>Leave Type</span><select name="leave_type"><option value="annual">Annual</option><option value="sick">Sick</option><option value="casual">Casual</option><option value="unpaid">Unpaid</option><option value="other">Other</option></select></label>
        {date_input_optional("From Date", "date_from", "")}
        {date_input_optional("To Date", "date_to", "")}
        {number_input("Days", "days", "1")}
      </div>
      <label class="field wide-field"><span>Reason</span><textarea name="reason" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Leave</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Leave Requests</h3><table><thead><tr><th>Staff</th><th>Type</th><th>Period</th><th>Days</th><th>Status</th><th>Reason</th><th>Actions</th></tr></thead><tbody>{leave_table_rows}</tbody></table></article>
</section>""",
        "payroll": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Run Payroll</h3>
    <form class="product-form" method="post" action="/hrm/payroll/save">
      <div class="form-grid two-col">
        <label class="field"><span>Staff</span><select name="user_id" required>{staff_options_html}</select></label>
        {text_input("Pay Period", "pay_period", required=True)}
        {number_input("Basic Salary", "basic_salary", "0")}
        {number_input("Allowances", "allowances", "0")}
        {number_input("Overtime Amount", "overtime_amount", "0")}
        {number_input("Commission Amount", "commission_amount", "0")}
        {number_input("Deductions", "deductions", "0")}
        <label class="field"><span>Payment Status</span><select name="payment_status"><option value="unpaid">Unpaid</option><option value="partial">Partial</option><option value="paid">Paid</option></select></label>
        {date_input_optional("Payment Date", "payment_date", "")}
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Payroll</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Payroll Sheet</h3><table><thead><tr><th>Period</th><th>Staff</th><th>Basic</th><th>Allow.</th><th>Comm.</th><th>Deduct.</th><th>Net</th><th>Status</th></tr></thead><tbody>{payroll_table_rows}</tbody></table></article>
</section>""",
        "documents": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Add Staff Document</h3>
    <form class="product-form" method="post" action="/hrm/documents/create">
      <div class="form-grid two-col">
        <label class="field"><span>Staff</span><select name="user_id" required>{staff_options_html}</select></label>
        {text_input("Document Type", "document_type", required=True)}
        {text_input("Document No", "document_no")}
        {date_input_optional("Expiry Date", "expiry_date", "")}
        <label class="field"><span>Status</span><select name="status"><option value="valid">Valid</option><option value="expiring">Expiring</option><option value="expired">Expired</option><option value="missing">Missing</option></select></label>
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Document</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Document Register</h3><table><thead><tr><th>Staff</th><th>Type</th><th>No</th><th>Expiry</th><th>Status</th><th>Note</th></tr></thead><tbody>{document_table_rows}</tbody></table></article>
</section>""",
        "reports": f"""
<section class="metrics">
  <article class="metric"><span>Staff</span><strong>{hrm_summary["staff"]}</strong></article>
  <article class="metric"><span>Attendance Rows</span><strong>{hrm_summary["attendance"]}</strong></article>
  <article class="metric"><span>Pending Leave</span><strong>{hrm_summary["pending_leave"]}</strong></article>
  <article class="metric"><span>Unpaid Payroll</span><strong>{hrm_summary["unpaid_payroll"]}</strong></article>
</section>
<article class="panel table-panel"><h3>HRM Check History</h3><table><thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead><tbody>{log_rows}</tbody></table></article>""",
        "setup": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>HRM Setup</h3>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="hrm_essentials">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>HRM Mode</span><select name="connection_mode"><option value="manual" {"selected" if module["connection_mode"] == "manual" else ""}>Manual HRM</option><option value="api" {"selected" if module["connection_mode"] == "api" else ""}>Attendance API</option><option value="webhook" {"selected" if module["connection_mode"] == "webhook" else ""}>Attendance Events</option><option value="file_import" {"selected" if module["connection_mode"] == "file_import" else ""}>CSV / Excel Import</option></select></label>
        {preset_text_input("Attendance Endpoint / File Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Device / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save HRM Setup</button></div>
    </form>
  </article>
  <article class="panel"><h3>Workflow</h3><div class="coverage-list">{coverage_item("Staff", "Users")}{coverage_item("Attendance", "Daily")}{coverage_item("Leave", "Approval")}{coverage_item("Payroll", "Monthly")}{coverage_item("Documents", "Expiry")}{coverage_item("Reports", "Excel")}</div></article>
</section>""",
    }

    return f"""
<div class="page-title action-title">
  <div>
    <h2>HRM / Essentials</h2>
    <p>Manage staff, attendance, leave, payroll, documents, and HR reports in one clean workflow.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action"><input type="hidden" name="module_key" value="hrm_essentials"><button type="submit">Run Check</button></form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Staff</span><strong>{hrm_summary["staff"]}</strong><small>Active users</small></article>
  <article><span>Attendance</span><strong>{hrm_summary["attendance"]}</strong><small>Saved rows</small></article>
  <article><span>Pending Leave</span><strong>{hrm_summary["pending_leave"]}</strong><small>Need approval</small></article>
  <article><span>Unpaid Payroll</span><strong>{hrm_summary["unpaid_payroll"]}</strong><small>Open salary rows</small></article>
</section>
<nav class="hrm-tabs">{tab_nav}</nav>
{content_by_tab[active_tab]}"""


def render_crm_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "crm"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual CRM"),
            ("api", "CRM API"),
            ("webhook", "Lead Events"),
            ("file_import", "CSV / Lead Import"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Customers", "Profile, phone, address, group, sales history, payments, due.", "01"),
            ("Leads", "New inquiries, source, interested products, lead status.", "02"),
            ("Follow-ups", "Call, WhatsApp, quotation, and due payment reminders.", "03"),
            ("Quotations", "Draft, sent, accepted, rejected, convert quotation to sale.", "04"),
            ("Segments & Loyalty", "VIP, wholesale, inactive, due, rewards, discounts.", "05"),
            ("Ledger & Reports", "Customer ledger, aging, top customers, inactive customers.", "06"),
        )
    )
    rule_rows = "".join(
        f"""
        <tr>
          <td>{area}</td>
          <td>{source}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for area, source, rule, status in (
            ("Customer Profile", "Customers module", "One customer record per phone/customer code", '<span class="badge ok">Core</span>'),
            ("Lead", "Walk-in, phone, web, WhatsApp", "Track source and next action", '<span class="badge">Pipeline</span>'),
            ("Follow-up", "Lead, quotation, due", "Always keep next follow-up date", '<span class="badge danger">Important</span>'),
            ("Quotation", "POS quotation", "Convert accepted quotation to sale", '<span class="badge ok">Sales</span>'),
            ("Segment", "Purchase/due behavior", "Group customers for pricing and offers", '<span class="badge">Marketing</span>'),
            ("Ledger", "Sales/payments/returns", "Show due balance and aging clearly", '<span class="badge ok">Accounts</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", True),
            ("complete", "Complete", False),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No CRM tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No CRM checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>CRM</h2>
    <p>Manage customers, leads, follow-ups, quotations, loyalty, ledgers, and CRM reports.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="crm">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>CRM capture method</small></article>
  <article><span>Pending</span><strong>{summary["pending"]}</strong><small>CRM setup tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Active tasks</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>CRM Setup</h3>
        <p>Choose how leads, follow-ups, and customer activities are captured.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="crm">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>CRM Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Lead Endpoint / Import Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Campaign / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save CRM Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>CRM Flow</h3>
        <p>Correct customer workflow from inquiry to repeat sale.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Create customer or lead</strong><span>Capture phone, source, interest, and group.</span></li>
      <li><strong>Schedule follow-up</strong><span>Call/WhatsApp/reminder with next date and assigned staff.</span></li>
      <li><strong>Create quotation</strong><span>Send quote and track accepted/rejected status.</span></li>
      <li><strong>Convert to sale</strong><span>Accepted quotation becomes POS sale or sales order.</span></li>
      <li><strong>Track ledger and loyalty</strong><span>Due balance, payments, rewards, and customer value.</span></li>
      <li><strong>Review CRM reports</strong><span>Leads, follow-ups, quotations, inactive customers, top customers.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>CRM Control Rules</h3><p>These rules keep customer follow-up and sales handoff clean.</p></div></div>
  <table>
    <thead><tr><th>Area</th><th>Source</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{rule_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add CRM Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="crm">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>CRM Controls</h3>
    <div class="coverage-list">
      {coverage_item("Customers", "Profile")}
      {coverage_item("Leads", "Pipeline")}
      {coverage_item("Follow-ups", "Next Date")}
      {coverage_item("Quotations", "Convert")}
      {coverage_item("Segments", "Groups")}
      {coverage_item("Loyalty", "Rewards")}
      {coverage_item("Ledger", "Due")}
      {coverage_item("Reports", "Excel")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>CRM Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>CRM Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_crm_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    crm = CRMRepository()
    active_tab = (query.get("tab", ["customers"])[0] or "customers").lower()
    tabs = (
        ("customers", "Customers"),
        ("leads", "Leads"),
        ("followups", "Follow-ups"),
        ("quotations", "Quotations"),
        ("segments", "Segments"),
        ("ledger", "Ledger"),
        ("reports", "Reports"),
        ("setup", "Setup"),
    )
    valid_tabs = {key for key, _ in tabs}
    if active_tab not in valid_tabs:
        active_tab = "customers"

    summary = crm.summary()
    customers = crm.list_customers()
    leads = crm.list_leads()
    followups = crm.list_followups()
    quotations = crm.list_quotations()
    customer_options = crm.customer_options()
    lead_options = crm.lead_options()
    staff_options = crm.staff_options()
    sync_logs = repository.list_sync_logs("crm", limit=12)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'

    def option_rows(options: list[LookupItem], empty_label: str = "None") -> str:
        rows = [f'<option value="">{html.escape(empty_label)}</option>']
        rows.extend(f'<option value="{item.id}">{html.escape(item.name)}</option>' for item in options)
        return "".join(rows)

    def tab_link(tab_key: str, label: str) -> str:
        active = " active" if tab_key == active_tab else ""
        return f'<a class="hrm-tab{active}" href="/dashboard?page=CRM&tab={html.escape(tab_key)}">{html.escape(label)}</a>'

    tab_nav = "".join(tab_link(key, label) for key, label in tabs)
    customer_options_html = option_rows(customer_options, "Select customer")
    lead_options_html = option_rows(lead_options, "Select lead")
    staff_options_html = option_rows(staff_options, "Unassigned")

    customer_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["name"])}</strong><p class="table-note">{html.escape(row["phone"] or "")} {html.escape(row["email"] or "")}</p></td>
          <td>{html.escape(row["city"] or "")}</td>
          <td class="numeric">{int(row["sale_count"] or 0)}</td>
          <td class="numeric">{float(row["sale_total"] or 0):.2f}</td>
          <td class="numeric">{float(row["due_total"] or 0):.2f}</td>
          <td><a class="secondary-link" href="/contacts/ledger?type=customer&id={row["id"]}" target="_blank">Ledger</a></td>
        </tr>
        """
        for row in customers
    ) or '<tr><td colspan="6" class="empty">No customers yet.</td></tr>'

    lead_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["name"])}</strong><p class="table-note">{html.escape(row["phone"] or "")} {html.escape(row["email"] or "")}</p></td>
          <td>{html.escape(row["source"].replace("_", " ").title())}</td>
          <td>{html.escape(row["interested_in"] or "")}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["assigned_name"] or "Unassigned")}</td>
          <td>{html.escape(row["next_followup_date"] or "")}</td>
          <td class="actions-cell">
            <form method="post" action="/crm/leads/status" class="table-action"><input type="hidden" name="lead_id" value="{row["id"]}"><input type="hidden" name="status" value="contacted"><button type="submit">Contacted</button></form>
            <form method="post" action="/crm/leads/status" class="table-action"><input type="hidden" name="lead_id" value="{row["id"]}"><input type="hidden" name="status" value="converted"><button type="submit">Converted</button></form>
            <form method="post" action="/crm/leads/status" class="table-action"><input type="hidden" name="lead_id" value="{row["id"]}"><input type="hidden" name="status" value="lost"><button type="submit">Lost</button></form>
          </td>
        </tr>
        """
        for row in leads
    ) or '<tr><td colspan="7" class="empty">No leads yet.</td></tr>'

    followup_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["due_date"])} {html.escape(row["due_time"] or "")}</td>
          <td><strong>{html.escape(row["lead_name"] or row["customer_name"] or "No party")}</strong></td>
          <td>{html.escape(row["followup_type"].replace("_", " ").title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["assigned_name"] or "Unassigned")}</td>
          <td>{html.escape(row["note"] or "")}</td>
          <td class="actions-cell">
            <form method="post" action="/crm/followups/status" class="table-action"><input type="hidden" name="followup_id" value="{row["id"]}"><input type="hidden" name="status" value="done"><button type="submit">Done</button></form>
            <form method="post" action="/crm/followups/status" class="table-action"><input type="hidden" name="followup_id" value="{row["id"]}"><input type="hidden" name="status" value="missed"><button type="submit">Missed</button></form>
          </td>
        </tr>
        """
        for row in followups
    ) or '<tr><td colspan="7" class="empty">No follow-ups yet.</td></tr>'

    quotation_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["invoice_no"])}</td>
          <td>{html.escape(row["sale_date"])}</td>
          <td>{html.escape(row["customer_name"] or "Walk-in Customer")}</td>
          <td class="numeric">{float(row["total"] or 0):.2f}</td>
          <td>{status_label(row["payment_status"])}</td>
          <td><a class="secondary-link" href="/dashboard?page=Quotations">Open</a></td>
        </tr>
        """
        for row in quotations
    ) or '<tr><td colspan="6" class="empty">No quotations yet.</td></tr>'

    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No CRM checks logged yet.</td></tr>'

    content_by_tab = {
        "customers": f"""
<article class="panel table-panel">
  <div class="panel-heading"><div><h3>Customers</h3><p>Customer master comes from Contacts. Add new customers from the Customers page.</p></div><a class="secondary-link" href="/dashboard?page=Customers">Open Customers</a></div>
  <table><thead><tr><th>Customer</th><th>City</th><th>Sales</th><th>Total</th><th>Due</th><th>Ledger</th></tr></thead><tbody>{customer_rows}</tbody></table>
</article>""",
        "leads": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Add Lead</h3>
    <form class="product-form" method="post" action="/crm/leads/create">
      <div class="form-grid two-col">
        {text_input("Lead Name", "name", required=True)}
        {text_input("Phone", "phone")}
        {text_input("Email", "email")}
        <label class="field"><span>Source</span><select name="source"><option value="walk_in">Walk-in</option><option value="phone">Phone</option><option value="whatsapp">WhatsApp</option><option value="facebook">Facebook</option><option value="website">Website</option><option value="referral">Referral</option><option value="other">Other</option></select></label>
        {text_input("Interested Product / Service", "interested_in")}
        <label class="field"><span>Status</span><select name="status"><option value="new">New</option><option value="contacted">Contacted</option><option value="qualified">Qualified</option><option value="converted">Converted</option><option value="lost">Lost</option></select></label>
        <label class="field"><span>Assigned Staff</span><select name="assigned_user_id">{staff_options_html}</select></label>
        {date_input_optional("Next Follow-up", "next_followup_date", "")}
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Lead</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Lead Pipeline</h3><table><thead><tr><th>Lead</th><th>Source</th><th>Interest</th><th>Status</th><th>Owner</th><th>Next</th><th>Actions</th></tr></thead><tbody>{lead_rows}</tbody></table></article>
</section>""",
        "followups": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>Add Follow-up</h3>
    <form class="product-form" method="post" action="/crm/followups/create">
      <div class="form-grid two-col">
        <label class="field"><span>Lead</span><select name="lead_id">{lead_options_html}</select></label>
        <label class="field"><span>Customer</span><select name="customer_id">{customer_options_html}</select></label>
        <label class="field"><span>Type</span><select name="followup_type"><option value="call">Call</option><option value="whatsapp">WhatsApp</option><option value="visit">Visit</option><option value="email">Email</option><option value="quotation">Quotation</option><option value="payment">Payment</option></select></label>
        {date_input_optional("Due Date", "due_date", __import__("datetime").date.today().isoformat())}
        {text_input("Due Time", "due_time")}
        <label class="field"><span>Status</span><select name="status"><option value="pending">Pending</option><option value="done">Done</option><option value="missed">Missed</option><option value="cancelled">Cancelled</option></select></label>
        <label class="field"><span>Assigned Staff</span><select name="assigned_user_id">{staff_options_html}</select></label>
      </div>
      <label class="field wide-field"><span>Note</span><textarea name="note" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Follow-up</button></div>
    </form>
  </article>
  <article class="panel table-panel"><h3>Follow-up Board</h3><table><thead><tr><th>Due</th><th>Lead / Customer</th><th>Type</th><th>Status</th><th>Owner</th><th>Note</th><th>Actions</th></tr></thead><tbody>{followup_rows}</tbody></table></article>
</section>""",
        "quotations": f"""
<article class="panel table-panel">
  <div class="panel-heading"><div><h3>Quotations</h3><p>Quotations come from the existing POS quotation workflow.</p></div><a class="secondary-link" href="/dashboard?page=Quotations">Create Quotation</a></div>
  <table><thead><tr><th>No</th><th>Date</th><th>Customer</th><th>Total</th><th>Status</th><th>Open</th></tr></thead><tbody>{quotation_rows}</tbody></table>
</article>""",
        "segments": f"""
<section class="metrics">
  <article class="metric"><span>VIP / Top</span><strong>{sum(1 for row in customers if float(row["sale_total"] or 0) >= 10000)}</strong></article>
  <article class="metric"><span>Due Customers</span><strong>{sum(1 for row in customers if float(row["due_total"] or 0) > 0)}</strong></article>
  <article class="metric"><span>New Leads</span><strong>{sum(1 for row in leads if row["status"] == "new")}</strong></article>
  <article class="metric"><span>Lost Leads</span><strong>{sum(1 for row in leads if row["status"] == "lost")}</strong></article>
</section>
<article class="panel"><h3>Customer Segments</h3><div class="coverage-list">{coverage_item("VIP", "High Sale")}{coverage_item("Due", "Payment Follow-up")}{coverage_item("New", "New Leads")}{coverage_item("Inactive", "No Recent Sale")}{coverage_item("Wholesale", "Customer Group")}{coverage_item("Lost", "Lead Review")}</div></article>""",
        "ledger": f"""
<article class="panel table-panel">
  <div class="panel-heading"><div><h3>Customer Ledger</h3><p>Open a customer ledger from the Customers tab or Customers page.</p></div><a class="secondary-link" href="/dashboard?page=Customers">Open Customers</a></div>
  <table><thead><tr><th>Customer</th><th>Phone</th><th>Sales</th><th>Total</th><th>Due</th><th>Ledger</th></tr></thead><tbody>{customer_rows}</tbody></table>
</article>""",
        "reports": f"""
<section class="metrics">
  <article class="metric"><span>Customers</span><strong>{summary["customers"]}</strong></article>
  <article class="metric"><span>Open Leads</span><strong>{summary["open_leads"]}</strong></article>
  <article class="metric"><span>Follow-ups</span><strong>{summary["pending_followups"]}</strong></article>
  <article class="metric"><span>Quotations</span><strong>{summary["quotations"]}</strong></article>
</section>
<article class="panel table-panel"><h3>CRM Check History</h3><table><thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead><tbody>{log_rows}</tbody></table></article>""",
        "setup": f"""
<section class="woo-layout">
  <article class="panel">
    <h3>CRM Setup</h3>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="crm">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>CRM Mode</span><select name="connection_mode"><option value="manual" {"selected" if module["connection_mode"] == "manual" else ""}>Manual CRM</option><option value="api" {"selected" if module["connection_mode"] == "api" else ""}>CRM API</option><option value="webhook" {"selected" if module["connection_mode"] == "webhook" else ""}>Lead Events</option><option value="file_import" {"selected" if module["connection_mode"] == "file_import" else ""}>CSV / Lead Import</option></select></label>
        {preset_text_input("Lead Endpoint / Import Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Campaign / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save CRM Setup</button></div>
    </form>
  </article>
  <article class="panel"><h3>CRM Controls</h3><div class="coverage-list">{coverage_item("Customers", "Contacts")}{coverage_item("Leads", "Pipeline")}{coverage_item("Follow-ups", "Reminder")}{coverage_item("Quotations", "Sales")}{coverage_item("Ledger", "Due")}{coverage_item("Reports", "Summary")}</div></article>
</section>""",
    }

    return f"""
<div class="page-title action-title">
  <div>
    <h2>CRM</h2>
    <p>Manage customers, leads, follow-ups, quotations, segments, ledger, and CRM reports.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action"><input type="hidden" name="module_key" value="crm"><button type="submit">Run Check</button></form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Customers</span><strong>{summary["customers"]}</strong><small>Active customers</small></article>
  <article><span>Open Leads</span><strong>{summary["open_leads"]}</strong><small>Need conversion</small></article>
  <article><span>Follow-ups</span><strong>{summary["pending_followups"]}</strong><small>Pending reminders</small></article>
  <article><span>Quotations</span><strong>{summary["quotations"]}</strong><small>Open quotes</small></article>
</section>
<nav class="hrm-tabs">{tab_nav}</nav>
{content_by_tab[active_tab]}"""


def render_restaurant_kitchen_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "restaurant_kitchen"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Single Counter"),
            ("api", "Kitchen Display API"),
            ("webhook", "Printer / KOT Events"),
            ("file_import", "Manual Table Setup"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Service Type", "Dine-in, takeaway, delivery, counter sale, and parcel flow.", "01"),
            ("Tables", "Floor, table number, waiter, occupied/free/reserved status.", "02"),
            ("KOT", "Kitchen order ticket with item notes, token number, and printer route.", "03"),
            ("Kitchen Display", "New, preparing, ready, served, cancelled, and delay alerts.", "04"),
            ("Billing", "Hold table bill, split bill, service charge, tax, and final receipt.", "05"),
            ("Reports", "Daily restaurant sales, waiter sales, table sales, KOT cancellations.", "06"),
        )
    )
    rule_rows = "".join(
        f"""
        <tr>
          <td>{area}</td>
          <td>{source}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for area, source, rule, status in (
            ("Dining Type", "POS order start", "Select dine-in, takeaway, delivery, or counter before items", '<span class="badge ok">Required</span>'),
            ("Table", "Dine-in order", "Assign floor/table and keep bill open until paid", '<span class="badge">Dine-in</span>'),
            ("KOT", "Food items", "Send kitchen items before final bill; allow item notes", '<span class="badge danger">Important</span>'),
            ("Kitchen Status", "Kitchen screen", "New to preparing to ready to served, with cancel reason", '<span class="badge ok">Core</span>'),
            ("Bill Split", "Checkout", "Support full payment, split payment, and split table bill", '<span class="badge">Billing</span>'),
            ("Reports", "Sales/KOT data", "Show table, waiter, item, cancelled KOT, and delay reports", '<span class="badge ok">Reports</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == "in_progress" else ""}>{label}</option>'
        for value, label in (
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("complete", "Complete"),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No restaurant tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No restaurant checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>Restaurant / Kitchen</h2>
    <p>Run table orders, KOT, kitchen status, takeaway, delivery, billing, and restaurant reports.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="restaurant_kitchen">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>Restaurant service setup</small></article>
  <article><span>Pending</span><strong>{summary["pending"]}</strong><small>Workflow tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Active setup</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Restaurant Setup</h3>
        <p>Choose the service mode and store kitchen printer/display notes.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="restaurant_kitchen">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>Kitchen Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Kitchen Display / Printer Path", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Printer / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save Restaurant Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Restaurant Flow</h3>
        <p>Correct order movement from table to kitchen to final bill.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Select service type</strong><span>Dine-in, takeaway, delivery, or counter sale.</span></li>
      <li><strong>Assign table and waiter</strong><span>Use only for dine-in; keep table bill open.</span></li>
      <li><strong>Add items and send KOT</strong><span>Kitchen receives food items with notes and token.</span></li>
      <li><strong>Update kitchen status</strong><span>Preparing, ready, served, cancelled with reason.</span></li>
      <li><strong>Complete bill</strong><span>Apply tax/service charge, split payment, print receipt.</span></li>
      <li><strong>Review reports</strong><span>Daily sales, waiter sales, item sales, KOT cancellation, delay.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Restaurant Control Rules</h3><p>These rules make the kitchen workflow clear for staff.</p></div></div>
  <table>
    <thead><tr><th>Area</th><th>Source</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{rule_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add Restaurant Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="restaurant_kitchen">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>Restaurant Controls</h3>
    <div class="coverage-list">
      {coverage_item("Dine-in", "Tables")}
      {coverage_item("Takeaway", "Parcel")}
      {coverage_item("Delivery", "Rider")}
      {coverage_item("KOT", "Kitchen")}
      {coverage_item("Kitchen Display", "Status")}
      {coverage_item("Split Bill", "Payment")}
      {coverage_item("Waiter Sales", "Report")}
      {coverage_item("Cancelled KOT", "Audit")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>Restaurant Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>Restaurant Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_saas_super_admin_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "saas_super_admin"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual Tenant Control"),
            ("api", "Billing API"),
            ("webhook", "Subscription Webhooks"),
            ("file_import", "Tenant Import"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Tenants", "Create businesses, assign owner, set active/trial/suspended status.", "01"),
            ("Plans", "Define monthly/yearly plans with user, location, product, and invoice limits.", "02"),
            ("Billing", "Track subscription invoices, renewals, due payments, and expiry dates.", "03"),
            ("Usage Limits", "Monitor users, locations, products, storage, and invoice usage per tenant.", "04"),
            ("Super Admin", "Impersonate safely, reset access, suspend tenant, and review health.", "05"),
            ("Security & Reports", "Audit actions, login activity, MRR, expired plans, and due tenants.", "06"),
        )
    )
    rule_rows = "".join(
        f"""
        <tr>
          <td>{area}</td>
          <td>{source}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for area, source, rule, status in (
            ("Tenant", "Business registration", "Every business needs owner, plan, status, and expiry date", '<span class="badge ok">Required</span>'),
            ("Plan", "Subscription setup", "Limit users, locations, products, invoices, and features", '<span class="badge">Plan</span>'),
            ("Billing", "Subscription payments", "Show paid, pending, overdue, next renewal, and payment history", '<span class="badge danger">Important</span>'),
            ("Usage", "Tenant activity", "Warn before limit, block only after configured grace rules", '<span class="badge ok">Core</span>'),
            ("Super Admin Access", "Support/admin action", "Log every impersonation, reset, suspend, and plan change", '<span class="badge danger">Audit</span>'),
            ("Reports", "All tenants", "Show active tenants, expired plans, MRR, due payments, and churn", '<span class="badge ok">Reports</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == "in_progress" else ""}>{label}</option>'
        for value, label in (
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("complete", "Complete"),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No SaaS admin tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No SaaS admin checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>SaaS / Super Admin</h2>
    <p>Control tenants, subscription plans, billing, usage limits, support access, security, and global reports.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="saas_super_admin">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>Super admin control</small></article>
  <article><span>Pending</span><strong>{summary["pending"]}</strong><small>Admin tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Active setup</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Super Admin Setup</h3>
        <p>Choose tenant control mode and save billing/subscription integration notes.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="saas_super_admin">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>Admin Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("Billing API / Tenant Portal URL", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Billing / Webhook Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save Super Admin Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>SaaS Admin Flow</h3>
        <p>Correct flow from new business signup to renewal and support control.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Create tenant</strong><span>Add business, owner admin, country, location, and login status.</span></li>
      <li><strong>Assign plan</strong><span>Set trial/monthly/yearly plan, limits, start date, and expiry date.</span></li>
      <li><strong>Track billing</strong><span>Record payment, pending amount, renewal invoice, and due date.</span></li>
      <li><strong>Monitor usage</strong><span>Users, locations, products, invoices, storage, and feature usage.</span></li>
      <li><strong>Support tenant</strong><span>Impersonate, reset access, suspend/reactivate, and record reason.</span></li>
      <li><strong>Review reports</strong><span>MRR, active tenants, expired plans, overdue payments, churn, audit log.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>SaaS Control Rules</h3><p>These rules prevent confusion in tenant billing and admin access.</p></div></div>
  <table>
    <thead><tr><th>Area</th><th>Source</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{rule_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add SaaS Admin Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="saas_super_admin">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>Super Admin Controls</h3>
    <div class="coverage-list">
      {coverage_item("Tenants", "Businesses")}
      {coverage_item("Plans", "Limits")}
      {coverage_item("Billing", "Renewal")}
      {coverage_item("Usage", "Quota")}
      {coverage_item("Suspend", "Control")}
      {coverage_item("Login As", "Audit")}
      {coverage_item("MRR", "Report")}
      {coverage_item("Audit Log", "Security")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>SaaS Admin Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>SaaS Admin Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_api_connector_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
) -> str:
    module_key = "api_connector"
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key, limit=12)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual Sync"),
            ("api", "REST API"),
            ("webhook", "Webhook"),
            ("file_import", "CSV / File Import"),
        )
    )
    flow_cards = "".join(
        f"""
        <article class="woo-flow-card">
          <span>{number}</span>
          <strong>{html.escape(title)}</strong>
          <p>{html.escape(text)}</p>
        </article>
        """
        for title, text, number in (
            ("Connection", "Base URL, auth type, token label, timeout, and test connection.", "01"),
            ("Endpoints", "Products, customers, sales, stock, payments, and returns endpoints.", "02"),
            ("Mapping", "Map external fields to POS SKU, customer, sale, payment, and stock fields.", "03"),
            ("Sync Direction", "Import only, export only, two-way sync, manual sync, or scheduled sync.", "04"),
            ("Webhooks", "Receive order, payment, product, stock, and customer update events.", "05"),
            ("Retry & Logs", "Failed API calls, duplicate records, retry queue, audit, and sync history.", "06"),
        )
    )
    mapping_rows = "".join(
        f"""
        <tr>
          <td>{external}</td>
          <td>{pos_field}</td>
          <td>{rule}</td>
          <td>{status}</td>
        </tr>
        """
        for external, pos_field, rule, status in (
            ("External Product ID / SKU", "POS Product / SKU / Barcode", "Match SKU first, create only when allowed", '<span class="badge ok">Required</span>'),
            ("External Customer", "POS Customer", "Match by phone or customer code before creating", '<span class="badge">Mapping</span>'),
            ("External Order", "POS Sale / Sales Order", "Import by order status and prevent duplicate invoices", '<span class="badge ok">Core</span>'),
            ("External Payment", "POS Payment Method", "Map cash/card/bank/online names correctly", '<span class="badge danger">Important</span>'),
            ("External Stock", "POS Stock Balance", "Choose POS master or external master before two-way sync", '<span class="badge">Stock</span>'),
            ("External Return", "POS Sales Return", "Link return to original sale when available", '<span class="badge ok">Audit</span>'),
        )
    )
    endpoint_rows = "".join(
        f"""
        <tr>
          <td>{name}</td>
          <td>{purpose}</td>
          <td>{direction}</td>
          <td>{status}</td>
        </tr>
        """
        for name, purpose, direction, status in (
            ("Products", "Create/update item master, SKU, barcode, image, price", "Import / Export", '<span class="badge ok">Core</span>'),
            ("Customers", "Customer profile, phone, address, group", "Import / Export", '<span class="badge">CRM</span>'),
            ("Orders / Sales", "External orders to POS sale or sales order", "Import", '<span class="badge ok">Sales</span>'),
            ("Stock", "Stock balance updates after purchase/sale/adjustment", "Two-way", '<span class="badge danger">Careful</span>'),
            ("Payments", "Payment status, method, reference, due amount", "Import", '<span class="badge">Accounts</span>'),
            ("Returns", "Refunds and sales returns from external system", "Import", '<span class="badge">Audit</span>'),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == "in_progress" else ""}>{label}</option>'
        for value, label in (
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("complete", "Complete"),
        )
    )
    work_rows = "".join(
        f"""
        <tr>
          <td><strong>{html.escape(row["title"])}</strong><p class="table-note">{html.escape(row["notes"] or "")}</p></td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    ) or '<tr><td colspan="5" class="empty">No API connector tasks yet.</td></tr>'
    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No API checks logged yet.</td></tr>'

    return f"""
<div class="page-title action-title">
  <div>
    <h2>API Connector</h2>
    <p>Connect external systems with POS through API auth, endpoints, mapping, webhooks, retry queue, and logs.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="api_connector">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Mode</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>Integration method</small></article>
  <article><span>Pending</span><strong>{summary["pending"]}</strong><small>Connector tasks</small></article>
  <article><span>In Progress</span><strong>{summary["in_progress"]}</strong><small>Active setup</small></article>
  <article><span>Completed</span><strong>{summary["complete"]}</strong><small>Ready controls</small></article>
</section>
<section class="woo-workflow">{flow_cards}</section>
<section class="woo-layout">
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>Connection Setup</h3>
        <p>Store the base URL and token label. Keep real secrets outside screenshots.</p>
      </div>
    </div>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="api_connector">
      <div class="form-grid two-col">
        <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
        <label class="field"><span>Connector Mode</span><select name="connection_mode">{mode_options}</select></label>
        {preset_text_input("API Base URL / Webhook URL", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Auth / Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
      <div class="form-actions"><button type="submit">Save API Setup</button></div>
    </form>
  </article>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3>API Flow</h3>
        <p>Correct integration flow before allowing live sync.</p>
      </div>
    </div>
    <ol class="woo-steps">
      <li><strong>Configure auth</strong><span>None, API key, bearer token, basic auth, or webhook secret label.</span></li>
      <li><strong>Register endpoints</strong><span>Products, customers, sales, stock, payments, and returns.</span></li>
      <li><strong>Map fields</strong><span>External IDs to POS SKU, customer, invoice, payment, and stock.</span></li>
      <li><strong>Choose sync direction</strong><span>Import, export, two-way, manual, scheduled, or webhook driven.</span></li>
      <li><strong>Handle failures</strong><span>Retry failed calls, resolve duplicate records, and log response details.</span></li>
      <li><strong>Review logs</strong><span>Last sync, success count, failed count, user, and API response history.</span></li>
    </ol>
  </article>
</section>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Endpoint Registry</h3><p>Core endpoints needed for real POS integration.</p></div></div>
  <table>
    <thead><tr><th>Endpoint</th><th>Purpose</th><th>Direction</th><th>Status</th></tr></thead>
    <tbody>{endpoint_rows}</tbody>
  </table>
</article>
<article class="panel table-panel woo-mapping-panel">
  <div class="panel-heading"><div><h3>Field Mapping Rules</h3><p>These decisions prevent duplicate items, wrong payments, and stock mismatch.</p></div></div>
  <table>
    <thead><tr><th>External Field</th><th>POS Field</th><th>Rule</th><th>Status</th></tr></thead>
    <tbody>{mapping_rows}</tbody>
  </table>
</article>
<section class="woo-layout">
  <article class="panel">
    <h3>Add API Task</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="api_connector">
      <div class="form-grid two-col">
        {text_input("Task Title", "title", required=True)}
        <label class="field"><span>Status</span><select name="status">{work_status_options}</select></label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field"><span>Notes</span><textarea name="notes" rows="3"></textarea></label>
      <div class="form-actions"><button type="submit">Save Task</button></div>
    </form>
  </article>
  <article class="panel">
    <h3>Connector Controls</h3>
    <div class="coverage-list">
      {coverage_item("Auth", "Token")}
      {coverage_item("Endpoints", "Registry")}
      {coverage_item("Mapping", "Fields")}
      {coverage_item("Import", "Pull")}
      {coverage_item("Export", "Push")}
      {coverage_item("Webhooks", "Events")}
      {coverage_item("Retry Queue", "Fix")}
      {coverage_item("Logs", "Audit")}
    </div>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>API Connector Work Board</h3>
  <table>
    <thead><tr><th>Task</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>API Connector Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>"""


def render_woocommerce_page(
    repository: AddonRepository,
    module: sqlite3.Row,
    message: str = "",
    error: str = "",
    query: dict[str, list[str]] | None = None,
) -> str:
    query = query or {}
    active_tab = (query.get("tab", ["connection"])[0] or "connection").lower()
    tabs = (
        ("connection", "Connection"),
        ("products", "Products"),
        ("orders", "Orders"),
        ("customers", "Customers"),
        ("stock", "Stock"),
        ("conflicts", "Conflicts"),
        ("logs", "Logs"),
        ("setup", "Setup"),
    )
    valid_tabs = {key for key, _ in tabs}
    if active_tab not in valid_tabs:
        active_tab = "connection"

    sync_logs = repository.list_sync_logs("woocommerce", limit=30)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'

    with get_connection() as connection:
        mappings = list(
            connection.execute(
                """
                SELECT *
                FROM external_sync_mappings
                WHERE source = 'woocommerce'
                ORDER BY last_synced_at DESC, id DESC
                LIMIT 200
                """
            )
        )
        product_count = connection.execute("SELECT COUNT(*) AS count FROM products").fetchone()["count"]
        customer_count = connection.execute("SELECT COUNT(*) AS count FROM contacts WHERE contact_type IN ('customer', 'both')").fetchone()["count"]
        order_count = connection.execute("SELECT COUNT(*) AS count FROM sales WHERE invoice_no LIKE 'WOO-%'").fetchone()["count"]

    mapped_products = [row for row in mappings if row["external_type"] == "product"]
    mapped_customers = [row for row in mappings if row["external_type"] == "customer"]
    mapped_orders = [row for row in mappings if row["external_type"] == "order"]
    failed_logs = [row for row in sync_logs if str(row["status"]).lower() in {"failed", "attention"}]

    def tab_link(tab_key: str, label: str) -> str:
        active = " active" if tab_key == active_tab else ""
        return f'<a class="hrm-tab{active}" href="/dashboard?page=WooCommerce&tab={html.escape(tab_key)}">{html.escape(label)}</a>'

    def action_form(action: str, label: str, note: str) -> str:
        return f"""
        <form method="post" action="{html.escape(action)}" class="woo-tab-action">
          <button type="submit">{html.escape(label)}</button>
          <span>{html.escape(note)}</span>
        </form>"""

    def mapping_rows(rows: list[sqlite3.Row], empty: str) -> str:
        return "".join(
            f"""
            <tr>
              <td>{html.escape(row["external_type"].replace("_", " ").title())}</td>
              <td>{html.escape(row["external_id"])}</td>
              <td>{html.escape(row["local_type"].replace("_", " ").title())} #{row["local_id"]}</td>
              <td>{html.escape(row["payload_summary"] or "")}</td>
              <td>{html.escape(row["last_synced_at"])}</td>
            </tr>
            """
            for row in rows
        ) or f'<tr><td colspan="5" class="empty">{html.escape(empty)}</td></tr>'

    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace("_", " ").title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    ) or '<tr><td colspan="4" class="empty">No WooCommerce logs yet.</td></tr>'

    conflict_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace("_", " ").title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in failed_logs
    ) or '<tr><td colspan="4" class="empty">No failed or attention logs.</td></tr>'

    setup_form = f"""
<article class="panel">
  <h3>Connection Setup</h3>
  <form class="product-form" method="post" action="/addons/update">
    <input type="hidden" name="module_key" value="woocommerce">
    <div class="form-grid two-col">
      <label class="field"><span>Status</span><select name="is_enabled"><option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option><option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option></select></label>
      <label class="field"><span>Sync Method</span><select name="connection_mode"><option value="manual" {"selected" if module["connection_mode"] == "manual" else ""}>Manual Setup</option><option value="api" {"selected" if module["connection_mode"] == "api" else ""}>REST API</option><option value="webhook" {"selected" if module["connection_mode"] == "webhook" else ""}>Webhook</option><option value="file_import" {"selected" if module["connection_mode"] == "file_import" else ""}>CSV / File Import</option></select></label>
      {preset_text_input("Store URL", "endpoint_url", module["endpoint_url"] or "")}
      {preset_text_input("API Key Label", "token_label", module["token_label"] or "")}
    </div>
    <label class="field wide-field"><span>Setup Notes</span><textarea name="notes" rows="4">{html.escape(module["notes"] or "")}</textarea></label>
    <p class="form-hint">Use: consumer_key=ck_xxx and consumer_secret=cs_xxx. Or put ck_xxx:cs_xxx in API Key Label.</p>
    <div class="form-actions"><button type="submit">Save Connection</button></div>
  </form>
</article>"""

    content_by_tab = {
        "connection": f"""
<section class="woo-layout">
  {setup_form}
  <article class="panel">
    <h3>Connection Actions</h3>
    <div class="woo-action-list">
      {action_form("/woocommerce/test", "Test Connection", "Verify store URL and API credentials.")}
      {action_form("/addons/sync/run", "Run Setup Check", "Check pending setup tasks and readiness.").replace('<form method="post" action="/addons/sync/run" class="woo-tab-action">', '<form method="post" action="/addons/sync/run" class="woo-tab-action"><input type="hidden" name="module_key" value="woocommerce">')}
    </div>
  </article>
</section>""",
        "products": f"""
<section class="woo-layout">
  <article class="panel"><h3>Product Sync</h3><div class="woo-action-list">{action_form("/woocommerce/import-products", "Import Products", "Create/update POS products using WooCommerce SKU.")}</div></article>
  <article class="panel"><h3>Product Rules</h3><div class="coverage-list">{coverage_item("SKU", "Primary Match")}{coverage_item("Barcode", "Optional")}{coverage_item("Price", "Woo Price")}{coverage_item("Stock", "Opening Adjust")}</div></article>
</section>
<article class="panel table-panel"><h3>Mapped Products</h3><table><thead><tr><th>Type</th><th>Woo ID</th><th>POS Record</th><th>Summary</th><th>Synced</th></tr></thead><tbody>{mapping_rows(mapped_products, "No WooCommerce products mapped yet.")}</tbody></table></article>""",
        "orders": f"""
<section class="woo-layout">
  <article class="panel"><h3>Order Import</h3><div class="woo-action-list">{action_form("/woocommerce/import-orders", "Import Orders", "Import processing/completed orders into POS sales.")}</div></article>
  <article class="panel"><h3>Order Rules</h3><div class="coverage-list">{coverage_item("Duplicate", "Blocked")}{coverage_item("Product SKU", "Required")}{coverage_item("Customer", "Auto Create")}{coverage_item("Stock", "Validated")}</div></article>
</section>
<article class="panel table-panel"><h3>Imported Orders</h3><table><thead><tr><th>Type</th><th>Woo ID</th><th>POS Record</th><th>Summary</th><th>Synced</th></tr></thead><tbody>{mapping_rows(mapped_orders, "No WooCommerce orders imported yet.")}</tbody></table></article>""",
        "customers": f"""
<section class="woo-layout">
  <article class="panel"><h3>Customer Sync</h3><div class="woo-action-list">{action_form("/woocommerce/import-customers", "Import Customers", "Create/update POS customers using email or phone.")}</div></article>
  <article class="panel"><h3>Customer Rules</h3><div class="coverage-list">{coverage_item("Email", "Match")}{coverage_item("Phone", "Fallback")}{coverage_item("Address", "Billing")}{coverage_item("Duplicates", "Mapped")}</div></article>
</section>
<article class="panel table-panel"><h3>Mapped Customers</h3><table><thead><tr><th>Type</th><th>Woo ID</th><th>POS Record</th><th>Summary</th><th>Synced</th></tr></thead><tbody>{mapping_rows(mapped_customers, "No WooCommerce customers mapped yet.")}</tbody></table></article>""",
        "stock": f"""
<section class="woo-layout">
  <article class="panel"><h3>Stock Push</h3><div class="woo-action-list">{action_form("/woocommerce/push-stock", "Push Stock", "Update WooCommerce stock from mapped POS products.")}</div></article>
  <article class="panel"><h3>Stock Rules</h3><div class="coverage-list">{coverage_item("Master", "POS Stock")}{coverage_item("Mapped Products", str(len(mapped_products)))}{coverage_item("Woo Manage Stock", "Enabled")}{coverage_item("Unmapped", "Skipped")}</div></article>
</section>""",
        "conflicts": f"""
<section class="woo-layout">
  <article class="panel"><h3>Conflict Actions</h3><div class="woo-action-list">{action_form("/woocommerce/test", "Retest Connection", "Check if credentials or store URL are fixed.")}{action_form("/woocommerce/import-products", "Retry Products", "Retry product import after fixing SKU/category issues.")}</div></article>
  <article class="panel"><h3>Conflict Checklist</h3><div class="coverage-list">{coverage_item("Duplicate SKU", "Review")}{coverage_item("Missing SKU", "Fix")}{coverage_item("Missing Product", "Import")}{coverage_item("Stock Failed", "Retry")}</div></article>
</section>
<article class="panel table-panel"><h3>Failed / Attention Logs</h3><table><thead><tr><th>Time</th><th>Action</th><th>Status</th><th>Details</th></tr></thead><tbody>{conflict_rows}</tbody></table></article>""",
        "logs": f"""
<article class="panel table-panel"><h3>WooCommerce Logs</h3><table><thead><tr><th>Time</th><th>Action</th><th>Status</th><th>Details</th></tr></thead><tbody>{log_rows}</tbody></table></article>""",
        "setup": f"""
<section class="woo-layout">
  {setup_form}
  <article class="panel"><h3>Setup Order</h3><ol class="woo-steps"><li><strong>Save credentials</strong><span>Store URL and consumer key/secret.</span></li><li><strong>Test connection</strong><span>Make sure Woo API responds.</span></li><li><strong>Import products</strong><span>SKU mapping starts here.</span></li><li><strong>Import customers/orders</strong><span>Bring online business into POS.</span></li><li><strong>Push stock</strong><span>After product mapping is ready.</span></li></ol></article>
</section>""",
    }

    return f"""
<div class="page-title action-title">
  <div>
    <h2>WooCommerce</h2>
    <p>Connect online store products, orders, customers, stock, conflicts, and sync logs with POS.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/woocommerce/test" class="inline-action"><button type="submit">Test Connection</button></form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="woo-hero">
  <article><span>Store</span><strong>{html.escape(module["connection_mode"].replace("_", " ").title())}</strong><small>{html.escape(module["endpoint_url"] or "Store URL not set")}</small></article>
  <article><span>Products</span><strong>{len(mapped_products)}</strong><small>{int(product_count)} POS products</small></article>
  <article><span>Orders</span><strong>{len(mapped_orders)}</strong><small>{int(order_count)} Woo sales</small></article>
  <article><span>Customers</span><strong>{len(mapped_customers)}</strong><small>{int(customer_count)} POS customers</small></article>
</section>
<nav class="hrm-tabs">{"".join(tab_link(key, label) for key, label in tabs)}</nav>
{content_by_tab[active_tab]}"""


def render_addon_page(module_key: str, message: str = "", error: str = "", query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    repository = AddonRepository()
    module = repository.get_module(module_key)
    if module is None:
        return render_not_found_page("Addon module not found.")
    if module_key == "woocommerce":
        return render_woocommerce_page(repository, module, message, error, query=query)
    if module_key == "manufacturing":
        return render_manufacturing_page(repository, module, message, error)
    if module_key == "accounting":
        return render_accounting_page(repository, module, message, error)
    if module_key == "hrm_essentials":
        return render_hrm_essentials_page(repository, module, message, error, query=query)
    if module_key == "crm":
        return render_crm_page(repository, module, message, error, query=query)
    if module_key == "restaurant_kitchen":
        return render_restaurant_kitchen_page(repository, module, message, error)
    if module_key == "saas_super_admin":
        return render_saas_super_admin_page(repository, module, message, error)
    if module_key == "api_connector":
        return render_api_connector_page(repository, module, message, error)

    modules = repository.list_modules()
    work_items = repository.list_work_items(module_key)
    sync_logs = repository.list_sync_logs(module_key)
    summary = repository.module_summary(module_key)
    status_badge = '<span class="badge ok">Enabled</span>' if module["is_enabled"] else '<span class="badge danger">Disabled</span>'
    module_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{'<span class="badge ok">Enabled</span>' if row["is_enabled"] else '<span class="badge danger">Disabled</span>'}</td>
          <td>{html.escape(row["connection_mode"].replace('_', ' ').title())}</td>
          <td>{html.escape(row["updated_at"])}</td>
        </tr>
        """
        for row in modules
    )

    work_rows = "".join(
        f"""
        <tr>
          <td>
            <strong>{html.escape(row["title"])}</strong>
            <p class="table-note">{html.escape(row["notes"] or "")}</p>
          </td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["owner"] or "Unassigned")}</td>
          <td>{html.escape(row["due_date"] or "")}</td>
          <td class="actions-cell">
            {addon_status_form(row["id"], "in_progress", "Start")}
            {addon_status_form(row["id"], "complete", "Complete")}
            {addon_status_form(row["id"], "pending", "Reopen")}
          </td>
        </tr>
        """
        for row in work_items
    )
    if not work_rows:
        work_rows = '<tr><td colspan="5" class="empty">No addon work items yet.</td></tr>'

    log_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row["created_at"])}</td>
          <td>{html.escape(row["run_type"].replace('_', ' ').title())}</td>
          <td>{status_label(row["status"])}</td>
          <td>{html.escape(row["details"] or "")}</td>
        </tr>
        """
        for row in sync_logs
    )
    if not log_rows:
        log_rows = '<tr><td colspan="4" class="empty">No checks logged yet.</td></tr>'

    mode_options = "".join(
        f'<option value="{value}" {"selected" if module["connection_mode"] == value else ""}>{label}</option>'
        for value, label in (
            ("manual", "Manual"),
            ("api", "API"),
            ("webhook", "Webhook"),
            ("file_import", "File Import"),
        )
    )
    work_status_options = "".join(
        f'<option value="{value}" {"selected" if value == selected else ""}>{label}</option>'
        for value, label, selected in (
            ("pending", "Pending", False),
            ("in_progress", "In Progress", False),
            ("complete", "Complete", True),
        )
    )

    return f"""
<div class="page-title action-title">
  <div>
    <h2>{html.escape(module["name"])}</h2>
    <p>Addon control panel for activation, completion tracking, connection details, and operational checks.</p>
  </div>
  <div class="top-actions">
    <form method="post" action="/addons/sync/run" class="inline-action">
      <input type="hidden" name="module_key" value="{html.escape(module_key)}">
      <button type="submit">Run Check</button>
    </form>
    <div>{status_badge}</div>
  </div>
</div>
{render_notice(message, error)}
<section class="metrics">
  <article class="metric"><span>Pending</span><strong>{summary["pending"]}</strong></article>
  <article class="metric"><span>In Progress</span><strong>{summary["in_progress"]}</strong></article>
  <article class="metric"><span>Complete</span><strong>{summary["complete"]}</strong></article>
  <article class="metric"><span>Mode</span><strong>{html.escape(module["connection_mode"].replace('_', ' ').title())}</strong></article>
</section>
<section class="grid">
  <article class="panel">
    <h3>Addon Configuration</h3>
    <form class="product-form" method="post" action="/addons/update">
      <input type="hidden" name="module_key" value="{html.escape(module_key)}">
      <div class="form-grid two-col">
        <label class="field">
          <span>Status</span>
          <select name="is_enabled">
            <option value="1" {"selected" if module["is_enabled"] else ""}>Enabled</option>
            <option value="0" {"selected" if not module["is_enabled"] else ""}>Disabled</option>
          </select>
        </label>
        <label class="field">
          <span>Connection Mode</span>
          <select name="connection_mode">{mode_options}</select>
        </label>
        {preset_text_input("Endpoint URL", "endpoint_url", module["endpoint_url"] or "")}
        {preset_text_input("Token Label", "token_label", module["token_label"] or "")}
      </div>
      <label class="field wide-field">
        <span>Notes</span>
        <textarea name="notes" rows="5">{html.escape(module["notes"] or "")}</textarea>
      </label>
      <div class="form-actions">
        <button type="submit">Save Addon</button>
      </div>
    </form>
  </article>
  <article class="panel">
    <h3>Add Work Item</h3>
    <form class="product-form" method="post" action="/addons/work/create">
      <input type="hidden" name="module_key" value="{html.escape(module_key)}">
      <div class="form-grid two-col">
        {text_input("Title", "title", required=True)}
        <label class="field">
          <span>Status</span>
          <select name="status">{work_status_options}</select>
        </label>
        {text_input("Owner", "owner")}
        {date_input_optional("Due Date", "due_date", "")}
      </div>
      <label class="field wide-field">
        <span>Notes</span>
        <textarea name="notes" rows="5"></textarea>
      </label>
      <div class="form-actions">
        <button type="submit">Save Work Item</button>
      </div>
    </form>
  </article>
</section>
<article class="panel register-history table-panel">
  <h3>Addon Work Board</h3>
  <table>
    <thead><tr><th>Work Item</th><th>Status</th><th>Owner</th><th>Due</th><th>Actions</th></tr></thead>
    <tbody>{work_rows}</tbody>
  </table>
</article>
<article class="panel register-history table-panel">
  <h3>Check History</h3>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{log_rows}</tbody>
  </table>
</article>
<article class="panel register-history">
  <h3>All Addon Modules</h3>
  <table>
    <thead><tr><th>Module</th><th>Status</th><th>Mode</th><th>Updated</th></tr></thead>
    <tbody>{module_rows}</tbody>
  </table>
</article>"""


def text_input(label: str, name: str, required: bool = False) -> str:
    required_attr = " required" if required else ""
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}"{required_attr}>
</label>"""


def password_input(label: str, name: str, required: bool = False) -> str:
    required_attr = " required" if required else ""
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="password"{required_attr}>
</label>"""


def preset_text_input(label: str, name: str, value: str, required: bool = False) -> str:
    required_attr = " required" if required else ""
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" value="{html.escape(value)}"{required_attr}>
</label>"""


def automatic_barcode_input(value: str = "", input_attributes: str = "") -> str:
    name_attribute = ' name="barcode"' if "data-quick-product-barcode" not in input_attributes else ""
    return f"""
<label class="field barcode-field" data-barcode-field>
  <span>Barcode</span>
  <div class="barcode-input-row">
    <input{name_attribute} value="{html.escape(value, quote=True)}" data-barcode-input {input_attributes}
      placeholder="Scan / enter barcode or generate">
    <button type="button" data-barcode-generate>Auto Generate</button>
  </div>
</label>"""


def date_input(label: str, name: str, value: str) -> str:
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="date" value="{html.escape(value)}" required>
</label>"""


def date_input_optional(label: str, name: str, value: str) -> str:
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="date" value="{html.escape(value)}">
</label>"""


def time_input(label: str, name: str, value: str) -> str:
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="time" value="{html.escape(value)}" required>
</label>"""


def number_input(label: str, name: str, value: str) -> str:
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <input name="{html.escape(name)}" type="number" min="0" step="0.01" value="{html.escape(value)}">
</label>"""


def simple_select(
    label: str,
    name: str,
    options: list[tuple[str, str]],
    selected: str = "",
) -> str:
    option_html = "".join(
        f'<option value="{html.escape(value, quote=True)}" {"selected" if value == selected else ""}>'
        f'{html.escape(option_label)}</option>'
        for value, option_label in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}">{option_html}</select>
</label>"""


def select_input(label: str, name: str, options: list, selected_id: int | None = None) -> str:
    option_html = [f'<option value="" {"selected" if selected_id is None else ""}>None</option>']
    option_html.extend(
        f'<option value="{item.id}" {"selected" if selected_id == item.id else ""}>{html.escape(item.name)}</option>'
        for item in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}">{''.join(option_html)}</select>
</label>"""


def payment_method_select(label: str, name: str, methods: list) -> str:
    active_methods = [method for method in methods if method["is_active"]]
    if not active_methods:
        active_methods = [{"method_key": "cash", "name": "Cash"}]
    options = "".join(
        f'<option value="{html.escape(method["method_key"])}">{html.escape(method["name"])}</option>'
        for method in active_methods
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}">{options}</select>
</label>"""


def status_select() -> str:
    return """
<label class="field">
  <span>Status</span>
  <select name="is_active">
    <option value="1">Active</option>
    <option value="0">Inactive</option>
    </select>
</label>"""


def status_label(status: str) -> str:
    labels = {
        "pending": ("Pending", "danger"),
        "in_progress": ("In Progress", ""),
        "complete": ("Complete", "ok"),
        "attention": ("Attention", "danger"),
        "ready-disabled": ("Ready Disabled", ""),
        "ready": ("Ready", "ok"),
    }
    label, class_name = labels.get(status, (status.replace("_", " ").title(), ""))
    class_attr = f" {class_name}" if class_name else ""
    return f'<span class="badge{class_attr}">{html.escape(label)}</span>'


def addon_status_form(work_item_id: int, status: str, label: str) -> str:
    return f"""
<form method="post" action="/addons/work/status" class="table-action addon-action">
  <input type="hidden" name="work_item_id" value="{work_item_id}">
  <input type="hidden" name="status" value="{html.escape(status)}">
  <button type="submit">{html.escape(label)}</button>
</form>"""


def sale_product_select(label: str, name: str, options: list) -> str:
    option_html = ['<option value="">Select sale product</option>']
    option_html.extend(
        f'<option value="{row["sale_id"]}:{row["product_id"]}">{html.escape(row["name"])}</option>'
        for row in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}" required>{''.join(option_html)}</select>
</label>"""


def purchase_product_select(label: str, name: str, options: list) -> str:
    option_html = ['<option value="">Select purchase product</option>']
    option_html.extend(
        f'<option value="{row["purchase_id"]}:{row["product_id"]}">{html.escape(row["name"])}</option>'
        for row in options
    )
    return f"""
<label class="field">
  <span>{html.escape(label)}</span>
  <select name="{html.escape(name)}" required>{''.join(option_html)}</select>
</label>"""


def render_placeholder(active_page: str) -> str:
    section_name = "Module"
    for section in MENU_SECTIONS:
        if active_page in section["items"]:
            section_name = section["title"]
            break

    rows = [
        ("Module", section_name),
        ("Screen", active_page),
        ("Database", "SQLite service layer pending"),
        ("Permissions", "Role-based access pending"),
        ("Audit Log", "Pending"),
        ("Export/Print", "Pending where applicable"),
    ]
    row_html = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>" for label, value in rows
    )
    return f"""
<div class="page-title">
  <h2>{html.escape(active_page)}</h2>
  <p>{html.escape(section_name)} module screen. Forms, tables, filters, permissions, and database services will be added here.</p>
</div>
<article class="panel">
  <h3>Screen status</h3>
  <strong class="status">Ready for implementation</strong>
  <table>{row_html}</table>
</article>"""


def styles() -> str:
    return """
:root {
  color-scheme: light;
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  --bg: #f6f8fb;
  --surface: #ffffff;
  --surface-muted: #f8fafc;
  --border: #e5e7eb;
  --text: #111827;
  --muted: #64748b;
  --primary: #0f766e;
  --primary-strong: #0b5f59;
  --sidebar: #0b1220;
  --sidebar-soft: #111827;
  --sidebar-border: rgba(148, 163, 184, .16);
  --sidebar-text: #dbeafe;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
a { color: inherit; text-decoration: none; }
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: 304px;
  overflow-y: auto;
  background:
    radial-gradient(circle at 20% 0%, rgba(20, 184, 166, .16), transparent 28%),
    linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
  color: var(--sidebar-text);
  border-right: 1px solid var(--sidebar-border);
  padding: 14px 12px;
}
.brand-card {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 70px;
  padding: 12px;
  border: 1px solid var(--sidebar-border);
  border-radius: 14px;
  background: rgba(15, 23, 42, .72);
  box-shadow: 0 18px 40px rgba(0, 0, 0, .18);
  margin-bottom: 14px;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  color: #ecfeff;
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  font-size: 14px;
  font-weight: 900;
}
.brand { font-size: 17px; font-weight: 900; line-height: 1.1; letter-spacing: 0; }
.brand-sub { margin-top: 3px; color: #94a3b8; font-size: 12px; font-weight: 700; }
.sidebar-nav { display: flex; flex-direction: column; gap: 6px; padding-bottom: 18px; }
.menu-group {
  border: 1px solid transparent;
  border-radius: 12px;
  overflow: hidden;
}
.menu-group.active-group {
  background: rgba(15, 23, 42, .7);
  border-color: rgba(20, 184, 166, .22);
}
.menu-section {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: .04em;
  text-transform: uppercase;
  cursor: pointer;
  list-style: none;
  user-select: none;
  border-radius: 12px;
}
.menu-section::-webkit-details-marker { display: none; }
.menu-section::after {
  content: "";
  margin-left: auto;
  width: 8px;
  height: 8px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg);
  transition: transform .16s ease;
  opacity: .72;
}
.menu-section:hover { background: rgba(148, 163, 184, .10); color: #ffffff; }
.menu-group[open] > .menu-section { color: #ffffff; }
.menu-group[open] > .menu-section::after { transform: rotate(45deg); }
.menu-symbol, .menu-item-symbol {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  color: #5eead4;
}
.menu-symbol {
  width: 18px;
  height: 18px;
}
.menu-item-symbol {
  width: 16px;
  height: 16px;
  color: #94a3b8;
}
.menu-symbol svg, .menu-item-symbol svg {
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.menu-items {
  display: grid;
  gap: 2px;
  padding: 0 6px 8px;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 36px;
  margin: 0;
  padding: 8px 10px;
  border-radius: 10px;
  color: #cbd5e1;
  font-size: 14px;
  font-weight: 650;
}
.menu-item:hover { background: rgba(148, 163, 184, .10); color: #ffffff; }
.menu-item.active {
  background: linear-gradient(135deg, rgba(20, 184, 166, .22), rgba(15, 118, 110, .14));
  color: #ffffff;
  box-shadow: inset 0 0 0 1px rgba(45, 212, 191, .18);
}
.menu-item.active .menu-item-symbol { color: #2dd4bf; }
.app { margin-left: 304px; min-height: 100vh; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 5;
  min-height: 78px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 28px;
  background: rgba(255, 255, 255, .98);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(14px);
}
.topbar h1 { margin: 0; font-size: 24px; font-weight: 900; letter-spacing: 0; }
.topbar p { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.top-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.top-actions a, .panel a, button { border: 1px solid var(--border); background: var(--surface); padding: 9px 13px; border-radius: 10px; font-weight: 750; cursor: pointer; }
.top-actions a:hover, .panel a:hover, button:hover { border-color: var(--primary); color: var(--primary); }
.top-actions .top-icon-action {
  display: inline-grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  padding: 9px;
  border-radius: 9px;
  color: #475569;
}
.top-actions .top-icon-action svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.top-actions .top-icon-action:hover { color: var(--primary-strong); background: #ecfdf8; }
.top-actions .top-icon-logout:hover { border-color: #fecaca; color: #b91c1c; background: #fff1f2; }
.pos-top-context { display: flex; align-items: center; gap: 8px; margin-right: 4px; }
.pos-top-location { display: flex; align-items: center; gap: 7px; min-height: 38px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-muted); }
.pos-top-location small { color: var(--muted); font-size: 10px; font-weight: 900; text-transform: uppercase; }
.pos-top-location strong { font-size: 13px; white-space: nowrap; }
.pos-top-date { color: #4338ca; font-size: 13px; font-weight: 900; white-space: nowrap; }
.content { padding: 28px; }
.page-title h2 { margin: 0; font-size: 28px; }
.page-title p { margin: 6px 0 18px; color: var(--muted); }
.action-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.metric, .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; box-shadow: 0 10px 30px rgba(15, 23, 42, .05); }
.metric span { display: block; color: var(--muted); font-size: 14px; }
.metric strong { display: block; margin-top: 8px; font-size: 26px; }
.role-stats { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.role-metric { min-height: 110px; }
.role-layout { display: grid; grid-template-columns: minmax(360px, .9fr) minmax(520px, 1.1fr); gap: 18px; align-items: start; margin-bottom: 18px; }
.role-workflow { display: grid; grid-template-columns: minmax(360px, .9fr) minmax(520px, 1.1fr); gap: 18px; align-items: start; margin-top: 18px; }
.role-create-panel { border-color: #ccfbf1; background: linear-gradient(180deg, #ffffff 0%, #f8fffd 100%); }
.role-table-panel { min-height: 100%; }
.role-form { margin: 0; }
.role-edit-stack { display: grid; gap: 10px; }
.role-edit-stack > .panel-heading { padding: 0 0 4px; }
.role-edit-card { scroll-margin-top: 96px; border: 1px solid var(--border); border-radius: 8px; background: white; overflow: hidden; }
.role-edit-card > summary,
.role-permission-details > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 14px; cursor: pointer; list-style: none; font-weight: 900; }
.role-edit-card > summary::-webkit-details-marker,
.role-permission-details > summary::-webkit-details-marker { display: none; }
.role-edit-card > summary::after,
.role-permission-details > summary::after { content: "+"; display: grid; place-items: center; width: 24px; height: 24px; border-radius: 999px; background: #ecfeff; color: var(--primary-strong); font-weight: 950; }
.role-edit-card[open] > summary::after,
.role-permission-details[open] > summary::after { content: "-"; }
.role-edit-card > summary small,
.role-permission-details > summary small { margin-left: auto; color: var(--muted); font-size: 12px; font-weight: 750; }
.role-edit-card .role-form { padding: 14px; border-top: 1px solid var(--border); background: #f8fafc; }
.role-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.role-card-head h3 { margin: 8px 0 5px; font-size: 20px; }
.role-card-head p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.role-card-head button { width: auto; min-width: 106px; margin-top: 0; }
.role-chip { display: inline-flex; align-items: center; min-height: 25px; padding: 4px 9px; border-radius: 999px; color: var(--primary-strong); background: #ccfbf1; font-size: 12px; font-weight: 900; }
.role-permission-details { margin-top: 14px; border: 1px solid var(--border); border-radius: 8px; background: white; overflow: hidden; }
.role-permission-grid { margin-top: 0; grid-template-columns: repeat(2, minmax(150px, 1fr)); padding: 0 14px 14px; }
.permission-card { min-height: 44px; transition: border-color .16s ease, background .16s ease, color .16s ease; }
.permission-card:has(input:checked) { border-color: #5eead4; background: #ecfeff; color: var(--primary-strong); }
.role-badges { display: flex; flex-wrap: wrap; gap: 6px; max-width: 360px; }
.role-badge { color: #334155; background: #f1f5f9; }
.agent-stats { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.agent-metric { min-height: 110px; }
.agent-layout { display: grid; grid-template-columns: minmax(400px, .95fr) minmax(560px, 1.05fr); gap: 18px; align-items: start; margin-bottom: 18px; }
.agent-create-panel { border-color: #dbeafe; background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); }
.agent-table-panel { min-height: 100%; }
.agent-form { margin: 0; }
.agent-edit-grid { display: grid; grid-template-columns: repeat(2, minmax(380px, 1fr)); gap: 18px; }
.agent-edit-card { scroll-margin-top: 96px; }
.agent-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.agent-card-head h3 { margin: 8px 0 5px; font-size: 20px; }
.agent-card-head p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.agent-card-head button { width: auto; min-width: 106px; margin-top: 0; }
.agent-chip { display: inline-flex; align-items: center; min-height: 25px; padding: 4px 9px; border-radius: 999px; color: #1d4ed8; background: #dbeafe; font-size: 12px; font-weight: 900; }
.dashboard-hero {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 20px;
  min-height: 178px;
  margin-bottom: 18px;
  padding: 26px;
  border: 1px solid var(--border);
  border-radius: 22px;
  background:
    linear-gradient(135deg, rgba(15, 118, 110, .12), transparent 42%),
    linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: 0 20px 48px rgba(15, 23, 42, .08);
}
.dashboard-hero h2 { margin: 8px 0 8px; font-size: 36px; line-height: 1.05; letter-spacing: 0; }
.dashboard-hero p { max-width: 640px; margin: 0; color: var(--muted); font-size: 15px; line-height: 1.6; }
.hero-kicker { display: inline-flex; align-items: center; min-height: 28px; padding: 5px 10px; border-radius: 999px; color: var(--primary-strong); background: #ccfbf1; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .06em; }
.hero-balance {
  min-width: 260px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 20px;
  border: 1px solid #d1fae5;
  border-radius: 18px;
  background: #f0fdfa;
}
.hero-balance span { color: var(--muted); font-size: 13px; font-weight: 800; text-transform: uppercase; }
.hero-balance strong { margin-top: 8px; color: var(--primary-strong); font-size: 34px; line-height: 1; }
.hero-balance small { margin-top: 10px; color: var(--muted); font-weight: 650; }
.dashboard-overview {
  margin-bottom: 18px;
  padding: 20px;
  border: 1px solid #cbdad6;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 14px 34px rgba(15, 23, 42, .055);
}
.overview-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.overview-kicker { color: var(--primary-strong); font-size: 10px; font-weight: 950; text-transform: uppercase; letter-spacing: .08em; }
.overview-heading h3 { margin: 4px 0 3px; font-size: 24px; }
.overview-heading p { margin: 0; color: var(--muted); font-size: 12px; }
.overview-periods { display: inline-flex; gap: 3px; padding: 3px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-muted); }
.overview-periods button { width: auto; min-height: 32px; margin: 0; padding: 6px 12px; border: 0; border-radius: 5px; color: #64748b; background: transparent; font-size: 11px; font-weight: 900; }
.overview-periods button.active { color: #ffffff; background: var(--primary); box-shadow: 0 5px 12px rgba(13, 148, 136, .18); }
.overview-grid { display: grid; grid-template-columns: 1.25fr 1fr .58fr; gap: 14px; min-height: 230px; }
.overview-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.overview-stat { display: flex; min-width: 0; flex-direction: column; justify-content: center; padding: 14px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); background: #fbfdfc; }
.overview-stat:nth-child(3n) { border-right: 0; }
.overview-stat:nth-child(n+4) { border-bottom: 0; }
.overview-stat-primary { background: #eafaf6; }
.overview-stat > span { color: #64748b; font-size: 10px; font-weight: 900; text-transform: uppercase; }
.overview-stat > strong { margin-top: 7px; overflow: hidden; color: #17201f; font-size: 21px; line-height: 1; text-overflow: ellipsis; }
.overview-stat-primary > strong { color: var(--primary-strong); }
.overview-stat > small { margin-top: 7px; color: #8b9b98; font-size: 9px; }
.overview-trend { display: flex; min-width: 0; flex-direction: column; padding: 14px; border: 1px solid var(--border); border-radius: 7px; background: #fbfdfc; }
.overview-trend-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.overview-trend-head span, .overview-trend-head strong { display: block; }
.overview-trend-head span { color: #64748b; font-size: 10px; font-weight: 900; text-transform: uppercase; }
.overview-trend-head strong { margin-top: 3px; font-size: 13px; }
.overview-trend-head > small { color: #8b9b98; font-size: 9px; }
.overview-bars { display: grid; grid-template-columns: repeat(7, minmax(18px, 1fr)); align-items: end; gap: 7px; height: 156px; margin-top: auto; padding-top: 22px; border-bottom: 1px solid #dce7e4; }
.overview-bar-item { display: grid; grid-template-rows: 14px 1fr 18px; align-items: end; height: 100%; text-align: center; }
.overview-bar-item > span { overflow: hidden; color: #899995; font-size: 7px; text-overflow: ellipsis; }
.overview-bar-item i { display: block; width: min(22px, 72%); min-height: 7px; margin: 0 auto; border-radius: 3px 3px 0 0; background: #46b9a7; transform-origin: bottom; animation: overviewBarIn .55s ease both; }
.overview-bar-item:nth-child(3n) i { background: #ff8877; }
.overview-bar-item small { padding-top: 5px; color: #71817e; font-size: 8px; font-weight: 800; }
.overview-attention { display: grid; grid-template-rows: auto repeat(3, 1fr); border: 1px solid #f0d5d0; border-radius: 7px; overflow: hidden; background: #fffafa; }
.overview-attention > span { padding: 11px 12px; color: #9f4a3d; background: #fff1ee; font-size: 10px; font-weight: 950; text-transform: uppercase; }
.overview-attention a { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 9px; padding: 10px 12px; border-top: 1px solid #f2dfdb; }
.overview-attention a:hover { background: #fff4f1; }
.overview-attention strong { color: #c75545; font-size: 18px; }
.overview-attention small { color: #7f706d; font-size: 9px; line-height: 1.3; }
.value-updated { animation: overviewValue .34s ease; }
.dashboard-section-title { display: flex; align-items: end; justify-content: space-between; gap: 12px; margin: 22px 0 10px; }
.dashboard-section-title h3 { margin: 0; font-size: 16px; }
.dashboard-section-title p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
@keyframes overviewBarIn { from { transform: scaleY(0); opacity: .2; } to { transform: scaleY(1); opacity: 1; } }
@keyframes overviewValue { 50% { color: var(--primary); transform: translateY(-2px); } }
@media (max-width: 1200px) {
  .overview-grid { grid-template-columns: 1fr 1fr; }
  .overview-attention { grid-column: span 2; grid-template-columns: auto repeat(3, 1fr); grid-template-rows: 1fr; min-height: 68px; }
  .overview-attention > span { display: grid; place-items: center; }
  .overview-attention a { border-top: 0; border-left: 1px solid #f2dfdb; }
}
@media (max-width: 760px) {
  .dashboard-overview { padding: 14px; }
  .overview-heading { align-items: stretch; flex-direction: column; }
  .overview-periods { display: grid; grid-template-columns: repeat(3, 1fr); }
  .overview-grid { grid-template-columns: 1fr; }
  .overview-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-stat:nth-child(3n) { border-right: 1px solid var(--border); }
  .overview-stat:nth-child(2n) { border-right: 0; }
  .overview-stat:nth-child(n+4) { border-bottom: 1px solid var(--border); }
  .overview-stat:nth-child(n+5) { border-bottom: 0; }
  .overview-attention { grid-column: auto; grid-template-columns: 1fr; grid-template-rows: auto repeat(3, 1fr); }
  .overview-attention > span { display: block; }
  .overview-attention a { border-top: 1px solid #f2dfdb; border-left: 0; }
}
.dash-metrics { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 14px; margin-bottom: 18px; }
.dash-card {
  min-height: 166px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: white;
  box-shadow: 0 14px 34px rgba(15, 23, 42, .06);
}
.dash-card-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--muted); font-size: 13px; font-weight: 850; }
.dash-card strong { display: block; margin-top: 20px; font-size: 30px; line-height: 1; letter-spacing: 0; }
.dash-card p { margin: 10px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.dash-icon, .dash-action-icon {
  display: inline-grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 13px;
}
.dash-icon svg, .dash-action-icon svg {
  width: 21px;
  height: 21px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dash-icon-sales, .dash-icon-profit { color: #047857; background: #d1fae5; }
.dash-icon-purchase { color: #1d4ed8; background: #dbeafe; }
.dash-icon-product, .dash-icon-stock { color: #7c3aed; background: #ede9fe; }
.dash-icon-cash { color: #b45309; background: #fef3c7; }
.dash-icon-backup { color: #334155; background: #e2e8f0; }
.dash-layout { display: grid; grid-template-columns: 1.15fr .85fr; gap: 18px; }
.dash-panel {
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: white;
  box-shadow: 0 14px 34px rgba(15, 23, 42, .05);
}
.dash-panel-wide { grid-column: span 2; }
.panel-heading { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-heading h3 { margin: 0; font-size: 18px; }
.panel-heading p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
.action-grid { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 12px; }
.dash-action {
  display: grid;
  gap: 8px;
  min-height: 130px;
  align-content: center;
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-muted);
}
.dash-action:hover { border-color: #99f6e4; background: #f0fdfa; color: var(--primary-strong); }
.dash-action strong { font-size: 14px; }
.dash-action small { color: var(--muted); font-size: 12px; font-weight: 650; }
.woo-hero { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.woo-hero article { min-height: 104px; padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: white; box-shadow: 0 14px 36px rgba(15, 23, 42, .05); }
.woo-hero span { display: block; color: var(--muted); font-size: 12px; font-weight: 950; text-transform: uppercase; letter-spacing: .04em; }
.woo-hero strong { display: block; margin-top: 12px; font-size: 26px; line-height: 1; }
.woo-hero small { display: block; margin-top: 10px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.woo-workflow { display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px; }
.woo-flow-card { display: grid; grid-template-columns: 38px 1fr; gap: 5px 12px; min-height: 104px; padding: 14px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.woo-flow-card span { grid-row: 1 / span 2; display: grid; place-items: center; width: 38px; height: 38px; border-radius: 10px; color: var(--primary-strong); background: #ecfeff; font-weight: 950; }
.woo-flow-card strong { font-size: 14px; }
.woo-flow-card p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.woo-layout { display: grid; grid-template-columns: minmax(420px, 1fr) minmax(360px, .85fr); gap: 18px; align-items: start; margin-bottom: 18px; }
.woo-action-list { display: grid; gap: 10px; }
.woo-action-list form { display: grid; grid-template-columns: minmax(150px, 190px) 1fr; gap: 12px; align-items: center; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-muted); }
.woo-action-list button { width: 100%; min-height: 38px; }
.woo-action-list span { color: var(--muted); font-size: 12px; line-height: 1.45; }
.woo-steps { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.woo-steps li { display: grid; gap: 3px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-muted); }
.woo-steps strong { font-size: 13px; }
.woo-steps span { color: var(--muted); font-size: 12px; line-height: 1.45; }
.woo-sync-plan, .woo-mapping-panel { margin-bottom: 18px; }
.hrm-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.hrm-tab { display: inline-flex; align-items: center; min-height: 36px; padding: 0 14px; border: 1px solid transparent; border-radius: 7px; color: var(--muted); font-size: 13px; font-weight: 950; text-decoration: none; }
.hrm-tab:hover, .hrm-tab.active { border-color: rgba(13, 148, 136, .35); color: var(--primary-strong); background: #ecfeff; }
.compact-table th, .compact-table td { padding: 10px 8px; }
.coverage-list { display: grid; gap: 10px; }
.coverage-item { display: flex; align-items: center; justify-content: space-between; min-height: 44px; padding: 10px 12px; border-radius: 12px; background: var(--surface-muted); }
.coverage-item span { color: var(--muted); font-weight: 750; }
.coverage-item strong { color: var(--primary-strong); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.contacts-grid { grid-template-columns: minmax(360px, .85fr) minmax(520px, 1.15fr); }
.quick-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0 0 16px; }
.quick-actions a { display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; color: var(--primary); background: white; font-weight: 850; }
.quick-actions a:hover { border-color: #99f6e4; background: #f0fdfa; color: var(--primary-strong); }
.expense-entry-panel { max-width: 1180px; }
.expense-form-section { padding: 18px 0; border-top: 1px solid var(--border); }
.expense-form-section:first-child { padding-top: 0; border-top: 0; }
.expense-form-section h3 { margin: 0 0 14px; font-size: 17px; }
.expense-type-control { display: grid; grid-template-columns: repeat(3, minmax(140px, 1fr)); gap: 10px; max-width: 620px; }
.expense-type-control label { cursor: pointer; }
.expense-type-control input { position: absolute; opacity: 0; pointer-events: none; }
.expense-type-control span { display: grid; place-items: center; min-height: 48px; border: 1px solid var(--border); border-radius: 8px; background: #f8fafc; font-weight: 900; }
.expense-type-control input:checked + span { border-color: var(--primary); color: white; background: var(--primary); }
.expense-attachment { display: grid; grid-template-columns: minmax(300px, 1fr) auto; align-items: end; gap: 14px; margin-bottom: 14px; padding: 14px; border: 1px dashed #94a3b8; border-radius: 8px; background: #f8fafc; }
.expense-attachment small { padding-bottom: 10px; color: var(--muted); font-weight: 750; }
.expense-list-title .quick-actions { margin: 0; justify-content: flex-end; }
.expense-list-title .quick-actions button { width: auto; margin: 0; }
.expense-filter-panel { margin-bottom: 14px; padding: 14px; }
.expense-filter-grid { display: grid; grid-template-columns: 1.4fr repeat(7, minmax(120px, .8fr)) auto; gap: 9px; align-items: end; margin: 0; }
.expense-filter-grid .field { margin: 0; }
.expense-filter-grid .field span { font-size: 11px; color: var(--muted); }
.expense-filter-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.expense-filter-actions button, .expense-filter-actions a { min-height: 42px; margin: 0; }
.expense-sheet-panel { padding: 0; overflow: hidden; border-radius: 8px; }
.sheet-meta { display: flex; justify-content: space-between; gap: 12px; padding: 11px 14px; border-bottom: 1px solid var(--border); color: var(--muted); font-size: 12px; }
.sheet-meta strong { color: var(--text); }
.expense-sheet-scroll { overflow: auto; max-height: calc(100vh - 390px); }
.expense-sheet { min-width: 1850px; border-collapse: separate; border-spacing: 0; }
.expense-sheet th { position: sticky; top: 0; z-index: 2; padding: 8px 7px; border-right: 1px solid #dbe2ea; border-bottom: 1px solid #cbd5e1; background: #eaf0f6; white-space: nowrap; font-size: 11px; }
.expense-sheet td { height: 38px; padding: 6px 7px; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; white-space: nowrap; font-size: 12px; }
.expense-sheet tbody tr:nth-child(even) { background: #f8fafc; }
.expense-sheet tbody tr:hover { background: #ecfeff; }
.sheet-sort { color: inherit; text-decoration: none; }
.sheet-select { width: 34px; text-align: center; }
.expense-sheet .clip-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.expense-row-actions { display: flex; gap: 4px; }
.expense-row-actions form { margin: 0; }
.expense-row-actions button { width: auto; min-height: 27px; margin: 0; padding: 4px 7px; font-size: 10px; }
.setup-rule-list { display: grid; gap: 9px; }
.setup-rule-list div { display: grid; grid-template-columns: 120px 1fr; gap: 10px; padding: 11px; border: 1px solid var(--border); border-radius: 8px; background: #f8fafc; }
.setup-rule-list span { color: var(--muted); font-size: 13px; }
.checkbox-field { display: flex; align-items: center; flex-direction: row; gap: 9px; min-height: 42px; }
.checkbox-field input { width: auto; }
.report-title .quick-actions { margin: 0; justify-content: flex-end; }
.report-title .quick-actions button { width: auto; margin: 0; }
.report-filter-panel { margin-bottom: 14px; padding: 14px; }
.report-presets { display: flex; gap: 7px; flex-wrap: wrap; margin-bottom: 11px; }
.report-presets a { min-height: 30px; padding: 6px 9px; border: 1px solid var(--border); border-radius: 7px; background: #f8fafc; font-size: 11px; font-weight: 850; }
.report-filter-grid { display: grid; grid-template-columns: minmax(180px, 1.2fr) repeat(7, minmax(118px, .8fr)) auto; gap: 9px; align-items: end; margin: 0; }
.report-filter-grid .field { margin: 0; }
.report-filter-grid .field span { font-size: 11px; color: var(--muted); }
.report-sheet-panel { padding: 0; overflow: hidden; border-radius: 8px; }
.report-sheet-scroll { overflow: auto; max-height: calc(100vh - 410px); }
.report-sheet { min-width: 1450px; border-collapse: separate; border-spacing: 0; }
.report-sheet th { position: sticky; top: 0; z-index: 2; padding: 8px 7px; border-right: 1px solid #dbe2ea; border-bottom: 1px solid #cbd5e1; background: #eaf0f6; white-space: nowrap; font-size: 11px; }
.report-sheet th.sortable-heading { cursor: pointer; user-select: none; }
.report-sheet th.sortable-heading::after { content: " ↕"; color: #94a3b8; }
.report-sheet th.sortable-heading[data-direction="asc"]::after { content: " ↑"; color: var(--primary); }
.report-sheet th.sortable-heading[data-direction="desc"]::after { content: " ↓"; color: var(--primary); }
.report-sheet td { height: 38px; padding: 6px 7px; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; white-space: nowrap; font-size: 12px; }
.report-sheet tbody tr:nth-child(even) { background: #f8fafc; }
.report-sheet tbody tr:hover { background: #ecfeff; }
.stock-history-sheet { min-width: 1900px; }
.stock-history-sheet .negative-stock-row { background: #fff1f2; color: #9f1239; }
.stock-history-sheet .negative-stock-row:hover { background: #ffe4e6; }
.sales-history-filter-grid { display: grid; grid-template-columns: minmax(180px, 1.3fr) repeat(10, minmax(112px, .75fr)) auto; gap: 8px; align-items: end; margin: 0; }
.sales-history-filter-grid .field { margin: 0; }
.sales-history-filter-grid .field span { color: var(--muted); font-size: 11px; }
.sales-history-sheet { min-width: 2800px; }
.sales-history-sheet .clip-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.sales-history-sheet .non-final-sale-row { background: #f8fafc; color: #64748b; }
.sales-history-actions { display: flex; gap: 5px; }
.sales-history-actions .table-link { margin: 0; white-space: nowrap; }
@media print {
  .sidebar, .topbar, .expense-filter-panel, .report-filter-panel, .expense-list-title .quick-actions, .report-title .quick-actions, .expense-row-actions, .sheet-select { display: none !important; }
  .app { margin-left: 0 !important; }
  .content { padding: 0 !important; }
  .expense-sheet-scroll { overflow: visible; max-height: none; }
  .expense-sheet { min-width: 100%; font-size: 8px; }
  .expense-sheet th, .expense-sheet td { position: static; font-size: 8px; padding: 3px; }
  .report-sheet-scroll { overflow: visible; max-height: none; }
  .report-sheet { min-width: 100%; }
  .report-sheet th, .report-sheet td { position: static; font-size: 8px; padding: 3px; }
}

.product-title { margin-bottom: 16px; }
.product-title h2 { margin-top: 5px; }
.product-title p { max-width: 760px; margin-bottom: 0; }
.product-kicker { display: inline-flex; align-items: center; min-height: 26px; padding: 4px 9px; border-radius: 999px; color: var(--primary-strong); background: #ccfbf1; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .04em; }
.product-title-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.product-stats { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.product-metric { min-height: 116px; }
.product-metric small { display: block; margin-top: 8px; color: var(--muted); font-size: 12px; font-weight: 750; }
.product-filter-panel { margin-bottom: 14px; padding: 16px; }
.product-filter-form { display: grid; grid-template-columns: minmax(190px, 1.2fr) repeat(5, minmax(96px, .72fr)) minmax(132px, auto); gap: 10px; align-items: end; margin: 0; }
.product-filter-form .field span { font-size: 12px; color: var(--muted); }
.product-filter-form button { width: auto; min-width: 76px; margin-top: 0; }
.product-search-field input { min-width: 0; }
.product-filter-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; min-width: 0; }
.product-filter-actions .secondary-link { min-height: 42px; padding-inline: 10px; }
.product-viewbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin: 0 0 14px; color: var(--muted); font-weight: 750; }
.product-viewbar strong { color: var(--text); font-size: 18px; }
.segmented-control { display: inline-flex; min-height: 40px; padding: 3px; border: 1px solid var(--border); border-radius: 10px; background: white; }
.segmented-control a { display: inline-flex; align-items: center; justify-content: center; min-width: 72px; margin: 0; padding: 7px 11px; border-radius: 8px; color: var(--muted); font-weight: 850; }
.segmented-control a.active { color: white; background: var(--primary); }
.product-table-panel { padding: 0; overflow-x: hidden; }
.product-table { table-layout: fixed; min-width: 0; }
.product-table th, .product-table td { padding: 9px 7px; vertical-align: middle; font-size: 13px; }
.product-table th { font-size: 12px; }
.product-table .col-product { width: 22%; }
.product-table .col-sku { width: 14%; }
.product-table .col-category { width: 11%; }
.product-table .col-brand { width: 9%; }
.product-table .col-unit { width: 5%; }
.product-table .col-stock { width: 9%; }
.product-table .col-alert { width: 6%; }
.product-table .col-purchase { width: 7%; }
.product-table .col-selling { width: 7%; }
.product-table .col-status { width: 6%; }
.product-table .col-action { width: 12%; }
.product-cell { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; align-items: center; min-width: 0; }
.product-cell strong { display: block; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; }
.product-cell small { display: block; margin-top: 3px; color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-name-col, .product-sku-col, .clip-cell { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.product-sku-col strong { display: block; overflow: hidden; text-overflow: ellipsis; }
.product-table .table-note { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.product-thumb, .product-card-thumb { display: inline-grid; place-items: center; overflow: hidden; border: 1px solid var(--border); background: #f8fafc; color: var(--primary-strong); font-weight: 900; object-fit: cover; }
.product-thumb { width: 42px; height: 42px; border-radius: 10px; }
.product-card-thumb { width: 100%; height: 100%; border-radius: 0; }
.product-thumb-placeholder { background: linear-gradient(135deg, #ecfeff 0%, #f8fafc 100%); }
.selling-price { color: var(--primary-strong); font-weight: 900; }
.compact-stock-badge { min-height: 24px; padding: 3px 7px; font-size: 11px; white-space: normal; line-height: 1.1; }
.product-actions-cell { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; align-items: center; }
.product-actions-cell .table-link { display: inline-flex; align-items: center; justify-content: center; min-height: 28px; margin: 0; padding: 5px 6px; border-radius: 8px; background: #f8fafc; text-align: center; font-size: 12px; line-height: 1; }
.product-actions-cell .table-action { grid-column: 1 / -1; }
.product-actions-cell .table-action button { width: 100%; min-height: 28px; padding: 5px 7px; font-size: 11px; }
.product-card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.product-card { overflow: hidden; border: 1px solid var(--border); border-radius: 14px; background: white; box-shadow: 0 12px 28px rgba(15, 23, 42, .06); }
.product-card-image { height: 180px; background: #f8fafc; }
.product-card-body { display: grid; gap: 13px; padding: 15px; }
.product-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.product-card-head h3 { margin: 0; font-size: 17px; line-height: 1.25; }
.product-card-head p { margin: 5px 0 0; color: var(--muted); font-size: 12px; }
.product-card-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.product-card-meta span { min-height: 25px; padding: 5px 8px; border-radius: 999px; color: #334155; background: #f1f5f9; font-size: 12px; font-weight: 800; }
.product-card-bottom { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.product-card-bottom small { display: block; color: var(--muted); font-size: 12px; font-weight: 800; }
.product-card-bottom strong { display: block; margin-top: 4px; color: var(--primary-strong); font-size: 24px; line-height: 1; }
.product-card-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.product-card-actions a { margin-top: 0; }
.product-empty { grid-column: 1 / -1; }
.product-form-panel { max-width: 1180px; }
.product-form-section { padding: 18px 0; border-top: 1px solid var(--border); }
.product-form-section:first-of-type { border-top: 0; padding-top: 0; }
.product-image-uploader { display: grid; grid-template-columns: 180px minmax(260px, 1fr); gap: 18px; align-items: stretch; margin-bottom: 20px; padding: 16px; border: 1px solid var(--border); border-radius: 14px; background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); }
.product-upload-preview { display: grid; place-items: center; min-height: 170px; overflow: hidden; border: 1px dashed #94a3b8; border-radius: 12px; background: white; color: var(--muted); font-weight: 900; }
.product-upload-preview img { width: 100%; height: 100%; object-fit: cover; }
.product-upload-controls { display: grid; align-content: start; gap: 12px; }
.product-upload-controls .field { margin: 0; }
.product-upload-controls .hint { margin: 0; }
.product-edit-preview { display: grid; grid-template-columns: 88px 1fr; gap: 14px; align-items: center; margin-bottom: 18px; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-muted); }
.product-edit-preview .product-card-thumb { width: 88px; height: 88px; border-radius: 12px; }
.product-edit-preview strong { display: block; font-size: 18px; }
.product-edit-preview span { display: block; margin-top: 5px; color: var(--muted); font-weight: 750; }
.label-page-title { margin-bottom: 16px; }
.label-toolbar { display: grid; grid-template-columns: repeat(3, minmax(150px, 1fr)); gap: 14px; margin-bottom: 16px; }
.label-sheet-panel { padding: 18px; background: #f8fafc; }
.label-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; }
.label-box { min-height: 132px; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; color: #111827; box-shadow: 0 8px 18px rgba(15, 23, 42, .06); break-inside: avoid; }
.label-brand { color: var(--primary-strong); font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }
.label-box strong { display: block; min-height: 34px; margin-top: 5px; font-size: 14px; line-height: 1.2; }
.label-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; font-size: 11px; }
.label-meta span { color: #64748b; font-weight: 900; }
.label-meta b { font-size: 11px; }
.label-bars { display: flex; align-items: stretch; justify-content: center; gap: 2px; height: 34px; margin-top: 8px; padding: 4px 6px; background: #fff; border: 1px solid #e5e7eb; }
.label-bars span { display: block; background: #111827; min-width: 1px; }
.barcode-text { margin-top: 4px; text-align: center; font-family: Consolas, 'Courier New', monospace; font-size: 11px; letter-spacing: .04em; }
.label-price { margin-top: 6px; text-align: right; font-size: 18px; font-weight: 950; color: var(--primary-strong); }
.pos-shell { display: grid; grid-template-columns: minmax(440px, 1.08fr) minmax(390px, .92fr); grid-template-rows: minmax(650px, calc(100vh - 235px)) auto; gap: 10px; align-items: stretch; margin: 0; }
.pos-catalog, .pos-cart-panel { min-width: 0; border: 1px solid var(--border); border-radius: 8px; background: white; box-shadow: 0 8px 24px rgba(15, 23, 42, .05); }
.pos-cart-panel { display: flex; flex-direction: column; overflow-x: hidden; overflow-y: auto; padding: 12px; scrollbar-width: thin; }
.pos-catalog { position: relative; display: flex; flex-direction: column; padding: 12px; overflow: hidden; }
.pos-customer-bar { display: grid; grid-template-columns: 1fr 42px; gap: 8px; align-items: end; }
.pos-customer-bar .field, .pos-cart-search .field { margin: 0; }
.pos-icon-link { display: inline-grid; place-items: center; min-height: 42px; border: 1px solid #2563eb; border-radius: 8px; color: white; background: #2563eb; font-size: 23px; font-weight: 700; text-decoration: none; }
.pos-cart-search { margin-top: 8px; }
.pos-search input { min-height: 44px; font-size: 15px; }
.pos-catalog-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.pos-catalog-head h3 { margin: 2px 0 0; font-size: 17px; }
.pos-kicker { color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; }
.pos-count { display: grid; place-items: center; min-width: 80px; min-height: 44px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-muted); }
.pos-count strong { font-size: 18px; line-height: 1; }
.pos-count span { color: var(--muted); font-size: 11px; font-weight: 800; }
.pos-filter-block { display: grid; grid-template-columns: 66px minmax(0, 1fr); gap: 8px; align-items: center; margin-bottom: 7px; }
.pos-filter-label { color: #334155; font-size: 12px; font-weight: 900; }
.pos-filter-row { display: flex; gap: 6px; overflow-x: auto; padding: 2px 1px 5px; scrollbar-width: thin; }
.pos-filter-chip { flex: 0 0 auto; width: auto; min-height: 30px; margin: 0; padding: 5px 10px; border: 1px solid #cbd5e1; border-radius: 7px; color: #334155; background: white; font-size: 12px; font-weight: 800; }
.pos-filter-chip.active { border-color: #2563eb; color: white; background: #2563eb; }
.pos-browser-tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 0 0 10px; }
.pos-browser-tab { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; margin: 0; padding: 7px 10px; border: 1px solid #dbe4f0; border-radius: 999px; background: #fff; color: #172033; box-shadow: 0 8px 18px rgba(15, 23, 42, .05); font-weight: 900; white-space: nowrap; overflow: hidden; }
.pos-browser-tab span:not(.pos-browser-tab-icon) { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.pos-browser-tab-icon { display: inline-grid; place-items: center; flex: 0 0 18px; width: 18px; height: 18px; color: #2563eb; }
.pos-browser-tab-icon svg { width: 18px; height: 18px; stroke-width: 2.4; }
.pos-browser-tab strong { display: inline-grid; place-items: center; flex: 0 0 auto; min-width: 28px; height: 18px; padding: 0 8px; border-radius: 999px; background: #ede9fe; color: #4f46e5; font-size: 11px; }
.pos-browser-tab.active { border-color: #c7d2fe; background: #f8fbff; color: #0f172a; box-shadow: 0 12px 26px rgba(37, 99, 235, .12); }
.pos-browser-tab[data-pos-featured-filter] .pos-browser-tab-icon { color: #f59e0b; }
.pos-browser-overlay { position: fixed; inset: 0; z-index: 1000; background: rgba(15, 23, 42, .42); backdrop-filter: blur(1px); }
.pos-browser-drawer { position: fixed; z-index: 1001; top: 0; right: 0; width: min(520px, 92vw); height: 100vh; padding: 20px; border-left: 1px solid #e2e8f0; background: #fff; box-shadow: -22px 0 50px rgba(15, 23, 42, .16); overflow-y: auto; animation: posDrawerIn .18s ease-out both; }
.pos-browser-drawer[hidden], .pos-browser-overlay[hidden] { display: none; }
.pos-browser-drawer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding-bottom: 18px; margin-bottom: 18px; border-bottom: 1px solid #edf2f7; }
.pos-browser-drawer-head h3 { margin: 0 0 8px; font-size: 24px; line-height: 1.1; }
.pos-browser-drawer-head span { color: #64748b; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .12em; }
.pos-browser-drawer-head button { display: inline-grid; place-items: center; width: 38px; height: 38px; margin: 0; border: 0; border-radius: 12px; background: #f1f5f9; color: #64748b; font-size: 22px; line-height: 1; }
.pos-drawer-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.pos-drawer-tile { display: grid; place-items: center; min-height: 78px; margin: 0; padding: 14px; border: 1px solid #dbe4f0; border-radius: 10px; background: #fff; color: #111827; box-shadow: none; font-weight: 900; text-align: center; }
.pos-drawer-tile span { min-width: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pos-drawer-tile:hover, .pos-drawer-tile.active { border-color: #93c5fd; background: #eff6ff; color: #1d4ed8; }
.pos-card-modal { position: fixed; inset: 0; z-index: 1100; display: grid; place-items: center; padding: 20px; background: rgba(15, 23, 42, .46); backdrop-filter: blur(2px); }
.pos-card-modal[hidden] { display: none; }
.pos-card-dialog { width: min(560px, calc(100vw - 32px)); border: 1px solid #dbe4f0; border-radius: 14px; background: #fff; box-shadow: 0 28px 70px rgba(15, 23, 42, .22); padding: 18px; animation: posDrawerIn .16s ease-out both; }
.pos-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 14px; margin-bottom: 14px; border-bottom: 1px solid #e5eaf2; }
.pos-card-head span { color: #0f766e; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }
.pos-card-head h3 { margin: 4px 0 0; font-size: 22px; }
.pos-card-head > strong { display: grid; place-items: center; min-width: 126px; min-height: 48px; border-radius: 12px; background: #ecfdf5; color: #047857; font-size: 18px; }
.pos-card-help { margin: 10px 0 0; color: #64748b; font-size: 12px; line-height: 1.45; }
.pos-card-actions { display: flex; justify-content: flex-end; gap: 10px; padding-top: 14px; margin-top: 14px; border-top: 1px solid #e5eaf2; }
.pos-card-actions button { width: auto; min-width: 140px; margin: 0; }
@keyframes posDrawerIn { from { transform: translateX(18px); opacity: .6; } to { transform: translateX(0); opacity: 1; } }
.pos-product-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; overflow-y: auto; padding: 2px 3px 8px 1px; }
.pos-product-tile { display: grid; grid-template-rows: 86px minmax(50px, auto) auto; gap: 6px; min-width: 0; min-height: 176px; padding: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: white; color: var(--text); text-align: left; cursor: pointer; }
.pos-product-tile:hover { border-color: #2563eb; box-shadow: 0 5px 14px rgba(37, 99, 235, .12); }
.pos-product-tile:disabled { cursor: not-allowed; opacity: .58; }
.pos-product-image { display: block; height: 86px; background: #f8fafc; }
.pos-product-info { display: grid; align-content: start; gap: 3px; min-width: 0; padding: 0 8px; }
.pos-product-info strong { overflow: hidden; font-size: 12px; line-height: 1.25; }
.pos-product-info small { overflow: hidden; color: var(--muted); font-size: 10px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.pos-product-foot { display: grid; gap: 3px; padding: 0 8px 8px; }
.pos-product-foot b { color: var(--primary-strong); font-size: 15px; }
.pos-product-foot .badge { justify-self: start; min-height: 21px; padding: 3px 6px; font-size: 10px; }
.pos-product-empty { padding: 40px 12px; color: var(--muted); text-align: center; font-weight: 800; }
.pos-ticket-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; padding: 9px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.pos-ticket-head span { display: block; color: var(--muted); font-size: 12px; font-weight: 850; text-transform: uppercase; }
.pos-ticket-head strong { display: block; margin-top: 3px; font-size: 15px; }
.pos-ticket-actions { display: flex; align-items: center; gap: 7px; }
.pos-entry-toggle { display: inline-grid; place-items: center; width: 34px; min-width: 34px; min-height: 34px; margin: 0; padding: 7px; border: 1px solid #99d9ce; border-radius: 7px; color: #0f766e; background: #ecfdf8; }
.pos-entry-toggle:hover, .pos-entry-toggle.active { color: #ffffff; background: #0f766e; border-color: #0f766e; }
.pos-entry-toggle svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.pos-cart-entry-row[hidden] { display: none !important; }
.pos-sale-meta[hidden] { display: none !important; }
.pos-payment-row[hidden] { display: none !important; }
.pos-cart-entry-row:not([hidden]), .pos-sale-meta:not([hidden]), .pos-payment-row:not([hidden]) { animation: posEntryOpen .18s ease both; }
.pos-clear-button { width: auto; min-height: 34px; margin: 0; padding: 6px 10px; border: 1px solid #fecaca; border-radius: 7px; color: #b91c1c; background: #fff; font-size: 12px; font-weight: 850; }
.secondary-button { width: auto; min-height: 36px; margin: 0; padding: 7px 11px; border: 1px solid var(--border); border-radius: 8px; color: var(--primary); background: white; font-weight: 850; }
.pos-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 9px 0; }
.pos-meta .field { margin: 0; }
.pos-cart-lines { display: grid; align-content: start; gap: 7px; flex: 1 1 120px; min-height: 100px; overflow: auto; padding: 8px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.pos-empty-cart { display: grid; place-items: center; align-content: center; gap: 7px; min-height: 120px; color: var(--muted); text-align: center; }
.pos-empty-cart strong { color: #334155; font-size: 17px; }
.pos-empty-cart span { font-size: 13px; }
.pos-cart-line { display: grid; grid-template-columns: minmax(120px, 1fr) 108px 76px 76px 62px 30px; gap: 7px; align-items: center; min-height: 54px; padding: 7px; border-radius: 7px; background: var(--surface-muted); }
.pos-cart-line strong { font-size: 13px; line-height: 1.25; }
.pos-cart-line small { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }
.pos-qty-control { display: grid; grid-template-columns: 28px 1fr 28px; gap: 4px; align-items: center; }
.pos-qty-control button, .pos-remove { min-height: 30px; margin: 0; padding: 4px 6px; border-radius: 7px; font-size: 12px; }
.pos-qty-control input { min-height: 30px; padding: 4px; text-align: center; }
.pos-remove { width: 30px; border: 0; color: transparent; background: #fee2e2; font-size: 0; font-weight: 850; }
.pos-remove::after { content: "×"; color: #991b1b; font-size: 18px; }
.pos-totals { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 18px; margin-top: 8px; }
.pos-totals div, .pos-totals label { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 34px; margin: 0; color: var(--muted); font-size: 12px; font-weight: 850; }
.pos-totals input { width: 105px; min-height: 32px; padding: 5px 7px; text-align: right; }
.pos-totals strong { color: var(--text); font-size: 16px; }
.pos-grand-total { padding: 5px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.pos-grand-total strong { color: var(--primary-strong); font-size: 23px; }
.pos-payment-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 7px; }
.pos-payment-row .field { margin: 0; }
.pos-multiple-pay-panel[hidden] { display: none !important; }
.pos-multiple-pay-panel { margin-top: 8px; padding: 10px; border: 1px solid #c7d2fe; border-radius: 10px; background: #f8fbff; }
.pos-multiple-pay-head, .pos-multiple-pay-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.pos-multiple-pay-head strong { display: block; color: #0f172a; font-size: 13px; }
.pos-multiple-pay-head span { display: block; color: #64748b; font-size: 11px; font-weight: 700; }
.pos-multiple-pay-head button { min-height: 32px; padding: 0 10px; border: 1px solid #bfdbfe; border-radius: 8px; color: #1d4ed8; background: #eff6ff; font-size: 12px; font-weight: 900; }
.pos-multiple-pay-rows { display: grid; gap: 7px; margin-top: 9px; }
.pos-split-row { display: grid; grid-template-columns: minmax(110px, .8fr) minmax(90px, .7fr) minmax(110px, 1fr) 66px; gap: 7px; align-items: center; }
.pos-split-row select, .pos-split-row input { width: 100%; min-height: 34px; border: 1px solid #cbd5e1; border-radius: 7px; padding: 6px 8px; background: white; color: #0f172a; font-size: 12px; font-weight: 800; }
.pos-split-row button { min-height: 34px; border: 0; border-radius: 7px; color: #b91c1c; background: #fee2e2; font-size: 11px; font-weight: 900; }
.pos-multiple-pay-summary { margin-top: 8px; padding-top: 8px; border-top: 1px solid #dbeafe; color: #475569; font-size: 12px; font-weight: 900; }
.pos-multiple-pay-summary strong { color: #0f766e; font-size: 14px; }
.pos-multiple-pay-summary button { min-height: 34px; padding: 0 12px; border: 0; border-radius: 8px; color: white; background: #0f766e; font-size: 12px; font-weight: 950; }
.pos-action-bar { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(130px, 1.05fr) 1px repeat(5, minmax(76px, .62fr)) minmax(138px, 1.08fr) minmax(128px, 1fr); gap: 7px; align-items: center; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: white; box-shadow: 0 8px 24px rgba(15, 23, 42, .06); }
.pos-action { display: inline-flex; align-items: center; justify-content: center; width: 100%; min-height: 44px; margin: 0; padding: 7px 9px; border: 1px solid #cbd5e1; border-radius: 7px; color: #334155; background: #f8fafc; font-size: 12px; font-weight: 900; text-align: center; text-decoration: none; }
.pos-action-divider { width: 1px; height: 36px; background: #e2e8f0; }
.pos-action-icon { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; flex: 0 0 18px; }
.pos-action-icon svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2.3; stroke-linecap: round; stroke-linejoin: round; }
.pos-action-compact { flex-direction: column; gap: 4px; min-height: 50px; padding: 5px 4px; border-color: transparent; background: transparent; box-shadow: none; }
.pos-action-wide { flex-direction: row; gap: 7px; min-height: 44px; }
.pos-action-cancel { border-color: #fca5a5; color: #b91c1c; background: #fff; }
.pos-action-pay { border-color: #334155; color: white; background: #334155; }
.pos-action-complete { border-color: #0f766e; color: white; background: #0f766e; }
.pos-action-cash { border-color: #16a34a; color: white; background: #16a34a; }
.pos-shell { grid-template-columns: minmax(500px, 1.08fr) minmax(430px, .92fr); gap: 12px; }
.pos-catalog, .pos-cart-panel { border-color: rgba(148, 163, 184, .28); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: 0 18px 50px rgba(15, 23, 42, .08); }
.pos-customer-bar { padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: linear-gradient(180deg, #ffffff, #f8fafc); }
.pos-icon-link { min-height: 46px; border: 0; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #1d4ed8); box-shadow: 0 12px 26px rgba(37, 99, 235, .22); }
.pos-cart-search { margin-top: 10px; }
.pos-search { position: relative; }
.pos-search input { min-height: 48px; padding-left: 42px; border: 2px solid #0f172a; border-radius: 10px; background: linear-gradient(90deg, #ffffff, #f8fafc); font-weight: 750; }
.pos-search::before { content: ""; position: absolute; left: 15px; bottom: 13px; width: 14px; height: 14px; border: 2px solid #0f766e; border-radius: 50%; box-shadow: 8px 8px 0 -6px #0f766e; z-index: 1; }
.pos-search::after { content: ""; position: absolute; left: 42px; right: 12px; bottom: 10px; height: 2px; border-radius: 999px; background: linear-gradient(90deg, transparent, rgba(20,184,166,.7), transparent); animation: posScanLine 2.4s ease-in-out infinite; opacity: .55; }
.pos-catalog-head { margin-bottom: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: #f8fafc; }
.pos-kicker { color: var(--primary); font-weight: 950; letter-spacing: .06em; }
.pos-count { min-height: 52px; border-color: #bfdbfe; border-radius: 10px; background: #eff6ff; }
.pos-count strong { color: #1d4ed8; font-size: 20px; }
.pos-filter-chip { min-height: 32px; padding: 6px 12px; border-radius: 999px; font-weight: 900; }
.pos-filter-chip.active { background: linear-gradient(135deg, #2563eb, #1d4ed8); box-shadow: 0 10px 20px rgba(37, 99, 235, .16); }
.pos-product-grid { gap: 10px; }
.pos-product-tile { grid-template-rows: 104px minmax(62px, auto) auto; min-height: 210px; border-color: #dbe3ef; border-radius: 10px; transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease; }
.pos-product-tile:hover { transform: translateY(-2px); border-color: #14b8a6; box-shadow: 0 16px 34px rgba(15, 118, 110, .12); }
.pos-product-tile:disabled { transform: none; }
.pos-product-image { height: 104px; background: linear-gradient(135deg, #ecfeff, #f8fafc); }
.pos-product-info { gap: 4px; padding: 0 10px; }
.pos-product-info strong { font-size: 13px; }
.pos-product-foot { display: flex; align-items: end; justify-content: space-between; gap: 8px; padding: 0 10px 10px; }
.pos-product-foot b { font-size: 17px; letter-spacing: .01em; }
.pos-product-foot .badge { border-radius: 999px; }
.pos-price-stack { display: grid; gap: 2px; min-width: 0; }
.pos-offer-note { color: #475569; font-size: 10px; font-weight: 900; line-height: 1.1; }
.pos-offer-note del { color: #94a3b8; font-weight: 800; }
.pos-ticket-head { padding: 11px 12px; border: 1px solid var(--border); border-radius: 10px; background: #f8fafc; }
.pos-ticket-head span { font-size: 11px; font-weight: 950; letter-spacing: .05em; }
.pos-clear-button { border-radius: 8px; font-weight: 900; }
.pos-cart-lines { gap: 8px; min-height: 130px; padding: 10px 0; }
.pos-empty-cart { min-height: 160px; border: 1px dashed #cbd5e1; border-radius: 12px; background: linear-gradient(135deg, #ffffff, #f8fafc); }
.pos-empty-cart i { width: 42px; height: 42px; border: 2px solid #99f6e4; border-radius: 12px; background: linear-gradient(135deg, #ecfeff, #ffffff); box-shadow: inset 0 -8px 0 rgba(20,184,166,.08); }
.pos-empty-cart strong { font-size: 18px; }
.pos-cart-line { grid-template-columns: minmax(135px, 1fr) 122px 82px 82px 72px 32px; gap: 8px; min-height: 62px; padding: 9px; border: 1px solid #e2e8f0; border-radius: 10px; background: #ffffff; box-shadow: 0 8px 22px rgba(15, 23, 42, .04); }
.pos-qty-control { grid-template-columns: 30px 1fr 30px; gap: 5px; }
.pos-qty-control button { border-color: #ccfbf1; color: #0f766e; background: #f0fdfa; }
.pos-qty-control button, .pos-remove { min-height: 32px; border-radius: 8px; }
.pos-qty-control input { min-height: 32px; font-weight: 800; }
.pos-totals { gap: 6px 20px; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: linear-gradient(180deg, #ffffff, #f8fafc); }
.pos-totals div, .pos-totals label { min-height: 36px; font-weight: 900; }
.pos-totals input { width: 112px; min-height: 33px; font-weight: 800; }
.pos-grand-total { border-color: #cbd5e1; }
.pos-grand-total strong { font-size: 25px; }
.pos-payment-row { gap: 9px; margin-top: 9px; }
.pos-action-bar { gap: 8px; padding: 9px; border-color: rgba(148, 163, 184, .3); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: 0 18px 48px rgba(15, 23, 42, .10); }
.pos-action { min-height: 46px; border-radius: 9px; font-weight: 950; transition: transform .12s ease, box-shadow .12s ease, background .12s ease; }
.pos-action:hover { transform: translateY(-1px); box-shadow: 0 10px 20px rgba(15,23,42,.08); }
.pos-action-compact:hover { background: #f8fafc; box-shadow: none; }
.pos-action-cancel { border: 2px solid #fb7185; color: #ef4444; background: #fff; }
.pos-action-draft { color: #0ea5e9; }
.pos-action-quote { color: #eab308; }
.pos-action-suspend { color: #fb7185; }
.pos-action-credit { color: #818cf8; }
.pos-action-pay { border-color: transparent; color: #334155; background: transparent; }
.pos-action-complete { border-color: #334155; color: white; background: linear-gradient(135deg, #334155, #1e293b); }
.pos-action-cash { border-color: #34d399; color: white; background: linear-gradient(135deg, #4ade80, #10b981); }
.pos-cart-entry-row { display: grid; grid-template-columns: minmax(210px, .46fr) minmax(320px, 1fr); gap: 10px; align-items: end; margin-bottom: 10px; padding: 8px; border: 1px solid #e2e8f0; border-radius: 14px; background: #ffffff; }
.pos-cart-entry-row .pos-customer-bar { padding: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.pos-cart-entry-row .pos-cart-search { margin-top: 0; }
.pos-cart-entry-row .pos-search input { min-height: 40px; border-width: 1px; border-color: #2563eb; border-radius: 0; background: #ffffff; }
.pos-cart-entry-row .pos-search::before { bottom: 11px; border-color: #475569; box-shadow: 8px 8px 0 -6px #475569; }
.pos-cart-entry-row .pos-search::after { bottom: 8px; }
.pos-cart-entry-row .field > span { font-size: 10px; }
.pos-cart-entry-row .pos-icon-link { min-height: 40px; border-radius: 0; }
.pos-cart-lines { gap: 0; min-height: 330px; padding: 0; border: 1px solid #e2e8f0; border-radius: 14px 14px 0 0; background: #ffffff; }
.pos-cart-header { position: sticky; top: 0; z-index: 2; display: grid; grid-template-columns: minmax(170px, 1.35fr) minmax(118px, .7fr) minmax(104px, .72fr) minmax(94px, .68fr) minmax(88px, .58fr) 42px; gap: 9px; align-items: center; min-height: 34px; padding: 0 10px; border-bottom: 1px solid #e2e8f0; color: #94a3b8; background: #f8fafc; font-size: 10px; font-weight: 950; text-transform: uppercase; }
.pos-cart-line { grid-template-columns: minmax(170px, 1.35fr) minmax(118px, .7fr) minmax(104px, .72fr) minmax(94px, .68fr) minmax(88px, .58fr) 42px; gap: 9px; min-height: 78px; padding: 9px 10px; border: 0; border-bottom: 1px solid #e2e8f0; border-radius: 0; background: #ffffff; box-shadow: none; }
.pos-cart-line:hover { background: #f8fafc; }
.pos-line-product { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 9px; align-items: center; min-width: 0; }
.pos-line-image { display: grid; place-items: center; width: 40px; height: 40px; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 7px; background: #f8fafc; }
.pos-line-image .product-card-thumb { width: 100%; height: 100%; object-fit: cover; border-radius: 0; }
.pos-line-image .product-card-initial { width: 100%; height: 100%; border-radius: 0; font-size: 14px; }
.pos-line-name { min-width: 0; }
.pos-line-name strong { display: block; overflow: hidden; color: #0284c7; font-size: 13px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.pos-line-name small { overflow: hidden; margin-top: 3px; color: #64748b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.pos-qty-control { grid-template-columns: 34px minmax(48px, 1fr) 34px; gap: 0; align-items: start; }
.pos-qty-control button { min-height: 32px; border: 1px solid #cbd5e1; border-radius: 0; color: #0891b2; background: #f8fafc; font-size: 18px; line-height: 1; }
.pos-qty-control button:first-child { color: #ef4444; border-radius: 6px 0 0 6px; }
.pos-qty-control button:last-of-type { border-radius: 0 6px 6px 0; }
.pos-qty-control input { min-height: 32px; border-left: 0; border-right: 0; border-radius: 0; font-size: 14px; font-weight: 850; }
.pos-qty-control small { grid-column: 1 / -1; margin-top: 4px; color: #64748b; font-size: 11px; font-weight: 700; }
.pos-line-price, .pos-line-discount { width: 100%; min-height: 34px; margin: 0; border-radius: 0; font-weight: 800; }
.pos-line-price-view { display: grid; align-content: center; gap: 2px; min-height: 42px; padding: 5px 8px; border: 1px solid #cbd5e1; background: #ffffff; }
.pos-line-price-view del { color: #94a3b8; font-size: 11px; font-weight: 800; }
.pos-line-price-view strong { color: #0f172a; font-size: 14px; font-weight: 950; }
.pos-line-save { display: grid; place-items: center; min-height: 42px; padding: 5px 8px; border: 1px solid #bbf7d0; background: #f0fdf4; color: #166534; font-size: 12px; font-weight: 950; text-align: center; }
.pos-line-discount { color: #0f172a; background: #ffffff; }
.pos-line-discount[readonly] { border-color: #fed7aa; background: #fffbeb; cursor: default; }
.pos-line-subtotal { justify-self: end; color: #0f172a; font-size: 14px; }
.pos-remove { display: grid; place-items: center; width: 36px; min-height: 36px; border-radius: 999px; background: #fee2e2; }
.pos-remove::after { content: "x"; color: #ef4444; font-size: 16px; font-weight: 950; }
.pos-checkout-strip { display: grid; grid-template-columns: repeat(4, minmax(88px, 1fr)) minmax(180px, 1.35fr); gap: 0; margin-top: 0; padding: 0; overflow: hidden; border: 1px solid #e2e8f0; border-top: 0; border-radius: 0 0 14px 14px; background: #ffffff; }
.pos-checkout-strip .pos-total-cell { display: grid; place-items: center; align-content: center; gap: 3px; min-height: 70px; padding: 8px; border-right: 1px solid #e2e8f0; color: #64748b; text-align: center; }
.pos-checkout-strip .pos-total-cell span, .pos-checkout-strip .pos-grand-total span { color: #94a3b8; font-size: 10px; font-weight: 950; letter-spacing: .04em; text-transform: uppercase; }
.pos-checkout-strip .pos-total-cell strong { color: #0f172a; font-size: 15px; font-weight: 950; }
.pos-checkout-strip .pos-total-input input { width: 92px; min-height: 28px; padding: 3px 7px; border: 0; color: #0f172a; background: transparent; font-size: 15px; font-weight: 950; text-align: center; }
.pos-checkout-strip .pos-total-input small { color: #64748b; font-size: 10px; font-weight: 900; }
.pos-checkout-strip .pos-total-input small b { color: #166534; }
.pos-checkout-strip .pos-total-input input:focus { outline: 2px solid #bfdbfe; border-radius: 6px; background: white; }
.pos-checkout-strip .pos-total-input:first-of-type input { color: #ef4444; }
.pos-checkout-strip .pos-total-cell:nth-child(5) { grid-column: 1 / 3; }
.pos-checkout-strip .pos-grand-total { display: grid; place-items: center; align-content: center; gap: 5px; min-height: 70px; padding: 10px 14px; border: 0; background: #dcfce7; }
.pos-checkout-strip .pos-grand-total { grid-column: 5; grid-row: 1 / span 2; }
.pos-checkout-strip .pos-grand-total strong { color: #047857; font-size: 30px; line-height: 1; }
.pos-shell { grid-template-rows: minmax(0, calc(100vh - 235px)) auto; }
.pos-cart-panel, .pos-catalog { min-height: 0; }
.pos-cart-panel { overflow-x: hidden; overflow-y: auto; }
.pos-cart-entry-row, .pos-ticket-head, .pos-sale-meta, .pos-checkout-strip, .pos-payment-row, .pos-multiple-pay-panel { flex: 0 0 auto; }
.pos-cart-lines { flex: 1 1 140px; min-height: 120px; overflow: auto; }
.pos-cart-header, .pos-cart-line { grid-template-columns: minmax(132px, 1fr) 102px 92px 82px 72px 38px; gap: 7px; }
.pos-cart-line { align-items: center; }
.pos-cart-line .pos-qty-control { grid-template-columns: 30px minmax(46px, 1fr) 30px; width: 110px; }
.pos-cart-line .pos-qty-control button, .pos-cart-line .pos-qty-control input { width: 100%; min-width: 0; height: 32px; min-height: 32px; padding-left: 3px; padding-right: 3px; }
.pos-cart-line .pos-line-price, .pos-cart-line .pos-line-discount, .pos-cart-line .pos-line-price-view, .pos-cart-line .pos-line-save { width: 100%; min-width: 0; height: 42px; min-height: 42px; padding: 6px 8px; }
.pos-cart-line .pos-line-subtotal { width: 72px; overflow: hidden; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.pos-checkout-strip .pos-total-cell { min-height: 54px; padding: 6px 8px; }
.pos-checkout-strip .pos-grand-total { min-height: 108px; }
.pos-checkout-strip .pos-grand-total strong { font-size: 28px; }
.pos-payment-row { margin-top: 8px; }
@media (max-height: 820px) and (min-width: 901px) {
  .pos-cart-panel { padding: 9px; }
  .pos-cart-entry-row { gap: 7px; margin-bottom: 5px; padding: 5px 7px; }
  .pos-cart-entry-row .pos-customer-bar { grid-template-columns: 1fr 38px; gap: 6px; }
  .pos-cart-entry-row select, .pos-cart-entry-row .pos-search input, .pos-cart-entry-row .pos-icon-link { min-height: 36px; height: 36px; }
  .pos-cart-entry-row .pos-search::before { bottom: 9px; }
  .pos-cart-entry-row .pos-search::after { bottom: 7px; }
  .pos-ticket-head { margin-top: 4px; padding: 6px 9px; }
  .pos-ticket-head span { font-size: 9px; }
  .pos-ticket-head strong { margin-top: 1px; font-size: 13px; }
  .pos-clear-button { min-height: 30px; padding: 4px 8px; }
  .pos-meta { gap: 7px; margin: 5px 0; }
  .pos-meta .field > span, .pos-payment-row .field > span { font-size: 10px; }
  .pos-meta input, .pos-payment-row select { min-height: 36px; height: 36px; padding-top: 5px; padding-bottom: 5px; }
  .pos-split-row { grid-template-columns: 1fr 92px 1fr 58px; gap: 5px; }
  .pos-split-row select, .pos-split-row input, .pos-split-row button { min-height: 32px; font-size: 11px; }
  .pos-cart-lines { flex-basis: 132px; min-height: 118px; }
  .pos-cart-header { min-height: 30px; font-size: 9px; }
  .pos-cart-line { min-height: 70px; padding-top: 7px; padding-bottom: 7px; }
  .pos-checkout-strip .pos-total-cell { min-height: 44px; padding: 4px 6px; }
  .pos-checkout-strip .pos-grand-total { min-height: 88px; }
  .pos-checkout-strip .pos-grand-total strong { font-size: 25px; }
  .pos-checkout-strip .pos-total-cell span, .pos-checkout-strip .pos-grand-total span { font-size: 9px; }
  .pos-checkout-strip .pos-total-cell strong, .pos-checkout-strip .pos-total-input input { font-size: 13px; }
  .pos-payment-row { margin-top: 5px; }
}
@keyframes posScanLine {
  0%, 100% { transform: translateX(-18px); opacity: .15; }
  50% { transform: translateX(18px); opacity: .75; }
}
@keyframes posEntryOpen {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}
.sales-return-workspace { display: grid; grid-template-columns: minmax(560px, 1.35fr) minmax(360px, .65fr); gap: 14px; align-items: start; }
.return-invoice-panel, .return-editor-panel, .return-history-panel { border-radius: 8px; }
.return-editor-panel { position: sticky; top: 94px; }
.return-step-head { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 14px; }
.return-step-head > span { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 6px; color: white; background: #0f766e; font-size: 11px; font-weight: 900; }
.return-step-head h3 { margin: 0; font-size: 17px; }
.return-step-head p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.return-invoice-search { margin: 0 0 10px; }
.return-sale-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.return-sale-summary > div { min-height: 62px; padding: 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-muted); }
.return-sale-summary span { display: block; color: var(--muted); font-size: 10px; font-weight: 850; text-transform: uppercase; }
.return-sale-summary strong { display: block; margin-top: 6px; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.return-items-table { position: relative; min-height: 220px; overflow: auto; border: 1px solid var(--border); border-radius: 7px; }
.return-items-table table { border: 0; border-radius: 0; }
.return-items-table td small { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
.return-items-table button { width: auto; min-height: 31px; margin: 0; padding: 5px 9px; }
.return-empty-state { position: absolute; inset: 45px 0 0; display: grid; place-items: center; color: var(--muted); background: white; font-size: 13px; font-weight: 750; }
.return-empty-state[hidden] { display: none; }
.return-selected-product { display: grid; gap: 3px; min-height: 74px; margin-bottom: 12px; padding: 11px; border: 1px solid #99f6e4; border-radius: 7px; background: #f0fdfa; }
.return-selected-product span { color: #0f766e; font-size: 10px; font-weight: 900; text-transform: uppercase; }
.return-selected-product strong { font-size: 15px; }
.return-selected-product small { color: var(--muted); font-size: 11px; }
.return-stock-toggle { display: flex; align-items: flex-start; gap: 10px; margin: 12px 0; padding: 11px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-muted); }
.return-stock-toggle input { width: 18px; height: 18px; margin: 1px 0 0; }
.return-stock-toggle strong, .return-stock-toggle small { display: block; }
.return-stock-toggle small { margin-top: 3px; color: var(--muted); font-size: 11px; }
.return-refund-total { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; padding: 11px; border-top: 1px solid var(--border); color: var(--muted); font-weight: 850; }
.return-refund-total strong { color: #0f766e; font-size: 24px; }
.return-confirm-button { min-height: 48px; margin-top: 8px; font-size: 15px; }
.return-history-panel { margin-top: 14px; }
.return-history-scroll { overflow-x: auto; }
.register-open-state { display: grid; place-items: center; min-height: 430px; }
.register-open-card { display: grid; grid-template-columns: 58px minmax(220px, 1fr) minmax(420px, 1.25fr); gap: 18px; align-items: center; width: min(1050px, 100%); border-radius: 8px; }
.register-state-icon { display: grid; place-items: center; width: 58px; height: 58px; border-radius: 8px; color: white; background: #0f766e; font-weight: 950; }
.register-kicker { color: var(--muted); font-size: 10px; font-weight: 900; text-transform: uppercase; }
.register-open-card h3 { margin: 4px 0; font-size: 21px; }
.register-open-card p { margin: 0; color: var(--muted); font-size: 13px; }
.register-open-form { display: grid; grid-template-columns: 1fr 1fr auto; gap: 9px; align-items: end; margin: 0; }
.register-open-form .field { margin: 0; }
.register-open-form button { width: auto; min-height: 42px; margin: 0; }
.register-live { display: grid; gap: 10px; }
.register-live-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.register-live-head h3 { margin: 5px 0 2px; font-size: 20px; }
.register-live-head p { margin: 0; color: var(--muted); font-size: 12px; }
.register-status-dot { display: inline-flex; align-items: center; gap: 6px; color: #047857; font-size: 11px; font-weight: 900; text-transform: uppercase; }
.register-status-dot::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: #10b981; }
.register-live-head .secondary-link { margin: 0; }
.register-metrics { display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 9px; }
.register-metric { min-height: 96px; padding: 13px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.register-metric span, .register-metric small { display: block; color: var(--muted); font-size: 11px; font-weight: 800; }
.register-metric strong { display: block; margin: 8px 0 5px; font-size: 22px; }
.register-metric.positive { background: #f0fdf4; }
.register-metric.negative { background: #fff7ed; }
.register-metric.primary { color: white; background: #0f766e; border-color: #0f766e; }
.register-metric.primary span, .register-metric.primary small { color: #ccfbf1; }
.register-main-grid { display: grid; grid-template-columns: minmax(520px, 1.35fr) minmax(340px, .65fr); gap: 10px; align-items: start; }
.register-ledger, .register-side-stack .panel { border-radius: 8px; }
.register-section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.register-section-head h3 { margin: 0; font-size: 16px; }
.register-section-head p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
.register-ledger-scroll { max-height: 540px; overflow: auto; border: 1px solid var(--border); border-radius: 7px; }
.register-ledger-scroll table { border: 0; border-radius: 0; }
.register-side-stack { display: grid; gap: 10px; }
.register-movement-form { display: grid; gap: 8px; margin: 0; }
.register-movement-form .field { margin: 0; }
.register-movement-form button { margin-top: 2px; }
.register-denominations { overflow: hidden; margin-top: 8px; border: 1px solid var(--border); border-radius: 7px; }
.register-denomination-head, .register-denomination-row, .register-coins-row { display: grid; grid-template-columns: 1fr 90px 110px; gap: 8px; align-items: center; margin: 0; padding: 7px 9px; border-bottom: 1px solid var(--border); }
.register-denomination-head { color: var(--muted); background: var(--surface-muted); font-size: 10px; font-weight: 900; text-transform: uppercase; }
.register-denomination-head span:nth-child(2), .register-denomination-head span:nth-child(3) { text-align: right; }
.register-denomination-row span, .register-coins-row span { font-size: 12px; font-weight: 850; }
.register-denomination-row input, .register-coins-row input { min-height: 31px; padding: 4px 6px; text-align: right; }
.register-denomination-row strong, .register-coins-row strong { text-align: right; font-size: 12px; }
.register-coins-row { border-bottom: 0; background: #f8fafc; }
.register-counted-total { display: flex; align-items: center; justify-content: space-between; margin-top: 9px; padding: 11px; border: 1px solid #99f6e4; border-radius: 7px; background: #f0fdfa; color: #0f766e; font-weight: 900; }
.register-counted-total strong { font-size: 22px; }
.register-difference { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; padding: 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-muted); font-weight: 850; }
.register-difference strong { font-size: 20px; }
.register-approval { display: flex; align-items: center; gap: 8px; margin: 10px 0; font-size: 12px; }
.register-approval input { width: 17px; margin: 0; }
.register-close-button { border-color: #b91c1c; background: #b91c1c; }
.register-history { overflow-x: auto; }
.supplier-page-title { margin-bottom: 16px; }
.supplier-filter-panel { margin-bottom: 16px; padding: 16px; }
.supplier-filter-form { display: grid; grid-template-columns: minmax(260px, 1fr) 180px 180px auto auto; gap: 12px; align-items: end; margin: 0; }
.supplier-filter-form button { width: auto; min-width: 96px; margin-top: 0; }
.supplier-filter-form .secondary-link { min-height: 42px; }
.supplier-summary-row { display: grid; grid-template-columns: repeat(3, minmax(150px, 1fr)); gap: 14px; margin-bottom: 16px; }
.supplier-mini-metric { min-height: 92px; }
.supplier-list-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 12px; }
.supplier-list-head h3 { margin-bottom: 4px; }
.supplier-list-head p { margin: 0; color: var(--muted); font-size: 13px; }
.supplier-list-head .primary-link { flex: 0 0 auto; }
.supplier-modal-panel { width: min(920px, 100%); }
.purchase-filter-panel { margin-bottom: 16px; padding: 14px; }
.purchase-filter-form { display: grid; grid-template-columns: minmax(170px, 1fr) minmax(190px, 1fr) 150px 150px auto auto; gap: 9px; align-items: end; margin: 0; }
.purchase-filter-form .field { margin: 0; }
.purchase-filter-form button, .purchase-filter-form .secondary-link { width: auto; min-height: 42px; margin: 0; }
.purchase-item-entry { display: grid; grid-template-columns: minmax(260px, 1fr) 140px 160px 120px; gap: 10px; align-items: end; margin: 18px 0 12px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-muted); }
.purchase-item-entry .field { margin: 0; }
.purchase-item-entry button { min-height: 42px; margin: 0; }
.purchase-product-picker { display: grid; grid-template-columns: minmax(190px, 1fr) auto; gap: 7px; align-items: end; }
.purchase-new-product-button { width: auto; min-width: 120px; padding: 8px 10px; border-color: #2563eb; color: #1d4ed8; background: white; }
.barcode-input-row { display: grid; grid-template-columns: minmax(150px, 1fr) auto; gap: 7px; }
.barcode-input-row button { width: auto; min-width: 112px; min-height: 42px; margin: 0; padding: 8px 10px; border-color: #2563eb; color: #1d4ed8; background: white; font-size: 12px; }
.purchase-items-table { overflow: auto; margin-bottom: 14px; padding: 0; }
.purchase-items-table input { min-width: 92px; min-height: 34px; padding: 5px 7px; }
.purchase-items-table button { width: auto; min-height: 32px; margin: 0; padding: 5px 8px; }
.purchase-summary-fields { align-items: end; }
.purchase-summary { display: grid; grid-template-columns: 1fr auto; gap: 7px 18px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-muted); }
.purchase-summary span { color: var(--muted); font-size: 12px; font-weight: 850; }
.purchase-summary strong { text-align: right; font-size: 17px; }
.purchase-quick-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: 20px; background: rgba(15, 23, 42, .58); }
.purchase-quick-modal[hidden] { display: none; }
.purchase-quick-dialog { width: min(860px, 100%); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--border); border-radius: 8px; background: white; box-shadow: 0 24px 70px rgba(15, 23, 42, .28); }
.purchase-quick-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.purchase-quick-head span { color: var(--muted); font-size: 10px; font-weight: 900; text-transform: uppercase; }
.purchase-quick-head h3 { margin: 3px 0 0; font-size: 19px; }
.purchase-quick-head .modal-close { width: 38px; min-height: 38px; margin: 0; padding: 4px; font-size: 20px; }
.purchase-quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 18px; }
.purchase-quick-grid .field { margin: 0; }
.purchase-quick-error { margin: 0 18px 12px; padding: 9px 11px; border-radius: 6px; color: #991b1b; background: #fee2e2; font-weight: 750; }
.purchase-quick-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 18px; border-top: 1px solid var(--border); }
.purchase-quick-actions button { width: auto; min-width: 150px; min-height: 42px; margin: 0; }
.purchase-detail-body { min-height: 100vh; padding: 24px; background: #eef2f6; }
.purchase-detail-page { width: min(1500px, 100%); margin: 0 auto; }
.purchase-detail-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 12px; padding: 16px 18px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.purchase-detail-toolbar span { color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; }
.purchase-detail-toolbar h1 { margin: 3px 0; font-size: 22px; }
.purchase-detail-toolbar p { margin: 0; color: var(--muted); font-size: 13px; }
.purchase-detail-actions { display: flex; gap: 8px; }
.purchase-detail-actions a, .purchase-detail-actions button { width: auto; min-width: 90px; min-height: 40px; margin: 0; }
.purchase-detail-metrics { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 10px; margin-bottom: 10px; }
.purchase-detail-metrics article { min-height: 84px; padding: 13px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.purchase-detail-metrics span { display: block; color: var(--muted); font-size: 11px; font-weight: 850; }
.purchase-detail-metrics strong { display: block; margin-top: 9px; font-size: 20px; }
.purchase-detail-summary { display: grid; grid-template-columns: 2fr 1.3fr repeat(3, 1fr); gap: 10px; margin-bottom: 10px; }
.purchase-detail-summary > div { min-height: 92px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-muted); }
.purchase-detail-summary span, .purchase-detail-summary small { display: block; color: var(--muted); font-size: 11px; font-weight: 800; }
.purchase-detail-summary strong { display: block; margin: 6px 0; font-size: 15px; }
.purchase-detail-table, .purchase-payment-detail { overflow: hidden; margin-bottom: 10px; border: 1px solid var(--border); border-radius: 8px; background: white; }
.purchase-detail-section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.purchase-detail-section-head h2 { margin: 0; font-size: 15px; }
.purchase-detail-section-head span { color: var(--muted); font-size: 12px; font-weight: 800; }
.purchase-detail-table table { border: 0; border-radius: 0; }
.purchase-detail-table th, .purchase-detail-table td { padding: 9px 10px; border-right: 1px solid #e5e7eb; }
.purchase-detail-table th:last-child, .purchase-detail-table td:last-child { border-right: 0; }
.purchase-detail-table tfoot th { background: #e2e8f0; color: #0f172a; }
.purchase-payment-grid { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); }
.purchase-payment-grid > div { min-height: 76px; padding: 13px; border-right: 1px solid var(--border); }
.purchase-payment-grid > div:last-child { border-right: 0; }
.purchase-payment-grid span { display: block; color: var(--muted); font-size: 11px; font-weight: 850; }
.purchase-payment-grid strong { display: block; margin-top: 8px; font-size: 17px; }
.purchase-payment-grid .total { background: #ecfdf5; }
.purchase-payment-grid .due { background: #fff7ed; }
@media print {
  .purchase-detail-body { padding: 0; background: white; }
  .purchase-detail-page { width: 100%; }
  .purchase-detail-actions { display: none; }
  .purchase-detail-toolbar { border: 0; padding: 0 0 12px; }
  .purchase-detail-metrics article, .purchase-detail-summary > div, .purchase-detail-table, .purchase-payment-detail { box-shadow: none; break-inside: avoid; }
}
.supplier-form { margin: 0; }
.supplier-form-section { padding: 18px; border-bottom: 1px solid var(--border); background: white; }
.supplier-form-section:last-child { border-bottom: 0; }
.import-contact-form { margin: 0; }
.import-section { padding: 18px; border-bottom: 1px solid var(--border); }
.import-section:last-of-type { border-bottom: 0; }
.import-instruction-table { max-height: 360px; overflow: auto; border: 1px solid var(--border); border-radius: 12px; }
.import-instruction-table code { color: var(--primary-strong); font-weight: 850; }
.role-choice-block { margin-bottom: 16px; }
.role-choice-block > span { display: block; margin-bottom: 8px; font-weight: 850; }
.role-choice-list { display: grid; gap: 8px; max-width: 360px; }
.choice-row { display: flex; align-items: center; gap: 10px; min-height: 42px; margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-muted); font-weight: 800; }
.choice-row input { width: auto; margin: 0; }
.choice-row:has(input:checked) { border-color: #5eead4; background: #ecfeff; color: var(--primary-strong); }
.contact-stats { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.contact-metric { min-height: 110px; }
.contact-table-panel { margin-bottom: 18px; }
.contact-edit-grid { display: grid; grid-template-columns: 1fr; gap: 18px; }
.contact-edit-card { scroll-margin-top: 96px; padding: 0; overflow: hidden; }
.contact-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 18px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); }
.contact-card-head h3 { margin: 8px 0 5px; font-size: 20px; }
.contact-card-head p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.contact-card-head button { width: auto; min-width: 106px; margin-top: 0; }
.contact-chip { display: inline-flex; align-items: center; min-height: 25px; padding: 4px 9px; border-radius: 999px; color: var(--primary-strong); background: #ccfbf1; font-size: 12px; font-weight: 900; }
.contact-form { margin: 0; }
.contact-form-section { padding: 18px; border-bottom: 1px solid var(--border); background: white; }
.contact-form-section:last-child { border-bottom: 0; }
.contact-person-grid { display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 14px; }
.contact-person-card { padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-muted); }
.contact-person-card h5 { margin: 0 0 12px; font-size: 14px; }
.contact-person-card .field { margin-top: 10px; }
.category-create-panel { margin-bottom: 18px; padding: 0; overflow: hidden; }
.category-create-panel > .supplier-list-head { padding: 20px 22px 16px; border-bottom: 1px solid var(--border); }
.category-create-panel .product-form { margin: 0; }
.category-create-panel .product-form-section,
.category-create-panel .product-form-section:first-of-type {
  margin: 0;
  padding: 20px 22px;
  border-top: 0;
  border-bottom: 1px solid var(--border);
}
.category-create-panel .product-form-section:last-of-type { border-bottom: 0; }
.category-create-panel .form-grid { width: 100%; min-width: 0; }
.category-create-panel .field { min-width: 0; }
.category-create-panel .form-actions { margin: 0; padding: 16px 22px 20px; border-top: 1px solid var(--border); background: #fbfdfc; }
.category-empty-panel { margin-bottom: 18px; border-color: #99f6e4; background: #f0fdfa; }
.category-empty-panel h3 { margin-bottom: 6px; }
.category-template-panel { margin-bottom: 18px; padding: 16px; }
.category-template-form { display: grid; grid-template-columns: minmax(240px, 420px) auto; gap: 12px; align-items: end; margin: 0 0 14px; }
.category-template-form button { width: auto; min-width: 170px; margin: 0; }
.category-template-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.category-template-card { display: grid; grid-template-columns: 12px 1fr; gap: 8px 10px; align-items: center; min-height: 58px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-muted); }
.category-template-card span { grid-row: 1 / span 2; width: 12px; height: 38px; border-radius: 4px; }
.category-template-card strong { font-size: 13px; line-height: 1.2; }
.category-template-card small { color: var(--muted); font-size: 12px; font-weight: 800; }
.category-table td { vertical-align: middle; }
.category-name-cell { display: flex; align-items: flex-start; gap: 10px; min-width: 220px; }
.category-color { flex: 0 0 auto; width: 14px; height: 32px; border: 1px solid rgba(15, 23, 42, .12); border-radius: 4px; }
.category-branch { color: var(--primary); font-weight: 950; }
.category-toggle-grid { margin-top: 16px; }
@media (max-width: 1100px) and (min-width: 901px) {
  .category-create-panel .form-grid.three-col { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .category-create-panel > .supplier-list-head,
  .category-create-panel .product-form-section,
  .category-create-panel .product-form-section:first-of-type,
  .category-create-panel .form-actions { padding-left: 18px; padding-right: 18px; }
}
@media (max-width: 560px) {
  .category-create-panel > .supplier-list-head,
  .category-create-panel .product-form-section,
  .category-create-panel .product-form-section:first-of-type,
  .category-create-panel .form-actions { padding-left: 14px; padding-right: 14px; }
  .category-create-panel .form-actions button { width: 100%; }
}
.modal-screen { position: fixed; inset: 0; z-index: 40; display: none; align-items: center; justify-content: center; padding: 22px; }
.modal-screen:target { display: flex; }
.modal-backdrop { position: absolute; inset: 0; background: rgba(15, 23, 42, .58); backdrop-filter: blur(8px); }
.modal-panel { position: relative; z-index: 1; width: min(1120px, 100%); max-height: min(88vh, 920px); overflow: auto; border: 1px solid var(--border); border-radius: 18px; background: white; box-shadow: 0 28px 90px rgba(15, 23, 42, .32); }
.contact-modal-panel { padding: 0; }
.modal-head { position: sticky; top: 0; z-index: 2; display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 18px; border-bottom: 1px solid var(--border); background: rgba(255, 255, 255, .94); backdrop-filter: blur(12px); }
.modal-head h3 { margin: 8px 0 5px; font-size: 22px; }
.modal-head p { margin: 0; color: var(--muted); font-size: 13px; }
.modal-close { display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; color: var(--text); background: white; font-weight: 800; }
.panel h3 { margin: 0 0 14px; font-size: 20px; }
.panel a { display: block; margin-top: 8px; text-align: center; }
.panel p { color: var(--muted); }
.primary-link, .secondary-link, .form-actions a { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; border: 1px solid var(--primary); border-radius: 10px; padding: 9px 14px; font-weight: 800; }
.primary-link { background: var(--primary); color: white; }
.secondary-link, .form-actions a { color: var(--primary); background: white; }
.table-link { color: var(--primary); font-weight: 800; }
.badge { display: inline-flex; align-items: center; min-height: 26px; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 800; }
.badge.ok { color: #065f46; background: #d1fae5; }
.badge.danger { color: #991b1b; background: #fee2e2; }
.status { display: block; margin-bottom: 16px; font-size: 20px; }
table { width: 100%; border-collapse: collapse; }
th, td { border-top: 1px solid var(--border); padding: 12px; text-align: left; vertical-align: top; }
th { color: var(--muted); }
thead th { border-top: 0; color: var(--text); font-size: 13px; white-space: nowrap; }
.table-panel { overflow-x: auto; }
.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.positive { color: #065f46; font-weight: 800; }
.negative { color: #991b1b; font-weight: 800; }
.actions-cell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.inline-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 260px; }
.inline-actions form { margin: 0; }
.inline-actions .table-link { margin-top: 0; }
.table-action { margin: 0; }
.table-action button { width: auto; min-width: 0; margin-top: 0; padding: 6px 9px; font-size: 12px; background: white; color: #991b1b; border-color: #fecaca; }
.addon-action button { color: var(--primary); border-color: #99f6e4; }
.addon-action button:hover { background: #f0fdfa; color: var(--primary-strong); }
.empty { text-align: center; color: var(--muted); padding: 28px; }
.table-note { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.4; }
.product-form { margin: 0; }
.form-grid { display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 16px; }
.form-grid.two-col { grid-template-columns: repeat(2, minmax(160px, 1fr)); }
.form-grid.three-col { grid-template-columns: repeat(3, minmax(170px, 1fr)); }
.field { display: block; margin: 0; }
.field span { display: block; margin: 0 0 6px; font-weight: 800; }
.wide-field { margin-top: 16px; }
.form-actions { display: flex; align-items: center; gap: 10px; margin-top: 20px; }
.form-actions button { width: auto; min-width: 150px; margin-top: 0; }
.user-overview { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; margin-bottom: 18px; }
.user-overview article { min-height: 92px; padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: white; box-shadow: 0 14px 36px rgba(15, 23, 42, .05); }
.user-overview span { display: block; color: var(--muted); font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .04em; }
.user-overview strong { display: block; margin-top: 12px; font-size: 30px; line-height: 1; color: var(--text); }
.user-list-panel { margin-bottom: 18px; }
.user-list-panel .panel-heading { padding: 0 0 14px; }
.user-form-panel { padding: 0; overflow: hidden; }
.user-form-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 18px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); }
.user-form-head span { color: var(--primary); font-size: 12px; font-weight: 950; text-transform: uppercase; letter-spacing: .05em; }
.user-form-head h3 { margin: 6px 0 4px; font-size: 22px; }
.user-form-head p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.45; }
.staff-core-form { padding: 18px; border-bottom: 1px solid var(--border); background: white; }
.staff-advanced { display: grid; gap: 10px; padding: 14px 18px 18px; background: #f8fafc; }
.staff-advanced details { border: 1px solid var(--border); border-radius: 8px; background: white; overflow: hidden; }
.staff-advanced summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 14px; cursor: pointer; list-style: none; font-weight: 900; }
.staff-advanced summary::-webkit-details-marker { display: none; }
.staff-advanced summary::after { content: "+"; display: grid; place-items: center; width: 24px; height: 24px; border-radius: 999px; background: #ecfeff; color: var(--primary-strong); font-weight: 950; }
.staff-advanced details[open] summary::after { content: "-"; }
.staff-advanced summary span { font-size: 14px; }
.staff-advanced summary small { margin-left: auto; color: var(--muted); font-size: 12px; font-weight: 750; }
.staff-advanced details > .form-grid,
.staff-advanced details > .permission-grid,
.staff-advanced details > .field { padding: 0 14px 14px; }
.user-form-layout { display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 0; border-top: 1px solid var(--border); }
.form-section { padding: 18px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); background: white; }
.form-section:nth-child(even) { border-right: 0; }
.section-heading { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.section-heading > span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: #ecfeff; color: var(--primary-strong); font-weight: 900; font-size: 12px; }
.section-heading h4 { margin: 0; font-size: 16px; }
.section-heading p { margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.permission-grid { display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)); gap: 10px; }
.check-card { display: flex; align-items: center; gap: 9px; min-height: 42px; margin: 0; padding: 10px 11px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-muted); font-size: 13px; font-weight: 800; }
.check-card input { width: auto; margin: 0; }
.sticky-form-actions { position: sticky; bottom: 0; display: flex; justify-content: flex-end; gap: 10px; padding: 14px 18px; background: rgba(255, 255, 255, .92); border-top: 1px solid var(--border); backdrop-filter: blur(12px); }
.sticky-form-actions button, .sticky-form-actions a { width: auto; min-width: 140px; margin-top: 0; }
.filter-panel { margin-bottom: 18px; }
.inline-filter { display: flex; align-items: end; gap: 12px; margin: 0; }
.inline-filter .field { min-width: 280px; }
.inline-filter button { width: auto; min-width: 100px; margin-top: 0; }
.inline-action { margin: 0; }
.inline-action button { width: auto; min-width: 150px; margin-top: 0; }
.close-register-form { margin-top: 18px; }
.register-history { margin-top: 18px; }
.login-body {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 28px;
  background:
    radial-gradient(circle at 18% 12%, rgba(20, 184, 166, .18), transparent 28%),
    radial-gradient(circle at 82% 20%, rgba(59, 130, 246, .14), transparent 30%),
    linear-gradient(135deg, #eef6f5 0%, #f8fafc 44%, #edf2f7 100%);
  overflow: hidden;
}
.login-body::before,
.login-body::after {
  content: "";
  position: fixed;
  inset: auto;
  pointer-events: none;
  z-index: 0;
}
.login-body::before {
  width: 760px;
  height: 760px;
  left: -220px;
  top: -260px;
  border-radius: 50%;
  background:
    repeating-linear-gradient(90deg, rgba(15, 118, 110, .10) 0 2px, transparent 2px 16px),
    radial-gradient(circle, rgba(20, 184, 166, .16), transparent 62%);
  animation: slowRotate 28s linear infinite;
}
.login-body::after {
  right: -180px;
  bottom: -220px;
  width: 640px;
  height: 640px;
  border-radius: 50%;
  background:
    linear-gradient(135deg, rgba(59, 130, 246, .14), transparent 58%),
    repeating-linear-gradient(0deg, rgba(15, 23, 42, .07) 0 1px, transparent 1px 18px);
  animation: driftPanel 18s ease-in-out infinite;
}
.login-shell {
  position: relative;
  display: grid;
  grid-template-columns: minmax(360px, .95fr) minmax(360px, 430px);
  gap: 18px;
  width: min(980px, 100%);
  min-height: 560px;
  z-index: 1;
}
.login-showcase,
.login-card {
  border: 1px solid rgba(148, 163, 184, .28);
  border-radius: 18px;
  box-shadow: 0 30px 80px rgba(15, 23, 42, .13);
}
.login-showcase {
  position: relative;
  overflow: hidden;
  padding: 28px;
  color: #ecfeff;
  background:
    linear-gradient(145deg, rgba(15, 23, 42, .94), rgba(15, 118, 110, .84)),
    #0f172a;
}
.login-showcase::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.06) 1px, transparent 1px);
  background-size: 34px 34px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.72), transparent);
}
.login-showcase::after {
  content: "";
  position: absolute;
  inset: 18px;
  border-radius: 16px;
  border: 1px solid rgba(94, 234, 212, .16);
  background:
    linear-gradient(90deg, transparent 0%, rgba(94, 234, 212, .11) 50%, transparent 100%);
  transform: translateX(-120%);
  animation: surfaceSweep 4.8s ease-in-out infinite;
  pointer-events: none;
}
.login-brand-lockup {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  z-index: 1;
}
.login-brand-mark {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  border-radius: 16px;
  background: linear-gradient(135deg, #14b8a6, #0f766e);
  font-weight: 950;
}
.login-brand-lockup h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
.login-brand-lockup p { max-width: 430px; margin: 6px 0 0; color: #b7f7ee; line-height: 1.5; }
.login-counter-scene {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1fr 160px;
  gap: 20px;
  align-items: end;
  min-height: 340px;
  margin-top: 34px;
}
.counter-terminal {
  position: relative;
  min-height: 270px;
  padding: 18px;
  border: 1px solid rgba(255,255,255,.2);
  border-radius: 18px;
  background: rgba(15, 23, 42, .72);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 30px 70px rgba(0,0,0,.22);
}
.terminal-top {
  height: 20px;
  border-radius: 999px;
  background: linear-gradient(90deg, #14b8a6, #93c5fd);
}
.terminal-screen {
  display: grid;
  gap: 12px;
  margin-top: 20px;
  padding: 18px;
  border-radius: 14px;
  background: #ecfeff;
}
.terminal-screen span {
  display: block;
  height: 12px;
  border-radius: 999px;
  background: #0f766e;
  opacity: .85;
  animation: loginPulse 1.6s ease-in-out infinite;
}
.terminal-screen span:nth-child(2) { width: 74%; animation-delay: .18s; }
.terminal-screen span:nth-child(3) { width: 54%; animation-delay: .32s; }
.terminal-keys {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 18px;
}
.terminal-keys i {
  height: 36px;
  border-radius: 10px;
  background: rgba(255,255,255,.12);
}
.receipt-strip {
  display: grid;
  gap: 12px;
  padding: 18px 16px;
  border-radius: 14px;
  color: #0f172a;
  background: #ffffff;
  box-shadow: 0 24px 50px rgba(0,0,0,.18);
  animation: receiptFloat 4.2s ease-in-out infinite;
}
.receipt-strip strong { font-size: 13px; }
.receipt-strip span { padding-top: 10px; border-top: 1px dashed #cbd5e1; color: #475569; font-size: 12px; font-weight: 800; }
.scan-beam {
  position: absolute;
  left: 20px;
  right: 190px;
  top: 120px;
  height: 3px;
  border-radius: 999px;
  background: #5eead4;
  box-shadow: 0 0 24px #5eead4;
  animation: scanBeam 2.2s ease-in-out infinite;
  z-index: 2;
}
.login-status-row {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 26px;
}
.login-status-row span {
  padding: 9px 12px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 999px;
  color: #ccfbf1;
  background: rgba(255,255,255,.08);
  font-size: 12px;
  font-weight: 900;
}
.inventory-flow {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
}
.flow-card {
  position: absolute;
  display: grid;
  gap: 3px;
  min-width: 118px;
  padding: 12px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 14px;
  color: #ecfeff;
  background: rgba(15, 23, 42, .54);
  box-shadow: 0 18px 40px rgba(0,0,0,.18);
  backdrop-filter: blur(8px);
}
.flow-card span {
  color: #99f6e4;
  font-size: 11px;
  font-weight: 950;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.flow-card strong { font-size: 15px; }
.flow-card-a { right: 34px; top: 116px; animation: inventoryMatchA 5.4s ease-in-out infinite; }
.flow-card-b { left: 42px; bottom: 116px; animation: inventoryMatchB 5.8s ease-in-out infinite; }
.flow-card-c { right: 190px; bottom: 54px; animation: inventoryMatchC 6.2s ease-in-out infinite; }
.barcode-ribbon {
  position: absolute;
  left: 36px;
  right: 36px;
  bottom: 26px;
  display: flex;
  gap: 5px;
  height: 38px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255,255,255,.08);
  opacity: .86;
  overflow: hidden;
}
.barcode-ribbon::after {
  content: "";
  position: absolute;
  top: 6px;
  bottom: 6px;
  width: 42px;
  border-radius: 999px;
  background: rgba(94, 234, 212, .34);
  box-shadow: 0 0 22px rgba(94, 234, 212, .76);
  animation: barcodeScan 2.4s ease-in-out infinite;
}
.barcode-ribbon i {
  display: block;
  width: 8px;
  height: 100%;
  border-radius: 2px;
  background: rgba(236, 254, 255, .82);
}
.barcode-ribbon i:nth-child(2),
.barcode-ribbon i:nth-child(5) { width: 3px; }
.barcode-ribbon i:nth-child(3),
.barcode-ribbon i:nth-child(7) { width: 14px; }
.barcode-ribbon i:nth-child(6) { width: 18px; }
.login-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 34px;
  background: rgba(255, 255, 255, .92);
  backdrop-filter: blur(18px);
}
.login-card-head { margin-bottom: 24px; }
.login-kicker { color: var(--primary); font-size: 12px; font-weight: 950; text-transform: uppercase; letter-spacing: .08em; }
.login-card h2 { margin: 8px 0 8px; font-size: 32px; letter-spacing: 0; }
.login-card p, .hint { color: #607080; }
.login-card form { display: grid; gap: 10px; }
.login-card label { margin-top: 4px; font-size: 13px; font-weight: 900; }
.login-card input {
  height: 46px;
  border-radius: 10px;
  background: #f8fafc;
}
.login-card button {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 48px;
  margin-top: 10px;
  border-radius: 10px;
}
.login-card button i {
  display: none;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,.45);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: loaderSpin .8s linear infinite;
}
.login-shell.is-loading .login-card button i { display: inline-block; }
.login-loader {
  position: absolute;
  inset: 0;
  display: none;
  place-items: center;
  align-content: center;
  gap: 12px;
  border-radius: 18px;
  color: #ecfeff;
  background: rgba(15, 23, 42, .72);
  backdrop-filter: blur(10px);
  z-index: 5;
}
.login-shell.is-loading .login-loader { display: grid; }
.loader-ring {
  width: 58px;
  height: 58px;
  border: 4px solid rgba(255,255,255,.24);
  border-top-color: #5eead4;
  border-radius: 50%;
  animation: loaderSpin .85s linear infinite;
}
.login-loader strong { font-size: 20px; }
.login-loader span { color: #b7f7ee; font-size: 13px; }
@keyframes loaderSpin { to { transform: rotate(360deg); } }
@keyframes loginPulse {
  0%, 100% { transform: scaleX(.82); opacity: .55; }
  50% { transform: scaleX(1); opacity: .95; }
}
@keyframes scanBeam {
  0%, 100% { transform: translateY(-62px); opacity: .15; }
  50% { transform: translateY(92px); opacity: .95; }
}
@keyframes receiptFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}
@keyframes slowRotate { to { transform: rotate(360deg); } }
@keyframes driftPanel {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  50% { transform: translate(-42px, -28px) rotate(8deg); }
}
@keyframes surfaceSweep {
  0%, 100% { transform: translateX(-130%); opacity: 0; }
  18%, 60% { opacity: .7; }
  70% { transform: translateX(130%); opacity: 0; }
}
@keyframes inventoryMatchA {
  0%, 100% { transform: translate(0, 0); opacity: .72; }
  50% { transform: translate(-18px, 14px); opacity: 1; }
}
@keyframes inventoryMatchB {
  0%, 100% { transform: translate(0, 0); opacity: .7; }
  50% { transform: translate(24px, -12px); opacity: 1; }
}
@keyframes inventoryMatchC {
  0%, 100% { transform: translate(0, 0); opacity: .66; }
  50% { transform: translate(18px, -18px); opacity: 1; }
}
@keyframes barcodeScan {
  0%, 100% { left: -50px; opacity: .08; }
  45%, 55% { opacity: 1; }
  70% { left: calc(100% + 10px); opacity: .08; }
}
label { display: block; margin: 16px 0 6px; font-weight: 800; }
input, select, textarea { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; padding: 11px 12px; font-size: 15px; background: white; color: var(--text); font-family: inherit; }
input[type="color"] { min-height: 44px; padding: 5px; }
textarea { resize: vertical; }
button { width: 100%; margin-top: 18px; background: var(--primary); border-color: var(--primary); color: white; }
.error { margin: 16px 0; padding: 10px 12px; border-radius: 6px; color: #991b1b; background: #fee2e2; }
.success { margin: 16px 0; padding: 10px 12px; border-radius: 6px; color: #065f46; background: #d1fae5; }
@media print {
  body { background: white; }
  .sidebar, .topbar, .label-page-title, .label-toolbar { display: none !important; }
  .app { margin-left: 0; }
  .content { padding: 0; }
  .label-sheet-panel { padding: 0; border: 0; box-shadow: none; background: white; }
  .label-grid { grid-template-columns: repeat(3, 64mm); gap: 4mm; align-items: start; }
  .label-box { width: 64mm; min-height: 38mm; box-shadow: none; border-color: #111827; page-break-inside: avoid; }
}
@media (max-width: 1100px) and (min-width: 901px) {
  .pos-shell { grid-template-columns: minmax(340px, 1fr) minmax(320px, .9fr); }
  .pos-product-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pos-action-bar { grid-template-columns: repeat(4, minmax(90px, 1fr)); }
  .pos-action-divider { display: none; }
  .pos-action-complete, .pos-action-cash { grid-column: span 2; }
}
@media (max-width: 900px) {
  .login-body { padding: 14px; }
  .login-shell { grid-template-columns: 1fr; min-height: auto; }
  .login-showcase { min-height: 300px; padding: 20px; }
  .login-counter-scene { grid-template-columns: 1fr; min-height: 220px; margin-top: 22px; }
  .receipt-strip { display: none; }
  .flow-card { display: none; }
  .barcode-ribbon { left: 20px; right: 20px; bottom: 16px; }
  .scan-beam { right: 20px; }
  .login-card { padding: 24px; }
  .login-card h2 { font-size: 26px; }
  .sidebar { position: static; width: 100%; max-height: 420px; border-right: 0; border-bottom: 1px solid var(--sidebar-border); }
  .app { margin-left: 0; }
  .topbar { height: auto; align-items: flex-start; flex-direction: column; }
  .dashboard-hero { flex-direction: column; }
  .hero-balance { min-width: 0; }
  .dash-metrics, .dash-layout, .action-grid, .metrics, .woo-hero, .woo-workflow, .woo-layout, .user-overview, .role-stats, .role-layout, .role-workflow, .role-edit-grid, .agent-stats, .agent-layout, .agent-edit-grid, .contact-stats, .contact-person-grid, .supplier-filter-form, .supplier-summary-row, .product-stats, .product-filter-form, .product-image-uploader, .category-template-form, .purchase-filter-form, .purchase-item-entry, .purchase-detail-metrics, .purchase-detail-summary, .purchase-payment-grid, .pos-shell, .pos-toolbar, .pos-meta, .grid, .contacts-grid, .form-grid, .form-grid.two-col, .form-grid.three-col, .expense-filter-grid, .report-filter-grid, .sales-history-filter-grid, .expense-type-control, .expense-attachment { grid-template-columns: 1fr; }
  .woo-action-list form { grid-template-columns: 1fr; }
  .dash-panel-wide { grid-column: auto; }
  .action-title, .form-actions, .inline-filter, .product-title-actions, .product-viewbar, .product-filter-actions { align-items: stretch; flex-direction: column; }
  .user-form-layout, .permission-grid, .role-permission-grid { grid-template-columns: 1fr; }
  .form-section { border-right: 0; }
  .sticky-form-actions { position: static; flex-direction: column; }
  .user-form-head { flex-direction: column; }
  .staff-advanced summary { align-items: flex-start; flex-direction: column; }
  .staff-advanced summary small { margin-left: 0; }
  .inline-filter .field { min-width: 0; }
  .inline-action button { width: 100%; }
  .role-card-head { flex-direction: column; }
  .role-card-head button { width: 100%; }
  .agent-card-head { flex-direction: column; }
  .agent-card-head button { width: 100%; }
  .contact-card-head, .modal-head { flex-direction: column; }
  .contact-card-head button, .modal-close { width: 100%; }
  .supplier-list-head { flex-direction: column; }
  .supplier-list-head .primary-link, .supplier-filter-form button, .supplier-filter-form .secondary-link, .category-template-form button, .product-filter-form button, .product-filter-actions .secondary-link { width: 100%; }
  .purchase-filter-form button, .purchase-filter-form .secondary-link { width: 100%; }
  .purchase-product-picker, .purchase-quick-grid { grid-template-columns: 1fr; }
  .barcode-input-row { grid-template-columns: 1fr; }
  .barcode-input-row button { width: 100%; }
  .purchase-new-product-button { width: 100%; }
  .purchase-quick-actions { flex-direction: column-reverse; }
  .purchase-quick-actions button { width: 100%; }
  .purchase-detail-body { padding: 10px; }
  .purchase-detail-toolbar, .purchase-detail-section-head { align-items: stretch; flex-direction: column; }
  .purchase-detail-actions a, .purchase-detail-actions button { flex: 1; }
  .purchase-detail-table { overflow-x: auto; }
  .purchase-payment-grid > div { border-right: 0; border-bottom: 1px solid var(--border); }
  .pos-top-context { width: 100%; flex-wrap: wrap; margin-right: 0; }
  .pos-shell { grid-template-rows: auto; }
  .pos-cart-panel, .pos-catalog { min-height: 620px; }
  .pos-cart-entry-row { grid-template-columns: 1fr; }
  .pos-cart-line { grid-template-columns: 1fr; }
  .pos-cart-header { display: none; }
  .pos-line-price, .pos-line-discount, .pos-line-price-view, .pos-line-save, .pos-line-subtotal, .pos-remove { justify-self: stretch; width: 100%; }
  .pos-checkout-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pos-checkout-strip .pos-total-cell:nth-child(5), .pos-checkout-strip .pos-grand-total { grid-column: auto; grid-row: auto; }
  .pos-payment-row { grid-template-columns: 1fr; }
  .pos-split-row { grid-template-columns: 1fr; }
  .pos-product-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
  .pos-action-bar { grid-column: auto; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pos-action-divider { display: none; }
  .pos-action-compact { flex-direction: row; min-height: 42px; }
  .sales-return-workspace, .return-sale-summary { grid-template-columns: 1fr; }
  .return-editor-panel { position: static; }
  .register-open-card, .register-open-form, .register-metrics, .register-main-grid { grid-template-columns: 1fr; }
  .register-live-head { align-items: stretch; flex-direction: column; }
  .register-open-form button, .register-live-head .secondary-link { width: 100%; }
  .modal-screen { align-items: stretch; padding: 10px; }
  .modal-panel { max-height: calc(100vh - 20px); }
}

/* POS login experience */
.login-body {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 32px;
  color: #17201f;
  background: #e9f0ee;
  overflow: hidden;
}
.login-body::before {
  inset: 0;
  width: auto;
  height: auto;
  border-radius: 0;
  background-image: linear-gradient(rgba(20, 83, 75, .045) 1px, transparent 1px), linear-gradient(90deg, rgba(20, 83, 75, .045) 1px, transparent 1px);
  background-size: 32px 32px;
  animation: loginGridMove 18s linear infinite;
}
.login-body::after {
  right: 5vw;
  bottom: 6vh;
  width: 180px;
  height: 48px;
  border: 0;
  border-radius: 0;
  background: repeating-linear-gradient(90deg, #173e3a 0 4px, transparent 4px 9px);
  opacity: .08;
  animation: barcodeDrift 9s ease-in-out infinite;
}
.login-shell {
  grid-template-columns: minmax(560px, 1.35fr) minmax(360px, .78fr);
  gap: 0;
  width: min(1120px, 100%);
  min-height: 650px;
  border: 1px solid #b9cbc7;
  border-radius: 24px;
  background: #ffffff;
  box-shadow: 0 28px 70px rgba(22, 49, 45, .16);
  overflow: hidden;
}
.login-showcase,
.login-card { border: 0; border-radius: 0; box-shadow: none; }
.login-showcase {
  display: flex;
  flex-direction: column;
  padding: 34px 38px 28px;
  color: #f2fffc;
  background: #113f3a;
}
.login-showcase::before {
  background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: none;
}
.login-showcase::after {
  inset: 0;
  border: 0;
  border-radius: 0;
  background: linear-gradient(90deg, transparent, rgba(88, 222, 198, .08), transparent);
  animation: surfaceSweep 7s ease-in-out infinite;
}
.login-brand-lockup { min-height: 48px; gap: 12px; }
.login-brand-mark {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  color: #103b36;
  background: #63e6cb;
  box-shadow: 0 8px 22px rgba(0,0,0,.16);
}
.login-brand-lockup h1 { font-size: 21px; }
.login-brand-lockup p { margin-top: 2px; color: #afd8d1; font-size: 12px; }
.login-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  padding: 8px 11px;
  border: 1px solid rgba(152, 251, 230, .24);
  border-radius: 999px;
  color: #d8fff7;
  background: rgba(0,0,0,.12);
  font-size: 11px;
  font-weight: 850;
}
.login-live-pill i,
.login-status-row i,
.secure-note i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #51e3a4;
  box-shadow: 0 0 0 4px rgba(81, 227, 164, .12);
  animation: statusPulse 1.8s ease-in-out infinite;
}
.login-showcase-copy { position: relative; z-index: 2; margin: 38px 0 24px; }
.login-showcase-copy > span { color: #69e2cb; font-size: 11px; font-weight: 950; }
.login-showcase-copy h2 { margin: 8px 0 0; max-width: 560px; font-size: 31px; line-height: 1.16; letter-spacing: 0; }
.login-counter-scene {
  grid-template-columns: minmax(280px, 1fr) 168px;
  align-items: center;
  min-height: 270px;
  margin: 0;
  padding: 20px;
  border: 1px solid rgba(179, 244, 231, .17);
  border-radius: 16px;
  background: #0d342f;
  overflow: hidden;
}
.counter-terminal {
  min-height: 214px;
  padding: 14px;
  border-color: rgba(255,255,255,.12);
  border-radius: 12px;
  background: #f3faf8;
  box-shadow: 0 18px 35px rgba(0,0,0,.22);
  transform: perspective(800px) rotateY(3deg);
}
.terminal-top { height: 9px; background: #5bd7c1; }
.terminal-screen { gap: 9px; margin-top: 14px; padding: 15px; background: #dff6f1; }
.terminal-screen span { height: 9px; background: #267f73; transform-origin: left; }
.terminal-keys { gap: 7px; margin-top: 12px; }
.terminal-keys i { height: 28px; border: 1px solid #d4e5e1; border-radius: 7px; background: #ffffff; }
.receipt-strip {
  gap: 9px;
  padding: 16px 14px 20px;
  border-radius: 5px 5px 12px 12px;
  background: #fffdf6;
  box-shadow: 0 18px 36px rgba(0,0,0,.2);
  animation: receiptFeed 4s ease-in-out infinite;
}
.receipt-strip strong { color: #117267; }
.receipt-strip span { padding-top: 8px; font-size: 10px; }
.scan-beam {
  left: 38px;
  right: 214px;
  top: 80px;
  height: 2px;
  background: #ff806d;
  box-shadow: 0 0 18px #ff806d;
  animation: checkoutScan 2.7s ease-in-out infinite;
}
.inventory-flow { display: none; }
.login-status-row { margin-top: auto; padding-top: 22px; gap: 20px; }
.login-status-row span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: #b9ddd6;
  background: transparent;
  font-size: 11px;
}
.login-status-row i { width: 5px; height: 5px; box-shadow: none; animation: none; }
.login-card {
  position: relative;
  justify-content: center;
  padding: 52px 48px;
  background: #ffffff;
}
.login-card::before {
  content: "COUNTER 01";
  position: absolute;
  top: 24px;
  right: 28px;
  color: #8aa09c;
  font-size: 10px;
  font-weight: 900;
}
.login-card-head { margin-bottom: 28px; }
.login-kicker { color: #117267; font-size: 10px; letter-spacing: .14em; }
.login-card h2 { margin: 10px 0 8px; font-size: 34px; color: #17201f; }
.login-card p { margin: 0; color: #73817f; font-size: 14px; }
.login-card form { gap: 8px; }
.login-card label { margin: 10px 0 0; color: #34423f; font-size: 12px; }
.login-input-wrap {
  display: grid;
  grid-template-columns: 42px 1fr;
  align-items: center;
  height: 50px;
  border: 1px solid #cbd8d5;
  border-radius: 9px;
  background: #f7faf9;
  transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
}
.login-input-wrap:focus-within { border-color: #168c7c; box-shadow: 0 0 0 4px rgba(22, 140, 124, .1); transform: translateY(-1px); }
.login-input-wrap > span { display: grid; place-items: center; height: 24px; border-right: 1px solid #d8e2df; color: #65807b; font-size: 13px; font-weight: 900; }
.login-card .login-input-wrap input { height: 48px; padding: 0 12px; border: 0; border-radius: 0; outline: 0; background: transparent; }
.login-card button {
  height: 50px;
  margin-top: 18px;
  border-radius: 9px;
  background: #117267;
  box-shadow: 0 10px 22px rgba(17, 114, 103, .2);
  transition: transform .2s ease, background .2s ease, box-shadow .2s ease;
}
.login-card button:hover { background: #0b5d54; box-shadow: 0 13px 28px rgba(17, 114, 103, .26); transform: translateY(-2px); }
.login-help-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; }
.login-help-row .hint { color: #84918f; font-size: 11px; }
.secure-note { display: inline-flex; align-items: center; gap: 7px; color: #48706a; font-size: 10px; font-weight: 850; }
.secure-note i { width: 5px; height: 5px; box-shadow: none; animation: none; }
.login-loader { border-radius: 0; background: rgba(8, 38, 34, .92); }
.loader-inventory { display: flex; align-items: flex-end; gap: 7px; height: 48px; }
.loader-inventory span { width: 34px; height: 34px; border: 2px solid #a8f4e5; border-radius: 5px; background: #1d7468; animation: loaderParcel 1.15s ease-in-out infinite; }
.loader-inventory span:nth-child(2) { height: 44px; animation-delay: .14s; }
.loader-inventory span:nth-child(3) { animation-delay: .28s; }

@keyframes loginGridMove { to { background-position: 32px 32px; } }
@keyframes barcodeDrift { 0%, 100% { transform: translateX(0); } 50% { transform: translateX(-70px); } }
@keyframes statusPulse { 50% { opacity: .45; transform: scale(.75); } }
@keyframes checkoutScan { 0%, 100% { transform: translateY(0); opacity: .15; } 50% { transform: translateY(152px); opacity: 1; } }
@keyframes receiptFeed { 0%, 100% { transform: translateY(12px); } 50% { transform: translateY(-8px); } }
@keyframes loaderParcel { 0%, 100% { transform: translateY(0); opacity: .55; } 50% { transform: translateY(-14px); opacity: 1; } }

@media (max-width: 900px) {
  .login-body { align-items: start; padding: 16px; overflow: auto; }
  .login-shell { grid-template-columns: 1fr; width: min(560px, 100%); min-height: 0; margin: auto; }
  .login-showcase { min-height: 330px; padding: 24px; }
  .login-brand-lockup p, .login-live-pill { display: none; }
  .login-showcase-copy { margin: 26px 0 18px; }
  .login-showcase-copy h2 { font-size: 25px; }
  .login-counter-scene { grid-template-columns: 1fr 120px; min-height: 180px; padding: 12px; }
  .counter-terminal { min-height: 150px; }
  .terminal-keys i { height: 18px; }
  .receipt-strip { display: grid; }
  .scan-beam { right: 150px; top: 52px; }
  .login-status-row { display: none; }
  .login-card { padding: 40px 28px; }
}
@media (max-width: 520px) {
  .login-body { padding: 0; background: #ffffff; }
  .login-shell, .login-showcase, .login-card, .login-counter-scene, .counter-terminal, .login-input-wrap { width: 100%; min-width: 0; max-width: 100%; }
  .login-shell { border: 0; border-radius: 0; box-shadow: none; overflow: hidden; }
  .login-showcase { min-height: 240px; overflow: hidden; }
  .login-showcase-copy h2 { font-size: 22px; }
  .login-counter-scene { grid-template-columns: minmax(0, 1fr); width: calc(100% - 48px); min-height: 112px; }
  .counter-terminal { min-height: 98px; padding: 8px; transform: none; }
  .terminal-screen { margin-top: 8px; padding: 8px; }
  .terminal-screen span { height: 5px; }
  .terminal-keys { display: none; }
  .receipt-strip { display: none; }
  .scan-beam { right: 20px; top: 36px; animation: none; }
  .login-card::before { display: none; }
  .login-card { padding: 34px 22px 40px; }
  .login-card-head, .login-card form, .login-help-row, .login-card > .error { width: calc(100% - 44px); max-width: calc(100% - 44px); }
  .login-card .login-input-wrap input { width: 100%; min-width: 0; }
  .login-card h2 { font-size: 28px; }
  .login-help-row { align-items: flex-start; flex-direction: column; }
}

/* Advanced login composition */
.login-body {
  padding: 24px;
  background: #071c1a;
}
.login-body::before {
  background-image: linear-gradient(rgba(118, 231, 207, .045) 1px, transparent 1px), linear-gradient(90deg, rgba(118, 231, 207, .045) 1px, transparent 1px);
  background-size: 40px 40px;
}
.login-body::after {
  right: 3vw;
  bottom: 4vh;
  width: 240px;
  opacity: .13;
  background: repeating-linear-gradient(90deg, #74ead1 0 3px, transparent 3px 8px);
}
.login-shell {
  grid-template-columns: minmax(650px, 1.45fr) minmax(380px, .72fr);
  width: min(1220px, 100%);
  min-height: 700px;
  border-color: rgba(190, 240, 229, .19);
  border-radius: 28px;
  background: #f7faf9;
  box-shadow: 0 44px 120px rgba(0, 0, 0, .42);
  animation: loginStageIn .7s cubic-bezier(.2,.8,.2,1) both;
}
.login-showcase {
  padding: 32px 40px 24px;
  background: #0b332f;
}
.login-showcase::before {
  background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
  background-size: 32px 32px;
}
.login-showcase::after { background: linear-gradient(90deg, transparent, rgba(115, 235, 210, .085), transparent); }
.login-brand-lockup { animation: loginContentIn .6s .12s ease both; }
.login-brand-mark {
  color: #082f2b;
  background: #75ead2;
  box-shadow: 0 10px 30px rgba(117, 234, 210, .2);
}
.login-live-pill { border-color: rgba(117, 234, 210, .25); background: #092925; }
.login-showcase-copy { margin: 30px 0 18px; animation: loginContentIn .65s .2s ease both; }
.login-showcase-copy > span { color: #75ead2; letter-spacing: .12em; }
.login-showcase-copy h2 { font-size: 38px; line-height: 1.08; }
.login-showcase-copy h2 em { color: #75ead2; font-style: normal; font-weight: 800; }
.login-metrics {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin-bottom: 18px;
  border-top: 1px solid rgba(202, 247, 237, .14);
  border-bottom: 1px solid rgba(202, 247, 237, .14);
  animation: loginContentIn .65s .28s ease both;
}
.login-metrics > div { display: grid; gap: 4px; padding: 13px 16px 13px 0; }
.login-metrics > div + div { padding-left: 18px; border-left: 1px solid rgba(202, 247, 237, .14); }
.login-metrics span { color: #8abbb2; font-size: 9px; font-weight: 900; text-transform: uppercase; }
.login-metrics strong { color: #f4fffc; font-size: 19px; }
.login-metrics small { color: #63d9bf; font-size: 9px; font-weight: 850; }
.login-counter-scene {
  grid-template-columns: minmax(360px, 1fr) 154px;
  gap: 16px;
  min-height: 288px;
  padding: 16px;
  border-color: rgba(202, 247, 237, .14);
  border-radius: 18px;
  background: #072722;
  box-shadow: inset 0 1px rgba(255,255,255,.05), 0 20px 50px rgba(0,0,0,.17);
  animation: loginContentIn .7s .34s ease both;
}
.counter-terminal {
  min-height: 252px;
  padding: 0;
  border: 1px solid rgba(15, 70, 63, .16);
  border-radius: 13px;
  background: #f4f8f7;
  transform: none;
  overflow: hidden;
}
.terminal-top {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 12px;
  border-radius: 0;
  color: #718681;
  background: #e6efec;
}
.terminal-top i { width: 6px; height: 6px; border-radius: 50%; background: #a7bbb6; }
.terminal-top i:first-child { background: #ff7968; }
.terminal-top span { margin-left: 7px; font-size: 9px; font-weight: 850; }
.terminal-top strong { margin-left: auto; color: #187e70; font-size: 8px; }
.terminal-screen { gap: 10px; margin: 0; padding: 13px 14px 11px; border-radius: 0; background: #f4f8f7; }
.terminal-chart-head { display: flex; align-items: center; justify-content: space-between; color: #415650; font-size: 9px; font-weight: 850; }
.terminal-chart-head strong { padding: 4px 6px; border-radius: 4px; color: #0b6a5e; background: #d9f5ee; font-size: 7px; }
.terminal-chart {
  display: flex;
  align-items: end;
  gap: 6px;
  height: 66px;
  padding: 8px 9px 0;
  border-left: 1px solid #dbe7e4;
  border-bottom: 1px solid #dbe7e4;
  background-image: linear-gradient(#e4eeeb 1px, transparent 1px);
  background-size: 100% 18px;
}
.terminal-chart i {
  flex: 1;
  height: var(--bar);
  border-radius: 3px 3px 0 0;
  background: #27aa98;
  transform-origin: bottom;
  animation: chartGrow 2.8s ease-in-out infinite alternate;
}
.terminal-chart i:nth-child(3n) { background: #ff7968; }
.terminal-chart i:nth-child(2n) { animation-delay: .22s; }
.terminal-keys { display: grid; grid-template-columns: 1fr; gap: 0; margin: 0; padding: 0 14px 10px; }
.terminal-keys > div { display: grid; grid-template-columns: 24px 1fr auto; align-items: center; gap: 9px; min-width: 0; padding: 8px 0; border-top: 1px solid #dde8e5; }
.sale-product-dot { width: 24px; height: 24px; border-radius: 7px; }
.dot-mint { background: #9ae8d7; }
.dot-coral { background: #ffc0b7; }
.terminal-keys p { min-width: 0; margin: 0; }
.terminal-keys p strong, .terminal-keys p small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.terminal-keys p strong { color: #243c37; font-size: 9px; }
.terminal-keys p small { margin-top: 2px; color: #849691; font-size: 7px; }
.terminal-keys b { color: #183f39; font-size: 9px; }
.receipt-strip {
  align-self: center;
  gap: 8px;
  padding: 17px 13px 21px;
  border-radius: 5px 5px 10px 10px;
  animation: advancedReceipt 4.5s ease-in-out infinite;
}
.receipt-strip::after { content: ""; height: 20px; margin: 2px 0 -13px; background: repeating-linear-gradient(90deg, #183f39 0 2px, transparent 2px 5px); opacity: .58; }
.receipt-success { display: flex; align-items: center; gap: 7px; color: #0f766e; }
.receipt-success i { width: 16px; height: 16px; border: 4px solid #b8f0e5; border-radius: 50%; background: #1ca58f; }
.receipt-strip small { color: #788983; font-size: 7px; }
.receipt-strip span { display: flex; justify-content: space-between; gap: 5px; padding-top: 7px; font-size: 8px; }
.scene-scan-tag {
  position: absolute;
  left: 34px;
  bottom: 8px;
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 1px 8px;
  min-width: 146px;
  padding: 8px 10px;
  border: 1px solid rgba(117, 234, 210, .24);
  border-radius: 8px;
  color: #d9fff7;
  background: #0a3a34;
  box-shadow: 0 12px 25px rgba(0,0,0,.2);
  animation: scanTag 3.2s ease-in-out infinite;
  z-index: 4;
}
.scene-scan-tag i { grid-row: span 2; width: 24px; height: 24px; border-radius: 6px; background: #75ead2; }
.scene-scan-tag span { font-size: 7px; }
.scene-scan-tag strong { color: #75ead2; font-size: 9px; }
.scan-beam { left: 30px; right: 198px; top: 65px; background: #ff7968; animation: checkoutScanAdvanced 3s ease-in-out infinite; }
.login-status-row { padding-top: 15px; }
.login-card {
  padding: 58px 48px;
  background: rgba(248, 251, 250, .97);
}
.login-card::after {
  content: "";
  position: absolute;
  left: 48px;
  right: 48px;
  top: 0;
  height: 3px;
  background: #75ead2;
}
.login-card-head, .login-card form, .login-help-row { animation: loginFormIn .65s .2s ease both; }
.login-card h2 { font-size: 38px; }
.login-input-wrap { height: 54px; border-color: #c4d5d1; background: #ffffff; }
.login-card .login-input-wrap input { height: 52px; }
.login-card button { height: 54px; background: #0c7669; }
.login-card button:hover { background: #075e54; }
.login-loader { background: rgba(4, 27, 24, .94); }

@keyframes loginStageIn { from { opacity: 0; transform: translateY(18px) scale(.985); } to { opacity: 1; transform: none; } }
@keyframes loginContentIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes loginFormIn { from { opacity: 0; transform: translateX(14px); } to { opacity: 1; transform: none; } }
@keyframes chartGrow { 0% { transform: scaleY(.55); opacity: .65; } 100% { transform: scaleY(1); opacity: 1; } }
@keyframes advancedReceipt { 0%, 100% { transform: translateY(10px) rotate(0); } 50% { transform: translateY(-7px) rotate(.6deg); } }
@keyframes checkoutScanAdvanced { 0%, 100% { transform: translateY(0); opacity: 0; } 20% { opacity: 1; } 70% { transform: translateY(150px); opacity: .9; } 82% { opacity: 0; } }
@keyframes scanTag { 0%, 100% { transform: translateX(0); opacity: .78; } 50% { transform: translateX(16px); opacity: 1; } }

@media (max-width: 1050px) and (min-width: 901px) {
  .login-shell { grid-template-columns: minmax(520px, 1.2fr) minmax(350px, .8fr); }
  .login-showcase { padding-inline: 28px; }
  .login-showcase-copy h2 { font-size: 32px; }
}
@media (max-width: 900px) {
  .login-shell { grid-template-columns: 1fr; width: min(620px, 100%); }
  .login-showcase { min-height: 500px; }
  .login-showcase-copy h2 { font-size: 31px; }
  .login-card { padding: 48px 36px; }
}
@media (max-width: 520px) {
  .login-body { padding: 0; background: #0b332f; }
  .login-shell, .login-showcase, .login-card { width: 100vw; max-width: 100vw; min-width: 0; }
  .login-showcase { min-height: 375px; padding: 22px; }
  .login-showcase-copy { margin: 24px 0 14px; }
  .login-showcase-copy h2 { font-size: 27px; }
  .login-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); width: calc(88vw - 24px); max-width: calc(88vw - 24px); }
  .login-metrics > div { min-width: 0; overflow: hidden; }
  .login-metrics span, .login-metrics strong, .login-metrics small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .login-metrics > div { padding: 9px 7px 9px 0; }
  .login-metrics > div + div { padding-left: 8px; }
  .login-metrics strong { font-size: 13px; }
  .login-counter-scene { width: calc(88vw - 24px); max-width: calc(88vw - 24px); min-height: 128px; padding: 10px; }
  .counter-terminal { min-height: 108px; }
  .terminal-top { height: 26px; }
  .terminal-screen { padding: 8px; }
  .terminal-chart { height: 46px; }
  .terminal-keys, .scene-scan-tag { display: none; }
  .scan-beam { left: 18px; right: 18px; top: 42px; animation: checkoutScanAdvanced 3s ease-in-out infinite; }
  .login-card { width: 100%; padding: 38px 22px 44px; }
  .login-card::after { left: 22px; right: 22px; }
  .login-card-head, .login-card form, .login-help-row, .login-card > .error { width: calc(88vw - 24px); max-width: calc(88vw - 24px); }
}
@media (prefers-reduced-motion: reduce) {
  .login-body::before, .login-body::after, .login-shell, .login-showcase::after, .login-brand-lockup, .login-showcase-copy, .login-metrics, .login-counter-scene, .login-card-head, .login-card form, .login-help-row, .login-live-pill i, .terminal-chart i, .receipt-strip, .scan-beam, .scene-scan-tag, .loader-inventory span { animation: none !important; }
}

/* Responsive workspace guardrails */
html, body { width: 100%; max-width: 100%; overflow-x: clip; }
.app { width: calc(100% - 304px); min-width: 0; max-width: calc(100vw - 304px); }
.topbar, .content { width: 100%; min-width: 0; max-width: 100%; }
.content > *, .panel, .metric, .table-panel, .report-filter-panel, .report-sheet-panel { min-width: 0; max-width: 100%; }
.report-sheet-panel, .expense-sheet-panel { overflow: hidden; }
.report-sheet-scroll, .expense-sheet-scroll, .table-panel > .table-scroll { width: 100%; max-width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; scrollbar-gutter: stable; }
.report-filter-grid, .expense-filter-grid, .sales-history-filter-grid {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 132px), 1fr));
  width: 100%;
  min-width: 0;
}
.report-filter-grid > *, .expense-filter-grid > *, .sales-history-filter-grid > * { min-width: 0; }
.report-filter-grid .field:first-of-type, .expense-filter-grid .field:first-of-type, .sales-history-filter-grid .field:first-of-type { grid-column: span 2; }
.report-filter-grid input, .report-filter-grid select, .expense-filter-grid input, .expense-filter-grid select, .sales-history-filter-grid input, .sales-history-filter-grid select { min-width: 0; max-width: 100%; }
.expense-filter-actions { width: 100%; min-width: 0; }
.metrics, .dash-metrics, .product-stats, .role-stats, .contact-stats, .supplier-summary-row, .purchase-detail-metrics {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
}
.action-title, .report-title, .topbar { flex-wrap: wrap; }
.action-title > *, .report-title > *, .topbar > * { min-width: 0; }
.quick-actions, .top-actions { max-width: 100%; }
.quick-actions a, .quick-actions button, .top-actions a { white-space: nowrap; }
.restore-action {
  display: inline-grid;
  grid-template-columns: minmax(120px, 1fr) auto;
  gap: 6px;
  align-items: center;
}
.restore-action input {
  min-width: 0;
  height: 34px;
  padding: 7px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
}
.setup-list {
  display: grid;
  gap: 10px;
}
.setup-list div {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 10px;
  align-items: start;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}
.setup-list strong {
  display: inline-grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 999px;
  background: #ecfeff;
  color: #0f766e;
}
.muted-copy { color: #64748b; margin-top: 0; }

@media (max-width: 1200px) and (min-width: 901px) {
  .content { padding: 20px; }
  .topbar { padding: 14px 20px; }
  .pos-browser-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pos-browser-tab[data-pos-featured-filter] { grid-column: span 2; }
  .pos-drawer-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-filter-grid, .expense-filter-grid, .sales-history-filter-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); }
  .report-filter-grid .field:first-of-type, .expense-filter-grid .field:first-of-type, .sales-history-filter-grid .field:first-of-type { grid-column: span 2; }
}
@media (max-width: 900px) {
  html, body { overflow-x: hidden; }
  .app { width: 100%; max-width: 100%; margin-left: 0; }
  .content { padding: 16px; }
  .pos-browser-tabs { grid-template-columns: 1fr; }
  .pos-browser-drawer { width: 100%; }
  .pos-drawer-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-filter-grid, .expense-filter-grid, .sales-history-filter-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); }
  .report-filter-grid .field:first-of-type, .expense-filter-grid .field:first-of-type, .sales-history-filter-grid .field:first-of-type { grid-column: auto; }
  .metrics, .dash-metrics, .product-stats, .role-stats, .contact-stats, .supplier-summary-row, .purchase-detail-metrics { grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); }
}
@media (max-width: 560px) {
  .content { padding: 12px; }
  .topbar { padding: 12px; }
  .pos-drawer-grid { grid-template-columns: 1fr; }
  .report-filter-grid, .expense-filter-grid, .sales-history-filter-grid, .metrics, .dash-metrics, .product-stats, .role-stats, .contact-stats, .supplier-summary-row, .purchase-detail-metrics { grid-template-columns: 1fr; }
  .quick-actions, .top-actions { width: 100%; }
  .quick-actions a, .quick-actions button, .top-actions a { flex: 1 1 auto; }
}
"""


def invoice_styles() -> str:
    return """
.invoice-body { background: #dfe6ee; padding: 28px; }
.invoice-sheet { max-width: 980px; margin: 0 auto; background: white; border: 1px solid #cfd8e3; border-radius: 8px; padding: 32px; }
.invoice-actions { display: flex; justify-content: flex-end; gap: 10px; margin-bottom: 24px; }
.invoice-actions button { width: auto; min-width: 110px; margin-top: 0; }
.invoice-header { display: flex; justify-content: space-between; gap: 28px; border-bottom: 2px solid #17202a; padding-bottom: 20px; }
.invoice-header h1 { margin: 0 0 8px; font-size: 28px; }
.invoice-header p, .invoice-customer p, .invoice-footer p { margin: 4px 0; color: #607080; }
.invoice-meta { text-align: right; min-width: 240px; }
.invoice-meta h2 { margin: 0 0 10px; font-size: 26px; text-transform: uppercase; }
.invoice-customer { padding: 22px 0; }
.invoice-customer h3 { margin: 0 0 8px; }
.invoice-table { border: 0; padding: 0; }
.invoice-totals { display: flex; justify-content: flex-end; margin-top: 20px; }
.invoice-totals table { max-width: 360px; }
.invoice-totals th { width: 160px; }
.invoice-footer { border-top: 1px solid #dfe6ee; margin-top: 28px; padding-top: 16px; text-align: center; }
@media print {
  .invoice-body { background: white; padding: 0; }
  .invoice-sheet { max-width: none; border: 0; border-radius: 0; padding: 0; }
  .invoice-actions { display: none; }
  .invoice-header { break-inside: avoid; }
  a { text-decoration: none; }
}
@media (max-width: 700px) {
  .invoice-body { padding: 12px; }
  .invoice-sheet { padding: 18px; }
  .invoice-header { flex-direction: column; }
  .invoice-meta { text-align: left; }
}
"""


def receipt_styles() -> str:
    return """
.receipt-roll { width: min(86mm, calc(100vw - 24px)); margin: 0 auto; background: white; border: 1px solid #cfd8e3; border-radius: 8px; padding: 14px; color: #111827; }
.receipt-head { text-align: center; border-bottom: 1px dashed #94a3b8; padding-bottom: 10px; }
.receipt-head h1 { margin: 0 0 5px; font-size: 18px; line-height: 1.2; }
.receipt-head h2 { margin: 10px 0 4px; font-size: 17px; text-transform: uppercase; }
.receipt-head p { margin: 2px 0; color: #475569; font-size: 12px; }
.receipt-meta { display: grid; gap: 5px; padding: 10px 0; border-bottom: 1px dashed #94a3b8; }
.receipt-meta div, .receipt-totals div { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; font-size: 12px; }
.receipt-meta span, .receipt-totals span { color: #64748b; font-weight: 800; }
.receipt-meta strong, .receipt-totals strong { text-align: right; }
.receipt-meta-stack div { min-height: 24px; }
.receipt-table { margin-top: 8px; font-size: 12px; }
.receipt-table th, .receipt-table td { padding: 6px 4px; border-top: 1px solid #e5e7eb; }
.receipt-table th { font-size: 11px; }
.receipt-table small { display: block; color: #64748b; font-size: 10px; margin-top: 2px; }
.receipt-price-stack { display: grid; gap: 1px; justify-items: end; }
.receipt-price-stack del { color: #64748b; font-size: 10px; font-weight: 700; }
.receipt-price-stack strong { color: #111827; font-size: 12px; }
.receipt-totals { display: grid; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed #94a3b8; }
.receipt-footer { margin-top: 12px; padding-top: 10px; border-top: 1px dashed #94a3b8; text-align: center; color: #475569; font-size: 12px; }
@media print {
  @page { size: 80mm 200mm; margin: 3mm; }
  html, body { width: 74mm; min-width: 74mm; margin: 0; padding: 0; background: white; }
  .invoice-body { width: 74mm; min-width: 74mm; margin: 0; padding: 0; background: white; }
  .receipt-roll { box-sizing: border-box; width: 74mm; max-width: 74mm; margin: 0; border: 0; border-radius: 0; padding: 0; box-shadow: none; }
}
"""


def main() -> None:
    initialize_database()
    AuthService().ensure_default_admin()
    server = ThreadingHTTPServer((HOST, PORT), POSWebHandler)
    print(f"POS Ultimate web app running at http://localhost:{PORT}")
    server.serve_forever()
