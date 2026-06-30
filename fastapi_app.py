from __future__ import annotations

import sqlite3
import hmac
import os
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from pos_inventory_system.database.connection import initialize_database
from pos_inventory_system.repositories.addon_repository import (
    AddonModuleUpdateData,
    AddonRepository,
    AddonWorkItemData,
)
from pos_inventory_system.repositories.cash_register_repository import (
    CashMovementData,
    CashRegisterRepository,
    CloseRegisterData,
    OpenRegisterData,
)
from pos_inventory_system.repositories.commission_agent_repository import (
    CommissionAgentFormData,
    CommissionAgentRepository,
)
from pos_inventory_system.repositories.contact_repository import (
    ContactFormData,
    ContactRepository,
    CustomerGroupFormData,
)
from pos_inventory_system.repositories.expense_repository import (
    ExpenseCategoryData,
    ExpenseFormData,
    ExpenseRefundFormData,
    ExpenseRepository,
    ExpenseSettingsData,
)
from pos_inventory_system.repositories.payment_repository import (
    AccountFormData,
    DepositFormData,
    PaymentRepository,
    TransferFormData,
)
from pos_inventory_system.repositories.product_repository import (
    BrandFormData,
    CategoryFormData,
    PriceGroupFormData,
    ProductFormData,
    ProductRepository,
    ProductVariantFormData,
    VariationFormData,
    WarrantyFormData,
)
from pos_inventory_system.repositories.purchase_order_repository import (
    PurchaseOrderFormData,
    PurchaseOrderRepository,
)
from pos_inventory_system.repositories.purchase_repository import (
    PurchaseCheckoutData,
    PurchaseRepository,
)
from pos_inventory_system.repositories.purchase_return_repository import (
    PurchaseReturnFormData,
    PurchaseReturnRepository,
)
from pos_inventory_system.repositories.report_repository import ReportRepository
from pos_inventory_system.repositories.sale_repository import (
    SaleCheckoutData,
    SaleFormData,
    SaleRepository,
)
from pos_inventory_system.repositories.sales_return_repository import (
    SalesReturnFormData,
    SalesReturnRepository,
)
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
from pos_inventory_system.services.auth_service import AuthService
from pos_inventory_system.services.backup_service import BackupService


class CsvImportRequest(BaseModel):
    csv_text: str


class ProductOpeningStockImportRequest(BaseModel):
    csv_text: str
    location_id: int = 1


class LookupCreateRequest(BaseModel):
    table: str
    name: str
    short_name: str = ""


class TemplateApplyRequest(BaseModel):
    template_key: str


class RoleRequest(BaseModel):
    name: str
    description: str = ""
    permissions_text: str = ""


class ExpenseStatusRequest(BaseModel):
    status: str
    user_id: int | None = None


class DuplicateExpenseRequest(BaseModel):
    user_id: int | None = None


class PurchaseChequeStatusRequest(BaseModel):
    status: str
    action_date: str
    note: str = ""


class AddonWorkStatusRequest(BaseModel):
    status: str


class AddonSyncRequest(BaseModel):
    run_type: str = "manual"
    status: str = "success"
    details: str = "Manual API sync check recorded."


API_KEY = os.environ.get("POS_API_KEY", "").strip()


