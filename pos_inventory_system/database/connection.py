import sqlite3
from pathlib import Path

from pos_inventory_system.config import DATA_DIR, DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    connection = get_connection()
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        _apply_lightweight_migrations(connection)
        _seed_defaults(connection)
        connection.commit()
    finally:
        connection.close()


def _apply_lightweight_migrations(connection: sqlite3.Connection) -> None:
    role_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(roles)").fetchall()
    }
    if "permissions_text" not in role_columns:
        connection.execute("ALTER TABLE roles ADD COLUMN permissions_text TEXT")

    user_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    user_migrations = {
        "phone": "ALTER TABLE users ADD COLUMN phone TEXT",
        "email": "ALTER TABLE users ADD COLUMN email TEXT",
        "address": "ALTER TABLE users ADD COLUMN address TEXT",
        "emergency_contact": "ALTER TABLE users ADD COLUMN emergency_contact TEXT",
        "permissions_text": "ALTER TABLE users ADD COLUMN permissions_text TEXT",
        "sales_commission_rate": "ALTER TABLE users ADD COLUMN sales_commission_rate REAL NOT NULL DEFAULT 0",
        "sales_target": "ALTER TABLE users ADD COLUMN sales_target REAL NOT NULL DEFAULT 0",
        "bank_name": "ALTER TABLE users ADD COLUMN bank_name TEXT",
        "bank_account_name": "ALTER TABLE users ADD COLUMN bank_account_name TEXT",
        "bank_account_number": "ALTER TABLE users ADD COLUMN bank_account_number TEXT",
        "bank_branch": "ALTER TABLE users ADD COLUMN bank_branch TEXT",
        "employee_no": "ALTER TABLE users ADD COLUMN employee_no TEXT",
        "department": "ALTER TABLE users ADD COLUMN department TEXT",
        "designation": "ALTER TABLE users ADD COLUMN designation TEXT",
        "joining_date": "ALTER TABLE users ADD COLUMN joining_date TEXT",
        "employment_type": "ALTER TABLE users ADD COLUMN employment_type TEXT",
        "basic_salary": "ALTER TABLE users ADD COLUMN basic_salary REAL NOT NULL DEFAULT 0",
        "pay_frequency": "ALTER TABLE users ADD COLUMN pay_frequency TEXT",
        "allowances": "ALTER TABLE users ADD COLUMN allowances REAL NOT NULL DEFAULT 0",
        "deductions": "ALTER TABLE users ADD COLUMN deductions REAL NOT NULL DEFAULT 0",
    }
    for column, statement in user_migrations.items():
        if column not in user_columns:
            connection.execute(statement)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    expense_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(expenses)").fetchall()
    }
    added_expense_type = "expense_type" not in expense_columns
    if "expense_type" not in expense_columns:
        connection.execute(
            "ALTER TABLE expenses ADD COLUMN expense_type TEXT NOT NULL DEFAULT 'expense'"
        )
        cash_adjustments = connection.execute(
            """
            SELECT id, payment_type, payment_date, amount, note
            FROM payments
            WHERE reference_type = 'cash_adjustment'
            ORDER BY id
            """
        ).fetchall()
        for payment in cash_adjustments:
            cursor = connection.execute(
                """
                INSERT INTO expenses (
                    category_id,
                    location_id,
                    expense_date,
                    expense_type,
                    amount,
                    note
                )
                VALUES (NULL, 1, ?, ?, ?, ?)
                """,
                (
                    payment["payment_date"],
                    payment["payment_type"],
                    payment["amount"],
                    payment["note"],
                ),
            )
            connection.execute(
                """
                UPDATE payments
                SET reference_type = 'expense', reference_id = ?
                WHERE id = ?
                """,
                (int(cursor.lastrowid), payment["id"]),
            )
    migration_name = "expense_type_supports_expense_cash_in_cash_out"
    migration_applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE name = ?",
        (migration_name,),
    ).fetchone()
    if migration_applied is None:
        if not added_expense_type:
            connection.execute(
                "UPDATE expenses SET expense_type = 'expense' WHERE expense_type = 'out'"
            )
        connection.execute(
            "INSERT INTO app_migrations (name) VALUES (?)",
            (migration_name,),
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS purchase_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL,
            payment_type TEXT NOT NULL DEFAULT 'cash',
            amount REAL NOT NULL,
            payment_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'cleared',
            cheque_no TEXT,
            cheque_date TEXT,
            bank_name TEXT,
            note TEXT,
            cleared_at TEXT,
            bounced_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (purchase_id) REFERENCES purchases (id)
        )
        """
    )
    purchase_return_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(purchase_returns)").fetchall()
    }
    purchase_return_migrations = {
        "reason": "ALTER TABLE purchase_returns ADD COLUMN reason TEXT NOT NULL DEFAULT 'other'",
        "item_condition": "ALTER TABLE purchase_returns ADD COLUMN item_condition TEXT NOT NULL DEFAULT 'resellable'",
        "refund_method": "ALTER TABLE purchase_returns ADD COLUMN refund_method TEXT NOT NULL DEFAULT 'cash'",
        "return_to_stock": "ALTER TABLE purchase_returns ADD COLUMN return_to_stock INTEGER NOT NULL DEFAULT 1",
    }
    for column, statement in purchase_return_migrations.items():
        if column not in purchase_return_columns:
            connection.execute(statement)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS external_sync_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            local_type TEXT NOT NULL,
            local_id INTEGER NOT NULL,
            payload_summary TEXT,
            last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source, external_type, external_id)
        )
        """
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS hrm_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'present' CHECK (status IN ('present', 'absent', 'half_day', 'leave', 'late')),
            check_in TEXT,
            check_out TEXT,
            overtime_hours REAL NOT NULL DEFAULT 0,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, attendance_date),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS hrm_leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            leave_type TEXT NOT NULL DEFAULT 'annual',
            date_from TEXT NOT NULL,
            date_to TEXT NOT NULL,
            days REAL NOT NULL DEFAULT 1,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS hrm_payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pay_period TEXT NOT NULL,
            basic_salary REAL NOT NULL DEFAULT 0,
            allowances REAL NOT NULL DEFAULT 0,
            overtime_amount REAL NOT NULL DEFAULT 0,
            commission_amount REAL NOT NULL DEFAULT 0,
            deductions REAL NOT NULL DEFAULT 0,
            net_salary REAL NOT NULL DEFAULT 0,
            payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'paid', 'partial')),
            payment_date TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, pay_period),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS hrm_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            document_type TEXT NOT NULL,
            document_no TEXT,
            expiry_date TEXT,
            status TEXT NOT NULL DEFAULT 'valid' CHECK (status IN ('valid', 'expiring', 'expired', 'missing')),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS crm_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            source TEXT NOT NULL DEFAULT 'walk_in',
            interested_in TEXT,
            status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'qualified', 'converted', 'lost')),
            assigned_user_id INTEGER,
            next_followup_date TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assigned_user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS crm_followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            customer_id INTEGER,
            assigned_user_id INTEGER,
            followup_type TEXT NOT NULL DEFAULT 'call',
            due_date TEXT NOT NULL,
            due_time TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'missed', 'cancelled')),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES crm_leads (id),
            FOREIGN KEY (customer_id) REFERENCES contacts (id),
            FOREIGN KEY (assigned_user_id) REFERENCES users (id)
        );
        """
    )

    expense_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(expenses)").fetchall()
    }
    expense_migrations = {
        "account_id": "ALTER TABLE expenses ADD COLUMN account_id INTEGER",
        "expense_time": "ALTER TABLE expenses ADD COLUMN expense_time TEXT",
        "payment_method": "ALTER TABLE expenses ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'cash'",
        "party_name": "ALTER TABLE expenses ADD COLUMN party_name TEXT",
        "reference_no": "ALTER TABLE expenses ADD COLUMN reference_no TEXT",
        "tax_rate": "ALTER TABLE expenses ADD COLUMN tax_rate REAL NOT NULL DEFAULT 0",
        "tax_amount": "ALTER TABLE expenses ADD COLUMN tax_amount REAL NOT NULL DEFAULT 0",
        "tax_mode": "ALTER TABLE expenses ADD COLUMN tax_mode TEXT NOT NULL DEFAULT 'exclusive'",
        "status": "ALTER TABLE expenses ADD COLUMN status TEXT NOT NULL DEFAULT 'paid'",
        "recurrence": "ALTER TABLE expenses ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'once'",
        "attachment_name": "ALTER TABLE expenses ADD COLUMN attachment_name TEXT",
        "attachment_data": "ALTER TABLE expenses ADD COLUMN attachment_data TEXT",
        "created_by": "ALTER TABLE expenses ADD COLUMN created_by INTEGER",
        "approved_by": "ALTER TABLE expenses ADD COLUMN approved_by INTEGER",
        "approved_at": "ALTER TABLE expenses ADD COLUMN approved_at TEXT",
        "updated_at": "ALTER TABLE expenses ADD COLUMN updated_at TEXT",
    }
    for column, statement in expense_migrations.items():
        if column not in expense_columns:
            connection.execute(statement)
    connection.execute("UPDATE expenses SET account_id = 1 WHERE account_id IS NULL")
    connection.execute(
        "UPDATE expenses SET expense_time = '00:00' WHERE expense_time IS NULL OR expense_time = ''"
    )

    cash_register_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(cash_registers)").fetchall()
    }
    cash_register_migrations = {
        "denomination_breakdown": "ALTER TABLE cash_registers ADD COLUMN denomination_breakdown TEXT",
        "closing_note": "ALTER TABLE cash_registers ADD COLUMN closing_note TEXT",
        "approval_status": "ALTER TABLE cash_registers ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'pending'",
        "approved_by": "ALTER TABLE cash_registers ADD COLUMN approved_by INTEGER",
        "approved_at": "ALTER TABLE cash_registers ADD COLUMN approved_at TEXT",
    }
    for column, statement in cash_register_migrations.items():
        if column not in cash_register_columns:
            connection.execute(statement)

    expense_category_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(expense_categories)").fetchall()
    }
    expense_category_migrations = {
        "parent_id": "ALTER TABLE expense_categories ADD COLUMN parent_id INTEGER",
        "transaction_type": "ALTER TABLE expense_categories ADD COLUMN transaction_type TEXT NOT NULL DEFAULT 'all'",
        "monthly_budget": "ALTER TABLE expense_categories ADD COLUMN monthly_budget REAL NOT NULL DEFAULT 0",
        "requires_attachment": "ALTER TABLE expense_categories ADD COLUMN requires_attachment INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in expense_category_migrations.items():
        if column not in expense_category_columns:
            connection.execute(statement)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS expense_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            default_account_id INTEGER,
            default_location_id INTEGER,
            approval_limit REAL NOT NULL DEFAULT 0,
            require_attachment_over REAL NOT NULL DEFAULT 0,
            next_reference_number INTEGER NOT NULL DEFAULT 1,
            reference_prefix TEXT NOT NULL DEFAULT 'EXP-'
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO expense_settings (
            id
        )
        VALUES (1)
        """
    )

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(contacts)").fetchall()
    }
    if "customer_group_id" not in columns:
        connection.execute("ALTER TABLE contacts ADD COLUMN customer_group_id INTEGER")
        columns.add("customer_group_id")

    contact_migrations = {
        "supplier_type": "ALTER TABLE contacts ADD COLUMN supplier_type TEXT NOT NULL DEFAULT 'business'",
        "business_name": "ALTER TABLE contacts ADD COLUMN business_name TEXT",
        "contact_code": "ALTER TABLE contacts ADD COLUMN contact_code TEXT",
        "tax_number": "ALTER TABLE contacts ADD COLUMN tax_number TEXT",
        "alternate_phone": "ALTER TABLE contacts ADD COLUMN alternate_phone TEXT",
        "website": "ALTER TABLE contacts ADD COLUMN website TEXT",
        "city": "ALTER TABLE contacts ADD COLUMN city TEXT",
        "state": "ALTER TABLE contacts ADD COLUMN state TEXT",
        "country": "ALTER TABLE contacts ADD COLUMN country TEXT",
        "postal_code": "ALTER TABLE contacts ADD COLUMN postal_code TEXT",
        "payment_terms": "ALTER TABLE contacts ADD COLUMN payment_terms TEXT",
        "credit_days": "ALTER TABLE contacts ADD COLUMN credit_days INTEGER NOT NULL DEFAULT 0",
        "contact_person_1_name": "ALTER TABLE contacts ADD COLUMN contact_person_1_name TEXT",
        "contact_person_1_designation": "ALTER TABLE contacts ADD COLUMN contact_person_1_designation TEXT",
        "contact_person_1_phone": "ALTER TABLE contacts ADD COLUMN contact_person_1_phone TEXT",
        "contact_person_1_email": "ALTER TABLE contacts ADD COLUMN contact_person_1_email TEXT",
        "contact_person_2_name": "ALTER TABLE contacts ADD COLUMN contact_person_2_name TEXT",
        "contact_person_2_designation": "ALTER TABLE contacts ADD COLUMN contact_person_2_designation TEXT",
        "contact_person_2_phone": "ALTER TABLE contacts ADD COLUMN contact_person_2_phone TEXT",
        "contact_person_2_email": "ALTER TABLE contacts ADD COLUMN contact_person_2_email TEXT",
        "contact_person_3_name": "ALTER TABLE contacts ADD COLUMN contact_person_3_name TEXT",
        "contact_person_3_designation": "ALTER TABLE contacts ADD COLUMN contact_person_3_designation TEXT",
        "contact_person_3_phone": "ALTER TABLE contacts ADD COLUMN contact_person_3_phone TEXT",
        "contact_person_3_email": "ALTER TABLE contacts ADD COLUMN contact_person_3_email TEXT",
        "notes": "ALTER TABLE contacts ADD COLUMN notes TEXT",
        "updated_at": "ALTER TABLE contacts ADD COLUMN updated_at TEXT",
    }
    for column, statement in contact_migrations.items():
        if column not in columns:
            connection.execute(statement)
    _migrate_contacts_contact_type_constraint(connection)
    _repair_contacts_old_foreign_keys(connection)
    _repair_fk_old_foreign_keys(connection)

    sales_return_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sales_returns)").fetchall()
    }
    sales_return_migrations = {
        "reason": "ALTER TABLE sales_returns ADD COLUMN reason TEXT NOT NULL DEFAULT 'other'",
        "item_condition": "ALTER TABLE sales_returns ADD COLUMN item_condition TEXT NOT NULL DEFAULT 'resellable'",
        "refund_method": "ALTER TABLE sales_returns ADD COLUMN refund_method TEXT NOT NULL DEFAULT 'cash'",
        "return_to_stock": "ALTER TABLE sales_returns ADD COLUMN return_to_stock INTEGER NOT NULL DEFAULT 1",
    }
    for column, statement in sales_return_migrations.items():
        if column not in sales_return_columns:
            connection.execute(statement)

    agent_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sales_commission_agents)").fetchall()
    }
    agent_migrations = {
        "agent_code": "ALTER TABLE sales_commission_agents ADD COLUMN agent_code TEXT",
        "sales_target": "ALTER TABLE sales_commission_agents ADD COLUMN sales_target REAL NOT NULL DEFAULT 0",
        "territory": "ALTER TABLE sales_commission_agents ADD COLUMN territory TEXT",
        "payout_frequency": "ALTER TABLE sales_commission_agents ADD COLUMN payout_frequency TEXT",
        "payable_account": "ALTER TABLE sales_commission_agents ADD COLUMN payable_account TEXT",
        "notes": "ALTER TABLE sales_commission_agents ADD COLUMN notes TEXT",
        "updated_at": "ALTER TABLE sales_commission_agents ADD COLUMN updated_at TEXT",
    }
    for column, statement in agent_migrations.items():
        if column not in agent_columns:
            connection.execute(statement)

    product_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(products)").fetchall()
    }
    if "image_path" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
    if "warranty_id" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN warranty_id INTEGER")
    if "profit_margin" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN profit_margin REAL NOT NULL DEFAULT 0")
    if "offer_price" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN offer_price REAL NOT NULL DEFAULT 0")
    if "offer_start_date" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN offer_start_date TEXT")
    if "offer_end_date" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN offer_end_date TEXT")

    category_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(product_categories)").fetchall()
    }
    category_migrations = {
        "parent_id": "ALTER TABLE product_categories ADD COLUMN parent_id INTEGER",
        "code": "ALTER TABLE product_categories ADD COLUMN code TEXT",
        "description": "ALTER TABLE product_categories ADD COLUMN description TEXT",
        "image_path": "ALTER TABLE product_categories ADD COLUMN image_path TEXT",
        "color_hex": "ALTER TABLE product_categories ADD COLUMN color_hex TEXT NOT NULL DEFAULT '#0f766e'",
        "default_tax_rate_id": "ALTER TABLE product_categories ADD COLUMN default_tax_rate_id INTEGER",
        "default_unit_id": "ALTER TABLE product_categories ADD COLUMN default_unit_id INTEGER",
        "default_warranty_id": "ALTER TABLE product_categories ADD COLUMN default_warranty_id INTEGER",
        "default_profit_margin": "ALTER TABLE product_categories ADD COLUMN default_profit_margin REAL NOT NULL DEFAULT 0",
        "attributes_text": "ALTER TABLE product_categories ADD COLUMN attributes_text TEXT",
        "display_order": "ALTER TABLE product_categories ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0",
        "show_on_pos": "ALTER TABLE product_categories ADD COLUMN show_on_pos INTEGER NOT NULL DEFAULT 1",
        "created_at": "ALTER TABLE product_categories ADD COLUMN created_at TEXT",
        "updated_at": "ALTER TABLE product_categories ADD COLUMN updated_at TEXT",
    }
    for column, statement in category_migrations.items():
        if column not in category_columns:
            connection.execute(statement)
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_categories_code ON product_categories(code) WHERE code IS NOT NULL"
    )

    brand_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(product_brands)").fetchall()
    }
    brand_migrations = {
        "code": "ALTER TABLE product_brands ADD COLUMN code TEXT",
        "logo_path": "ALTER TABLE product_brands ADD COLUMN logo_path TEXT",
        "website": "ALTER TABLE product_brands ADD COLUMN website TEXT",
        "contact_person": "ALTER TABLE product_brands ADD COLUMN contact_person TEXT",
        "phone": "ALTER TABLE product_brands ADD COLUMN phone TEXT",
        "email": "ALTER TABLE product_brands ADD COLUMN email TEXT",
        "country": "ALTER TABLE product_brands ADD COLUMN country TEXT",
        "supplier_id": "ALTER TABLE product_brands ADD COLUMN supplier_id INTEGER",
        "default_warranty_id": "ALTER TABLE product_brands ADD COLUMN default_warranty_id INTEGER",
        "default_profit_margin": "ALTER TABLE product_brands ADD COLUMN default_profit_margin REAL NOT NULL DEFAULT 0",
        "description": "ALTER TABLE product_brands ADD COLUMN description TEXT",
        "created_at": "ALTER TABLE product_brands ADD COLUMN created_at TEXT",
        "updated_at": "ALTER TABLE product_brands ADD COLUMN updated_at TEXT",
    }
    for column, statement in brand_migrations.items():
        if column not in brand_columns:
            connection.execute(statement)
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_brands_code ON product_brands(code) WHERE code IS NOT NULL"
    )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS product_variation_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variation_id INTEGER NOT NULL,
            value_name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (variation_id, value_name),
            FOREIGN KEY (variation_id) REFERENCES product_variations (id)
        );

        CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            barcode TEXT UNIQUE,
            variation_summary TEXT NOT NULL,
            purchase_price REAL NOT NULL DEFAULT 0,
            selling_price REAL NOT NULL DEFAULT 0,
            alert_quantity REAL NOT NULL DEFAULT 0,
            image_path TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        );

        CREATE TABLE IF NOT EXISTS product_variant_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL,
            variation_id INTEGER NOT NULL,
            value_name TEXT NOT NULL,
            UNIQUE (variant_id, variation_id),
            FOREIGN KEY (variant_id) REFERENCES product_variants (id),
            FOREIGN KEY (variation_id) REFERENCES product_variations (id)
        );
        """
    )
    for table in (
        "purchase_orders",
        "purchase_items",
        "purchase_returns",
        "sale_items",
        "sales_returns",
        "stock_movements",
        "stock_adjustments",
        "stock_transfers",
    ):
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "variant_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN variant_id INTEGER")

    variation_rows = connection.execute(
        "SELECT id, values_text FROM product_variations"
    ).fetchall()
    for row in variation_rows:
        for value_name in _variation_values(row["values_text"]):
            connection.execute(
                """
                INSERT OR IGNORE INTO product_variation_values (variation_id, value_name, is_active)
                VALUES (?, ?, 1)
                """,
                (row["id"], value_name),
            )

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS invoice_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_prefix TEXT NOT NULL DEFAULT 'INV-',
            next_invoice_number INTEGER NOT NULL DEFAULT 1,
            receipt_footer TEXT,
            terms TEXT,
            show_tax INTEGER NOT NULL DEFAULT 1,
            show_logo INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS barcode_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode_prefix TEXT NOT NULL DEFAULT 'PRD',
            next_barcode_number INTEGER NOT NULL DEFAULT 1,
            label_width REAL NOT NULL DEFAULT 50,
            label_height REAL NOT NULL DEFAULT 30,
            copies_per_product INTEGER NOT NULL DEFAULT 1,
            show_price INTEGER NOT NULL DEFAULT 1,
            show_product_name INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            method_key TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS printer_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            printer_type TEXT NOT NULL DEFAULT 'receipt',
            connection_type TEXT NOT NULL DEFAULT 'windows',
            paper_width TEXT NOT NULL DEFAULT '80mm',
            device_name TEXT,
            is_default INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS addon_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL UNIQUE,
            is_enabled INTEGER NOT NULL DEFAULT 0,
            connection_mode TEXT NOT NULL DEFAULT 'manual',
            endpoint_url TEXT,
            token_label TEXT,
            notes TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS addon_work_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_key TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('pending', 'in_progress', 'complete')),
            owner TEXT,
            due_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (module_key, title),
            FOREIGN KEY (module_key) REFERENCES addon_modules (module_key)
        );

        CREATE TABLE IF NOT EXISTS addon_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_key TEXT NOT NULL,
            run_type TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_key) REFERENCES addon_modules (module_key)
        );
        """
    )
    barcode_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(barcode_settings)").fetchall()
    }
    if "next_barcode_number" not in barcode_columns:
        connection.execute(
            "ALTER TABLE barcode_settings ADD COLUMN next_barcode_number INTEGER NOT NULL DEFAULT 1"
        )


