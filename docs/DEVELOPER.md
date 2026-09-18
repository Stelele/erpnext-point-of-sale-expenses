# Pos Expenses — Developer Guide

*Architecture, API signatures, DocType schema, local dev setup, and testing notes.*

## Architecture Overview

The app extends the Point of Sale page through three layers:

1. **Python hooks** (`hooks.py`) — registers whitelisted API overrides and DocType JS mappings.
2. **Python overrides** (`overrides/point_of_sale.py`) — customizes `get_parent_item_group` to use POS Profile item groups instead of the upstream arbitrary selection.
3. **JavaScript extension** (`public/js/pos_extension.js`) — injects buttons (Add Expense, Reprint Invoices, Refund, New Invoice, Close POS) and modals into the POS page controller.

The JS extension monkey-patches `frappe.require` to replace the `PointOfSale.Controller` class at runtime, adding the new UI behavior while preserving the original `on_page_load`.

### Key Hooks (hooks.py)

| Hook | Target | Replacement |
|---|---|---|
| `override_whitelisted_methods` | `erpnext.selling.page.point_of_sale.point_of_sale.get_parent_item_group` | `pos_expenses.overrides.point_of_sale.get_parent_item_group` |
| `doctype_js` | `"POS Closing Entry"` | `"public/js/pos_closing_entry.js"` |
| `page_js` | `"point-of-sale"` | `"public/js/pos_extension.js"` |

### Whitelisted API Methods (`api.py`)

All methods are decorated with `@frappe.whitelist()` and exposed as `@frappe.whitelist(allow_guest=False)` where noted. They map to HTTP endpoints under `/api/method/pos_expenses.api.<method_name>`.

| Method | Signature (Python) | HTTP Method | Description |
|---|---|---|---|
| `post_expense` | `post_expense(posting_date=None, expense_account=None, amount=0, remarks=None)` | POST | Creates and submits a Journal Entry for the expense. Requires permission on "Journal Entry". Validates that the expense account currency matches the POS cash account currency. |
| `indirect_expense_account_query` | `indirect_expense_account_query(doctype, txt, searchfield, start, page_len, filters)` | POST (search) | Returns leaf accounts under the "Indirect Expenses" group for a given company. Used as the set_query filter for the Account Link field on the POS Expense Account setup form (pos_expense_account.js lines 3-9). The cashier expense modal uses `pos_expense_account_query` instead (pos_extension.js lines 68-74). |
| `pos_expense_account_query` | `pos_expense_account_query(doctype, txt, searchfield, start, page_len, filters)` | POST (search) | Returns POS Expense Accounts with profile-aware logic: profile-specific records override system-wide defaults (pos_profile IS NULL). Disabled records are excluded. |
| `get_pos_invoices_for_reprint` | `get_pos_invoices_for_reprint(date=None, from_time=None, to_time=None, status=None, search_term=None, limit=50)` | POST (search) | Returns submitted POS Invoices for reprinting. Supports date, time range, status filter, and search by name or customer. |
| `get_invoice_detail_for_reprint` | `get_invoice_detail_for_reprint(invoice_name)` | POST | Returns full invoice detail (customer, items, taxes, payments) for the reprint modal. |
| `get_pos_invoices_for_refund` | `get_pos_invoices_for_refund(date=None, from_time=None, to_time=None, status=None, search_term=None, limit=50)` | POST (search) | Returns returnable POS Invoices (excludes already-returned, drafts). Uses `is_invoice_returnable` from erpnext. |
| `get_invoice_detail_for_refund` | `get_invoice_detail_for_refund(invoice_name)` | POST | Returns invoice detail for refund modal, including returnable quantities per item. |
| `process_pos_refund` | `process_pos_refund(invoice_name, return_items)` | POST | Processes a refund/return. Parses `return_items` JSON, validates quantities, and creates a return invoice via `make_return_doc`. Supports partial and full returns. |
| `get_partial_print_url` | `get_partial_print_url(invoice_name, selected_items)` | POST | Generates a cached HTML print preview URL for selected invoice items. Key is MD5-hashed and expires in 600 seconds. |
| `show_partial_print` | `show_partial_print(key)` | GET | Returns the cached HTML print preview as a downloadable page with `window.print()` on load. `allow_guest=False`. |

