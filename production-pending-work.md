# Production Pending Work

This checklist is for completing the build before full QA starts.

## Foundation

- [x] Add real Python dependency list.
- [x] Add optional API key protection for FastAPI.
- [x] Remove visible/default password autofill from login screens.
- [x] Show backup integrity status and manual verify action.
- [x] Add confirmed restore flow for verified backup files.
- [x] Add scheduled backup setting and retention rules.
- [x] Add CSRF protection for web POST forms.
- [x] Add session timeout and logout-on-password-change behavior.

## Core Workflow

- [x] POS cart can save final sale, draft, quotation, and suspended sale from the same counter screen.
- [x] Final POS sale writes payment and stock movement; draft/quotation/suspended documents do not reduce stock.
- [x] Credit/due POS sale requires a selected customer.
- [x] POS multiple-pay split collection UI and separate payment rows.
- [x] POS reopen and convert draft, quotation, and suspended sale back into final sale.
- [x] Purchase: cash, cheque, due, pending cheque close, product quick-add.
- [x] Stock: adjustment, transfer, movement history, low-stock workflow.
- [x] Returns: sale return and purchase return with stock/payment effects.
- [x] Cash register: open, cash in/out, denomination close, approval.

## Business Setup

- [x] Business, locations, tax, payment methods, barcode, printer setup review.
- [x] Users, roles, and permissions real cashier/manager/admin testing.
- [x] Product setup: categories, brands, units, warranties, variations, price groups.

## Reports

- [x] Daily, weekly, monthly sales history.
- [x] Purchase history with supplier, product, qty, payments, cheque status.
- [x] Stock report and product movement ledger.
- [x] Profit/loss, tax, due payments, cash register, customer/supplier ledger.

## Add-ons

- [ ] WooCommerce sandbox sync test.
- [ ] HRM attendance, leave, payroll workflow test.
- [ ] CRM lead, follow-up, quotation handoff test.
- [ ] Decide whether Manufacturing, Accounting, Restaurant, SaaS, API Connector are production modules or optional planning modules.

## QA Gate

- [ ] Add automated repository tests.
- [ ] Add web smoke tests for every menu page.
- [ ] Add end-to-end business scenario test data.
- [ ] Run full QA after pending build work is complete.
