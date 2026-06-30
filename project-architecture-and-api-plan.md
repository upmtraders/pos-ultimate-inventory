# POS Ultimate Inventory System - Project Architecture and API Plan

This document explains the planned architecture for building a POS and inventory management system in three stages:

1. Python version
2. C++ version
3. Web version

The goal is to design the project in a clean way so the business logic can be reused when moving from Python to C++ and later to a web system.

## 1. Project Goal

The system should manage:

- Products
- Stock
- Sales
- Purchases
- Customers
- Suppliers
- Expenses
- Payments
- Users
- Reports
- Business settings

The system should support one shop first, then later support multiple branches, warehouses, and online access.

## 2. Recommended Development Roadmap

## Stage 1: Python Desktop Version

Build the first working version in Python.

Recommended stack:

- Language: Python
- UI: Tkinter + CustomTkinter
- Database: SQLite for first version
- Reports: ReportLab, Pandas, or Excel export
- Receipt printing: ESC/POS printer library or normal Windows printer
- Barcode: Keyboard-style barcode scanner

Best first choice:

- Python + CustomTkinter + Tkinter + SQLite

Why Tkinter and CustomTkinter:

- Tkinter is included with Python
- CustomTkinter gives a modern UI style
- Easy to create forms, tables, buttons, tabs, and dialogs
- Good for a Windows desktop POS application
- Simple to package later as an `.exe`
- Suitable for a first complete working version

Why Python first:

- Faster to develop
- Easy to test business logic
- Easy database handling
- Good for prototypes and local shop software
- Easier to modify while learning the system

## Stage 2: C++ Desktop Version

After the Python version is complete and tested, convert the stable logic to C++.

Recommended stack:

- Language: C++
- UI: Qt
- Database: SQLite or PostgreSQL/MySQL
- Reports: Qt PDF/print system
- API client: Qt Network

Why C++ later:

- Better performance
- Strong desktop application feel
- Better hardware integration
- Easier to package as professional Windows software

Important note:

Do not convert to C++ too early. First complete and test the Python version. The Python version will become the blueprint for the C++ version.

## Stage 3: Web Version

After the desktop system is stable, build the web version.

Recommended stack options:

Option A:

- Backend: FastAPI
- Frontend: React, Next.js, or Vue
- Database: PostgreSQL or MySQL

Option B:

- Backend: Django
- Frontend: Django templates or React
- Database: PostgreSQL or MySQL

Best modern choice:

- FastAPI + PostgreSQL + React or Next.js

Why web later:

- Access from multiple devices
- Can support branches
- Can support mobile app later
- Can support cloud backup
- Can support online reports

## 3. High Level Architecture

The system should be separated into layers.

```text
User Interface Layer
        |
Application / Service Layer
        |
Business Logic Layer
        |
Data Access Layer
        |
Database
```

## 4. Layer Explanation

## User Interface Layer

This is what the user sees.

Examples:

- Login screen
- Dashboard
- POS billing screen
- Product form
- Purchase form
- Reports screen
- Settings screen

In Python:

- Tkinter and CustomTkinter windows, dialogs, frames, tabs, buttons, forms, and tables

In C++:

- Qt windows, dialogs, tables, buttons, forms

In Web:

- React or HTML pages

## Application / Service Layer

This layer controls application actions.

Examples:

- Create sale
- Add product
- Add purchase
- Transfer stock
- Generate report
- Login user

This layer receives input from the UI and calls the business logic.

## Business Logic Layer

This is the most important layer. It contains the rules of the business.

Examples:

- When sale is completed, reduce stock
- When purchase is added, increase stock
- When sale return is added, increase stock
- Do not sell more than available stock
- Calculate tax
- Calculate discount
- Calculate profit
- Calculate due payment
- Check low stock
- Check product expiry

This layer should be written cleanly because it will later be converted to C++ and web API logic.

## Data Access Layer

This layer talks to the database.

Examples:

- Save product
- Get product by barcode
- Save sale
- Get stock balance
- Save customer
- Read reports

In Python:

- SQLAlchemy or sqlite3

In C++:

- Qt SQL

In Web:

- SQLAlchemy, Django ORM, Prisma, or Laravel Eloquent depending on backend

## Database Layer

This stores all data permanently.

First version:

- SQLite

Later version:

- PostgreSQL or MySQL

## 5. Recommended Python Project Folder Structure

