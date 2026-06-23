import frappe
import json
from frappe.utils import flt, today, cint


@frappe.whitelist()
def post_expense(posting_date=None, expense_account=None, amount=0, remarks=None):
	frappe.has_permission("Journal Entry", throw=True)

	real_account = frappe.db.get_value("POS Expense Account", expense_account, "account")
	if not real_account:
		frappe.throw(f"POS Expense Account '{expense_account}' not found.")

	company = frappe.defaults.get_user_default("Company")
	payment_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": company})
	if not payment_account:
		frappe.throw("Could not find a default Cash account for this company.")

	expense_currency = frappe.db.get_value("Account", real_account, "account_currency")
	payment_currency = frappe.db.get_value("Account", payment_account, "account_currency")

	if expense_currency != payment_currency:
		frappe.throw(
			f"Expense account '{real_account}' is in {expense_currency} "
			f"but the Cash account is in {payment_currency}. "
			"Please use accounts in the same currency."
		)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date or today()
	je.remark = remarks

	je.append("accounts", {
		"account": real_account,
		"debit_in_account_currency": flt(amount),
		"credit_in_account_currency": 0
	})

	je.append("accounts", {
		"account": payment_account,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": flt(amount)
	})

	je.insert()
	je.submit()

	return je.name


# Used by POS Expense Account form to filter account selector
# to only leaf accounts under the Indirect Expenses group of a company.
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def indirect_expense_account_query(doctype, txt, searchfield, start, page_len, filters):
	indirect = frappe.db.get_value(
		"Account",
		{
			"account_name": "Indirect Expenses",
			"root_type": "Expense",
			"is_group": 1,
			"company": filters.get("company"),
		},
		["lft", "rgt"],
		as_dict=True,
	)

	if not indirect:
		return []

	search_pattern = f"%{txt}%" if txt else "%"

	return frappe.db.sql(
		"""
		SELECT name, account_name
		FROM `tabAccount`
		WHERE lft > %(lft)s
		  AND rgt < %(rgt)s
		  AND is_group = 0
		  AND (name LIKE %(txt)s OR account_name LIKE %(txt)s)
		ORDER BY lft
		LIMIT %(page_len)s OFFSET %(start)s
	""",
		{
			"lft": indirect.lft,
			"rgt": indirect.rgt,
			"txt": search_pattern,
			"page_len": page_len,
			"start": start,
		},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pos_expense_account_query(doctype, txt, searchfield, start, page_len, filters):
	"""Return POS Expense Accounts with profile-aware override logic.

	Profile-specific records (matching filters.pos_profile) override
	system defaults (pos_profile IS NULL). Disabled records are excluded.
	"""
	pos_profile = filters.get("pos_profile")
	company = filters.get("company")

	search_pattern = f"%{txt}%" if txt else "%"

	if pos_profile:
		return frappe.db.sql(
			"""
			SELECT name, friendly_name
			FROM (
				SELECT name, friendly_name, account, 1 AS priority
				FROM `tabPOS Expense Account`
				WHERE pos_profile = %(pos_profile)s
				  AND company = %(company)s
				  AND enabled = 1
				  AND (friendly_name LIKE %(txt)s OR account LIKE %(txt)s)

				UNION ALL

				SELECT name, friendly_name, account, 2 AS priority
				FROM `tabPOS Expense Account`
				WHERE pos_profile IS NULL
				  AND company = %(company)s
				  AND enabled = 1
				  AND (friendly_name LIKE %(txt)s OR account LIKE %(txt)s)
				  AND account NOT IN (
					  SELECT account FROM `tabPOS Expense Account`
					  WHERE pos_profile = %(pos_profile)s
					    AND company = %(company)s
				  )
			) AS merged
			ORDER BY priority, friendly_name
			LIMIT %(page_len)s OFFSET %(start)s
			""",
			{
				"pos_profile": pos_profile,
				"company": company,
				"txt": search_pattern,
				"page_len": page_len,
				"start": start,
			},
		)
	else:
		return frappe.db.sql(
			"""
			SELECT name, friendly_name
			FROM `tabPOS Expense Account`
			WHERE pos_profile IS NULL
			  AND company = %(company)s
			  AND enabled = 1
			  AND (friendly_name LIKE %(txt)s OR account LIKE %(txt)s)
			ORDER BY friendly_name
			LIMIT %(page_len)s OFFSET %(start)s
			""",
			{
				"company": company,
				"txt": search_pattern,
				"page_len": page_len,
				"start": start,
			},
		)


@frappe.whitelist()
def get_pos_invoices_for_reprint(date=None, from_time=None, to_time=None,
                                  status=None, search_term=None, limit=50):
	filters = {"docstatus": 1}

	if date:
		filters["posting_date"] = date

	if status and status != "All":
		filters["status"] = status

	if from_time and to_time:
		filters["posting_time"] = ["between", [from_time, to_time]]
	elif from_time:
		filters["posting_time"] = [">=", from_time]
	elif to_time:
		filters["posting_time"] = ["<=", to_time]

	or_filters = None
	if search_term:
		or_filters = {
			"name": ["like", f"%{search_term}%"],
			"customer_name": ["like", f"%{search_term}%"],
		}

	return frappe.get_all(
		"POS Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "customer", "customer_name", "status",
			"grand_total", "currency", "posting_date", "posting_time",
			"paid_amount", "total_qty", "owner",
		],
		order_by="posting_date desc, posting_time desc",
		limit=cint(limit),
	)