def require_api_key(x_pos_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if not x_pos_api_key or not hmac.compare_digest(x_pos_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Valid X-POS-API-Key header is required")


app = FastAPI(
    title="POS Ultimate Inventory API",
    version="0.2.0",
    description="FastAPI endpoints for the POS Ultimate inventory system.",
    dependencies=[Depends(require_api_key)],
)


@app.on_event("startup")
def startup() -> None:
    initialize_database()
    AuthService().ensure_default_admin()


def encode(value: Any) -> Any:
    if isinstance(value, sqlite3.Row):
        return {key: encode(value[key]) for key in value.keys()}
    if is_dataclass(value):
        return {key: encode(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def created(item_id: int | None = None, **extra: Any) -> dict[str, Any]:
    response: dict[str, Any] = {"ok": True}
    if item_id is not None:
        response["id"] = item_id
    response.update(extra)
    return response


def run_write(callback: Any) -> dict[str, Any]:
    try:
        result = callback()
        if isinstance(result, int):
            return created(result)
        return created(result=result)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health() -> dict[str, Any]:
    health_data = dict(SettingsRepository().system_health())
    health_data["api_key_required"] = "yes" if API_KEY else "no"
    return encode(health_data)


@app.post("/auth/login", tags=["Auth"])
def login(username: str, password: str) -> dict[str, Any]:
    user = AuthService().authenticate(username, password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return encode(user)


@app.get("/products", tags=["Products"])
def list_products() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_products())


@app.get("/products/{product_id}", tags=["Products"])
def get_product(product_id: int) -> dict[str, Any]:
    product = ProductRepository().get_product(product_id)
    if product is None:
        raise not_found("Product not found")
    return encode(product)


@app.post("/products", tags=["Products"])
def create_product(product: ProductFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_product(product))


@app.put("/products/{product_id}", tags=["Products"])
def update_product(product_id: int, product: ProductFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().update_product(product_id, product))


@app.delete("/products/{product_id}", tags=["Products"])
def deactivate_product(product_id: int) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().deactivate_product(product_id))


@app.post("/products/import", tags=["Products"])
def import_products(request: CsvImportRequest) -> dict[str, Any]:
    imported, errors = ProductRepository().import_products_csv(request.csv_text)
    return created(imported=imported, errors=errors)


@app.post("/products/opening-stock/import", tags=["Products"])
def import_opening_stock(request: ProductOpeningStockImportRequest) -> dict[str, Any]:
    imported, errors = ProductRepository().import_opening_stock_csv(request.csv_text, request.location_id)
    return created(imported=imported, errors=errors)


@app.get("/products/options", tags=["Products"])
def product_options() -> list[dict[str, Any]]:
    return encode(ProductRepository().product_options())


@app.get("/products/available-stock/{product_id}", tags=["Products"])
def sale_available_stock(product_id: int) -> dict[str, float]:
    return {"available_stock": SaleRepository().available_stock(product_id)}


@app.get("/categories", tags=["Products"])
def list_categories(active_only: bool = False) -> list[dict[str, Any]]:
    return encode(ProductRepository().list_category_records(active_only))


@app.post("/categories", tags=["Products"])
def create_category(category: CategoryFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_category(category))


@app.put("/categories/{category_id}", tags=["Products"])
def update_category(category_id: int, category: CategoryFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().update_category(category_id, category))


@app.delete("/categories/{category_id}", tags=["Products"])
def deactivate_category(category_id: int) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().deactivate_category(category_id))


@app.post("/categories/template", tags=["Products"])
def apply_category_template(request: TemplateApplyRequest) -> dict[str, Any]:
    count = ProductRepository().apply_category_template(request.template_key)
    return created(created_count=count)


@app.get("/brands", tags=["Products"])
def list_brands(active_only: bool = False) -> list[dict[str, Any]]:
    return encode(ProductRepository().list_brand_records(active_only))


@app.post("/brands", tags=["Products"])
def create_brand(brand: BrandFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_brand(brand))


@app.put("/brands/{brand_id}", tags=["Products"])
def update_brand(brand_id: int, brand: BrandFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().update_brand(brand_id, brand))


@app.delete("/brands/{brand_id}", tags=["Products"])
def deactivate_brand(brand_id: int) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().deactivate_brand(brand_id))


@app.post("/brands/template", tags=["Products"])
def apply_brand_template(request: TemplateApplyRequest) -> dict[str, Any]:
    count = ProductRepository().apply_brand_template(request.template_key)
    return created(created_count=count)


@app.get("/units", tags=["Products"])
def list_units() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_units())


@app.post("/lookups", tags=["Products"])
def create_lookup(request: LookupCreateRequest) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_lookup(request.table, request.name, request.short_name))


@app.get("/variations", tags=["Products"])
def list_variations() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_variations())


@app.post("/variations", tags=["Products"])
def create_variation(variation: VariationFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_variation(variation))


@app.get("/variation-values", tags=["Products"])
def list_variation_values() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_variation_values())


@app.get("/variants", tags=["Products"])
def list_variants(product_id: int | None = None) -> list[dict[str, Any]]:
    return encode(ProductRepository().list_product_variants(product_id))


