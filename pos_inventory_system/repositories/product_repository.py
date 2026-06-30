from __future__ import annotations

import sqlite3
import csv
from dataclasses import dataclass
from io import StringIO

from pos_inventory_system.database.connection import get_connection


CATEGORY_TEMPLATES: dict[str, dict[str, object]] = {
    "grocery": {
        "name": "Grocery / Supermarket",
        "color": "#0f766e",
        "categories": {
            "Beverages": ("Soft Drinks", "Juices", "Water", "Tea & Coffee"),
            "Snacks": ("Biscuits", "Chips", "Sweets", "Nuts"),
            "Dairy": ("Milk", "Yogurt", "Cheese", "Butter"),
            "Household": ("Cleaning", "Paper Goods", "Kitchen Supplies"),
            "Fresh Food": ("Fruits", "Vegetables", "Meat", "Bakery"),
        },
    },
    "clothing": {
        "name": "Clothing / Fashion",
        "color": "#7c3aed",
        "categories": {
            "Men": ("Shirts", "T-Shirts", "Trousers", "Shoes"),
            "Women": ("Dresses", "Tops", "Skirts", "Shoes"),
            "Kids": ("Boys", "Girls", "Baby Clothing"),
            "Accessories": ("Bags", "Belts", "Caps", "Jewelry"),
        },
    },
    "pharmacy": {
        "name": "Pharmacy",
        "color": "#0284c7",
        "categories": {
            "Medicine": ("Pain Relief", "Cold & Flu", "Vitamins", "First Aid"),
            "Personal Care": ("Skin Care", "Hair Care", "Oral Care"),
            "Baby Care": ("Diapers", "Baby Food", "Baby Hygiene"),
            "Medical Devices": ("Thermometers", "Blood Pressure", "Glucose Care"),
        },
    },
    "electronics": {
        "name": "Electronics",
        "color": "#2563eb",
        "categories": {
            "Mobile Phones": ("Smartphones", "Feature Phones", "Phone Accessories"),
            "Computers": ("Laptops", "Desktops", "Monitors", "Storage"),
            "Audio": ("Speakers", "Headphones", "Microphones"),
            "Accessories": ("Chargers", "Cables", "Adapters", "Cases"),
        },
    },
    "restaurant": {
        "name": "Restaurant / Cafe",
        "color": "#dc2626",
        "categories": {
            "Food": ("Breakfast", "Main Course", "Rice & Noodles", "Desserts"),
            "Beverages": ("Tea & Coffee", "Juices", "Soft Drinks", "Water"),
            "Add-ons": ("Extra Cheese", "Sauces", "Toppings"),
        },
    },
    "hardware": {
        "name": "Hardware",
        "color": "#475569",
        "categories": {
            "Tools": ("Hand Tools", "Power Tools", "Measuring Tools"),
            "Electrical": ("Switches", "Wires", "Bulbs", "Fittings"),
            "Plumbing": ("Pipes", "Valves", "Taps", "Connectors"),
            "Paint": ("Wall Paint", "Brushes", "Thinners", "Accessories"),
        },
    },
    "beauty": {
        "name": "Beauty / Cosmetics",
        "color": "#db2777",
        "categories": {
            "Makeup": ("Face", "Eyes", "Lips", "Nails"),
            "Skin Care": ("Cleansers", "Moisturizers", "Sunscreen"),
            "Hair Care": ("Shampoo", "Conditioner", "Styling"),
            "Fragrance": ("Perfume", "Body Spray", "Gift Sets"),
        },
    },
    "auto_parts": {
        "name": "Auto Parts",
        "color": "#ea580c",
        "categories": {
            "Engine": ("Filters", "Spark Plugs", "Belts", "Oils"),
            "Electrical": ("Batteries", "Lights", "Sensors"),
            "Body Parts": ("Mirrors", "Bumpers", "Panels"),
            "Accessories": ("Mats", "Covers", "Audio"),
        },
    },
    "bookshop": {
        "name": "Bookshop",
        "color": "#0891b2",
        "categories": {
            "Books": ("Fiction", "Non Fiction", "School Books", "Children"),
            "Stationery": ("Pens", "Notebooks", "Files", "Art Supplies"),
            "Office Supplies": ("Paper", "Envelopes", "Desk Items"),
        },
    },
    "general": {
        "name": "General Retail",
        "color": "#0f766e",
        "categories": {
            "General Goods": ("Popular Items", "New Arrivals", "Discount Items"),
            "Accessories": ("Small Items", "Gift Items", "Seasonal"),
        },
    },
}


