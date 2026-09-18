### Pos Expenses

Easily log expenses without needing to leave the point of sale page. For fast easy recording.

### Features

- **Add Expense button** on the Point of Sale page — opens a modal to log an expense instantly
- **POS Expense Account DocType** — configures which accounts are available per POS Profile and company
- **Profile-aware account selection** — system-wide defaults overridden by profile-specific records
- **Reprint Invoices** — select previously submitted invoices and reprint full or selected items
- **Refund Invoices** — process returns with quantity selection, partial or full returns supported
- **POS Closing Entry** — on-submit automatically returns to the POS page

### Screenshots

Screenshots coming soon — see docs/USER_GUIDE.md for the walkthrough.

### Installation

#### (A) Using the bench CLI

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Stelele/erpnext-point-of-sale-expenses.git --branch version-16
bench --site <site> install-app pos_expenses
```

#### (B) Frappe Cloud

1. Add the app from GitHub: `https://github.com/Stelele/erpnext-point-of-sale-expenses`
2. In Site Settings → Apps tab, click **Install App** for **Pos Expenses**
3. After installation, reload the Point of Sale page to see the new action buttons

### Setup

1. **Create POS Expense Accounts** → Setup → Pos Expense Accounts
   - Fill in: Company, Account (Link to Account), Friendly Name, and optionally POS Profile
   - Enable records that should be available to cashiers
   - System-wide defaults (blank POS Profile) apply to all profiles; profile-specific records override them

2. **Ensure erpnext is installed** — this app requires the erpnext app

3. **Reload apps** and open any Point of Sale page to see the new buttons

### Usage Walkthrough (Cashier Flow)

1. **Open the Point of Sale page** in ERPNext
2. Click the **Add Expense** button that appears in the inner toolbar
3. **Fill in the expense modal**:
   - **Date** — defaults to today; select the expense date
   - **Expense Account** — select from the filtered list (shows accounts for your POS Profile or system-wide defaults)
   - **Amount** — the expense amount (the expense account currency must match the POS cash account currency)
   - **Remarks** — required note description
4. Click **Submit Expense**
5. A green alert confirms "Expense successfully posted!" and the modal closes
6. The expense is recorded as a Journal Entry behind the scenes

**Reprint Invoices**:
1. On the POS page, click **Reprint Invoices**
2. Select a date range or search by customer name
3. Click an invoice row to view details
4. Check individual items to print, or click **Print Full Invoice**
5. A new tab opens with the print-ready receipt

**Refund Invoices**:
1. On the POS page, click **Refund**
2. Select a date range or search by customer name
3. Click an invoice row to view returnable items
4. Check items and enter quantities (max = returnable qty)
5. Click **Return Everything** or **Return Selected Items**
6. Confirm the return action — a return invoice is created successfully

**POS Closing Entry**:
- After closing the till, open the **POS Closing Entry** form
- Click **Submit**
- Automatically routes back to the Point of Sale page

### Configuration Reference

| Setting | Description |
|---|---|
| **POS Expense Account** | Configures account mappings per company and POS Profile |
| **pos_profile** | Blank = system-wide default; set to a specific Profile for profile-specific override |
| **enabled** | Check to make the account available to cashiers on the POS |
| **Friendly Name** | Display name shown in the expense account selector |
| **Company** | Required — limits the account to a specific company |

**Unique mapping rule**: A blank `pos_profile` is stored/compared as "not set", so a blank mapping collides only with other blank mappings for the same company + account. If `pos_profile` is set, the combination of company + account + pos_profile must be unique. A profile-specific mapping can coexist with a blank (system-wide) mapping for the same company + account — that coexistence is the intended override.

### Troubleshooting / FAQ

| Issue | Resolution |
|---|---|
| "POS Expense Account 'X' not found" | Ensure a POS Expense Account record exists for your company and the selected account |
| Account not appearing in the expense modal | Check that the record is **Enabled** and that the POS Profile / company match |
| "Could not find a default Cash account for this company" | Set up a Cash account in your company's chart of accounts |
| Expense posted but Journal Entry not visible | Journal Entries are auto-submitted; check the Accounts module for the entry |
| Reprint Invoices shows "No invoices found" | Ensure invoices have been submitted (docstatus = 1) and fall within the selected date range |
| Refund button disabled for an invoice | Only submitted invoices with returnable items appear; check the invoice status and returnable quantities |

### Contributing

1. Install `pre-commit` hooks: `cd apps/pos_expenses && pre-commit install`
2. Code is checked with `ruff`, `eslint`, and `prettier`
3. Add tests under `pos_expenses/tests/` if adding new functionality
4. Follow the existing code style (tab-indented Python, semicolon-terminated JS)
5. Run `bench --site <site> execute "pos_expenses.api.post_expense(...)"` to manually verify new API methods

   Note: in the example above, `expense_account='Gas - Main Store'` is the **name of a POS Expense Account mapping record**, not a raw Account name — `api.py` resolves it via `frappe.db.get_value("POS Expense Account", expense_account, "account")` (api.py line 15).

### License

MIT (see license.txt).

Held by Gift Mugweni (per `app_publisher` in `pos_expenses/hooks.py`); license.txt still carries an unfilled `Copyright (c) [year] [fullname]` placeholder.