@app.post("/variants", tags=["Products"])
def create_variant(variant: ProductVariantFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_product_variant(variant))


@app.get("/price-groups", tags=["Products"])
def list_price_groups() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_price_groups())


@app.post("/price-groups", tags=["Products"])
def create_price_group(group: PriceGroupFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_price_group(group))


@app.put("/price-groups/{group_id}", tags=["Products"])
def update_price_group(group_id: int, group: PriceGroupFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().update_price_group(group_id, group))


@app.get("/warranties", tags=["Products"])
def list_warranties() -> list[dict[str, Any]]:
    return encode(ProductRepository().list_warranties())


@app.post("/warranties", tags=["Products"])
def create_warranty(warranty: WarrantyFormData) -> dict[str, Any]:
    return run_write(lambda: ProductRepository().create_warranty(warranty))


@app.get("/contacts", tags=["Contacts"])
def list_contacts(contact_type: str = Query("customer", pattern="^(customer|supplier|both)$")) -> list[dict[str, Any]]:
    return encode(ContactRepository().list_contacts(contact_type))


@app.post("/contacts", tags=["Contacts"])
def create_contact(contact: ContactFormData) -> dict[str, Any]:
    return run_write(lambda: ContactRepository().create_contact(contact))


@app.put("/contacts/{contact_id}", tags=["Contacts"])
def update_contact(contact_id: int, contact: ContactFormData) -> dict[str, Any]:
    return run_write(lambda: ContactRepository().update_contact(contact_id, contact))


@app.delete("/contacts/{contact_id}", tags=["Contacts"])
def deactivate_contact(contact_id: int) -> dict[str, Any]:
    return run_write(lambda: ContactRepository().deactivate_contact(contact_id))


@app.post("/contacts/import", tags=["Contacts"])
def import_contacts(request: CsvImportRequest) -> dict[str, Any]:
    imported, errors = ContactRepository().import_contacts_csv(request.csv_text)
    return created(imported=imported, errors=errors)


@app.get("/contacts/{contact_id}/ledger", tags=["Contacts"])
def contact_ledger(contact_id: int, contact_type: str = Query("customer", pattern="^(customer|supplier)$")) -> list[dict[str, Any]]:
    repository = ContactRepository()
    return encode(
        repository.customer_ledger(contact_id)
        if contact_type == "customer"
        else repository.supplier_ledger(contact_id)
    )


@app.get("/customer-groups", tags=["Contacts"])
def list_customer_groups() -> list[dict[str, Any]]:
    return encode(ContactRepository().list_customer_groups())


@app.post("/customer-groups", tags=["Contacts"])
def create_customer_group(group: CustomerGroupFormData) -> dict[str, Any]:
    return run_write(lambda: ContactRepository().create_customer_group(group))


@app.put("/customer-groups/{group_id}", tags=["Contacts"])
def update_customer_group(group_id: int, group: CustomerGroupFormData) -> dict[str, Any]:
    return run_write(lambda: ContactRepository().update_customer_group(group_id, group))


@app.get("/purchases", tags=["Purchases"])
def list_purchases(
    supplier_id: int | None = None,
    product_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
) -> list[dict[str, Any]]:
    return encode(PurchaseRepository().list_purchases(supplier_id, product_id, start_date, end_date))


@app.get("/purchases/{purchase_id}", tags=["Purchases"])
def get_purchase_detail(purchase_id: int) -> dict[str, Any]:
    purchase, items, payments = PurchaseRepository().get_purchase_detail(purchase_id)
    if purchase is None:
        raise not_found("Purchase not found")
    return {"purchase": encode(purchase), "items": encode(items), "payments": encode(payments)}


@app.post("/purchases", tags=["Purchases"])
def create_purchase(purchase: PurchaseCheckoutData) -> dict[str, Any]:
    return run_write(lambda: PurchaseRepository().create_checkout_purchase(purchase))


@app.get("/purchase-cheques", tags=["Purchases"])
def list_purchase_cheques(status: str = "") -> list[dict[str, Any]]:
    return encode(PurchaseRepository().list_purchase_cheques(status))


