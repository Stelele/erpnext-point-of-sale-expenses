import json
import math

import frappe
from erpnext.controllers.sales_and_purchase_return import (
	get_invoice_item_returned_qty,
	is_invoice_returnable,
	make_return_doc,
)
from frappe import _
from frappe.utils import cint, flt, today


@frappe.whitelist()
def post_expense(
	posting_date: str | None = None,
	expense_account: str | None = None,
	amount: float = 0,
	remarks: str | None = None,
):
	frappe.has_permission("Journal Entry", "create", throw=True)

	real_account = frappe.db.get_value("POS Expense Account", expense_account, "account")
	if not real_account:
		frappe.throw(_("POS Expense Account '{0}' not found.").format(frappe.bold(expense_account)))

	company = frappe.defaults.get_user_default("Company")
	payment_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": company})
	if not payment_account:
		frappe.throw(_("Could not find a default Cash account for this company."))

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

	je.append(
		"accounts",
		{"account": real_account, "debit_in_account_currency": flt(amount), "credit_in_account_currency": 0},
	)

	je.append(
		"accounts",
		{
			"account": payment_account,
			"debit_in_account_currency": 0,
			"credit_in_account_currency": flt(amount),
		},
	)

	je.insert()
	je.submit()

	return je.name


# Used by POS Expense Account form to filter account selector
# to only leaf accounts under the Indirect Expenses group of a company.
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def indirect_expense_account_query(
	doctype: str = "Account",
	txt: str = "",
	searchfield: str = "name",
	start: int = 0,
	page_len: int = 20,
	filters: dict | None = None,
):
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
def pos_expense_account_query(
	doctype: str = "POS Expense Account",
	txt: str = "",
	searchfield: str = "friendly_name",
	start: int = 0,
	page_len: int = 20,
	filters: dict | None = None,
):
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


def _bounded_limit(limit: int, default: int = 50) -> int:
	"""HTTP params arrive as strings; coerce and clamp to a sane range."""
	value = cint(limit) or default
	return max(1, min(value, 500))


@frappe.whitelist()
def get_pos_invoices_for_reprint(
	date: str | None = None,
	from_time: str | None = None,
	to_time: str | None = None,
	status: str | None = None,
	search_term: str | None = None,
	limit: int = 50,
):
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
			"name",
			"customer",
			"customer_name",
			"status",
			"grand_total",
			"currency",
			"posting_date",
			"posting_time",
			"paid_amount",
			"total_qty",
			"owner",
		],
		order_by="posting_date desc, posting_time desc",
		limit=_bounded_limit(limit),
	)


@frappe.whitelist()
def get_invoice_detail_for_reprint(invoice_name: str):
	doc = frappe.get_doc("POS Invoice", invoice_name)

	items = []
	for item in doc.items:
		items.append(
			{
				"name": item.name,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item.qty,
				"uom": item.uom,
				"rate": item.rate,
				"amount": item.amount,
				"discount_percentage": item.discount_percentage,
				"price_list_rate": item.price_list_rate,
			}
		)

	taxes = []
	for tax in doc.taxes:
		taxes.append(
			{
				"description": tax.description,
				"tax_amount_after_discount_amount": tax.tax_amount_after_discount_amount,
			}
		)

	payments = []
	for payment in doc.get("payments", []):
		payments.append(
			{
				"mode_of_payment": payment.mode_of_payment,
				"amount": payment.amount,
			}
		)

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
def get_pos_invoices_for_refund(
	date: str | None = None,
	from_time: str | None = None,
	to_time: str | None = None,
	status: str | None = None,
	search_term: str | None = None,
	limit: int = 50,
):
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

	invoices = frappe.get_all(
		"POS Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"status",
			"grand_total",
			"currency",
			"posting_date",
			"posting_time",
			"paid_amount",
			"total_qty",
			"owner",
		],
		order_by="posting_date desc, posting_time desc",
		limit=_bounded_limit(limit),
	)

	# Filter to only returnable invoices (excludes already-returned, drafts, etc.)
	returnable = []
	for inv in invoices:
		if is_invoice_returnable("POS Invoice", inv.name):
			returnable.append(inv)

	return returnable