BRAND_TEMPLATES: dict[str, dict[str, object]] = {
    "electronics": {
        "name": "Electronics",
        "brands": ("Samsung", "Apple", "Xiaomi", "HP", "Dell", "Lenovo", "Sony", "LG", "Asus", "Acer"),
    },
    "grocery": {
        "name": "Grocery / Supermarket",
        "brands": ("Coca-Cola", "Pepsi", "Nestle", "Unilever", "Maliban", "Munchee", "Anchor", "Prima", "Keells", "Elephant House"),
    },
    "pharmacy": {
        "name": "Pharmacy",
        "brands": ("GSK", "Pfizer", "Cipla", "Sun Pharma", "Bayer", "Abbott", "Hemas", "Sanofi", "Novartis"),
    },
    "clothing": {
        "name": "Clothing / Fashion",
        "brands": ("Nike", "Adidas", "Puma", "Levi's", "Zara", "H&M", "Reebok", "Under Armour"),
    },
    "beauty": {
        "name": "Beauty / Cosmetics",
        "brands": ("L'Oreal", "Maybelline", "Nivea", "Dove", "Garnier", "Lakme", "Olay", "Vaseline"),
    },
    "hardware": {
        "name": "Hardware",
        "brands": ("Bosch", "Stanley", "Makita", "Dewalt", "Black+Decker", "Philips", "S-lon", "Dulux"),
    },
    "auto_parts": {
        "name": "Auto Parts",
        "brands": ("Toyota", "Honda", "Nissan", "Hyundai", "Bosch", "Denso", "NGK", "Castrol", "Mobil"),
    },
    "bookshop": {
        "name": "Bookshop",
        "brands": ("Penguin", "Oxford", "Cambridge", "Atlas", "Rathna", "Promate", "Mango", "Faber-Castell"),
    },
    "restaurant": {
        "name": "Restaurant / Cafe",
        "brands": ("House Brand", "Coca-Cola", "Pepsi", "Nestle", "Dilmah", "Prima", "Anchor"),
    },
    "general": {
        "name": "General Retail",
        "brands": ("House Brand", "Local Brand", "Imported", "Generic"),
    },
}


@dataclass(frozen=True)
class LookupItem:
    id: int
    name: str


@dataclass(frozen=True)
class ProductFormData:
    name: str
    sku: str
    barcode: str
    image_path: str
    category_id: int | None
    brand_id: int | None
    unit_id: int | None
    purchase_price: float
    selling_price: float
    offer_price: float
    offer_start_date: str
    offer_end_date: str
    tax_rate_id: int | None
    warranty_id: int | None
    profit_margin: float
    alert_quantity: float
    is_active: int


@dataclass(frozen=True)
class VariationFormData:
    name: str
    values_text: str
    is_active: int


@dataclass(frozen=True)
class ProductVariantFormData:
    product_id: int
    sku: str
    barcode: str
    variation_summary: str
    option_values_text: str
    purchase_price: float
    selling_price: float
    alert_quantity: float
    image_path: str
    is_active: int


@dataclass(frozen=True)
class CategoryFormData:
    name: str
    parent_id: int | None
    code: str
    description: str
    image_path: str
    color_hex: str
    default_tax_rate_id: int | None
    default_unit_id: int | None
    default_warranty_id: int | None
    default_profit_margin: float
    attributes_text: str
    display_order: int
    show_on_pos: int
    is_active: int


@dataclass(frozen=True)
class BrandFormData:
    name: str
    code: str
    logo_path: str
    website: str
    contact_person: str
    phone: str
    email: str
    country: str
    supplier_id: int | None
    default_warranty_id: int | None
    default_profit_margin: float
    description: str
    is_active: int


@dataclass(frozen=True)
class PriceGroupFormData:
    name: str
    description: str
    is_active: int


@dataclass(frozen=True)
class WarrantyFormData:
    name: str
    duration_value: int
    duration_unit: str
    description: str
    is_active: int