@app.put("/purchase-cheques/{payment_id}", tags=["Purchases"])
def update_purchase_cheque(payment_id: int, request: PurchaseChequeStatusRequest) -> dict[str, Any]:
    return run_write(
        lambda: PurchaseRepository().update_cheque_status(
            payment_id, request.status, request.action_date, request.note
        )
    )


@app.get("/purchase-orders", tags=["Purchases"])
def list_purchase_orders() -> list[dict[str, Any]]:
    return encode(PurchaseOrderRepository().list_orders())


@app.post("/purchase-orders", tags=["Purchases"])
def create_purchase_order(order: PurchaseOrderFormData) -> dict[str, Any]:
    return run_write(lambda: PurchaseOrderRepository().create_order(order))


@app.get("/purchase-returns", tags=["Purchases"])
def list_purchase_returns() -> list[dict[str, Any]]:
    return encode(PurchaseReturnRepository().list_returns())


@app.post("/purchase-returns", tags=["Purchases"])
def create_purchase_return(purchase_return: PurchaseReturnFormData) -> dict[str, Any]:
    return run_write(lambda: PurchaseReturnRepository().create_return(purchase_return))


@app.get("/sales", tags=["Sales"])
def list_sales() -> list[dict[str, Any]]:
    return encode(SaleRepository().list_sales())


@app.get("/sales/history", tags=["Sales"])
def sales_history(
    customer_id: str = "",
    location_id: str = "",
    sale_status: str = "",
    payment_status: str = "",
    date_from: str = "",
    date_to: str = "",
    payment_method: str = "",
    product_id: str = "",
    category_id: str = "",
    brand_id: str = "",
    search: str = "",
) -> list[dict[str, Any]]:
    filters = {
        "customer_id": customer_id,
        "location_id": location_id,
        "sale_status": sale_status,
        "payment_status": payment_status,
        "date_from": date_from,
        "date_to": date_to,
        "payment_method": payment_method,
        "product_id": product_id,
        "category_id": category_id,
        "brand_id": brand_id,
        "search": search,
    }
    return encode(SaleRepository().sales_history(filters))


@app.get("/sales/{sale_id}/invoice", tags=["Sales"])
def get_sale_invoice(sale_id: int) -> dict[str, Any]:
    sale, items = SaleRepository().get_sale_invoice(sale_id)
    if sale is None:
        raise not_found("Sale not found")
    return {"sale": encode(sale), "items": encode(items)}


@app.post("/sales", tags=["Sales"])
def create_sale(sale: SaleCheckoutData) -> dict[str, Any]:
    return run_write(lambda: SaleRepository().create_checkout_sale(sale))


@app.post("/sales/non-final/{sale_status}", tags=["Sales"])
def create_non_final_sale(sale_status: str, sale: SaleFormData) -> dict[str, Any]:
    return run_write(lambda: SaleRepository().create_non_final_sale(sale, sale_status))


@app.get("/sales-returns", tags=["Sales"])
def list_sales_returns() -> list[dict[str, Any]]:
    return encode(SalesReturnRepository().list_returns())


@app.post("/sales-returns", tags=["Sales"])
def create_sales_return(sale_return: SalesReturnFormData) -> dict[str, Any]:
    return run_write(lambda: SalesReturnRepository().create_return(sale_return))


@app.get("/sales-returns/{return_id}/receipt", tags=["Sales"])
def get_sales_return_receipt(return_id: int) -> dict[str, Any]:
    receipt = SalesReturnRepository().get_return_receipt(return_id)
    if receipt is None:
        raise not_found("Sales return not found")
    return encode(receipt)


@app.get("/shipments", tags=["Sales"])
def list_shipments() -> list[dict[str, Any]]:
    return encode(ShipmentRepository().list_shipments())


@app.post("/shipments", tags=["Sales"])
def create_shipment(shipment: ShipmentFormData) -> dict[str, Any]:
    return run_write(lambda: ShipmentRepository().create_shipment(shipment))


@app.get("/stock", tags=["Stock"])
def stock_report() -> list[dict[str, Any]]:
    return encode(StockRepository().stock_report())


