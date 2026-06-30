# User Management - How to Connect the Users Screen

This guide explains how to connect the **User Management > Users** screen to the SQLite database, service layer, permissions, audit log, and export/print features.

Current screen status:

```text
Module        User Management
Screen        Users
Database      SQLite service layer pending
Permissions   Role-based access pending
Audit Log     Pending
Export/Print  Pending where applicable
```

## 1. Current Project Files

The project already has these useful files:

```text
pos_inventory_system/
    database/
        connection.py
        schema.sql
    services/
        auth_service.py
    ui/
        dashboard_window.py
        login_window.py
        menu_structure.py
```

The `Users` screen is currently only a placeholder inside:

```text
pos_inventory_system/ui/dashboard_window.py
```

The placeholder is created by this method:

```text
_build_placeholder_panel()
```

To connect the real Users screen, replace the placeholder for `User Management > Users` with a real UI screen.

## 2. Existing Database Tables

The database already has these related tables in:

```text
pos_inventory_system/database/schema.sql
```

Existing `roles` table:

```sql
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Existing `users` table:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles (id)
);
```

Existing `activity_logs` table:

```sql
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);
```

These tables are enough for the first Users screen.

## 3. Connection Architecture

Use this flow:

```text
Users Screen
    |
    v
UserService
    |
    v
UserRepository
    |
    v
SQLite Database
```

For permissions:

```text
Users Screen
    |
    v
PermissionService
    |
    v
Current Logged-In User Role
```

For audit log:

```text
UserService action
    |
    v
AuditService
    |
    v
activity_logs table
```

## 4. Files to Add

Add these files:

```text
pos_inventory_system/repositories/user_repository.py
pos_inventory_system/services/user_service.py
pos_inventory_system/services/permission_service.py
pos_inventory_system/services/audit_service.py
pos_inventory_system/ui/users_window.py
```

Optional later:

```text
pos_inventory_system/reports/user_export.py
```

## 5. User Repository

Purpose:

- Talk directly to SQLite
- Run SQL queries
- Return database rows
- Do not contain UI logic

File:

```text
pos_inventory_system/repositories/user_repository.py
```

Main methods:

```python
class UserRepository:
    def list_users(self):
        pass

    def get_user(self, user_id):
        pass

    def create_user(self, role_id, username, password_hash, full_name, is_active):
        pass

    def update_user(self, user_id, role_id, username, full_name, is_active):
        pass

    def update_password(self, user_id, password_hash):
        pass

    def deactivate_user(self, user_id):
        pass

    def list_roles(self):
        pass
```

Example query for listing users:

```sql
SELECT
    users.id,
    users.username,
    users.full_name,
    users.is_active,
    users.created_at,
    roles.name AS role_name
FROM users
JOIN roles ON roles.id = users.role_id
ORDER BY users.id DESC;
```

## 6. User Service

Purpose:

- Validate user input
- Hash passwords
- Call repository methods
- Call audit log
- Protect business rules

File:

```text
pos_inventory_system/services/user_service.py
```

Main methods:

```python
class UserService:
    def list_users(self):
        pass

    def create_user(self, current_user, role_id, username, password, full_name, is_active=True):
        pass

    def update_user(self, current_user, user_id, role_id, username, full_name, is_active=True):
        pass

    def reset_password(self, current_user, user_id, new_password):
        pass

    def deactivate_user(self, current_user, user_id):
        pass
```

Important validation rules:

- Username is required
- Username must be unique
- Full name is required
- Role is required
- Password is required when creating a new user
- Password should not be stored as plain text
- Admin user should not be accidentally disabled

Password hashing:

Use the existing password functions from:

```text
pos_inventory_system/services/auth_service.py
```

Existing methods:

```python
AuthService.hash_password(password)
AuthService.verify_password(password, stored_hash)
```

## 7. Permission Service

Purpose:

- Control who can open screens
- Control who can create, edit, delete, export, and print

File:

```text
pos_inventory_system/services/permission_service.py
```

For the first version, use simple role-based permissions.

Example permission map:

```python
ROLE_PERMISSIONS = {
    "Admin": {
        "users.view",
        "users.create",
        "users.update",
        "users.delete",
        "users.export",
        "users.print",
    },
    "Manager": {
        "users.view",
    },
    "Cashier": set(),
}
```

Example method:

```python
class PermissionService:
    def has_permission(self, user, permission_name):
        if user is None:
            return False
        permissions = ROLE_PERMISSIONS.get(user.role_name, set())
        return permission_name in permissions
```

How it connects:

- Before opening the Users screen, check `users.view`
- Before Add button action, check `users.create`
- Before Save/Edit action, check `users.update`
- Before Delete/Deactivate action, check `users.delete`
- Before export, check `users.export`
- Before print, check `users.print`

