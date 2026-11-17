"""POS Invoice must not toast a false zero-valuation-rate warning on draft saves.

Upstream bug: frappe/erpnext#66738. `StockController.check_zero_rate` (run from
`on_update`, so on every save) toasts when a stock row has `incoming_rate == 0`
and `allow_zero_valuation_rate` is off — but `SellingController.set_incoming_rate`
only computes incoming rates for Delivery Note and Sales Invoice, so POS Invoice
rows always carry zero and the warning is a guaranteed false positive. Valuation
itself is computed correctly at SLE posting time; only the toast is wrong.

Schema note: `incoming_rate` was added to POS Invoice Item upstream in 1b974b63ea
(after this bench's 16.52.1 checkout, present on the live v16 sites where the bug
was captured). These tests set the row's `incoming_rate = 0` in memory to mirror
the exact draft-row state captured live in the issue, so they exercise the bug on
either schema. The fix itself is schema-agnostic.

The characterization test below pins the upstream premise: when it starts failing
because upstream fixed #66738, the local mixin in pos_expenses/zero_rate_toast.py
can be dropped.
"""

import random

import frappe

from pos_expenses.tests.pos_session_fixtures import COMPANY, WAREHOUSE, POSSessionFixtureBed


class POSZeroRateToastTest(POSSessionFixtureBed):
	"""Reuses the shared POS session fixture bed (profile, cashier, opening entry, items)."""

	def zero_rate_toasts(self):
		return [m for m in frappe.message_log if "has zero rate" in str(m.get("message", ""))]

	def test_pos_draft_save_does_not_toast_zero_rate(self):
		"""A cart-edit save of a normally-priced stock row must stay silent.

		Break caught: the zero-rate mixin (or its hook wiring) is removed, so the
		core false positive returns on every POS draft save.
		"""
		self.open_pos()
		pi = self.create_pi(qty=1)

		frappe.message_log.clear()
		# the live-captured draft state from the issue: normal rate, incoming_rate 0
		pi.items[0].incoming_rate = 0
		pi.save(ignore_permissions=True)

		self.assertFalse(
			self.zero_rate_toasts(),
			f"POS draft save toasted a false zero-rate warning: {self.zero_rate_toasts()}",
		)

	def test_core_check_reproduces_the_upstream_false_positive(self):
		"""Characterization of frappe/erpnext#66738's premise: given the live-captured
		row state, the *core* check toasts even though the rate is normal. When
		upstream fixes the issue this test fails — the signal to drop the local mixin.

		Break caught: upstream changes the check or starts computing POS incoming
		rates, invalidating the reason this local patch exists.
		"""
		from erpnext.controllers.stock_controller import StockController

		self.open_pos()
		pi = self.create_pi(qty=1)
		pi.items[0].incoming_rate = 0

		frappe.message_log.clear()
		StockController.check_zero_rate(pi)

		self.assertTrue(
			self.zero_rate_toasts(),
			"upstream premise changed: core check no longer false-positives on POS rows "
			"— re-check frappe/erpnext#66738 and drop pos_expenses/zero_rate_toast.py if fixed",
		)

	def test_sales_invoice_zero_rate_check_still_active(self):
		"""The suppression must be POS-only: a Sales Invoice with update_stock and a
		stock item that has no incoming rate must still get the core warning.

		Break caught: the fix leaks beyond POS Invoice (global override, or the
		mixin wired onto another doctype).
		"""
		item_code = "ZTOAST-SI-" + str(random.randint(100000, 999999))
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": "All Item Groups",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)

		si = frappe.new_doc("Sales Invoice")
		si.customer = self.customer
		si.company = COMPANY
		si.currency = frappe.db.get_value("Company", COMPANY, "default_currency")
		si.update_stock = 1
		si.append(
			"items",
			{"item_code": item_code, "qty": 1, "rate": 100, "warehouse": WAREHOUSE},
		)
		si.set_missing_values()

		frappe.message_log.clear()
		si.save(ignore_permissions=True)

		self.assertTrue(
			self.zero_rate_toasts(),
			"the core zero-rate warning must remain active for Sales Invoice",
		)

	def test_both_pos_mixins_are_wired(self):
		"""The hooks list must carry the race guard AND the toast fix together.

		Break caught: the hook value regresses to a single class (losing one of the
		fixes), or a mixin is dropped from the list.
		"""
		pi = frappe.get_doc({"doctype": "POS Invoice"})
		mro_names = [cls.__name__ for cls in type(pi).__mro__]
		self.assertIn("POSStockRaceGuardMixin", mro_names)
		self.assertIn("POSZeroRateToastMixin", mro_names)