@frappe.whitelist()
def get_invoice_detail_for_refund(invoice_name: str):
	doc = frappe.get_doc("POS Invoice", invoice_name)

	items = []
	for item in doc.items:
		item_qty = abs(item.qty) if item.qty else 0
		returned = get_invoice_item_returned_qty("POS Invoice", invoice_name, doc.customer, item.name)
		returned_qty = abs(returned.qty) if returned and returned.qty else 0
		returnable_qty = item_qty - returned_qty

		items.append(
			{
				"name": item.name,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item_qty,
				"returnable_qty": max(returnable_qty, 0),
				"uom": item.uom,
				"rate": item.rate,
				"amount": abs(item.amount) if item.amount else 0,
			}
		)

	taxes = []
	for tax in doc.taxes:
		taxes.append(
			{
				"description": tax.description,
				"tax_amount_after_discount_amount": abs(tax.tax_amount_after_discount_amount)
				if tax.tax_amount_after_discount_amount
				else 0,
			}
		)

	payments = []
	for payment in doc.get("payments", []):
		payments.append(
			{
				"mode_of_payment": payment.mode_of_payment,
				"amount": abs(payment.amount) if payment.amount else 0,
			}
		)

	return {
		"name": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"status": doc.status,
		"posting_date": str(doc.posting_date),
		"posting_time": str(doc.posting_time) if doc.posting_time else "",
		"paid_amount": doc.paid_amount,
		"owner": doc.owner,
		"currency": doc.currency,
		"net_total": abs(doc.net_total) if doc.net_total else 0,
		"grand_total": abs(doc.grand_total) if doc.grand_total else 0,
		"discount_amount": abs(doc.discount_amount) if doc.discount_amount else 0,
		"additional_discount_percentage": doc.additional_discount_percentage,
		"total_qty": doc.total_qty,
		"items": items,
		"taxes": taxes,
		"payments": payments,
	}


@frappe.whitelist()
def process_pos_refund(invoice_name: str, return_items: str):
	try:
		return_items = json.loads(return_items)
	except (TypeError, ValueError):
		return_items = None

	if not return_items or not isinstance(return_items, list):
		frappe.throw(_("No items selected for return."))

	source_doc = frappe.get_doc("POS Invoice", invoice_name)
	# Refund creates a return invoice: the caller must hold POS Invoice
	# create rights. Checked without a doc — the source doc is submitted
	# and belongs to whoever checked out; the new document is what matters.
	frappe.has_permission("POS Invoice", "create", throw=True)

	if source_doc.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))

	if source_doc.is_return:
		frappe.throw(_("Cannot return a return invoice."))

	# Validate all items exist and quantities are within returnable limits.
	# Aggregate duplicate rows first: submitting the same item row twice
	# must be treated as one combined request, not two independent ones.
	source_items_by_name = {item.name: item for item in source_doc.items}
	requested = {}
	for ri in return_items:
		item_name = ri.get("item_name")
		qty = flt(ri.get("qty", 0))
		if not item_name:
			frappe.throw(_("Each return item must have an item_name."))
		if qty <= 0:
			frappe.throw(_("Return quantity must be greater than zero for item {0}.").format(item_name))
		if item_name not in source_items_by_name:
			frappe.throw(_("Item {0} not found in invoice {1}.").format(item_name, invoice_name))
		requested[item_name] = requested.get(item_name, 0) + qty

	for item_name, qty in requested.items():
		source_item = source_items_by_name[item_name]
		item_qty = abs(source_item.qty) if source_item.qty else 0
		returned = get_invoice_item_returned_qty("POS Invoice", invoice_name, source_doc.customer, item_name)
		returned_qty = abs(returned.qty) if returned and returned.qty else 0
		max_returnable = item_qty - returned_qty
		if qty > max_returnable:
			frappe.throw(
				_("Return quantity {0} for item {1} exceeds maximum returnable quantity {2}.").format(
					qty, item_name, max_returnable
				)
			)

	# Get all source item names for comparison
	all_source_item_names = [item.name for item in source_doc.items]
	is_partial = len(requested) < len(all_source_item_names) or any(
		not math.isclose(qty, abs(flt(source_items_by_name[item_name].qty)), rel_tol=1e-5)
		for item_name, qty in requested.items()
	)

	# Create the return document via ERPNext's standard mechanism
	target_doc = make_return_doc("POS Invoice", invoice_name, target_doc=None)
	if not target_doc:
		frappe.throw(_("Could not create return invoice."))

	if is_partial:
		# Remove items not in return_items and adjust quantities
		items_to_keep = []
		for item in target_doc.items:
			source_item_name = getattr(item, "pos_invoice_item", None) or item.name
			if source_item_name in requested:
				item.qty = -abs(requested[source_item_name])
				item.amount = item.rate * item.qty if item.rate else 0
				items_to_keep.append(item)

		if not items_to_keep:
			frappe.throw(_("No matching items found in return document."))

		target_doc.items = items_to_keep
		target_doc.calculate_taxes_and_totals()

		# Adjust payments proportionally for partial return
		original_total = abs(source_doc.grand_total) or 1
		returned_total = abs(target_doc.grand_total)
		proportion = returned_total / original_total

		target_doc.set("payments", [])
		for payment in source_doc.payments:
			adjusted_amount = -1 * flt(payment.amount) * proportion
			if adjusted_amount != 0:
				target_doc.append(
					"payments",
					{
						"mode_of_payment": payment.mode_of_payment,
						"amount": adjusted_amount,
						"account": payment.account,
						"type": payment.type,
						"default": payment.default,
					},
				)

		target_doc.paid_amount = sum(flt(p.amount) for p in target_doc.payments)

	target_doc.save()
	target_doc.submit()

	return {"return_invoice": target_doc.name}