```text
pos_inventory_system/
    app.py
    config.py
    requirements.txt
    README.md

    database/
        schema.sql
        migrations/
        seed_data.sql

    models/
        product.py
        customer.py
        supplier.py
        sale.py
        sale_item.py
        purchase.py
        purchase_item.py
        stock.py
        expense.py
        user.py
        payment.py

    services/
        auth_service.py
        product_service.py
        pos_service.py
        purchase_service.py
        stock_service.py
        customer_service.py
        supplier_service.py
        expense_service.py
        report_service.py

    repositories/
        product_repository.py
        sale_repository.py
        purchase_repository.py
        stock_repository.py
        customer_repository.py
        supplier_repository.py
        user_repository.py

    ui/
        login_window.py
        dashboard_window.py
        pos_window.py
        product_window.py
        purchase_window.py
        stock_window.py
        customer_window.py
        supplier_window.py
        expense_window.py
        report_window.py
        settings_window.py

    reports/
        invoice_report.py
        sales_report.py
        stock_report.py
        purchase_report.py

    printers/
        receipt_printer.py
        barcode_printer.py

    utils/
        barcode.py
        currency.py
        date_time.py
        validators.py
```

## 6. Database Architecture

Recommended main tables:

- users
- roles
- permissions
- business_settings
- locations
- products
- product_categories
- product_brands
- product_units
- product_variations
- customers
- suppliers
- purchases
- purchase_items
- sales
- sale_items
- stock_movements
- stock_adjustments
- stock_transfers
- expenses
- expense_categories
- payments
- payment_accounts
- tax_rates
- invoices
- cash_registers
- activity_logs

## 7. Core Database Table Purpose

## products

Stores product information.

Common fields:

- id
- name
- sku
- barcode
- category_id
- brand_id
- unit_id
- purchase_price
- selling_price
- tax_rate_id
- alert_quantity
- image
- is_active

## customers

Stores customer information.

Common fields:

- id
- name
- phone
- email
- address
- opening_balance
- credit_limit

## suppliers

Stores supplier information.

Common fields:

- id
- name
- phone
- email
- address
- opening_balance

## purchases

Stores purchase invoice header.

Common fields:

- id
- supplier_id
- location_id
- invoice_no
- purchase_date
- subtotal
- discount
- tax
- total
- paid_amount
- due_amount
- payment_status

## purchase_items

Stores products inside a purchase.

Common fields:

- id
- purchase_id
- product_id
- quantity
- purchase_price
- tax
- discount
- line_total

## sales

Stores sale invoice header.

Common fields:

- id
- customer_id
- location_id
- invoice_no
- sale_date
- subtotal
- discount
- tax
- total
- paid_amount
- due_amount
- payment_status
- sale_status

## sale_items

Stores products inside a sale.

Common fields:

- id
- sale_id
- product_id
- quantity
- unit_price
- discount
- tax
- line_total

## stock_movements

Stores every stock change.

Common fields:

- id
- product_id
- location_id
- movement_type
- reference_type
- reference_id
- quantity_in
- quantity_out
- created_at

Movement examples:

- purchase
- sale
- sale_return
- purchase_return
- stock_adjustment
- stock_transfer_in
- stock_transfer_out
- opening_stock

## payments

Stores all payment transactions.

Common fields:

- id
- payment_type
- reference_type
- reference_id
- account_id
- amount
- method
- payment_date
- note

## 8. How Stock Works

Stock should not be stored only as one number. The best method is to save stock movement history.

When purchase is added:

```text
stock_movements.quantity_in = purchased quantity
```

When sale is completed:

```text
stock_movements.quantity_out = sold quantity
```

Available stock calculation:

```text
available_stock = total_quantity_in - total_quantity_out
```

Example:

```text
Opening stock: 100 in
Purchase: 50 in
Sale: 20 out
Sale return: 2 in
Damaged adjustment: 5 out

Available stock = 100 + 50 + 2 - 20 - 5
Available stock = 127
```

## 9. How Sale Works

Sale process:

1. Cashier opens POS screen
2. Cashier scans barcode or searches product
3. System checks available stock
4. Product is added to cart
5. System calculates subtotal
6. System applies discount
7. System applies tax
8. Customer selects payment method
9. System saves sale
10. System saves sale items
11. System saves payment
12. System creates stock movement
13. System prints invoice or receipt

Sale business rules:

- Cannot sell inactive product
- Cannot sell more than available stock unless negative stock is allowed
- Sale total must match item totals
- Paid amount cannot be negative
- Due amount equals total minus paid amount
- Stock must reduce only after final sale
- Draft sale should not reduce stock
- Suspended sale should not reduce stock

