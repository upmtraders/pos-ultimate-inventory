from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sqlite3

from pos_inventory_system.database.connection import get_connection
from pos_inventory_system.repositories.contact_repository import ContactFormData, ContactRepository
from pos_inventory_system.repositories.product_repository import ProductFormData, ProductRepository
from pos_inventory_system.repositories.sale_repository import SaleCheckoutData, SaleItemData, SaleRepository


@dataclass(frozen=True)
class WooCommerceCredentials:
    base_url: str
    consumer_key: str = ""
    consumer_secret: str = ""
    bearer_token: str = ""


@dataclass(frozen=True)
class WooSyncResult:
    status: str
    details: str


class WooCommerceService:
    source = "woocommerce"

    def __init__(self) -> None:
        self.product_repository = ProductRepository()
        self.contact_repository = ContactRepository()
        self.sale_repository = SaleRepository()

    def test_connection(self, module: sqlite3.Row) -> WooSyncResult:
        credentials = self._credentials(module)
        products = self._request(credentials, "GET", "products", {"per_page": 1})
        count = len(products) if isinstance(products, list) else 0
        return WooSyncResult("success", f"WooCommerce connection OK. Product endpoint responded with {count} sample item(s).")

    def import_products(self, module: sqlite3.Row) -> WooSyncResult:
        credentials = self._credentials(module)
        products = self._fetch_pages(credentials, "products", {"per_page": 50}, max_pages=4)
        created = 0
        updated = 0
        skipped = 0
        stock_adjusted = 0
        for item in products:
            if not isinstance(item, dict):
                skipped += 1
                continue
            external_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            sku = str(item.get("sku") or "").strip() or f"WOO-{external_id}"
            if not external_id or not name:
                skipped += 1
                continue
            price = self._money(item.get("regular_price") or item.get("price"))
            offer_price = self._money(item.get("sale_price"))
            image_path = ""
            images = item.get("images") or []
            if images and isinstance(images[0], dict):
                image_path = str(images[0].get("src") or "")
            product_id, was_created = self._upsert_product(
                ProductFormData(
                    name=name,
                    sku=sku,
                    barcode="",
                    image_path=image_path,
                    category_id=None,
                    brand_id=None,
                    unit_id=1,
                    purchase_price=0,
                    selling_price=price,
                    offer_price=offer_price,
                    offer_start_date="",
                    offer_end_date="",
                    tax_rate_id=None,
                    warranty_id=None,
                    profit_margin=0,
                    alert_quantity=0,
                    is_active=1 if str(item.get("status") or "publish") == "publish" else 0,
                )
            )
            self._save_mapping("product", external_id, "product", product_id, f"{name} / {sku}")
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            stock_quantity = item.get("stock_quantity")
            if stock_quantity is not None:
                if self._set_product_stock(product_id, self._money(stock_quantity)):
                    stock_adjusted += 1
        return WooSyncResult(
            "success",
            f"Products imported. Created {created}, updated {updated}, stock adjusted {stock_adjusted}, skipped {skipped}.",
        )

    def import_customers(self, module: sqlite3.Row) -> WooSyncResult:
        credentials = self._credentials(module)
        customers = self._fetch_pages(credentials, "customers", {"per_page": 50}, max_pages=4)
        created = 0
        updated = 0
        skipped = 0
        for item in customers:
            if not isinstance(item, dict):
                skipped += 1
                continue
            external_id = str(item.get("id") or "").strip()
            billing = item.get("billing") if isinstance(item.get("billing"), dict) else {}
            first_name = str(item.get("first_name") or billing.get("first_name") or "").strip()
            last_name = str(item.get("last_name") or billing.get("last_name") or "").strip()
            name = " ".join(part for part in (first_name, last_name) if part).strip()
            email = str(item.get("email") or billing.get("email") or "").strip()
            phone = str(billing.get("phone") or "").strip()
            if not name:
                name = email or phone or f"Woo Customer {external_id}"
            if not external_id:
                skipped += 1
                continue
            contact_id, was_created = self._upsert_customer(external_id, name, email, phone, billing)
            self._save_mapping("customer", external_id, "contact", contact_id, f"{name} / {email or phone}")
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        return WooSyncResult("success", f"Customers imported. Created {created}, updated {updated}, skipped {skipped}.")

    def import_orders(self, module: sqlite3.Row) -> WooSyncResult:
        credentials = self._credentials(module)
        orders = self._fetch_pages(
            credentials,
            "orders",
            {"per_page": 30, "status": "processing,completed,on-hold"},
            max_pages=4,
        )
        imported = 0
        skipped = 0
        failed = 0
        errors: list[str] = []
        for order in orders:
            if not isinstance(order, dict):
                skipped += 1
                continue
            external_id = str(order.get("id") or "").strip()
            if not external_id or self._mapping("order", external_id):
                skipped += 1
                continue
            try:
                sale_id = self._import_order(order)
            except Exception as error:
                failed += 1
                errors.append(f"#{external_id}: {error}")
                continue
            self._save_mapping("order", external_id, "sale", sale_id, str(order.get("number") or external_id))
            imported += 1
        detail = f"Orders imported. Imported {imported}, skipped {skipped}, failed {failed}."
        if errors:
            detail += " " + " | ".join(errors[:3])
        return WooSyncResult("attention" if failed else "success", detail)

    def push_stock(self, module: sqlite3.Row) -> WooSyncResult:
        credentials = self._credentials(module)
        pushed = 0
        skipped = 0
        failed = 0
        errors: list[str] = []
        for product in self.product_repository.list_products():
            external_id = self._external_id_for_local("product", int(product["id"]))
            if not external_id:
                skipped += 1
                continue
            try:
                stock = int(round(float(product["available_stock"] or 0)))
                self._request(credentials, "PUT", f"products/{external_id}", data={"manage_stock": True, "stock_quantity": stock})
                pushed += 1
            except Exception as error:
                failed += 1
                errors.append(f"{product['sku']}: {error}")
        detail = f"Stock pushed. Updated {pushed}, skipped unmapped {skipped}, failed {failed}."
        if errors:
            detail += " " + " | ".join(errors[:3])
        return WooSyncResult("attention" if failed else "success", detail)

    def _import_order(self, order: dict[str, Any]) -> int:
        items: list[SaleItemData] = []
        for line in order.get("line_items") or []:
            sku = str(line.get("sku") or "").strip()
            product_id = self._local_product_id_for_line(line, sku)
            if not product_id:
                raise ValueError(f"missing local product for SKU {sku or line.get('product_id')}")
            quantity = self._money(line.get("quantity"))
            if quantity <= 0:
                continue
            total = self._money(line.get("total"))
            unit_price = total / quantity if total > 0 else self._money(line.get("price"))
            items.append(SaleItemData(product_id=product_id, quantity=quantity, unit_price=unit_price, discount=0, tax=self._money(line.get("total_tax"))))
        if not items:
            raise ValueError("order has no importable line items")
        billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
        customer_id = self._customer_for_order(order, billing)
        total = self._money(order.get("total"))
        paid_amount = total if str(order.get("status") or "") in {"processing", "completed"} else 0
        invoice_no = f"WOO-{order.get('number') or order.get('id')}"
        sale_date = str(order.get("date_created") or date.today().isoformat())[:10]
        return self.sale_repository.create_checkout_sale(
            SaleCheckoutData(
                customer_id=customer_id,
                location_id=1,
                invoice_no=invoice_no,
                sale_date=sale_date,
                items=items,
                discount=self._money(order.get("discount_total")),
                tax=self._money(order.get("total_tax")),
                paid_amount=paid_amount,
                payment_method=str(order.get("payment_method") or "woocommerce")[:40],
            )
        )

    def _credentials(self, module: sqlite3.Row) -> WooCommerceCredentials:
        base_url = str(module["endpoint_url"] or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("WooCommerce Store URL is required.")
        notes = self._parse_notes(str(module["notes"] or ""))
        token_label = str(module["token_label"] or "").strip()
        consumer_key = notes.get("consumer_key", "")
        consumer_secret = notes.get("consumer_secret", "")
        bearer_token = notes.get("bearer_token", "")
        if ":" in token_label and not consumer_key and not consumer_secret:
            consumer_key, consumer_secret = [part.strip() for part in token_label.split(":", 1)]
        elif token_label.lower().startswith("bearer ") and not bearer_token:
            bearer_token = token_label[7:].strip()
        if not bearer_token and not (consumer_key and consumer_secret):
            raise ValueError("Add consumer_key and consumer_secret in Setup Notes, or use token label as ck_xxx:cs_xxx.")
        return WooCommerceCredentials(base_url, consumer_key, consumer_secret, bearer_token)

    def _request(
        self,
        credentials: WooCommerceCredentials,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        params = dict(params or {})
        return self._request_once(credentials, method, path, params, data, use_query_auth=False)

    def _request_once(
        self,
        credentials: WooCommerceCredentials,
        method: str,
        path: str,
        params: dict[str, Any],
        data: dict[str, Any] | None,
        use_query_auth: bool,
    ) -> Any:
        if use_query_auth and credentials.consumer_key and credentials.consumer_secret:
            params = dict(params)
            params["consumer_key"] = credentials.consumer_key
            params["consumer_secret"] = credentials.consumer_secret
        url = f"{credentials.base_url}/wp-json/wc/v3/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = Request(url, data=body, method=method.upper())
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        if credentials.bearer_token:
            request.add_header("Authorization", f"Bearer {credentials.bearer_token}")
        elif credentials.consumer_key and credentials.consumer_secret and not use_query_auth:
            token = base64.b64encode(f"{credentials.consumer_key}:{credentials.consumer_secret}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")
        try:
            context = ssl.create_default_context()
            with urlopen(request, timeout=25, context=context) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            if error.code in {401, 403} and credentials.consumer_key and credentials.consumer_secret and not use_query_auth:
                return self._request_once(credentials, method, path, params, data, use_query_auth=True)
            raise ValueError(f"WooCommerce API HTTP {error.code}: {details[:300]}") from error
        except URLError as error:
            raise ValueError(f"WooCommerce connection failed: {error.reason}") from error

    def _fetch_pages(self, credentials: WooCommerceCredentials, path: str, params: dict[str, Any], max_pages: int) -> list[Any]:
        records: list[Any] = []
        for page in range(1, max_pages + 1):
            page_params = dict(params)
            page_params["page"] = page
            chunk = self._request(credentials, "GET", path, page_params)
            if not isinstance(chunk, list) or not chunk:
                break
            records.extend(chunk)
            if len(chunk) < int(page_params.get("per_page", 50)):
                break
        return records

    def _upsert_product(self, product: ProductFormData) -> tuple[int, bool]:
        with get_connection() as connection:
            row = connection.execute("SELECT id FROM products WHERE sku = ?", (product.sku,)).fetchone()
        if row:
            self.product_repository.update_product(int(row["id"]), product)
            return int(row["id"]), False
        return self.product_repository.create_product(product), True

    def _upsert_customer(
        self,
        external_id: str,
        name: str,
        email: str,
        phone: str,
        billing: dict[str, Any],
    ) -> tuple[int, bool]:
        existing = self._mapping("customer", external_id)
        if existing:
            contact_id = int(existing["local_id"])
            self.contact_repository.update_contact(contact_id, self._contact_data(external_id, name, email, phone, billing))
            return contact_id, False
        with get_connection() as connection:
            row = None
            if email:
                row = connection.execute("SELECT id FROM contacts WHERE email = ? AND contact_type IN ('customer', 'both')", (email,)).fetchone()
            if row is None and phone:
                row = connection.execute("SELECT id FROM contacts WHERE phone = ? AND contact_type IN ('customer', 'both')", (phone,)).fetchone()
        if row:
            contact_id = int(row["id"])
            self.contact_repository.update_contact(contact_id, self._contact_data(external_id, name, email, phone, billing))
            return contact_id, False
        return self.contact_repository.create_contact(self._contact_data(external_id, name, email, phone, billing)), True

    def _contact_data(self, external_id: str, name: str, email: str, phone: str, billing: dict[str, Any]) -> ContactFormData:
        return ContactFormData(
            contact_type="customer",
            supplier_type="individual",
            name=name,
            business_name=str(billing.get("company") or ""),
            contact_code=f"WOO-CUS-{external_id}",
            tax_number="",
            phone=phone,
            alternate_phone="",
            email=email,
            website="",
            address=" ".join(str(billing.get(key) or "").strip() for key in ("address_1", "address_2")).strip(),
            city=str(billing.get("city") or ""),
            state=str(billing.get("state") or ""),
            country=str(billing.get("country") or ""),
            postal_code=str(billing.get("postcode") or ""),
            payment_terms="",
            credit_days=0,
            opening_balance=0,
            credit_limit=0,
            customer_group_id=None,
            contact_person_1_name="",
            contact_person_1_designation="",
            contact_person_1_phone="",
            contact_person_1_email="",
            contact_person_2_name="",
            contact_person_2_designation="",
            contact_person_2_phone="",
            contact_person_2_email="",
            contact_person_3_name="",
            contact_person_3_designation="",
            contact_person_3_phone="",
            contact_person_3_email="",
            notes="Imported from WooCommerce",
            is_active=1,
        )

    def _customer_for_order(self, order: dict[str, Any], billing: dict[str, Any]) -> int | None:
        external_customer_id = str(order.get("customer_id") or "").strip()
        if external_customer_id and external_customer_id != "0":
            mapped = self._mapping("customer", external_customer_id)
            if mapped:
                return int(mapped["local_id"])
        email = str(billing.get("email") or "").strip()
        phone = str(billing.get("phone") or "").strip()
        first_name = str(billing.get("first_name") or "").strip()
        last_name = str(billing.get("last_name") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part).strip() or email or phone
        if not name:
            return None
        contact_id, _ = self._upsert_customer(external_customer_id or f"order-{order.get('id')}", name, email, phone, billing)
        return contact_id

    def _local_product_id_for_line(self, line: dict[str, Any], sku: str) -> int | None:
        if sku:
            with get_connection() as connection:
                row = connection.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
            if row:
                return int(row["id"])
        external_id = str(line.get("product_id") or "").strip()
        mapped = self._mapping("product", external_id) if external_id else None
        return int(mapped["local_id"]) if mapped else None

    def _set_product_stock(self, product_id: int, target_stock: float) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(quantity_in - quantity_out), 0) AS available_stock
                FROM stock_movements
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
            current = float(row["available_stock"] or 0)
            delta = target_stock - current
            if abs(delta) < 0.0001:
                return False
            connection.execute(
                """
                INSERT INTO stock_movements (
                    product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                )
                VALUES (?, 1, 'woocommerce_sync', 'woocommerce_product', ?, ?, ?)
                """,
                (product_id, product_id, max(delta, 0), max(-delta, 0)),
            )
            return True

    def _save_mapping(self, external_type: str, external_id: str, local_type: str, local_id: int, summary: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO external_sync_mappings (
                    source, external_type, external_id, local_type, local_id, payload_summary
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, external_type, external_id) DO UPDATE SET
                    local_type = excluded.local_type,
                    local_id = excluded.local_id,
                    payload_summary = excluded.payload_summary,
                    last_synced_at = CURRENT_TIMESTAMP
                """,
                (self.source, external_type, external_id, local_type, local_id, summary[:240]),
            )

    def _mapping(self, external_type: str, external_id: str) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM external_sync_mappings
                WHERE source = ? AND external_type = ? AND external_id = ?
                """,
                (self.source, external_type, external_id),
            ).fetchone()

    def _external_id_for_local(self, external_type: str, local_id: int) -> str:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT external_id
                FROM external_sync_mappings
                WHERE source = ? AND external_type = ? AND local_id = ?
                """,
                (self.source, external_type, local_id),
            ).fetchone()
        return str(row["external_id"]) if row else ""

    @staticmethod
    def _parse_notes(notes: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in notes.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip().lower()] = value.strip()
        return values

    @staticmethod
    def _money(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