@app.get("/stock/history", tags=["Stock"])
def stock_movement_history(
    product_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    location_id: str = "",
    movement_type: str = "",
) -> list[dict[str, Any]]:
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "location_id": location_id,
        "movement_type": movement_type,
    }
    return encode(StockRepository().movement_history(product_id, filters))


@app.get("/stock/available", tags=["Stock"])
def stock_available(product_id: int, location_id: int) -> dict[str, float]:
    return {"available_stock": StockOperationRepository().available_stock(product_id, location_id)}


@app.get("/stock-adjustments", tags=["Stock"])
def list_stock_adjustments() -> list[dict[str, Any]]:
    return encode(StockOperationRepository().list_adjustments())


@app.post("/stock-adjustments", tags=["Stock"])
def create_stock_adjustment(adjustment: StockAdjustmentFormData) -> dict[str, Any]:
    return run_write(lambda: StockOperationRepository().create_adjustment(adjustment))


@app.get("/stock-transfers", tags=["Stock"])
def list_stock_transfers() -> list[dict[str, Any]]:
    return encode(StockOperationRepository().list_transfers())


@app.post("/stock-transfers", tags=["Stock"])
def create_stock_transfer(transfer: StockTransferFormData) -> dict[str, Any]:
    return run_write(lambda: StockOperationRepository().create_transfer(transfer))


@app.get("/expenses", tags=["Expenses"])
def list_expenses(
    expense_type: str = "",
    status: str = "",
    category_id: str = "",
    account_id: str = "",
    location_id: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
) -> list[dict[str, Any]]:
    filters = {
        "expense_type": expense_type,
        "status": status,
        "category_id": category_id,
        "account_id": account_id,
        "location_id": location_id,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
    }
    return encode(ExpenseRepository().list_expenses(filters))


@app.get("/expenses/summary", tags=["Expenses"])
def expense_summary() -> dict[str, Any]:
    return encode(ExpenseRepository().summary())


@app.get("/expenses/{expense_id}", tags=["Expenses"])
def get_expense(expense_id: int) -> dict[str, Any]:
    expense = ExpenseRepository().get_expense(expense_id)
    if expense is None:
        raise not_found("Expense not found")
    return encode(expense)


@app.post("/expenses", tags=["Expenses"])
def create_expense(expense: ExpenseFormData) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().create_expense(expense))


@app.put("/expenses/{expense_id}/status", tags=["Expenses"])
def update_expense_status(expense_id: int, request: ExpenseStatusRequest) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().update_status(expense_id, request.status, request.user_id))


@app.post("/expenses/{expense_id}/duplicate", tags=["Expenses"])
def duplicate_expense(expense_id: int, request: DuplicateExpenseRequest) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().duplicate_expense(expense_id, request.user_id))


@app.get("/expense-refunds", tags=["Expenses"])
def list_expense_refunds() -> list[dict[str, Any]]:
    return encode(ExpenseRepository().list_refunds())


@app.post("/expense-refunds", tags=["Expenses"])
def create_expense_refund(refund: ExpenseRefundFormData) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().create_refund(refund))


@app.get("/expense-categories", tags=["Expenses"])
def list_expense_categories() -> list[dict[str, Any]]:
    return encode(ExpenseRepository().list_categories())


@app.post("/expense-categories", tags=["Expenses"])
def create_expense_category(category: ExpenseCategoryData) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().create_category(category))


@app.get("/expense-settings", tags=["Expenses"])
def get_expense_settings() -> dict[str, Any]:
    return encode(ExpenseRepository().get_settings())


@app.put("/expense-settings", tags=["Expenses"])
def update_expense_settings(settings: ExpenseSettingsData) -> dict[str, Any]:
    return run_write(lambda: ExpenseRepository().update_settings(settings))


@app.get("/payment-accounts", tags=["Payments"])
def list_payment_accounts() -> list[dict[str, Any]]:
    return encode(PaymentRepository().list_accounts())


@app.post("/payment-accounts", tags=["Payments"])
def create_payment_account(account: AccountFormData) -> dict[str, Any]:
    return run_write(lambda: PaymentRepository().create_account(account))


@app.get("/payments", tags=["Payments"])
def list_payments() -> list[dict[str, Any]]:
    return encode(PaymentRepository().list_transactions())