def _variation_values(values_text: str | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in (values_text or "").split(","):
        value = raw_value.strip()
        value_key = value.lower()
        if value and value_key not in seen:
            values.append(value)
            seen.add(value_key)
    return values


def _migrate_contacts_contact_type_constraint(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'contacts'"
    ).fetchone()
    if not row or "contact_type IN ('customer', 'supplier')" not in (row["sql"] or ""):
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE contacts RENAME TO contacts_old")
    connection.execute(
        """
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_type TEXT NOT NULL CHECK (contact_type IN ('customer', 'supplier', 'both')),
            supplier_type TEXT NOT NULL DEFAULT 'business' CHECK (supplier_type IN ('individual', 'business')),
            name TEXT NOT NULL,
            business_name TEXT,
            contact_code TEXT,
            tax_number TEXT,
            phone TEXT,
            alternate_phone TEXT,
            email TEXT,
            website TEXT,
            address TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            postal_code TEXT,
            payment_terms TEXT,
            credit_days INTEGER NOT NULL DEFAULT 0,
            opening_balance REAL NOT NULL DEFAULT 0,
            credit_limit REAL NOT NULL DEFAULT 0,
            customer_group_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            contact_person_1_name TEXT,
            contact_person_1_designation TEXT,
            contact_person_1_phone TEXT,
            contact_person_1_email TEXT,
            contact_person_2_name TEXT,
            contact_person_2_designation TEXT,
            contact_person_2_phone TEXT,
            contact_person_2_email TEXT,
            contact_person_3_name TEXT,
            contact_person_3_designation TEXT,
            contact_person_3_phone TEXT,
            contact_person_3_email TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO contacts (
            id, contact_type, supplier_type, name, business_name, contact_code, tax_number,
            phone, alternate_phone, email, website, address, city, state, country, postal_code,
            payment_terms, credit_days, opening_balance, credit_limit, customer_group_id, is_active,
            contact_person_1_name, contact_person_1_designation, contact_person_1_phone, contact_person_1_email,
            contact_person_2_name, contact_person_2_designation, contact_person_2_phone, contact_person_2_email,
            contact_person_3_name, contact_person_3_designation, contact_person_3_phone, contact_person_3_email,
            notes, created_at, updated_at
        )
        SELECT
            id, contact_type, COALESCE(NULLIF(supplier_type, ''), 'business'), name, business_name, contact_code, tax_number,
            phone, alternate_phone, email, website, address, city, state, country, postal_code,
            payment_terms, credit_days, opening_balance, credit_limit, customer_group_id, is_active,
            contact_person_1_name, contact_person_1_designation, contact_person_1_phone, contact_person_1_email,
            contact_person_2_name, contact_person_2_designation, contact_person_2_phone, contact_person_2_email,
            contact_person_3_name, contact_person_3_designation, contact_person_3_phone, contact_person_3_email,
            notes, created_at, updated_at
        FROM contacts_old
        """
    )
    connection.execute("DROP TABLE contacts_old")
    connection.execute("PRAGMA foreign_keys = ON")


def _repair_contacts_old_foreign_keys(connection: sqlite3.Connection) -> None:
    affected_tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE '%contacts_old%'"
        ).fetchall()
    }
    if not affected_tables:
        return

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        if "sales" in affected_tables:
            _rebuild_table(
                connection,
                "sales",
                """
                CREATE TABLE sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER,
                    location_id INTEGER,
                    invoice_no TEXT NOT NULL UNIQUE,
                    sale_date TEXT NOT NULL,
                    subtotal REAL NOT NULL DEFAULT 0,
                    discount REAL NOT NULL DEFAULT 0,
                    tax REAL NOT NULL DEFAULT 0,
                    total REAL NOT NULL DEFAULT 0,
                    paid_amount REAL NOT NULL DEFAULT 0,
                    due_amount REAL NOT NULL DEFAULT 0,
                    payment_status TEXT NOT NULL DEFAULT 'due',
                    sale_status TEXT NOT NULL DEFAULT 'final',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES contacts (id),
                    FOREIGN KEY (location_id) REFERENCES locations (id)
                )
                """,
            )
        if "purchases" in affected_tables:
            _rebuild_table(
                connection,
                "purchases",
                """
                CREATE TABLE purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER,
                    location_id INTEGER,
                    invoice_no TEXT NOT NULL UNIQUE,
                    purchase_date TEXT NOT NULL,
                    subtotal REAL NOT NULL DEFAULT 0,
                    discount REAL NOT NULL DEFAULT 0,
                    tax REAL NOT NULL DEFAULT 0,
                    total REAL NOT NULL DEFAULT 0,
                    paid_amount REAL NOT NULL DEFAULT 0,
                    due_amount REAL NOT NULL DEFAULT 0,
                    payment_status TEXT NOT NULL DEFAULT 'due',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (supplier_id) REFERENCES contacts (id),
                    FOREIGN KEY (location_id) REFERENCES locations (id)
                )
                """,
            )
        if "purchase_orders" in affected_tables:
            _rebuild_table(
                connection,
                "purchase_orders",
                """
                CREATE TABLE purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER,
                    location_id INTEGER,
                    order_no TEXT NOT NULL UNIQUE,
                    order_date TEXT NOT NULL,
                    expected_date TEXT,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER,
                    quantity REAL NOT NULL,
                    purchase_price REAL NOT NULL DEFAULT 0,
                    subtotal REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ordered',
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (supplier_id) REFERENCES contacts (id),
                    FOREIGN KEY (location_id) REFERENCES locations (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
                )
                """,
            )
        connection.execute("PRAGMA foreign_keys = ON")
    except Exception:
        connection.execute("PRAGMA foreign_keys = ON")
        raise


