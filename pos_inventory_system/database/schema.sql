PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    permissions_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    address TEXT,
    emergency_contact TEXT,
    permissions_text TEXT,
    sales_commission_rate REAL NOT NULL DEFAULT 0,
    sales_target REAL NOT NULL DEFAULT 0,
    bank_name TEXT,
    bank_account_name TEXT,
    bank_account_number TEXT,
    bank_branch TEXT,
    employee_no TEXT,
    department TEXT,
    designation TEXT,
    joining_date TEXT,
    employment_type TEXT,
    basic_salary REAL NOT NULL DEFAULT 0,
    pay_frequency TEXT,
    allowances REAL NOT NULL DEFAULT 0,
    deductions REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles (id)
);

CREATE TABLE IF NOT EXISTS sales_commission_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    agent_code TEXT,
    phone TEXT,
    email TEXT,
    commission_rate REAL NOT NULL DEFAULT 0,
    sales_target REAL NOT NULL DEFAULT 0,
    territory TEXT,
    payout_frequency TEXT,
    payable_account TEXT,
    address TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS business_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    currency_symbol TEXT NOT NULL DEFAULT 'Rs.',
    tax_number TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER,
    code TEXT UNIQUE,
    description TEXT,
    image_path TEXT,
    color_hex TEXT NOT NULL DEFAULT '#0f766e',
    default_tax_rate_id INTEGER,
    default_unit_id INTEGER,
    default_warranty_id INTEGER,
    default_profit_margin REAL NOT NULL DEFAULT 0,
    attributes_text TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    show_on_pos INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (parent_id) REFERENCES product_categories (id),
    FOREIGN KEY (default_tax_rate_id) REFERENCES tax_rates (id),
    FOREIGN KEY (default_unit_id) REFERENCES product_units (id),
    FOREIGN KEY (default_warranty_id) REFERENCES warranties (id)
);

CREATE TABLE IF NOT EXISTS product_brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT UNIQUE,
    logo_path TEXT,
    website TEXT,
    contact_person TEXT,
    phone TEXT,
    email TEXT,
    country TEXT,
    supplier_id INTEGER,
    default_warranty_id INTEGER,
    default_profit_margin REAL NOT NULL DEFAULT 0,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (supplier_id) REFERENCES contacts (id),
    FOREIGN KEY (default_warranty_id) REFERENCES warranties (id)
);

CREATE TABLE IF NOT EXISTS product_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    short_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tax_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    rate REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sku TEXT NOT NULL UNIQUE,
    barcode TEXT UNIQUE,
    category_id INTEGER,
    brand_id INTEGER,
    unit_id INTEGER,
    purchase_price REAL NOT NULL DEFAULT 0,
    selling_price REAL NOT NULL DEFAULT 0,
    offer_price REAL NOT NULL DEFAULT 0,
    offer_start_date TEXT,
    offer_end_date TEXT,
    image_path TEXT,
    tax_rate_id INTEGER,
    warranty_id INTEGER,
    profit_margin REAL NOT NULL DEFAULT 0,
    alert_quantity REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES product_categories (id),
    FOREIGN KEY (brand_id) REFERENCES product_brands (id),
    FOREIGN KEY (unit_id) REFERENCES product_units (id),
    FOREIGN KEY (tax_rate_id) REFERENCES tax_rates (id),
    FOREIGN KEY (warranty_id) REFERENCES warranties (id)
);

CREATE TABLE IF NOT EXISTS product_variations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    values_text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS selling_price_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warranties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    duration_value INTEGER NOT NULL,
    duration_unit TEXT NOT NULL DEFAULT 'months',
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
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
);

CREATE TABLE IF NOT EXISTS customer_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    price_discount_percent REAL NOT NULL DEFAULT 0,
    note TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payment_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL DEFAULT 'cash',
    opening_balance REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS purchases (
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
);

CREATE TABLE IF NOT EXISTS purchase_orders (
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
);

CREATE TABLE IF NOT EXISTS purchase_items (
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
);

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
);

CREATE TABLE IF NOT EXISTS purchase_returns (
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
);

CREATE TABLE IF NOT EXISTS sales (
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
);

CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    shipment_date TEXT NOT NULL,
    courier TEXT,
    tracking_no TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sale_id) REFERENCES sales (id)
);