@app.get("/payments/{payment_id}/receipt", tags=["Payments"])
def get_payment_receipt(payment_id: int) -> dict[str, Any]:
    receipt = PaymentRepository().get_transaction_receipt(payment_id)
    if receipt is None:
        raise not_found("Payment not found")
    return encode(receipt)


@app.post("/deposits", tags=["Payments"])
def create_deposit(deposit: DepositFormData) -> dict[str, Any]:
    return run_write(lambda: PaymentRepository().create_deposit(deposit))


@app.get("/transfers", tags=["Payments"])
def list_transfers() -> list[dict[str, Any]]:
    return encode(PaymentRepository().list_transfers())


@app.post("/transfers", tags=["Payments"])
def create_transfer(transfer: TransferFormData) -> dict[str, Any]:
    return run_write(lambda: PaymentRepository().create_transfer(transfer))


@app.get("/cash-registers", tags=["Cash Register"])
def list_cash_registers() -> list[dict[str, Any]]:
    return encode(CashRegisterRepository().list_registers())


@app.get("/cash-registers/current", tags=["Cash Register"])
def current_cash_register(user_id: int) -> dict[str, Any] | None:
    return encode(CashRegisterRepository().current_open_register(user_id))


@app.get("/cash-registers/{register_id}", tags=["Cash Register"])
def get_cash_register(register_id: int) -> dict[str, Any]:
    register = CashRegisterRepository().get_register(register_id)
    if register is None:
        raise not_found("Cash register not found")
    return encode(register)


@app.get("/cash-registers/{register_id}/summary", tags=["Cash Register"])
def cash_register_summary(register_id: int) -> dict[str, Any]:
    repository = CashRegisterRepository()
    register = repository.get_register(register_id)
    if register is None:
        raise not_found("Cash register not found")
    return encode(repository.register_summary(register))


@app.post("/cash-registers/open", tags=["Cash Register"])
def open_cash_register(data: OpenRegisterData) -> dict[str, Any]:
    return run_write(lambda: CashRegisterRepository().open_register(data))


@app.post("/cash-registers/close", tags=["Cash Register"])
def close_cash_register(data: CloseRegisterData) -> dict[str, Any]:
    return run_write(lambda: CashRegisterRepository().close_register(data))


@app.post("/cash-registers/movements", tags=["Cash Register"])
def create_cash_movement(data: CashMovementData) -> dict[str, Any]:
    return run_write(lambda: CashRegisterRepository().create_manual_movement(data))


@app.get("/reports/sales", tags=["Reports"])
def report_sales(date_from: str = "", date_to: str = "", location_id: str = "") -> list[dict[str, Any]]:
    return encode(ReportRepository().sales_report({"date_from": date_from, "date_to": date_to, "location_id": location_id}))


@app.get("/reports/stock", tags=["Reports"])
def report_stock(location_id: str = "", product_id: str = "", category_id: str = "", brand_id: str = "") -> list[dict[str, Any]]:
    return encode(
        ReportRepository().stock_report(
            {
                "location_id": location_id,
                "product_id": product_id,
                "category_id": category_id,
                "brand_id": brand_id,
            }
        )
    )


@app.get("/reports/purchases", tags=["Reports"])
def report_purchases() -> list[dict[str, Any]]:
    return encode(ReportRepository().purchase_report())


@app.get("/reports/profit-loss", tags=["Reports"])
def report_profit_loss(date_from: str = "", date_to: str = "", location_id: str = "") -> dict[str, Any]:
    return encode(ReportRepository().profit_loss_summary({"date_from": date_from, "date_to": date_to, "location_id": location_id}))


@app.get("/reports/purchase-sale", tags=["Reports"])
def report_purchase_sale() -> dict[str, Any]:
    return encode(ReportRepository().purchase_sale_summary())


@app.get("/reports/tax", tags=["Reports"])
def report_tax() -> dict[str, Any]:
    return encode(ReportRepository().tax_report())


@app.get("/reports/supplier-customer", tags=["Reports"])
def report_supplier_customer() -> list[dict[str, Any]]:
    return encode(ReportRepository().supplier_customer_report())