def _rebuild_table(connection: sqlite3.Connection, table_name: str, create_sql: str) -> None:
    old_table = f"{table_name}_fk_old"
    connection.execute(f"ALTER TABLE {table_name} RENAME TO {old_table}")
    connection.execute(create_sql)
    old_columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({old_table})").fetchall()
    }
    new_columns = [
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        if row["name"] in old_columns
    ]
    if new_columns:
        columns_sql = ", ".join(new_columns)
        connection.execute(
            f"INSERT INTO {table_name} ({columns_sql}) SELECT {columns_sql} FROM {old_table}"
        )
    connection.execute(f"DROP TABLE {old_table}")


def _repair_fk_old_foreign_keys(connection: sqlite3.Connection) -> None:
    affected_tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE '%_fk_old%'"
        ).fetchall()
    }
    if not affected_tables:
        return

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        if "sale_items" in affected_tables:
            _rebuild_table(
                connection,
                "sale_items",
                """
                CREATE TABLE sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER,
                    quantity REAL NOT NULL,
                    unit_price REAL NOT NULL,
                    discount REAL NOT NULL DEFAULT 0,
                    tax REAL NOT NULL DEFAULT 0,
                    line_total REAL NOT NULL,
                    FOREIGN KEY (sale_id) REFERENCES sales (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
                )
                """,
            )
        if "sales_returns" in affected_tables:
            _rebuild_table(
                connection,
                "sales_returns",
                """
                CREATE TABLE sales_returns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER,
                    return_date TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    refund_amount REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT 'other',
                    item_condition TEXT NOT NULL DEFAULT 'resellable',
                    refund_method TEXT NOT NULL DEFAULT 'cash',
                    return_to_stock INTEGER NOT NULL DEFAULT 1,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sale_id) REFERENCES sales (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
                )
                """,
            )
        if "shipments" in affected_tables:
            _rebuild_table(
                connection,
                "shipments",
                """
                CREATE TABLE shipments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    shipment_date TEXT NOT NULL,
                    courier TEXT,
                    tracking_no TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sale_id) REFERENCES sales (id)
                )
                """,
            )
        if "purchase_items" in affected_tables:
            _rebuild_table(
                connection,
                "purchase_items",
                """
                CREATE TABLE purchase_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER,
                    quantity REAL NOT NULL,
                    purchase_price REAL NOT NULL,
                    tax REAL NOT NULL DEFAULT 0,
                    discount REAL NOT NULL DEFAULT 0,
                    line_total REAL NOT NULL,
                    FOREIGN KEY (purchase_id) REFERENCES purchases (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
                )
                """,
            )
        if "purchase_returns" in affected_tables:
            _rebuild_table(
                connection,
                "purchase_returns",
                """
                CREATE TABLE purchase_returns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER,
                    return_date TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    refund_amount REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT 'other',
                    item_condition TEXT NOT NULL DEFAULT 'resellable',
                    refund_method TEXT NOT NULL DEFAULT 'cash',
                    return_to_stock INTEGER NOT NULL DEFAULT 1,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (purchase_id) REFERENCES purchases (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
                )
                """,
            )
        connection.execute("PRAGMA foreign_keys = ON")
    except Exception:
        connection.execute("PRAGMA foreign_keys = ON")
        raise