**Endpoint base URL**: `/api/method/pos_expenses.api.<method_name>`

### DocType Schema — POS Expense Account

From `pos_expense_account.json`:

| Field | Type | Options | Required | Notes |
|---|---|---|---|---|
| **company** | Link | Company | Yes | Limits account to a specific company |
| **account** | Link | Account | Yes | The general ledger account for the expense |
| **friendly_name** | Data | — | Yes | Display name shown in selectors |
| **pos_profile** | Link | POS Profile | No | Blank = system-wide; set for profile-specific override |
| **enabled** | Check | — | No | If checked, account is available to cashiers |

**Title field**: `friendly_name`

**Permissions**:

| Role | Permissions |
|---|---|
| System Manager | create, delete, email, export, import, print, read, report, share, write |
| Accounts Manager | create, delete, email, export, print, read, report, share, write |

**Unique mapping constraint** (enforced by `pos_expense_account.py` `validate`):
- A blank `pos_profile` is stored/compared as "not set" (`["is", "not set"]`), so a blank mapping collides only with other blank mappings for the same company + account.
- If `pos_profile` is set, the triple (company, account, pos_profile) must be unique — checked against other records with the same profile.
- A profile-specific mapping coexists with a blank (system-wide) mapping for the same company + account; that coexistence is the intended override, not a duplicate.
- There is no global (company, account) uniqueness.

**Python model** (`pos_expense_account.py`):

```python
class POSExpenseAccount(Document):
    def validate(self):
        self._validate_unique_mapping()

    def _validate_unique_mapping(self):
        filters = {
            "company": self.company,
            "account": self.account,
            "pos_profile": self.pos_profile or ["is", "not set"],
            "name": ["!=", self.name],
        }
        if self.pos_profile:
            filters["pos_profile"] = self.pos_profile

        existing = frappe.db.exists("POS Expense Account", filters)
        if existing:
            profile_label = self.pos_profile or "system-wide default"
            frappe.throw(
                f"A mapping for account '{self.account}' in company '{self.company}' "
                f"already exists for {profile_label}."
            )
```

### JavaScript Extension Points (`pos_extension.js`)

The extension replaces the POS controller class at runtime. Available methods on the extended class:

| Method | Description |
|---|---|
| `prepare_btns()` | Clears the native primary/secondary actions, menu, and inner toolbar, then adds custom buttons: Add Expense (lines 20-23), Reprint Invoices (24-27), Refund (28-31) in the inner toolbar, New Invoice (32-37, primary), Close POS (38-44, danger) — see pos_extension.js lines 14-45. |
| `open_expense_modal()` | Opens a Dialog with fields: Date, Expense Account (Link to POS Expense Account), Amount (Currency), Remarks (Small Text, required — `reqd:1`, pos_extension.js line 87). Submits via `pos_expenses.api.post_expense`. |
| `open_reprint_invoices_modal()` | Opens a Dialog with a filtered list of POS Invoices (via `get_pos_invoices_for_reprint`). Supports date/time/status/search filtering. Click an invoice to view details; print full or selected items. |
| `open_refund_invoices_modal()` | Opens a Dialog with a filtered list of returnable POS Invoices. Supports date/time/status/search filtering. Select items and quantities; process return. |
| `_execute_refund(invoice_name, return_items)` | Internal method: shows `frappe.confirm()`, then calls `pos_expenses.api.process_pos_refund`. |
| `_process_refund_full(data)` | Returns all available items for the invoice. |
| `_process_refund_selected(data)` | Returns only the selected items (with specified quantities). |
| `_print_full_invoice(data)` | Calls `frappe.utils.print()` for the full invoice. |
| `_print_selected_items(data)` | Calls `get_partial_print_url` then opens the URL in a new window. |