@frappe.whitelist()
def get_partial_print_url(invoice_name: str, selected_items: str):
	import hashlib

	try:
		selected_items = json.loads(selected_items)
	except (TypeError, ValueError):
		selected_items = None
	if not isinstance(selected_items, list) or not selected_items:
		frappe.throw(_("At least one item must be selected."))

	doc = frappe.get_doc("POS Invoice", invoice_name)
	frappe.has_permission("POS Invoice", "read", doc, throw=True)
	matched_items = [item for item in doc.items if item.name in set(selected_items)]
	if not matched_items:
		frappe.throw(_("No matching items found in the invoice."))

	doc.items = matched_items
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

	# Bind the cache entry to the requesting user: keys are predictable
	# (md5 of invoice + selected rows), so possession of a key must not
	# let another user read someone else's cached receipt. Sort the items
	# first so equivalent selections hash to one entry.
	selected_items = sorted(selected_items)
	key = hashlib.md5((invoice_name + str(selected_items) + frappe.session.user).encode()).hexdigest()
	frappe.cache().set_value(
		f"reprint_parts:{key}",
		{"user": frappe.session.user, "html": html},
		expires_in_sec=600,
	)

	return {"url": f"/api/method/pos_expenses.api.show_partial_print?key={key}"}


@frappe.whitelist(allow_guest=False)
def show_partial_print(key: str):
	cache = frappe.cache().get_value(f"reprint_parts:{key}")
	# Entries written before the user-binding change stored the raw string;
	# treat anything that is not the new dict as expired.
	html = cache.get("html") if isinstance(cache, dict) else None

	if not html or cache.get("user") != frappe.session.user:
		frappe.throw(_("The print preview has expired. Please re-select items and try again."))

	# The preview is served inline and auto-prints; keep it unscriptable
	# and unframable — its HTML is built from print-format output.
	frappe.local.response_headers.set(
		"Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"
	)
	frappe.local.response_headers.set("X-Frame-Options", "DENY")
	frappe.local.response_headers.set("X-Content-Type-Options", "nosniff")

	full_page = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Print Receipt</title>
<style>@media print {{ body {{ margin: 0; padding: 0; }} }}</style>
<script>window.onload = function() {{ window.print(); }};</script>
</head>
<body>{html}</body>
</html>"""

	frappe.response.update(
		{
			"http_status_code": 200,
			"type": "download",
			"filecontent": full_page,
			"filename": "receipt.html",
			"content_type": "text/html",
			"display_content_as": "inline",
		}
	)
	return