class ProductRepository:
    def list_products(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        products.id,
                        products.name,
                        products.sku,
                        products.barcode,
                        products.image_path,
                        products.category_id,
                        products.brand_id,
                        products.purchase_price,
                        products.selling_price,
                        products.offer_price,
                        products.offer_start_date,
                        products.offer_end_date,
                        products.alert_quantity,
                        products.warranty_id,
                        products.profit_margin,
                        products.is_active,
                        product_categories.name AS category_name,
                        product_brands.name AS brand_name,
                        product_units.short_name AS unit_name,
                        tax_rates.name AS tax_name,
                        warranties.name AS warranty_name,
                        COALESCE(variant_counts.variant_count, 0) AS variant_count,
                        COALESCE(stock_totals.available_stock, 0) AS available_stock
                    FROM products
                    LEFT JOIN product_categories ON product_categories.id = products.category_id
                    LEFT JOIN product_brands ON product_brands.id = products.brand_id
                    LEFT JOIN product_units ON product_units.id = products.unit_id
                    LEFT JOIN tax_rates ON tax_rates.id = products.tax_rate_id
                    LEFT JOIN warranties ON warranties.id = products.warranty_id
                    LEFT JOIN (
                        SELECT product_id, COUNT(*) AS variant_count
                        FROM product_variants
                        GROUP BY product_id
                    ) AS variant_counts ON variant_counts.product_id = products.id
                    LEFT JOIN (
                        SELECT product_id, SUM(quantity_in - quantity_out) AS available_stock
                        FROM stock_movements
                        GROUP BY product_id
                    ) AS stock_totals ON stock_totals.product_id = products.id
                    GROUP BY products.id
                    ORDER BY products.created_at DESC, products.id DESC
                    """
                )
            )

    def create_product(self, product: ProductFormData) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO products (
                    name,
                    sku,
                    barcode,
                    image_path,
                    category_id,
                    brand_id,
                    unit_id,
                    purchase_price,
                    selling_price,
                    offer_price,
                    offer_start_date,
                    offer_end_date,
                    tax_rate_id,
                    warranty_id,
                    profit_margin,
                    alert_quantity,
                    is_active
                )
                VALUES (?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, ?)
                """,
                (
                    product.name,
                    product.sku,
                    product.barcode,
                    product.image_path,
                    product.category_id,
                    product.brand_id,
                    product.unit_id,
                    product.purchase_price,
                    product.selling_price,
                    product.offer_price,
                    product.offer_start_date,
                    product.offer_end_date,
                    product.tax_rate_id,
                    product.warranty_id,
                    product.profit_margin,
                    product.alert_quantity,
                    product.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def update_product(self, product_id: int, product: ProductFormData) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE products
                SET
                    name = ?,
                    sku = ?,
                    barcode = NULLIF(?, ''),
                    image_path = NULLIF(?, ''),
                    category_id = ?,
                    brand_id = ?,
                    unit_id = ?,
                    purchase_price = ?,
                    selling_price = ?,
                    offer_price = ?,
                    offer_start_date = NULLIF(?, ''),
                    offer_end_date = NULLIF(?, ''),
                    tax_rate_id = ?,
                    warranty_id = ?,
                    profit_margin = ?,
                    alert_quantity = ?,
                    is_active = ?
                WHERE id = ?
                """,
                (
                    product.name,
                    product.sku,
                    product.barcode,
                    product.image_path,
                    product.category_id,
                    product.brand_id,
                    product.unit_id,
                    product.purchase_price,
                    product.selling_price,
                    product.offer_price,
                    product.offer_start_date,
                    product.offer_end_date,
                    product.tax_rate_id,
                    product.warranty_id,
                    product.profit_margin,
                    product.alert_quantity,
                    product.is_active,
                    product_id,
                ),
            )

    def get_product(self, product_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()

    def deactivate_product(self, product_id: int) -> None:
        with get_connection() as connection:
            connection.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))

    def import_products_csv(self, csv_text: str) -> tuple[int, list[str]]:
        reader = csv.DictReader(StringIO(csv_text.strip()))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required.")
        fields = {field.strip().lower(): field for field in reader.fieldnames}
        if not {"name", "sku"}.issubset(fields):
            raise ValueError("CSV must include name and sku columns.")

        imported = 0
        errors: list[str] = []
        for line, row in enumerate(reader, start=2):
            try:
                product = ProductFormData(
                    name=(row.get(fields["name"]) or "").strip(),
                    sku=(row.get(fields["sku"]) or "").strip(),
                    barcode=(row.get(fields.get("barcode", ""), "") or "").strip(),
                    image_path=(
                        row.get(fields.get("image_path", ""), "")
                        or row.get(fields.get("image_url", ""), "")
                        or ""
                    ).strip(),
                    category_id=None,
                    brand_id=None,
                    unit_id=1,
                    purchase_price=self._csv_float(row, fields, "purchase_price"),
                    selling_price=self._csv_float(row, fields, "selling_price"),
                    offer_price=self._csv_float(row, fields, "offer_price"),
                    offer_start_date=(row.get(fields.get("offer_start_date", ""), "") or "").strip(),
                    offer_end_date=(row.get(fields.get("offer_end_date", ""), "") or "").strip(),
                    tax_rate_id=1,
                    warranty_id=None,
                    profit_margin=self._csv_float(row, fields, "profit_margin"),
                    alert_quantity=self._csv_float(row, fields, "alert_quantity"),
                    is_active=1,
                )
                if not product.name or not product.sku:
                    raise ValueError("name and sku are required")
                self.create_product(product)
                imported += 1
            except Exception as exc:
                errors.append(f"Line {line}: {exc}")
        return imported, errors

    def import_opening_stock_csv(self, csv_text: str, location_id: int = 1) -> tuple[int, list[str]]:
        reader = csv.DictReader(StringIO(csv_text.strip()))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required.")
        fields = {field.strip().lower(): field for field in reader.fieldnames}
        if not {"sku", "quantity"}.issubset(fields):
            raise ValueError("CSV must include sku and quantity columns.")

        imported = 0
        errors: list[str] = []
        with get_connection() as connection:
            for line, row in enumerate(reader, start=2):
                try:
                    sku = (row.get(fields["sku"]) or "").strip()
                    quantity = float((row.get(fields["quantity"]) or "0").strip())
                    if quantity <= 0:
                        raise ValueError("quantity must be greater than zero")
                    product = connection.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
                    if product is None:
                        raise ValueError(f"product SKU not found: {sku}")
                    connection.execute(
                        """
                        INSERT INTO stock_movements (
                            product_id, location_id, movement_type, reference_type, reference_id, quantity_in, quantity_out
                        )
                        VALUES (?, ?, 'opening_stock', 'opening_stock', 0, ?, 0)
                        """,
                        (product["id"], location_id, quantity),
                    )
                    imported += 1
                except Exception as exc:
                    errors.append(f"Line {line}: {exc}")
        return imported, errors

    def create_lookup(self, table: str, name: str, short_name: str = "") -> None:
        allowed_tables = {
            "product_categories": ("name",),
            "product_brands": ("name",),
            "product_units": ("name", "short_name"),
        }
        if table not in allowed_tables:
            raise ValueError("Unsupported lookup table.")
        name = name.strip()
        short_name = short_name.strip()
        if not name:
            raise ValueError("Name is required.")
        if table == "product_units" and not short_name:
            short_name = name[:3].lower()

        with get_connection() as connection:
            exists = connection.execute(
                f"SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A record with this name already exists.")
            if table == "product_units":
                short_exists = connection.execute(
                    "SELECT 1 FROM product_units WHERE LOWER(short_name) = LOWER(?) LIMIT 1",
                    (short_name,),
                ).fetchone()
                if short_exists is not None:
                    raise ValueError("A unit with this short name already exists.")
                connection.execute(
                    "INSERT INTO product_units (name, short_name) VALUES (?, ?)",
                    (name, short_name),
                )
            else:
                connection.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))

    def list_categories(self) -> list[LookupItem]:
        rows = self.list_category_records(active_only=True)
        return [
            LookupItem(
                id=row["id"],
                name=f'{"-- " if row["parent_name"] else ""}{row["name"]}',
            )
            for row in rows
        ]

    def list_category_records(self, active_only: bool = False) -> list[sqlite3.Row]:
        query = """
            SELECT
                categories.*,
                parents.name AS parent_name,
                tax_rates.name AS default_tax_name,
                product_units.short_name AS default_unit_name,
                warranties.name AS default_warranty_name,
                COUNT(DISTINCT products.id) AS product_count,
                COUNT(DISTINCT children.id) AS child_count
            FROM product_categories AS categories
            LEFT JOIN product_categories AS parents ON parents.id = categories.parent_id
            LEFT JOIN tax_rates ON tax_rates.id = categories.default_tax_rate_id
            LEFT JOIN product_units ON product_units.id = categories.default_unit_id
            LEFT JOIN warranties ON warranties.id = categories.default_warranty_id
            LEFT JOIN products ON products.category_id = categories.id
            LEFT JOIN product_categories AS children ON children.parent_id = categories.id
        """
        if active_only:
            query += " WHERE categories.is_active = 1"
        query += """
            GROUP BY categories.id
            ORDER BY
                COALESCE(parents.display_order, categories.display_order),
                COALESCE(parents.name, categories.name),
                CASE WHEN categories.parent_id IS NULL THEN 0 ELSE 1 END,
                categories.display_order,
                categories.name
        """
        with get_connection() as connection:
            return list(connection.execute(query))

    def get_category(self, category_id: int) -> sqlite3.Row | None:
        with get_connection() as connection:
            return connection.execute(
                "SELECT * FROM product_categories WHERE id = ?",
                (category_id,),
            ).fetchone()

    def create_category(self, category: CategoryFormData) -> int:
        self._validate_category(category)
        with get_connection() as connection:
            self._validate_category_parent(connection, category.parent_id)
            cursor = connection.execute(
                """
                INSERT INTO product_categories (
                    name, parent_id, code, description, image_path, color_hex,
                    default_tax_rate_id, default_unit_id, default_warranty_id,
                    default_profit_margin, attributes_text, display_order,
                    show_on_pos, is_active
                )
                VALUES (?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, ?, NULLIF(?, ''), ?, ?, ?)
                """,
                (
                    category.name.strip(),
                    category.parent_id,
                    category.code.strip().upper(),
                    category.description.strip(),
                    category.image_path.strip(),
                    category.color_hex.strip(),
                    category.default_tax_rate_id,
                    category.default_unit_id,
                    category.default_warranty_id,
                    category.default_profit_margin,
                    category.attributes_text.strip(),
                    category.display_order,
                    category.show_on_pos,
                    category.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def update_category(self, category_id: int, category: CategoryFormData) -> None:
        if category_id <= 0:
            raise ValueError("Category is required.")
        self._validate_category(category)
        with get_connection() as connection:
            if connection.execute(
                "SELECT 1 FROM product_categories WHERE id = ?",
                (category_id,),
            ).fetchone() is None:
                raise ValueError("Category was not found.")
            self._validate_category_parent(connection, category.parent_id, category_id)
            cursor = connection.execute(
                """
                UPDATE product_categories
                SET
                    name = ?, parent_id = ?, code = NULLIF(?, ''),
                    description = NULLIF(?, ''), image_path = NULLIF(?, ''),
                    color_hex = ?, default_tax_rate_id = ?, default_unit_id = ?,
                    default_warranty_id = ?, default_profit_margin = ?,
                    attributes_text = NULLIF(?, ''), display_order = ?,
                    show_on_pos = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    category.name.strip(),
                    category.parent_id,
                    category.code.strip().upper(),
                    category.description.strip(),
                    category.image_path.strip(),
                    category.color_hex.strip(),
                    category.default_tax_rate_id,
                    category.default_unit_id,
                    category.default_warranty_id,
                    category.default_profit_margin,
                    category.attributes_text.strip(),
                    category.display_order,
                    category.show_on_pos,
                    category.is_active,
                    category_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("Category was not found.")

    def deactivate_category(self, category_id: int) -> None:
        with get_connection() as connection:
            child = connection.execute(
                "SELECT 1 FROM product_categories WHERE parent_id = ? AND is_active = 1 LIMIT 1",
                (category_id,),
            ).fetchone()
            if child:
                raise ValueError("Deactivate active subcategories first.")
            connection.execute(
                "UPDATE product_categories SET is_active = 0, show_on_pos = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (category_id,),
            )

    def apply_category_template(self, template_key: str) -> int:
        template = CATEGORY_TEMPLATES.get(template_key)
        if template is None:
            raise ValueError("Select a valid shop type.")

        created = 0
        color = str(template["color"])
        categories = template["categories"]
        if not isinstance(categories, dict):
            raise ValueError("Category template is invalid.")

        with get_connection() as connection:
            for root_index, (root_name, child_names) in enumerate(categories.items(), start=1):
                root_id, root_created = self._ensure_category(
                    connection=connection,
                    name=root_name,
                    parent_id=None,
                    code=self._category_code(root_name),
                    color_hex=color,
                    display_order=root_index * 10,
                    attributes_text="",
                )
                created += root_created
                for child_index, child_name in enumerate(child_names, start=1):
                    _, child_created = self._ensure_category(
                        connection=connection,
                        name=child_name,
                        parent_id=root_id,
                        code=self._category_code(root_name, child_name),
                        color_hex=color,
                        display_order=(root_index * 10) + child_index,
                        attributes_text=self._template_attributes(template_key, root_name, child_name),
                    )
                    created += child_created
        return created

    def _ensure_category(
        self,
        connection: sqlite3.Connection,
        name: str,
        parent_id: int | None,
        code: str,
        color_hex: str,
        display_order: int,
        attributes_text: str,
    ) -> tuple[int, int]:
        existing = connection.execute(
            """
            SELECT id FROM product_categories
            WHERE lower(name) = lower(?) AND (
                (parent_id IS NULL AND ? IS NULL) OR parent_id = ?
            )
            """,
            (name, parent_id, parent_id),
        ).fetchone()
        if existing:
            return int(existing["id"]), 0

        cursor = connection.execute(
            """
            INSERT INTO product_categories (
                name, parent_id, code, color_hex, attributes_text,
                display_order, show_on_pos, is_active
            )
            VALUES (?, ?, NULLIF(?, ''), ?, NULLIF(?, ''), ?, 1, 1)
            """,
            (
                name,
                parent_id,
                self._unique_category_code(connection, code),
                color_hex,
                attributes_text,
                display_order,
            ),
        )
        return int(cursor.lastrowid), 1

    def list_warranty_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name FROM warranties WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_brands(self) -> list[LookupItem]:
        rows = self.list_brand_records(active_only=True)
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_brand_records(self, active_only: bool = False) -> list[sqlite3.Row]:
        query = """
            SELECT
                product_brands.*,
                warranties.name AS default_warranty_name,
                contacts.name AS supplier_name,
                COUNT(products.id) AS product_count
            FROM product_brands
            LEFT JOIN warranties ON warranties.id = product_brands.default_warranty_id
            LEFT JOIN contacts ON contacts.id = product_brands.supplier_id
            LEFT JOIN products ON products.brand_id = product_brands.id
        """
        if active_only:
            query += " WHERE product_brands.is_active = 1"
        query += """
            GROUP BY product_brands.id
            ORDER BY product_brands.name
        """
        with get_connection() as connection:
            return list(connection.execute(query))

    def create_brand(self, brand: BrandFormData) -> int:
        self._validate_brand(brand)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO product_brands (
                    name, code, logo_path, website, contact_person, phone, email, country,
                    supplier_id, default_warranty_id, default_profit_margin, description, is_active
                )
                VALUES (?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''),
                        NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, NULLIF(?, ''), ?)
                """,
                (
                    brand.name.strip(),
                    brand.code.strip().upper(),
                    brand.logo_path.strip(),
                    brand.website.strip(),
                    brand.contact_person.strip(),
                    brand.phone.strip(),
                    brand.email.strip(),
                    brand.country.strip(),
                    brand.supplier_id,
                    brand.default_warranty_id,
                    brand.default_profit_margin,
                    brand.description.strip(),
                    brand.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def update_brand(self, brand_id: int, brand: BrandFormData) -> None:
        if brand_id <= 0:
            raise ValueError("Brand is required.")
        self._validate_brand(brand)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE product_brands
                SET
                    name = ?, code = NULLIF(?, ''), logo_path = NULLIF(?, ''),
                    website = NULLIF(?, ''), contact_person = NULLIF(?, ''),
                    phone = NULLIF(?, ''), email = NULLIF(?, ''), country = NULLIF(?, ''),
                    supplier_id = ?, default_warranty_id = ?, default_profit_margin = ?,
                    description = NULLIF(?, ''), is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    brand.name.strip(),
                    brand.code.strip().upper(),
                    brand.logo_path.strip(),
                    brand.website.strip(),
                    brand.contact_person.strip(),
                    brand.phone.strip(),
                    brand.email.strip(),
                    brand.country.strip(),
                    brand.supplier_id,
                    brand.default_warranty_id,
                    brand.default_profit_margin,
                    brand.description.strip(),
                    brand.is_active,
                    brand_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("Brand was not found.")

    def deactivate_brand(self, brand_id: int) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE product_brands SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (brand_id,),
            )

    def apply_brand_template(self, template_key: str) -> int:
        template = BRAND_TEMPLATES.get(template_key)
        if template is None:
            raise ValueError("Select a valid shop type.")
        brands = template["brands"]
        if not isinstance(brands, tuple):
            raise ValueError("Brand template is invalid.")
        created = 0
        with get_connection() as connection:
            for name in brands:
                existing = connection.execute(
                    "SELECT 1 FROM product_brands WHERE lower(name) = lower(?)",
                    (name,),
                ).fetchone()
                if existing:
                    continue
                connection.execute(
                    """
                    INSERT INTO product_brands (name, code, description, is_active)
                    VALUES (?, ?, ?, 1)
                    """,
                    (
                        name,
                        self._unique_brand_code(connection, self._brand_code(name)),
                        f"Starter brand from {template['name']} template.",
                    ),
                )
                created += 1
        return created

    def supplier_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name
                FROM contacts
                WHERE is_active = 1 AND contact_type IN ('supplier', 'both')
                ORDER BY name
                """
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_units(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name || ' (' || short_name || ')' AS name FROM product_units WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def list_tax_rates(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name || ' - ' || rate || '%' AS name FROM tax_rates ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def product_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name || ' (' || sku || ')' AS name FROM products WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def create_variation(self, variation: VariationFormData) -> int:
        name = variation.name.strip()
        values = self._variation_values(variation.values_text)
        if not name:
            raise ValueError("Variation name is required.")
        if not values:
            raise ValueError("Add at least one variation value.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM product_variations WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A variation with this name already exists.")
            cursor = connection.execute(
                "INSERT INTO product_variations (name, values_text, is_active) VALUES (?, ?, ?)",
                (name, ", ".join(values), variation.is_active),
            )
            variation_id = int(cursor.lastrowid)
            for value_name in values:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO product_variation_values (variation_id, value_name, is_active)
                    VALUES (?, ?, ?)
                    """,
                    (variation_id, value_name, variation.is_active),
                )
            return variation_id

    def list_variations(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(connection.execute("SELECT * FROM product_variations ORDER BY name"))

    def list_variation_values(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        product_variation_values.id,
                        product_variation_values.variation_id,
                        product_variation_values.value_name,
                        product_variation_values.is_active,
                        product_variations.name AS variation_name
                    FROM product_variation_values
                    JOIN product_variations ON product_variations.id = product_variation_values.variation_id
                    ORDER BY product_variations.name, product_variation_values.value_name
                    """
                )
            )

    def create_product_variant(self, variant: ProductVariantFormData) -> int:
        if variant.product_id <= 0:
            raise ValueError("Product is required.")
        if not variant.sku.strip():
            raise ValueError("Variant SKU is required.")
        if not variant.variation_summary.strip():
            raise ValueError("Variation summary is required.")
        if variant.purchase_price < 0 or variant.selling_price < 0 or variant.alert_quantity < 0:
            raise ValueError("Variant prices and alert quantity cannot be negative.")

        with get_connection() as connection:
            product = connection.execute(
                "SELECT id FROM products WHERE id = ?",
                (variant.product_id,),
            ).fetchone()
            if product is None:
                raise ValueError("Selected product was not found.")

            self._ensure_variant_identity_is_unique(connection, variant.sku, variant.barcode)
            cursor = connection.execute(
                """
                INSERT INTO product_variants (
                    product_id,
                    sku,
                    barcode,
                    variation_summary,
                    purchase_price,
                    selling_price,
                    alert_quantity,
                    image_path,
                    is_active
                )
                VALUES (?, ?, NULLIF(?, ''), ?, ?, ?, ?, NULLIF(?, ''), ?)
                """,
                (
                    variant.product_id,
                    variant.sku.strip(),
                    variant.barcode.strip(),
                    variant.variation_summary.strip(),
                    variant.purchase_price,
                    variant.selling_price,
                    variant.alert_quantity,
                    variant.image_path.strip(),
                    variant.is_active,
                ),
            )
            variant_id = int(cursor.lastrowid)
            for variation_id, value_name in self._variant_options(connection, variant.option_values_text):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO product_variant_options (variant_id, variation_id, value_name)
                    VALUES (?, ?, ?)
                    """,
                    (variant_id, variation_id, value_name),
                )
            return variant_id

    def list_product_variants(self, product_id: int | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT
                product_variants.id,
                product_variants.product_id,
                product_variants.sku,
                product_variants.barcode,
                product_variants.variation_summary,
                product_variants.purchase_price,
                product_variants.selling_price,
                product_variants.alert_quantity,
                product_variants.image_path,
                product_variants.is_active,
                products.name AS product_name,
                COALESCE(SUM(stock_movements.quantity_in - stock_movements.quantity_out), 0) AS available_stock
            FROM product_variants
            JOIN products ON products.id = product_variants.product_id
            LEFT JOIN stock_movements ON stock_movements.variant_id = product_variants.id
            """
        params: tuple[int, ...] = ()
        if product_id is not None:
            query += " WHERE product_variants.product_id = ?"
            params = (product_id,)
        query += """
            GROUP BY product_variants.id
            ORDER BY products.name, product_variants.variation_summary, product_variants.sku
            """
        with get_connection() as connection:
            return list(connection.execute(query, params))

    def variant_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM product_variants").fetchone()
        return int(row["count"])

    def variant_options(self) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    product_variants.id,
                    products.name || ' - ' || product_variants.variation_summary || ' (' || product_variants.sku || ')' AS name
                FROM product_variants
                JOIN products ON products.id = product_variants.product_id
                WHERE product_variants.is_active = 1 AND products.is_active = 1
                ORDER BY products.name, product_variants.variation_summary
                """
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def create_price_group(self, group: PriceGroupFormData) -> int:
        name = group.name.strip()
        if not name:
            raise ValueError("Selling price group name is required.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM selling_price_groups WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A selling price group with this name already exists.")
            cursor = connection.execute(
                "INSERT INTO selling_price_groups (name, description, is_active) VALUES (?, ?, ?)",
                (name, group.description.strip(), group.is_active),
            )
            return int(cursor.lastrowid)

    def update_price_group(self, group_id: int, group: PriceGroupFormData) -> None:
        if group_id <= 0:
            raise ValueError("Selling price group is required.")
        if not group.name.strip():
            raise ValueError("Selling price group name is required.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM selling_price_groups WHERE LOWER(name) = LOWER(?) AND id <> ? LIMIT 1",
                (group.name.strip(), group_id),
            ).fetchone()
            if exists is not None:
                raise ValueError("A selling price group with this name already exists.")
            cursor = connection.execute(
                """
                UPDATE selling_price_groups
                SET name = ?, description = ?, is_active = ?
                WHERE id = ?
                """,
                (group.name.strip(), group.description.strip(), group.is_active, group_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Selling price group was not found.")

    def list_price_groups(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(connection.execute("SELECT * FROM selling_price_groups ORDER BY name"))

    def create_warranty(self, warranty: WarrantyFormData) -> int:
        name = warranty.name.strip()
        if not name:
            raise ValueError("Warranty name is required.")
        if warranty.duration_value <= 0:
            raise ValueError("Warranty duration must be greater than zero.")
        if warranty.duration_unit not in {"days", "months", "years"}:
            raise ValueError("Select a valid warranty duration unit.")
        with get_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM warranties WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if exists is not None:
                raise ValueError("A warranty with this name already exists.")
            cursor = connection.execute(
                """
                INSERT INTO warranties (name, duration_value, duration_unit, description, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    warranty.duration_value,
                    warranty.duration_unit,
                    warranty.description.strip(),
                    warranty.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def list_warranties(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(connection.execute("SELECT * FROM warranties ORDER BY name"))

    def product_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM products").fetchone()
        return int(row["count"])

    def stock_alert_count(self) -> int:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM products
                WHERE is_active = 1 AND alert_quantity > 0
                """
            ).fetchone()
        return int(row["count"])

    def _list_lookup(self, table: str, column: str) -> list[LookupItem]:
        with get_connection() as connection:
            rows = connection.execute(
                f"SELECT id, {column} AS name FROM {table} WHERE is_active = 1 ORDER BY {column}"
            ).fetchall()
        return [LookupItem(id=row["id"], name=row["name"]) for row in rows]

    def _ensure_variant_identity_is_unique(self, connection: sqlite3.Connection, sku: str, barcode: str) -> None:
        sku = sku.strip()
        barcode = barcode.strip()
        if connection.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
            raise ValueError("Variant SKU already exists as a product SKU.")
        if connection.execute("SELECT 1 FROM product_variants WHERE sku = ?", (sku,)).fetchone():
            raise ValueError("Variant SKU already exists.")
        if barcode and connection.execute("SELECT 1 FROM products WHERE barcode = ?", (barcode,)).fetchone():
            raise ValueError("Variant barcode already exists as a product barcode.")
        if barcode and connection.execute("SELECT 1 FROM product_variants WHERE barcode = ?", (barcode,)).fetchone():
            raise ValueError("Variant barcode already exists.")

    @staticmethod
    def _validate_category(category: CategoryFormData) -> None:
        if not category.name.strip():
            raise ValueError("Category name is required.")
        if category.default_profit_margin < 0:
            raise ValueError("Default profit margin cannot be negative.")
        if category.display_order < 0:
            raise ValueError("Display order cannot be negative.")
        color = category.color_hex.strip()
        if len(color) != 7 or not color.startswith("#"):
            raise ValueError("Category color must use #RRGGBB format.")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise ValueError("Category color must use #RRGGBB format.") from exc

    @staticmethod
    def _validate_category_parent(
        connection: sqlite3.Connection,
        parent_id: int | None,
        category_id: int | None = None,
    ) -> None:
        if parent_id is None:
            return
        if category_id is not None and parent_id == category_id:
            raise ValueError("A category cannot be its own parent.")
        if connection.execute(
            "SELECT 1 FROM product_categories WHERE id = ?",
            (parent_id,),
        ).fetchone() is None:
            raise ValueError("Parent category was not found.")

        current_id: int | None = parent_id
        while current_id is not None:
            if category_id is not None and current_id == category_id:
                raise ValueError("Category hierarchy cannot contain a cycle.")
            row = connection.execute(
                "SELECT parent_id FROM product_categories WHERE id = ?",
                (current_id,),
            ).fetchone()
            current_id = row["parent_id"] if row else None

    @staticmethod
    def _validate_brand(brand: BrandFormData) -> None:
        if not brand.name.strip():
            raise ValueError("Brand name is required.")
        if brand.default_profit_margin < 0:
            raise ValueError("Default profit margin cannot be negative.")

    @staticmethod
    def _category_code(*parts: str) -> str:
        tokens = []
        for part in parts:
            words = [word for word in "".join(char if char.isalnum() else " " for char in part.upper()).split() if word]
            tokens.append("".join(word[:3] for word in words)[:8])
        return "-".join(token for token in tokens if token)[:24]

    @staticmethod
    def _unique_category_code(connection: sqlite3.Connection, code: str) -> str:
        base_code = code[:20] or "CAT"
        candidate = base_code
        suffix = 2
        while connection.execute(
            "SELECT 1 FROM product_categories WHERE code = ?",
            (candidate,),
        ).fetchone():
            candidate = f"{base_code}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _brand_code(name: str) -> str:
        words = [word for word in "".join(char if char.isalnum() else " " for char in name.upper()).split() if word]
        return "".join(word[:4] for word in words)[:16] or "BRAND"

    @staticmethod
    def _unique_brand_code(connection: sqlite3.Connection, code: str) -> str:
        base_code = code[:18] or "BRAND"
        candidate = base_code
        suffix = 2
        while connection.execute(
            "SELECT 1 FROM product_brands WHERE code = ?",
            (candidate,),
        ).fetchone():
            candidate = f"{base_code}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _template_attributes(template_key: str, root_name: str, child_name: str) -> str:
        if template_key == "clothing":
            return "Size, Color, Material, Gender"
        if template_key == "electronics":
            return "Brand, Model, Warranty, Serial Number"
        if template_key == "pharmacy":
            return "Batch Number, Expiry Date, Dosage, Manufacturer"
        if template_key == "grocery":
            return "Weight, Pack Size, Expiry Date, Brand"
        if template_key == "restaurant":
            return "Portion Size, Spice Level, Add-ons"
        if template_key == "auto_parts":
            return "Vehicle Make, Vehicle Model, Year, Part Number"
        if template_key == "beauty":
            return "Shade, Skin Type, Size, Brand"
        if template_key == "hardware":
            return "Size, Material, Brand, Grade"
        if template_key == "bookshop":
            return "Author, Publisher, Grade, Language"
        return "Brand, Size, Color"

    def _variant_options(self, connection: sqlite3.Connection, option_values_text: str) -> list[tuple[int, str]]:
        options: list[tuple[int, str]] = []
        for raw_option in option_values_text.replace("\n", ",").split(","):
            if ":" not in raw_option:
                continue
            variation_name, value_name = (part.strip() for part in raw_option.split(":", 1))
            if not variation_name or not value_name:
                continue
            row = connection.execute(
                "SELECT id FROM product_variations WHERE lower(name) = lower(?)",
                (variation_name,),
            ).fetchone()
            if row is None:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO product_variation_values (variation_id, value_name, is_active)
                VALUES (?, ?, 1)
                """,
                (row["id"], value_name),
            )
            options.append((int(row["id"]), value_name))
        return options

    @staticmethod
    def _variation_values(values_text: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for raw_value in values_text.split(","):
            value = raw_value.strip()
            value_key = value.lower()
            if value and value_key not in seen:
                values.append(value)
                seen.add(value_key)
        return values

    @staticmethod
    def _csv_float(row: dict[str, str], fields: dict[str, str], key: str) -> float:
        field = fields.get(key)
        if not field:
            return 0.0
        value = (row.get(field) or "").strip()
        return float(value) if value else 0.0