@frappe.whitelist()
def get_invoice_detail_for_reprint(invoice_name):
	doc = frappe.get_doc("POS Invoice", invoice_name)

	items = []
	for item in doc.items:
		items.append({
			"name": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"uom": item.uom,
			"rate": item.rate,
			"amount": item.amount,
			"discount_percentage": item.discount_percentage,
			"price_list_rate": item.price_list_rate,
		})

	taxes = []
	for tax in doc.taxes:
		taxes.append({
			"description": tax.description,
			"tax_amount_after_discount_amount": tax.tax_amount_after_discount_amount,
		})

	payments = []
	for payment in doc.get("payments", []):
		payments.append({
			"mode_of_payment": payment.mode_of_payment,
			"amount": payment.amount,
		})

	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"status": doc.status,
		"posting_date": str(doc.posting_date),
		"posting_time": str(doc.posting_time) if doc.posting_time else "",
		"paid_amount": doc.paid_amount,
		"owner": doc.owner,
		"currency": doc.currency,
		"net_total": doc.net_total,
		"grand_total": doc.grand_total,
		"discount_amount": doc.discount_amount,
		"additional_discount_percentage": doc.additional_discount_percentage,
		"total_qty": doc.total_qty,
		"letter_head": doc.letter_head,
		"language": doc.language,
		"is_return": doc.is_return,
		"items": items,
		"taxes": taxes,
		"payments": payments,
	}


@frappe.whitelist()
def get_partial_print_url(invoice_name, selected_items):
	import hashlib

	selected_items = json.loads(selected_items)

	doc = frappe.get_doc("POS Invoice", invoice_name)
	doc.items = [item for item in doc.items if item.name in selected_items]
	doc.calculate_taxes_and_totals()

	print_format = None
	letter_head = doc.letter_head
	if doc.pos_profile:
		profile = frappe.get_doc("POS Profile", doc.pos_profile)
		print_format = profile.print_format
		if not letter_head:
			letter_head = profile.letter_head

	if not print_format and not frappe.db.get_value("Print Format", "POS Invoice", "disabled"):
		print_format = "POS Invoice"
	if not print_format:
		print_format = "Standard"

	html = frappe.utils.print_utils.get_print(
		doctype="POS Invoice",
		name=invoice_name,
		print_format=print_format,
		doc=doc,
		as_pdf=False,
		no_letterhead=0 if letter_head else 1,
		letterhead=letter_head,
	)

	key = hashlib.md5((invoice_name + str(selected_items)).encode()).hexdigest()
	frappe.cache().set_value(f"reprint_parts:{key}", html, expires_in_sec=600)

	return {"url": f"/api/method/pos_expenses.api.show_partial_print?key={key}"}


@frappe.whitelist(allow_guest=False)
def show_partial_print(key):
	html = frappe.cache().get_value(f"reprint_parts:{key}")

	if not html:
		frappe.throw("The print preview has expired. Please re-select items and try again.")

	full_page = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Print Receipt</title>
<style>@media print {{ body {{ margin: 0; padding: 0; }} }}</style>
<script>window.onload = function() {{ window.print(); }};</script>
</head>
<body>{html}</body>
</html>"""

	frappe.response.update({
		"http_status_code": 200,
		"type": "download",
		"filecontent": full_page,
		"filename": "receipt.html",
		"content_type": "text/html",
		"display_content_as": "inline",
	})
	return