# Pos Expenses — User Guide

*For shop owners and cashiers: logging expenses, processing refunds, and closing the POS till.*

## Setup (once per site)

1. **Ensure erpnext is installed** — this app requires the erpnext app.
2. **Install the Pos Expenses app** via Bench or Frappe Cloud (see README).
3. **Create POS Expense Accounts**:
   - Go to **Pos Expense Accounts** (Setup menu).
   - Click **New**.
   - Select **Company**, **Account** (from your chart of accounts), and give a **Friendly Name**.
   - Optionally select a **POS Profile** to limit this account to a specific profile; leave blank for system-wide default.
   - Check **Enabled** to make it available to cashiers.
   - Save.
4. **Reload the Point of Sale page** — the **Add Expense**, **Reprint Invoices**, and **Refund** buttons will appear in the inner toolbar.

## Daily Expense-Logging Flow (Cashier)

1. Open the **Point of Sale** page for the current sale.
2. Click the **Add Expense** button in the inner toolbar.
3. Fill in the fields:
   - **Date** — select the date of the expense (defaults to today).
   - **Expense Account** — choose from the filtered list of configured POS Expense Accounts.
   - **Amount** — enter the expense amount; the expense account currency must match the POS cash account currency.
   - **Remarks** — add a short description (required).
4. Click **Submit Expense**.
5. A green alert confirms *"Expense successfully posted!"* and the modal closes.
6. The expense is recorded as a submitted **Journal Entry** behind the scenes.

## Reprint Invoices

1. On the POS page, click **Reprint Invoices**.
2. Use the filters at the top:
   - **Date** — select a posting date (always applies; toggling the time filter only hides/shows and clears the time fields, the date value persists).
   - **From / To Time** — narrow by time range (hidden by default; toggle with "+ Add time filter").
   - **Status** — select an invoice status (All, Paid, Submitted, Consolidated, Return, Partly Paid, Unpaid, Credit Note Issued).
   - **Search** — type the invoice name or customer name.
3. Click an invoice row to load its details on the right panel.
4. View the customer, items, totals, and payments.
5. To print **all items**, click **Print Full Invoice** (opens a new tab with print preview).
6. To print **selected items only**, check the checkboxes next to individual items, then click **Print Selected Items**.

## Refund Invoices (Returns)

1. On the POS page, click **Refund**.
2. Use the filters at the top:
   - **Date** — select a posting date.
   - **From / To Time** — narrow by time range.
   - **Status** — select an invoice status (All, Paid, Submitted, Consolidated, Partly Paid, Unpaid).
   - **Search** — type the invoice name or customer name.
3. Click an invoice row to load its returnable items on the right panel.
4. Each item shows:
   - Item name and code
   - Maximum **returnable qty** (original qty minus already-returned qty)
   - Original quantity and amount
5. Check the items you want to return and enter a quantity (any value greater than 0, up to the max returnable).
6. Click **Return Everything** to return all available items, or **Return Selected Items** to return only the checked ones.
7. Confirm the action in the confirmation dialog.
8. A return invoice is created successfully; the cashier is routed back to the POS page.

## POS Closing Entry

1. When ready to close the till, open the **POS Closing Entry** form (appears in the Desk or POS menu).
2. Click **Submit**.
3. The form automatically routes back to the **Point of Sale** page.

## Frequently Asked Questions

| Question | Answer |
|---|---|
| **I don't see the Add Expense button** | Ensure a POS Expense Account is enabled and (if using a POS Profile) that the current session matches that profile. |
| **The account I need isn't in the dropdown** | Check that the POS Expense Account record is **Enabled** and that the Account is linked to the correct Company. |
| **I get "Could not find a default Cash account"** | Set up an Account with `account_type: Cash` under the user's **default company** — `post_expense` uses `frappe.defaults.get_user_default("Company")`, not the POS session's company. |
| **No invoices appear in Reprint/Refund** | Invoices must be **submitted** (docstatus = 1). Draft or cancelled invoices are not shown. |
| **Return quantity is less than expected** | The max returnable quantity = original qty minus any already-returned qty for that invoice. |
| **After submitting POS Closing Entry, I'm not back at POS** | This is by design — the form routes to the Point-of-Sale page after submit. |

## Glossary

- **POS Expense Account** — a config record that maps an Account to a Company and optionally a POS Profile, making it available in the expense modal.
- **POS Profile** — an ERPNext POS Profile document that controls item groups, print formats, and can scope POS Expense Accounts.
- **Journal Entry** — the internal ERPNext document type used to record the expense transaction (debit the expense account, credit the cash account).
- **Returnable qty** — the remaining quantity of an item that can still be returned (original qty minus previously returned qty).