def _seed_defaults(connection: sqlite3.Connection) -> None:
    default_roles = (
        (
            1,
            "Admin",
            "Full system access across sales, purchases, inventory, settings, and users.",
            "dashboard, sales, purchases, products, contacts, stock, expenses, payments, reports, settings, users, addons, users.view, users.create, users.delete",
        ),
        (
            2,
            "Manager",
            "Daily operations supervisor with reporting and staff visibility.",
            "dashboard, sales, purchases, products, contacts, stock, expenses, payments, reports, users.view",
        ),
        (
            3,
            "Cashier",
            "POS counter user focused on sales, payments, and cash register work.",
            "dashboard, sales, payments",
        ),
        (
            4,
            "Sales Staff",
            "Sales team member with customer and quotation workflow access.",
            "dashboard, sales, contacts",
        ),
        (
            5,
            "Inventory Controller",
            "Stock, product, transfer, and adjustment operator.",
            "dashboard, products, stock, reports",
        ),
        (
            6,
            "Purchasing Officer",
            "Supplier purchasing and purchase return operator.",
            "dashboard, purchases, contacts, products, stock",
        ),
        (
            7,
            "Accountant",
            "Payments, expenses, accounts, and financial reports operator.",
            "dashboard, expenses, payments, reports",
        ),
        (
            8,
            "HR / Essentials",
            "Staff profile and internal essentials coordinator.",
            "dashboard, users.view, reports",
        ),
        (
            9,
            "Read Only",
            "Audit-friendly read-only role for dashboards and reports.",
            "dashboard, reports",
        ),
    )
    for role_id, name, description, permissions_text in default_roles:
        if role_id == 1:
            connection.execute(
                """
                INSERT OR IGNORE INTO roles (id, name, description, permissions_text)
                VALUES (?, ?, ?, ?)
                """,
                (role_id, name, description, permissions_text),
            )
        else:
            connection.execute(
                """
                INSERT OR IGNORE INTO roles (name, description, permissions_text)
                VALUES (?, ?, ?)
                """,
                (name, description, permissions_text),
            )
        connection.execute(
            """
            UPDATE roles
            SET
                description = CASE
                    WHEN description IS NULL OR description = '' THEN ?
                    ELSE description
                END,
                permissions_text = CASE
                    WHEN permissions_text IS NULL OR permissions_text = '' THEN ?
                    ELSE permissions_text
                END
            WHERE name = ?
            """,
            (description, permissions_text, name),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO business_settings (id, business_name, currency_symbol)
        VALUES (1, 'POS Ultimate Inventory System', 'Rs.')
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO locations (id, name, address)
        VALUES (1, 'Main Location', 'Default shop location')
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO payment_accounts (id, name, account_type)
        VALUES (1, 'Cash Register', 'cash')
        """
    )
    connection.execute(
        """
        UPDATE expense_settings
        SET default_account_id = COALESCE(default_account_id, 1),
            default_location_id = COALESCE(default_location_id, 1)
        WHERE id = 1
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO product_units (id, name, short_name)
        VALUES (1, 'Piece', 'pc')
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO tax_rates (id, name, rate)
        VALUES (1, 'No Tax', 0)
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO invoice_settings (id, invoice_prefix, next_invoice_number, receipt_footer, terms)
        VALUES (1, 'INV-', 1, 'Thank you for your business.', 'Goods once sold are not returnable without receipt.')
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO barcode_settings (id, barcode_prefix, label_width, label_height, copies_per_product)
        VALUES (1, 'PRD', 50, 30, 1)
        """
    )
    for method_id, name, method_key in (
        (1, "Cash", "cash"),
        (2, "Card", "card"),
        (3, "Bank Transfer", "bank_transfer"),
        (4, "Cheque", "cheque"),
    ):
        connection.execute(
            """
            INSERT OR IGNORE INTO payment_methods (id, name, method_key)
            VALUES (?, ?, ?)
            """,
            (method_id, name, method_key),
        )

    for module_key, name in (
        ("woocommerce", "WooCommerce"),
        ("manufacturing", "Manufacturing"),
        ("accounting", "Accounting"),
        ("hrm_essentials", "HRM / Essentials"),
        ("crm", "CRM"),
        ("restaurant_kitchen", "Restaurant / Kitchen"),
        ("saas_super_admin", "SaaS / Super Admin"),
        ("api_connector", "API Connector"),
    ):
        connection.execute(
            """
            INSERT OR IGNORE INTO addon_modules (module_key, name)
            VALUES (?, ?)
            """,
            (module_key, name),
        )

    default_work_items = {
        "woocommerce": (
            "Product catalog export",
            "Order import queue",
            "Customer sync profile",
            "Stock push readiness",
        ),
        "manufacturing": (
            "Bill of materials planning",
            "Production issue tracking",
            "Finished goods stock intake",
            "Wastage and cost review",
        ),
        "accounting": (
            "Chart of accounts mapping",
            "Sales and purchase journal review",
            "Expense posting controls",
            "Tax summary handoff",
        ),
        "hrm_essentials": (
            "Staff profile control",
            "Attendance source mapping",
            "Payroll export notes",
            "Role access alignment",
        ),
        "crm": (
            "Lead and customer segmentation",
            "Follow-up activity tracking",
            "Quotation handoff",
            "Customer ledger visibility",
        ),
        "restaurant_kitchen": (
            "Kitchen order token readiness",
            "Table and service area notes",
            "Counter sale routing",
            "Receipt printer assignment",
        ),
        "saas_super_admin": (
            "Tenant setup notes",
            "Subscription status tracking",
            "Business location limits",
            "Admin access review",
        ),
        "api_connector": (
            "Endpoint registry",
            "Webhook mode selection",
            "Token reference label",
            "Manual sync checklist",
        ),
    }
    for module_key, titles in default_work_items.items():
        for title in titles:
            connection.execute(
                """
                INSERT OR IGNORE INTO addon_work_items (module_key, title, status, owner, notes)
                VALUES (?, ?, 'complete', 'System', 'Completed in the addon module build.')
                """,
                (module_key, title),
            )