## 8. Audit Service

Purpose:

- Save important actions to `activity_logs`

File:

```text
pos_inventory_system/services/audit_service.py
```

Actions to log:

- User created
- User updated
- User password reset
- User deactivated
- User exported
- User list printed
- Failed permission attempt

Example methods:

```python
class AuditService:
    def log(self, user_id, action, details=""):
        pass
```

Example SQL:

```sql
INSERT INTO activity_logs (user_id, action, details)
VALUES (?, ?, ?);
```

Example log details:

```text
Created user cashier01
Updated user manager01
Reset password for user id 4
Deactivated user id 7
Exported users list
```

## 9. Users UI Screen

Purpose:

- Show all users in a table
- Add new user
- Edit selected user
- Reset password
- Deactivate user
- Export users
- Print users where needed

File:

```text
pos_inventory_system/ui/users_window.py
```

Recommended layout:

```text
Users Screen
    Header
        Title: Users
        Buttons: Add, Edit, Reset Password, Deactivate, Export, Print

    Filters
        Search by username or full name
        Filter by role
        Filter by status

    Table
        ID
        Username
        Full Name
        Role
        Status
        Created At

    Form/Dialog
        Full Name
        Username
        Password
        Role
        Active checkbox
        Save / Cancel
```

Recommended Tkinter widgets:

- `ttk.Frame`
- `ttk.Label`
- `ttk.Entry`
- `ttk.Combobox`
- `ttk.Button`
- `ttk.Treeview`
- `tk.Toplevel` for Add/Edit dialog
- `messagebox` for confirmation and errors

## 10. How Dashboard Opens Users Screen

Current method:

```text
DashboardWindow.show_page(section, item)
```

Current behavior:

- If item is `Dashboard`, it opens dashboard
- Otherwise, it opens placeholder panel

New behavior should be:

```python
if section == "User Management" and item == "Users":
    self._show_users_screen()
    return
```

Then `_show_users_screen()` should:

1. Check permission `users.view`
2. Create a `UsersScreen` frame
3. Pass the logged-in user into the screen
4. Load users from `UserService`

Example flow:

```text
DashboardWindow.show_page("User Management", "Users")
    |
    v
PermissionService checks users.view
    |
    v
UsersScreen loads
    |
    v
UserService.list_users()
    |
    v
UserRepository.list_users()
    |
    v
SQLite users table
```

## 11. Export and Print

For the first version, keep this simple.

Export options:

- CSV export
- Excel export later
- PDF export later

Recommended first export:

```text
CSV
```

Python modules:

- `csv`
- `tkinter.filedialog`

Export flow:

```text
Click Export
    |
    v
Check users.export permission
    |
    v
Ask save file path
    |
    v
Write Treeview/list data to CSV
    |
    v
Audit log: Exported users list
```

Print flow for later:

```text
Click Print
    |
    v
Check users.print permission
    |
    v
Generate PDF or text report
    |
    v
Send to printer
    |
    v
Audit log: Printed users list
```

Print can be added after products, sales, and invoices because user-list printing is not urgent.

## 12. Recommended Implementation Order

Build the Users screen in this order:

1. Add `user_repository.py`
2. Add `audit_service.py`
3. Add `permission_service.py`
4. Add `user_service.py`
5. Add `users_window.py`
6. Connect `DashboardWindow.show_page()` to the Users screen
7. Display users in table
8. Add create user dialog
9. Add edit user dialog
10. Add reset password action
11. Add deactivate action
12. Add CSV export
13. Add print later if needed

## 13. Minimum Working Version

For the first working Users screen, only build:

- View users
- Add user
- Edit user
- Deactivate user
- Reset password

Leave these for later:

- Advanced permissions table
- Full audit log viewer
- PDF print
- Excel export

## 14. Important Safety Rules

- Never store password as plain text
- Always hash password using `AuthService.hash_password`
- Do not allow deleting users permanently in the first version
- Use `is_active = 0` for deactivate
- Do not allow the current logged-in admin to deactivate himself
- Always log create, edit, deactivate, and password reset
- Always check permission before important actions
- Keep SQL inside repository files
- Keep validation inside service files
- Keep button and table code inside UI files

## 15. Simple Final Connection Summary

Use this connection map:

```text
dashboard_window.py
    opens
users_window.py
    calls
user_service.py
    validates and calls
user_repository.py
    reads/writes
schema.sql tables: users, roles
```

Permissions:

```text
users_window.py -> permission_service.py -> current user role
```

Audit log:

```text
user_service.py -> audit_service.py -> activity_logs table
```

Export:

```text
users_window.py -> CSV file
```

Print:

```text
users_window.py -> PDF/text report -> printer
```