The extension also injects the **POS Closing Entry** behavior: on-submit of the POS Closing Entry form, the user is routed back to the point-of-sale page (`pos_closing_entry.js`).

### Local Development Setup

1. **Clone the repo** into your bench path:
   ```bash
   bench get-app https://github.com/Stelele/erpnext-point-of-sale-expenses.git --branch version-16
   ```

2. **Install on a site**:
   ```bash
   bench --site <site> install-app pos_expenses
   ```

3. **Enable developer mode** (persists DocType/Report schema changes to app files instead of only the database — Python edits still require a `bench restart`):
   ```bash
   bench --site <site> set-config developer_mode 1
   ```

4. **Run the app in bench**:
   ```bash
   bench start
   # or simply visit the Point of Sale page after installation
   ```

5. **Test the API manually**:
   ```bash
   bench --site <site> execute \
     "pos_expenses.api.post_expense(posting_date='2026-01-01', expense_account='Gas - Main Store', amount=100, remarks='Test expense')"
   ```

   Note: `expense_account` expects the **name of a POS Expense Account mapping record** — `api.py` resolves it via `frappe.db.get_value("POS Expense Account", expense_account, "account")` — not a raw Account name.

6. **Run existing tests** (if any):
   ```bash
   bench --site <site> run-tests --app pos_expenses
   ```

7. **Lint**:
   ```bash
   cd apps/pos_expenses
   pre-commit run --all-files
   # or individually:
   ruff check pos_expenses/
   ruff format --check pos_expenses/
   ```

### Testing Notes

- **Expense flow**: The `post_expense` method creates and submits a Journal Entry with two account legs: the debit leg is the mapped Account resolved from the POS Expense Account record via `frappe.db.get_value("POS Expense Account", expense_account, "account")` (api.py line 15) — not the mapping record itself — and the credit leg is the company's Cash account. Currencies must match. The method requires the user to have "Journal Entry" permission.
- **Refund flow**: `process_pos_refund` uses ERPNext's `make_return_doc` under the hood. It validates that quantities do not exceed returnable limits (original qty minus previously returned qty).
- **Account query**: `pos_expense_account_query` uses a UNION ALL to profile-specific records (priority 1) then system-wide defaults (priority 2), excluding any system-wide accounts that are already covered by a profile-specific record.
- **Invoice reprint**: `get_partial_print_url` caches HTML per key (MD5 of invoice_name + selected_items) for 600 seconds. The `show_partial_print` method returns a self-printing HTML page.
- **Unique mapping**: The DocType `validate` method prevents duplicates within the same scope: a blank `pos_profile` collides only with another blank ("not set") mapping for the same company + account, while a profile-specific mapping coexists with a blank (system-wide) one as the intended override. There is no global (company, account) uniqueness. Test by trying to save two records with the same company/account and both blank `pos_profile` — the second should fail with a clear error.

## File Inventory (grounding)

| File | Purpose |
|---|---|
| `pos_expenses/hooks.py` | App configuration; hook overrides; DocType/page JS mappings |
| `pos_expenses/api.py` | 10 whitelisted API methods with full signatures |
| `pos_expenses/overrides/point_of_sale.py` | Override of `get_parent_item_group` |
| `pos_expenses/pos_expenses/doctype/pos_expense_account/pos_expense_account.json` | DocType definition (fields, permissions, title) |
| `pos_expenses/pos_expenses/doctype/pos_expense_account/pos_expense_account.py` | DocType validate — unique mapping enforcement |
| `pos_expenses/pos_expenses/doctype/pos_expense_account/pos_expense_account.js` | onlink: account query hook pointing to `indirect_expense_account_query` |
| `pos_expenses/public/js/pos_extension.js` | Main JS extension — button injection and modals |
| `pos_expenses/public/js/pos_closing_entry.js` | POS Closing Entry on-submit handler |
| `docs/USER_GUIDE.md` | End-user guide |
| `docs/DEVELOPER.md` | This file |
| `README.md` | Project overview and installation |