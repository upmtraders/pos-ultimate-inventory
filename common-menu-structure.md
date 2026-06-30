# POS Ultimate Inventory System - Common Menu Structure

This document contains the common menu structure for a POS and inventory management system. It can be used as the base menu plan for the first Python version, then later reused for C++ desktop and web versions.

## 1. Dashboard

The dashboard is the first screen after login. It gives a quick summary of the business.

Common dashboard items:

- Today sales
- Today purchases
- Today expenses
- Total profit
- Low stock alerts
- Product expiry alerts
- Payment due alerts
- Recent sales
- Recent purchases
- Top selling products
- Sales chart
- Purchase chart
- Stock value summary

## 2. POS / Billing

The POS menu is used by the cashier to create sales quickly.

Sub menus:

- POS Screen
- Add Sale
- List Sales
- Draft Sales
- Suspended Sales
- Quotations
- Sales Orders
- Sales Return
- Recent Transactions
- Cash Register
- Customer Display Screen

Main functions:

- Search product by name, SKU, or barcode
- Scan barcode
- Add customer
- Add new customer from POS screen
- Add product quantity
- Apply discount
- Apply tax
- Select payment method
- Complete sale
- Print receipt
- Save sale as draft
- Suspend sale
- Return items
- Track cashier session

## 3. Products

The products menu is used to manage all items sold by the business.

Sub menus:

- List Products
- Add Product
- Edit Product
- Delete Product
- Bulk Delete Products
- Import Products
- Export Products
- Bulk Edit Products
- Bulk Price Update
- Product Categories
- Product Subcategories
- Brands
- Units
- Variations
- Variation Templates
- Product Warranty
- Product Labels
- Print Barcode Labels
- Opening Stock
- Product Stock History
- Product Stock Alert
- Product Expiry
- Lot Number
- Rack, Row, and Position

Main functions:

- Add single product
- Add variable product
- Generate SKU automatically
- Add barcode
- Add purchase price
- Add selling price
- Set profit margin
- Add tax
- Add product image
- Add product unit
- Add product category
- Add product brand
- Track product stock
- Track stock by location

## 4. Purchases

The purchases menu is used to manage stock coming from suppliers.

Sub menus:

- List Purchases
- Add Purchase
- Purchase Order
- Purchase Requisition
- Purchase Payments
- Purchase Invoice
- Purchase Return
- Supplier Due Payments
- Bonus / Free Supplier Items

Main functions:

- Add supplier purchase
- Add product quantity to stock
- Add purchase discount
- Add purchase tax
- Add transport or extra cost
- Mark purchase as paid, partial, or due
- Print purchase invoice
- Track supplier payment due date

## 5. Stock Management

The stock menu is used to control stock movement.

Sub menus:

- Stock Transfer
- Stock Adjustment
- Stock Report
- Stock History
- Opening Stock
- Physical Stock Count
- Low Stock Report
- Expired Product Report

Main functions:

- Transfer stock between locations
- Adjust damaged stock
- Adjust missing stock
- Add opening stock
- View stock balance
- View stock movement history
- Track available quantity
- Track sold quantity
- Track returned quantity

## 6. Contacts

The contacts menu is used to manage customers and suppliers.

Sub menus:

- Customers
- Suppliers
- Customer Groups
- Supplier Ledger
- Customer Ledger
- Opening Balance
- Contact Payments
- Loyalty Cards
- Import Contacts

Main functions:

- Add customer
- Add supplier
- Mark contact as customer, supplier, or both
- View contact balance
- View contact transaction history
- Add opening balance
- Add payment
- Manage credit sales
- Manage supplier due payments

## 7. Expenses

The expenses menu is used to record business expenses.

Sub menus:

- List Expenses
- Add Expense
- Expense Categories
- Expense Refund
- Expense Report

Main functions:

- Add rent, salary, transport, electricity, internet, or other expenses
- Assign expense to location
- Assign expense to user, customer, or supplier
- Categorize expenses
- Track expense refunds
- View expense reports

## 8. Payment Accounts

The payment accounts menu is used to manage business cash, bank, and other payment accounts.

Sub menus:

- List Accounts
- Add Account
- Account Transactions
- Deposit
- Withdraw
- Transfer
- Balance Sheet

Main functions:

- Manage cash account
- Manage bank account
- Manage card payment account
- Manage online payment account
- Track deposits
- Track withdrawals
- Track payment transfers

## 9. Reports

The reports menu is used for business analysis.

Sub menus:

- Profit and Loss Report
- Sales Report
- Purchase Report
- Purchase and Sale Report
- Stock Report
- Stock Adjustment Report
- Stock Transfer Report
- Product Stock History
- Product Expiry Report
- Low Stock Report
- Tax Report
- Expense Report
- Customer Report
- Supplier Report
- Customer Ledger
- Supplier Ledger
- Cash Register Report
- Sales Representative Report
- Trending Products
- Payment Report
- Due Payment Report

Main functions:

- View sales by date range
- View purchases by date range
- View profit
- View losses
- View inventory value
- View stock movement
- View due payments
- View tax summary
- View cashier performance

## 10. User Management

The user management menu controls access to the system.

Sub menus:

- Users
- Add User
- Edit User
- Roles
- Permissions
- Assign Location
- Commission Agents
- User Activity Log

Common roles:

- Admin
- Manager
- Cashier
- Accountant
- Stock Manager
- Purchase Manager
- Sales Representative

Main functions:

- Create users
- Assign roles
- Assign permissions
- Assign business location
- Restrict menu access
- Track user activity

## 11. Business Management

The business menu is used to configure company information.

Sub menus:

- Business Details
- Business Locations
- Warehouses
- Storefronts
- Financial Year
- Currency
- Timezone
- Default Profit Margin
- Business Registration

Main functions:

- Add company name
- Add address
- Add phone number
- Add tax number
- Add logo
- Add multiple branches
- Add multiple warehouses
- Configure financial year

## 12. Tax Settings

The tax menu is used to manage tax rules.

Sub menus:

- Tax Rates
- Tax Groups
- Invoice Tax
- Inline Tax
- Disable Tax
- GST / VAT Settings

Main functions:

- Add tax rate
- Add tax group
- Apply tax to product
- Apply tax to sale
- Apply tax to purchase
- View tax report

## 13. Invoice and Receipt Settings

This menu controls printed invoices, receipts, and bill formats.

Sub menus:

- Invoice Layout
- Invoice Scheme
- Receipt Settings
- Thermal Printer Settings
- Barcode Settings
- QR Code Settings
- Gift Receipt
- Proforma Invoice

Main functions:

- Customize invoice number
- Customize receipt layout
- Add logo to invoice
- Add QR code
- Add barcode
- Add terms and conditions
- Print A4 invoice
- Print thermal receipt

## 14. Hardware Support

This menu is used to configure POS hardware.

Sub menus:

- Barcode Scanner
- Barcode Printer
- Thermal Printer
- Cash Drawer
- Weighing Scale
- Customer Display

Main functions:

- Scan barcode
- Print barcode labels
- Print receipts
- Open cash drawer
- Read weighing scale values
- Show sale total to customer display

## 15. Notifications

The notifications menu is used to send system alerts.

Sub menus:

- Email Settings
- SMS Settings
- Desktop Notifications
- Internal Notifications
- Payment Due Alerts
- Stock Alerts
- Expiry Alerts

Main functions:

- Send low stock alert
- Send due payment alert
- Send sale notification
- Send purchase notification
- Send customer invoice email

## 16. Settings

The settings menu controls global system behavior.

Sub menus:

- General Settings
- Business Settings
- Product Settings
- Sale Settings
- Purchase Settings
- Payment Settings
- Language Settings
- Theme Settings
- Backup Settings
- System Logs

Main functions:

- Set default language
- Set date format
- Set currency format
- Set decimal precision
- Set default payment method
- Enable or disable modules
- Change theme color
- Backup database

## 17. Addons / Modules

Addons are optional modules that can be added later.

Common addon modules:

- Restaurant Module
- Kitchen Order Module
- Table Management Module
- Booking Module
- WooCommerce Module
- Accounting Module
- CRM Module
- HRM Module
- Payroll Module
- Manufacturing Module
- Repair Module
- Hotel Management Module
- Gym Management Module
- API Connector Module
- SaaS / Super Admin Module
- Mobile App Module

## 18. Backup and Maintenance

This menu is used to protect and maintain business data.

Sub menus:

- Database Backup
- Restore Backup
- Export Data
- Import Data
- Clear Cache
- System Health
- Error Logs

Main functions:

- Backup database
- Restore database
- Export reports
- Import old data
- Check system errors
- Maintain performance

## Recommended First Version Menu

For the first Python version, start with a smaller menu:

1. Dashboard
2. POS / Billing
3. Products
4. Purchases
5. Stock Management
6. Customers
7. Suppliers
8. Expenses
9. Reports
10. Users
11. Settings

After this first version is stable, add advanced menus like payment accounts, restaurant module, API connector, and web dashboard.
