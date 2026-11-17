"""Shared fixture bed for POS session tests (no tests of its own).

Builds the throwaway world a POS Invoice needs to validate: a _Test-company item
and customer, a POS profile with a Cash payment leg, a cashier user and an open
POS Opening Entry — and strips every committed leftover afterwards. Extracted
from test_pos_stock_race_guard.py so other POS test modules can reuse it without
inheriting (and re-running) the race-guard tests.

Runs on the erpnext `_Test` fixtures (`bench run-tests` scaffolds them); self-skips
where they are missing.
"""

import random
import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime

COMPANY = "_Test Company"
WAREHOUSE = "Stores - _TC"
ROLES = ("Accounts Manager", "Accounts User", "Sales Manager", "Stock User", "Item Manager")


class POSSessionFixtureBed(IntegrationTestCase):
	"""Shared fixture bed for POS session tests (no tests of its own)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Company", COMPANY):
			raise unittest.SkipTest(
				"requires the erpnext _Test company fixtures that bench run-tests sets up on the site"
			)

		cls.item_code = "ZGUARD-Race-" + str(random.randint(100000, 999999))
		cls.customer = "ZGUARD Customer Race " + str(random.randint(100000, 999999))

		currency = frappe.db.get_value("Company", COMPANY, "default_currency")
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": cls.customer,
				"customer_type": "Individual",
				"customer_group": "Commercial",
				"territory": "All Territories",
				"default_currency": currency,
			}
		).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": cls.item_code,
				"item_name": cls.item_code,
				"item_group": "All Item Groups",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		# some tests commit POS invoices on a second connection; roll those back so
		# the site is left as it was
		cls.addClassCleanup(cls._cleanup_committed_docs)

	@classmethod
	def _cancel_delete(cls, doctype, filters):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			try:
				doc = frappe.get_doc(doctype, name)
				if doc.docstatus == 1:
					doc.cancel()
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
				# commit per doc: a later failure's rollback must not resurrect the
				# docs already cleaned earlier in this loop
				frappe.db.commit()
			except Exception:
				# cancel/delete failed (e.g. a linked closing entry blocks cancel):
				# leave the doc in place rather than force-deleting a submitted
				# voucher and orphaning its GL/SLE rows on the shared test site
				frappe.db.rollback()
				frappe.log_error(
					title="POS fixture cleanup failed",
					message=f"could not cancel/delete {doctype} {name}; left in place\n{frappe.get_traceback()}",
				)

	@classmethod
	def _cleanup_committed_docs(cls):
		try:
			frappe.init(cls.TEST_SITE)
			if not frappe.local.db:
				frappe.connect()
			cls._cancel_delete("POS Invoice", {"customer": cls.customer})
			cls._cancel_delete(
				"Stock Entry",
				{
					"name": [
						"in",
						frappe.get_all(
							"Stock Entry Detail", filters={"item_code": cls.item_code}, pluck="parent"
						),
					]
				},
			)
			cls._cancel_delete("POS Opening Entry", {"pos_profile": ("like", "ZGUARD Profile%")})
			# filter on name: POS Profile is autoname=Prompt and has no
			# pos_profile_name column — filtering on it aborted this whole cleanup
			for name in frappe.get_all(
				"POS Profile", filters={"name": ("like", "ZGUARD Profile%")}, pluck="name"
			):
				frappe.delete_doc("POS Profile", name, ignore_permissions=True, force=True)
			# safety net for cashiers whose per-test deletion failed (the per-test
			# cleanup normally deletes its own); mirrors the profile loop above
			cls._cancel_delete("User", {"name": ("like", "pos_guard_cashier%@example.com")})
			# the class fixtures themselves are committed in setUpClass — without
			# this they accumulate on the shared site, one pair per test class run
			cls._cancel_delete("Customer", {"name": cls.customer})
			cls._cancel_delete("Item", {"name": cls.item_code})
			frappe.db.commit()
		except Exception:
			# committed leftovers may remain on the site — leave a trace so the
			# next confusing test run has a diagnostic instead of silence
			frappe.db.rollback()
			frappe.log_error(
				title="POS fixture class cleanup failed",
				message=frappe.get_traceback(),
			)

	def setUp(self):
		super().setUp()
		# cleanup order matters (addCleanup is LIFO): first roll back the test's
		# uncommitted state, then strip whatever it committed (some legs commit on a
		# separate connection, and the opening entry must be committed for their own
		# validation to pass)
		self.addCleanup(self._cleanup_this_test)
		self.addCleanup(frappe.db.rollback)

		# a cashier can hold only one open POS session and a profile only one open
		# opening entry, so each test owns a throwaway profile + cashier
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		self.cashier = create_user(
			f"pos_guard_cashier{random.randint(100000, 999999)}@example.com", *ROLES
		).name
		frappe.db.commit()
		self.profile = self.create_profile()
		frappe.db.commit()

	def _cleanup_this_test(self):
		"""Strip committed leftovers of one test (invoices, stock, session).

		Degrades per resource when setUp did not complete (e.g. create_profile
		raised SkipTest after the cashier was committed): a missing attribute
		must neither mask the original failure nor leak what was created.
		"""
		self._cancel_delete("POS Invoice", {"customer": self.customer})
		self._cancel_delete(
			"Stock Entry",
			{
				"name": (
					"in",
					frappe.get_all(
						"Stock Entry Detail", filters={"item_code": self.item_code}, pluck="parent"
					),
				)
			},
		)
		if getattr(self, "profile", None):
			self._cancel_delete("POS Opening Entry", {"pos_profile": self.profile.name})
			frappe.delete_doc("POS Profile", self.profile.name, ignore_permissions=True, force=True)
		if getattr(self, "cashier", None):
			frappe.delete_doc("User", self.cashier, ignore_permissions=True, force=True)
		# the deletions above must land: nothing later commits them on the last
		# test, and the class-level cleanup has no filter for the random cashier
		# users — without this they leak onto the shared site
		frappe.db.commit()

	def create_profile(self):
		write_off = frappe.db.get_value(
			"Account",
			{"company": COMPANY, "is_group": 0, "root_type": "Expense", "disabled": 0},
			"name",
			order_by="creation",
		)
		if not write_off:
			raise unittest.SkipTest("no expense account available for the POS profile write-off field")
		profile_name = "ZGUARD Profile " + str(random.randint(100000, 999999))
		return frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": profile_name,
				"pos_profile_name": profile_name,
				"company": COMPANY,
				"warehouse": WAREHOUSE,
				"currency": frappe.db.get_value("Company", COMPANY, "default_currency"),
				"selling_price_list": "Standard Selling",
				"write_off_account": write_off,
				"write_off_cost_center": frappe.db.get_value(
					"Cost Center", {"company": COMPANY, "is_group": 0}, "name", order_by="creation"
				),
				"payments": [
					{
						"default": 1,
						"mode_of_payment": "Cash",
						"default_account": frappe.db.get_value(
							"Account", {"account_type": "Cash", "company": COMPANY}, "name"
						),
					}
				],
			}
		).insert(ignore_permissions=True)

	def create_pi(self, qty=1, item_code=None, **overrides):
		pi = frappe.new_doc("POS Invoice")
		pi.is_pos = 1
		pi.update_stock = 1
		pi.pos_profile = self.profile.name
		pi.company = COMPANY
		pi.customer = overrides.pop("customer", self.customer)
		pi.append(
			"items",
			{
				"item_code": item_code or self.item_code,
				"qty": qty,
				"rate": 100,
				"price_list_rate": 100,
				"warehouse": WAREHOUSE,
			},
		)
		pi.append(
			"payments",
			{"mode_of_payment": "Cash", "account": "Cash - _TC", "amount": 100 * qty},
		)
		pi.set_missing_values()
		pi.save(ignore_permissions=True)
		return pi

	def stock_in(self, qty):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		make_stock_entry(item_code=self.item_code, target=WAREHOUSE, qty=qty, basic_rate=100)

	def open_pos(self):
		poe = frappe.new_doc("POS Opening Entry")
		poe.pos_profile = self.profile.name
		poe.user = self.cashier
		poe.company = COMPANY
		poe.period_start_date = get_datetime()
		poe.append("balance_details", {"mode_of_payment": "Cash"})
		poe.save(ignore_permissions=True)
		poe.submit()
		return poe