@app.get("/reports/expenses", tags=["Reports"])
def report_expenses() -> list[dict[str, Any]]:
    return encode(ReportRepository().expense_by_category())


@app.get("/reports/payments", tags=["Reports"])
def report_payments(date_from: str = "", date_to: str = "", account_id: str = "", payment_method: str = "") -> list[dict[str, Any]]:
    return encode(
        ReportRepository().payment_report(
            {
                "date_from": date_from,
                "date_to": date_to,
                "account_id": account_id,
                "payment_method": payment_method,
            }
        )
    )


@app.get("/reports/due-payments", tags=["Reports"])
def report_due_payments() -> list[dict[str, Any]]:
    return encode(ReportRepository().due_payment_report())


@app.get("/reports/cash-register", tags=["Reports"])
def report_cash_register() -> dict[str, Any]:
    return encode(ReportRepository().cash_register_summary())


@app.get("/reports/trending-products", tags=["Reports"])
def report_trending_products() -> list[dict[str, Any]]:
    return encode(ReportRepository().trending_products())


@app.get("/reports/sales-representatives", tags=["Reports"])
def report_sales_representatives() -> list[dict[str, Any]]:
    return encode(ReportRepository().sales_representative_report())


@app.get("/reports/low-stock", tags=["Reports"])
def report_low_stock() -> list[dict[str, Any]]:
    return encode(ReportRepository().low_stock_report())


@app.get("/reports/stock-adjustments", tags=["Reports"])
def report_stock_adjustments() -> list[dict[str, Any]]:
    return encode(ReportRepository().stock_adjustment_report())


@app.get("/reports/stock-transfers", tags=["Reports"])
def report_stock_transfers() -> list[dict[str, Any]]:
    return encode(ReportRepository().stock_transfer_report())


@app.get("/settings/business", tags=["Settings"])
def get_business_settings() -> dict[str, Any]:
    return encode(SettingsRepository().get_business_settings())


@app.put("/settings/business", tags=["Settings"])
def update_business_settings(settings: BusinessSettingsData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().update_business_settings(settings))


@app.get("/settings/locations", tags=["Settings"])
def list_locations() -> list[dict[str, Any]]:
    return encode(SettingsRepository().list_locations())


@app.post("/settings/locations", tags=["Settings"])
def create_location(location: LocationData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().create_location(location))


@app.get("/settings/invoice", tags=["Settings"])
def get_invoice_settings() -> dict[str, Any]:
    return encode(SettingsRepository().get_invoice_settings())


@app.put("/settings/invoice", tags=["Settings"])
def update_invoice_settings(settings: InvoiceSettingsData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().update_invoice_settings(settings))


@app.get("/settings/barcode", tags=["Settings"])
def get_barcode_settings() -> dict[str, Any]:
    return encode(SettingsRepository().get_barcode_settings())


@app.put("/settings/barcode", tags=["Settings"])
def update_barcode_settings(settings: BarcodeSettingsData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().update_barcode_settings(settings))


@app.post("/settings/barcode/generate", tags=["Settings"])
def generate_barcode() -> dict[str, str]:
    return {"barcode": SettingsRepository().generate_product_barcode()}


@app.get("/settings/tax-rates", tags=["Settings"])
def list_tax_rates() -> list[dict[str, Any]]:
    return encode(SettingsRepository().list_tax_rates())


@app.post("/settings/tax-rates", tags=["Settings"])
def create_tax_rate(tax_rate: TaxRateData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().create_tax_rate(tax_rate))


@app.get("/settings/payment-methods", tags=["Settings"])
def list_payment_methods() -> list[dict[str, Any]]:
    return encode(SettingsRepository().list_payment_methods())


@app.post("/settings/payment-methods", tags=["Settings"])
def create_payment_method(method: PaymentMethodData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().create_payment_method(method))


@app.get("/settings/printers", tags=["Settings"])
def list_printers() -> list[dict[str, Any]]:
    return encode(SettingsRepository().list_printers())


@app.post("/settings/printers", tags=["Settings"])
def create_printer(printer: PrinterSettingsData) -> dict[str, Any]:
    return run_write(lambda: SettingsRepository().create_printer(printer))


