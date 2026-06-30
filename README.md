# POS Ultimate Inventory System

First Python desktop version for the POS and inventory system.

## Run

```powershell
python app.py
```

## Current Status

- Python project scaffold created.
- Dashboard window created with the full requested menu structure.
- SQLite database initialization added.
- Login screen added with a seeded admin user.
- Web app added with functional pages for products, contacts, purchases, sales, stock, expenses, payments, reports, settings, users, backups, and addons.
- Addon modules now persist activation, connection settings, completed work items, custom work items, and operational check logs in SQLite.

## Development Login

```text
Username: admin
Password: admin123
```

For a fresh production database, set these before first startup:

```powershell
$env:POS_DEFAULT_ADMIN_USERNAME="your-admin-user"
$env:POS_DEFAULT_ADMIN_PASSWORD="change-this-password"
$env:POS_API_KEY="long-random-api-key"
```

`POS_API_KEY` protects the FastAPI endpoints with the `X-POS-API-Key` request header when it is set. Keep it unset only for local development.

## Next Build Order

1. Finish pending production workflow gaps module by module
2. Add restore and scheduled backup operations with confirmation controls
3. Add automated tests for repository and web form workflows
4. Run full QA across POS, purchases, stock, cash register, users, permissions, reports, and addons
