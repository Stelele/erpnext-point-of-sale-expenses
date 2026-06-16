import frappe
from frappe.utils import flt, today


@frappe.whitelist()
def post_expense(posting_date=None, expense_account=None, amount=0, remarks=None):
	frappe.has_permission("Journal Entry", throw=True)

	company = frappe.defaults.get_user_default("Company")

	payment_account = frappe.db.get_value("Account", {"account_type": "Cash", "company": company})

	if not payment_account:
		frappe.throw("Could not find a default Cash account for this company.")

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date or today()
	je.remark = remarks

	je.append("accounts", {
		"account": expense_account,
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


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def indirect_expense_account_query(doctype, txt, searchfield, start, page_len, filters):
	indirect = frappe.db.get_value(
		"Account",
		{"account_name": "Indirect Expenses", "root_type": "Expense", "is_group": 1},
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