CREATE TABLE IF NOT EXISTS sale_items (
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
);

CREATE TABLE IF NOT EXISTS sales_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    return_date TEXT NOT NULL,
    quantity REAL NOT NULL,
    refund_amount REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sale_id) REFERENCES sales (id),
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    location_id INTEGER,
    movement_type TEXT NOT NULL,
    reference_type TEXT,
    reference_id INTEGER,
    quantity_in REAL NOT NULL DEFAULT 0,
    quantity_out REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id),
    FOREIGN KEY (location_id) REFERENCES locations (id)
);

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    location_id INTEGER,
    adjustment_date TEXT NOT NULL,
    adjustment_type TEXT NOT NULL CHECK (adjustment_type IN ('increase', 'decrease')),
    quantity REAL NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id),
    FOREIGN KEY (location_id) REFERENCES locations (id)
);

CREATE TABLE IF NOT EXISTS stock_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    from_location_id INTEGER NOT NULL,
    to_location_id INTEGER NOT NULL,
    transfer_date TEXT NOT NULL,
    quantity REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id),
    FOREIGN KEY (from_location_id) REFERENCES locations (id),
    FOREIGN KEY (to_location_id) REFERENCES locations (id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    location_id INTEGER,
    account_id INTEGER,
    expense_date TEXT NOT NULL,
    expense_time TEXT,
    expense_type TEXT NOT NULL DEFAULT 'expense',
    amount REAL NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'cash',
    party_name TEXT,
    reference_no TEXT,
    tax_rate REAL NOT NULL DEFAULT 0,
    tax_amount REAL NOT NULL DEFAULT 0,
    tax_mode TEXT NOT NULL DEFAULT 'exclusive',
    status TEXT NOT NULL DEFAULT 'paid',
    recurrence TEXT NOT NULL DEFAULT 'once',
    attachment_name TEXT,
    attachment_data TEXT,
    created_by INTEGER,
    approved_by INTEGER,
    approved_at TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (category_id) REFERENCES expense_categories (id),
    FOREIGN KEY (location_id) REFERENCES locations (id),
    FOREIGN KEY (account_id) REFERENCES payment_accounts (id),
    FOREIGN KEY (created_by) REFERENCES users (id),
    FOREIGN KEY (approved_by) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS expense_refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    refund_date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expense_id) REFERENCES expenses (id)
);

CREATE TABLE IF NOT EXISTS expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER,
    transaction_type TEXT NOT NULL DEFAULT 'all',
    monthly_budget REAL NOT NULL DEFAULT 0,
    requires_attachment INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
    ,FOREIGN KEY (parent_id) REFERENCES expense_categories (id)
);

CREATE TABLE IF NOT EXISTS expense_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_account_id INTEGER,
    default_location_id INTEGER,
    approval_limit REAL NOT NULL DEFAULT 0,
    require_attachment_over REAL NOT NULL DEFAULT 0,
    next_reference_number INTEGER NOT NULL DEFAULT 1,
    reference_prefix TEXT NOT NULL DEFAULT 'EXP-',
    FOREIGN KEY (default_account_id) REFERENCES payment_accounts (id),
    FOREIGN KEY (default_location_id) REFERENCES locations (id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_type TEXT NOT NULL,
    reference_type TEXT NOT NULL,
    reference_id INTEGER NOT NULL,
    account_id INTEGER,
    amount REAL NOT NULL,
    method TEXT NOT NULL DEFAULT 'cash',
    payment_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES payment_accounts (id)
);

CREATE TABLE IF NOT EXISTS payment_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_account_id INTEGER NOT NULL,
    to_account_id INTEGER NOT NULL,
    transfer_date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_account_id) REFERENCES payment_accounts (id),
    FOREIGN KEY (to_account_id) REFERENCES payment_accounts (id)
);

CREATE TABLE IF NOT EXISTS cash_registers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    location_id INTEGER,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    opening_cash REAL NOT NULL DEFAULT 0,
    closing_cash REAL,
    denomination_breakdown TEXT,
    closing_note TEXT,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (location_id) REFERENCES locations (id),
    FOREIGN KEY (approved_by) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
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
);

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