@app.get("/users", tags=["Users"])
def list_users() -> list[dict[str, Any]]:
    return encode(UserRepository().list_users())


@app.post("/users", tags=["Users"])
def create_user(user: UserFormData) -> dict[str, Any]:
    return run_write(lambda: UserRepository().create_user(user))


@app.delete("/users/{user_id}", tags=["Users"])
def deactivate_user(user_id: int) -> dict[str, Any]:
    return run_write(lambda: UserRepository().deactivate_user(user_id))


@app.get("/roles", tags=["Users"])
def list_roles() -> list[dict[str, Any]]:
    return encode(UserRepository().list_roles())


@app.post("/roles", tags=["Users"])
def create_role(role: RoleRequest) -> dict[str, Any]:
    return run_write(lambda: UserRepository().create_role(role.name, role.description, role.permissions_text))


@app.put("/roles/{role_id}", tags=["Users"])
def update_role(role_id: int, role: RoleRequest) -> dict[str, Any]:
    return run_write(lambda: UserRepository().update_role(role_id, role.name, role.description, role.permissions_text))


@app.get("/commission-agents", tags=["Users"])
def list_commission_agents() -> list[dict[str, Any]]:
    return encode(CommissionAgentRepository().list_agents())


@app.post("/commission-agents", tags=["Users"])
def create_commission_agent(agent: CommissionAgentFormData) -> dict[str, Any]:
    return run_write(lambda: CommissionAgentRepository().create_agent(agent))


@app.put("/commission-agents/{agent_id}", tags=["Users"])
def update_commission_agent(agent_id: int, agent: CommissionAgentFormData) -> dict[str, Any]:
    return run_write(lambda: CommissionAgentRepository().update_agent(agent_id, agent))


@app.get("/backups", tags=["Backups"])
def list_backups() -> list[dict[str, Any]]:
    return encode(BackupService().list_backups())


@app.post("/backups", tags=["Backups"])
def create_backup() -> dict[str, Any]:
    return encode(BackupService().create_backup())


@app.get("/addons", tags=["Addons"])
def list_addons() -> list[dict[str, Any]]:
    return encode(AddonRepository().list_modules())


@app.get("/addons/{module_key}", tags=["Addons"])
def get_addon(module_key: str) -> dict[str, Any]:
    module = AddonRepository().get_module(module_key)
    if module is None:
        raise not_found("Addon module not found")
    return encode(module)


@app.put("/addons/{module_key}", tags=["Addons"])
def update_addon(module_key: str, module: AddonModuleUpdateData) -> dict[str, Any]:
    if module.module_key != module_key:
        raise HTTPException(status_code=400, detail="Path module_key must match body module_key")
    return run_write(lambda: AddonRepository().update_module(module))


@app.get("/addons/{module_key}/work-items", tags=["Addons"])
def list_addon_work_items(module_key: str) -> list[dict[str, Any]]:
    return encode(AddonRepository().list_work_items(module_key))


@app.post("/addons/{module_key}/work-items", tags=["Addons"])
def create_addon_work_item(module_key: str, item: AddonWorkItemData) -> dict[str, Any]:
    if item.module_key != module_key:
        raise HTTPException(status_code=400, detail="Path module_key must match body module_key")
    return run_write(lambda: AddonRepository().create_work_item(item))


@app.put("/addons/work-items/{item_id}/status", tags=["Addons"])
def update_addon_work_status(item_id: int, request: AddonWorkStatusRequest) -> dict[str, Any]:
    status = AddonRepository().update_work_item_status(item_id, request.status)
    return created(status=status)


@app.get("/addons/{module_key}/sync-logs", tags=["Addons"])
def list_addon_sync_logs(module_key: str, limit: int = 10) -> list[dict[str, Any]]:
    return encode(AddonRepository().list_sync_logs(module_key, limit))


@app.post("/addons/{module_key}/sync-logs", tags=["Addons"])
def create_addon_sync_log(module_key: str, request: AddonSyncRequest) -> dict[str, Any]:
    return run_write(
        lambda: AddonRepository().record_sync_log(
            module_key, request.run_type, request.status, request.details
        )
    )