## 10. How Purchase Works

Purchase process:

1. User selects supplier
2. User selects purchase date
3. User adds products
4. User enters quantity and purchase price
5. System calculates total
6. User enters payment amount
7. System saves purchase
8. System saves purchase items
9. System saves supplier payment
10. System creates stock movement

Purchase business rules:

- Purchase increases stock
- Purchase return decreases stock
- Purchase can be paid, partial, or due
- Supplier balance should update

## 11. API Meaning

API means Application Programming Interface.

In simple words, API is a way for one part of the system to talk to another part.

Example:

- Web frontend asks backend: "Give me product list"
- Backend returns product data
- POS screen sends sale data to backend
- Backend saves sale and reduces stock

In desktop Python version, you may not need a web API at first. But you should still design internal service methods like an API.

Example internal Python service call:

```python
pos_service.create_sale(sale_data)
```

Later in web version, this becomes an HTTP API:

```http
POST /api/sales
```

## 12. API Architecture for Web Version

Recommended API type:

- REST API first
- Later GraphQL only if needed

Recommended backend:

- FastAPI

Recommended database:

- PostgreSQL

Recommended authentication:

- JWT token authentication

API flow:

```text
React Web App / Mobile App
        |
        | HTTP request
        v
FastAPI Backend
        |
        | Business services
        v
Database
```

## 13. Common API Endpoints

## Authentication API

```http
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/change-password
```

## Dashboard API

```http
GET /api/dashboard/summary
GET /api/dashboard/sales-chart
GET /api/dashboard/top-products
GET /api/dashboard/stock-alerts
```

## Product API

```http
GET    /api/products
POST   /api/products
GET    /api/products/{id}
PUT    /api/products/{id}
DELETE /api/products/{id}
GET    /api/products/barcode/{barcode}
POST   /api/products/import
GET    /api/products/export
```

## Category API

```http
GET    /api/categories
POST   /api/categories
PUT    /api/categories/{id}
DELETE /api/categories/{id}
```

## Customer API

```http
GET    /api/customers
POST   /api/customers
GET    /api/customers/{id}
PUT    /api/customers/{id}
DELETE /api/customers/{id}
GET    /api/customers/{id}/ledger
```

## Supplier API

```http
GET    /api/suppliers
POST   /api/suppliers
GET    /api/suppliers/{id}
PUT    /api/suppliers/{id}
DELETE /api/suppliers/{id}
GET    /api/suppliers/{id}/ledger
```

## Purchase API

```http
GET    /api/purchases
POST   /api/purchases
GET    /api/purchases/{id}
PUT    /api/purchases/{id}
DELETE /api/purchases/{id}
POST   /api/purchases/{id}/payment
POST   /api/purchases/{id}/return
```

## Sales API

```http
GET    /api/sales
POST   /api/sales
GET    /api/sales/{id}
PUT    /api/sales/{id}
DELETE /api/sales/{id}
POST   /api/sales/{id}/payment
POST   /api/sales/{id}/return
GET    /api/sales/{id}/invoice
```

## POS API

```http
GET  /api/pos/products/search
GET  /api/pos/products/barcode/{barcode}
POST /api/pos/checkout
POST /api/pos/draft
POST /api/pos/suspend
GET  /api/pos/recent-transactions
```

## Stock API

```http
GET  /api/stock
GET  /api/stock/product/{product_id}
GET  /api/stock/history/{product_id}
POST /api/stock/adjustment
POST /api/stock/transfer
GET  /api/stock/low-stock
GET  /api/stock/expiry-alerts
```

## Expense API

```http
GET    /api/expenses
POST   /api/expenses
GET    /api/expenses/{id}
PUT    /api/expenses/{id}
DELETE /api/expenses/{id}
GET    /api/expense-categories
POST   /api/expense-categories
```

## Report API

```http
GET /api/reports/sales
GET /api/reports/purchases
GET /api/reports/profit-loss
GET /api/reports/stock
GET /api/reports/tax
GET /api/reports/expenses
GET /api/reports/customer-ledger/{customer_id}
GET /api/reports/supplier-ledger/{supplier_id}
```

## Settings API

```http
GET /api/settings/business
PUT /api/settings/business
GET /api/settings/invoice
PUT /api/settings/invoice
GET /api/settings/tax
PUT /api/settings/tax
```

## 14. Example API Request and Response

Create sale request:

```http
POST /api/sales
Content-Type: application/json
Authorization: Bearer JWT_TOKEN
```

Request body:

```json
{
  "customer_id": 1,
  "location_id": 1,
  "sale_date": "2026-06-24",
  "items": [
    {
      "product_id": 10,
      "quantity": 2,
      "unit_price": 1500.00,
      "discount": 0,
      "tax": 0
    }
  ],
  "payment": {
    "method": "cash",
    "amount": 3000.00
  }
}
```

Response:

```json
{
  "success": true,
  "message": "Sale completed successfully",
  "data": {
    "sale_id": 125,
    "invoice_no": "INV-000125",
    "total": 3000.00,
    "paid_amount": 3000.00,
    "due_amount": 0.00
  }
}
```

## 15. How API Works Internally

When the frontend sends `POST /api/sales`, the backend should do this:

1. Validate user token
2. Check user permission
3. Validate sale data
4. Check product availability
5. Calculate subtotal, tax, discount, and total
6. Save sale record
7. Save sale item records
8. Save payment record
9. Create stock movement records
10. Commit database transaction
11. Return invoice number and sale total

Important:

All sale operations should happen inside one database transaction. If one step fails, the system should cancel all changes.

## 16. Database Transaction Example

For sale checkout:

```text
BEGIN TRANSACTION
    save sale
    save sale items
    save payment
    reduce stock using stock movement
COMMIT
```

If there is an error:

```text
ROLLBACK
```

This protects stock and accounting data.

## 17. Authentication and Permissions

Recommended login method for web:

- User logs in with username and password
- Backend checks password
- Backend returns JWT token
- Frontend stores token
- Frontend sends token with every API request

Permission examples:

- Admin can access everything
- Cashier can access POS only
- Stock manager can access products and stock
- Accountant can access payments and reports
- Manager can access sales, purchases, and reports

## 18. Offline and Online Plan

For first Python desktop version:

- Local database using SQLite
- Works without internet
- Best for one shop

For later web version:

- Central database using PostgreSQL or MySQL
- Multiple devices can connect
- Best for branches and cloud access

Possible hybrid version:

- Desktop POS works offline
- Data syncs to cloud when internet is available

Hybrid sync is advanced. Build it only after the normal version is complete.

## 19. Hardware Integration

Barcode scanner:

- Most barcode scanners work like a keyboard
- When barcode is scanned, it types the barcode number and presses Enter
- POS screen searches product by barcode

Thermal receipt printer:

- Can print through Windows printer driver
- Or can use ESC/POS commands

Cash drawer:

- Usually connected to receipt printer
- Drawer opens when printer sends open-drawer command

Barcode label printer:

- Prints product barcode labels
- Can use normal printer driver or label printer SDK

Weighing scale:

- Usually uses serial port or USB
- System reads weight and calculates product price

## 20. Reporting Plan

Reports should be generated from database queries.

Important reports:

- Daily sales report
- Monthly sales report
- Product-wise sales report
- Customer-wise sales report
- Purchase report
- Stock report
- Low stock report
- Profit and loss report
- Expense report
- Tax report

Export formats:

- PDF
- Excel
- CSV

## 21. Recommended Build Order

Build the project in this order:

1. Database design
2. Login system
3. Product management
4. Customer management
5. Supplier management
6. Purchase management
7. Stock movement system
8. POS billing screen
9. Sales management
10. Payments
11. Expenses
12. Reports
13. Settings
14. Receipt printing
15. Backup and restore
16. User roles and permissions
17. Advanced modules

## 22. Important Development Rules

- Keep business logic separate from UI
- Keep database code separate from business logic
- Use stock movements instead of only one stock number
- Use database transactions for sales and purchases
- Never delete important financial records permanently
- Use soft delete where possible
- Keep audit logs for important actions
- Backup database regularly
- Validate all user input
- Use roles and permissions from the beginning

## 23. Best Final Architecture Direction

The best long-term architecture is:

```text
Shared Business Rules
        |
Desktop App First
        |
Web API Later
        |
Web Dashboard and Mobile App Later
```

In simple words:

1. Build and test the logic in Python.
2. Convert the stable desktop version to C++ if needed.
3. Build the web backend API using the same business rules.
4. Build web frontend and mobile app using the API.

## 24. Final Recommendation

Start with a small but clean Python version:

- SQLite database
- Products
- Customers
- Suppliers
- Purchases
- Stock movements
- POS sales
- Expenses
- Reports
- Users

After this works correctly, move to:

- C++ Qt desktop application
- PostgreSQL/MySQL database
- FastAPI backend
- React or Next.js web frontend

This path will reduce mistakes and make the project easier to complete step by step.
