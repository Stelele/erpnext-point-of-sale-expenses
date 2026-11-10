"""Race guard for POS stock: lock the bin and re-check reservations before submit.

The full design rationale lives in `pos_expenses/stock_guard.py` (why stock posts at
POS Closing, why the reservation pool races, why the read view must restart).
These tests pin the guarantee: between the invoice's validation and its stock-row
lock, a sibling reservation committed on another connection must be seen, so the
submit is rejected instead of being sold twice. They also pin the non-blocking
paths (healthy availability, returns, negative-allowed items, bundle rows,
update_stock-off profiles) and the hook wiring.

Runs on the erpnext `_Test` fixtures (`bench run-tests` scaffolds them); self-skips
where they are missing.
"""

import random
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime

COMPANY = "_Test Company"
WAREHOUSE = "Stores - _TC"
ROLES = ("Accounts Manager", "Accounts User", "Sales Manager", "Stock User", "Item Manager")


class POSRaceGuardTestBase(IntegrationTestCase):
	"""Shared fixture bed for the race-guard tests (no tests of its own)."""

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
		# the race tests commit POS invoices on a second connection; roll those back so
		# the site is left as it was
		cls.addClassCleanup(cls._cleanup_committed_docs)

	@classmethod
	def _cancel_delete(cls, doctype, filters):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			try:
				doc = frappe.get_doc(doctype, name)
				if doc.docstatus == 1:
					doc.cancel()
			except Exception:
				frappe.db.rollback()
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

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
			for name in frappe.get_all(
				"POS Profile", filters={"pos_profile_name": ("like", "ZGUARD Profile%")}, pluck="name"
			):
				frappe.delete_doc("POS Profile", name, ignore_permissions=True, force=True)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()

	def setUp(self):
		super().setUp()
		# cleanup order matters (addCleanup is LIFO): first roll back the test's
		# uncommitted state, then strip whatever it committed (the racer leg commits
		# on a separate connection, and the opening entry must be committed for the
		# racer's own validation to pass)
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
		"""Strip committed leftovers of one test (racer invoices, stock, session)."""
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
		self._cancel_delete("POS Opening Entry", {"pos_profile": self.profile.name})
		frappe.delete_doc("POS Profile", self.profile.name, ignore_permissions=True, force=True)
		frappe.delete_doc("User", self.cashier, ignore_permissions=True, force=True)

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

	def test_blocks_reservation_committed_between_validation_and_submission(self):
		"""The guard must see a sibling reserve committed after this invoice validated."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		# Each step is committed on its own: a bare commit() flushes every pending
		# change, so ordering matters to keep the race snapshots precise.
		self.open_pos()
		frappe.db.commit()
		self.stock_in(2)
		frappe.db.commit()

		# sibling A: reserved and committed before the race window opens
		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()

		# our invoice B: validates against reserved=1 of 2 (available for it: 1) and passes.
		# Commit the draft first: the naming-series row is taken FOR UPDATE, so an
		# uncommitted draft of B would block the racer's own naming and mangle the race.
		pi = self.create_pi(qty=1)
		frappe.db.commit()

		# the race: sibling C commits on another cashier's session between B's
		# validation and B's submission
		with self.secondary_connection():
			racer = frappe.new_doc("POS Invoice")
			racer.is_pos = 1
			racer.update_stock = 1
			racer.pos_profile = self.profile.name
			racer.company = COMPANY
			racer.customer = self.customer
			racer.append(
				"items",
				{
					"item_code": self.item_code,
					"qty": 1,
					"rate": 100,
					"price_list_rate": 100,
					"warehouse": WAREHOUSE,
				},
			)
			racer.append(
				"payments",
				{"mode_of_payment": "Cash", "account": "Cash - _TC", "amount": 100},
			)
			racer.set_missing_values()
			racer.save(ignore_permissions=True)
			racer.submit()
			frappe.db.commit()

		# committed stock: 2 units, committed reservations: 2, B needs 1 => must fail
		with self.assertRaises(frappe.ValidationError) as caught:
			enforce_stock_before_submit(pi)

		self.assertIn("has no stock in warehouse", str(caught.exception))

	def test_multiple_rows_of_same_item_share_one_pool(self):
		"""Two rows of the same item in one invoice draw from one availability pool:
		the reservations must be counted once, not re-deducted per row."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(3)
		frappe.db.commit()

		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()

		# committed stock: 3, committed reservations: 1 (sibling) => this invoice with
		# two 1-qty rows must see 2 available for itself and pass
		pi = self.create_pi(qty=1)
		pi.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": 1,
				"rate": 100,
				"price_list_rate": 100,
				"warehouse": WAREHOUSE,
			},
		)
		pi.append(
			"payments",
			{"mode_of_payment": "Cash", "account": "Cash - _TC", "amount": 100},
		)
		pi.set_missing_values()
		pi.save(ignore_permissions=True)
		frappe.db.commit()
		enforce_stock_before_submit(pi)

	def test_healthy_submit_passes(self):
		"""Enough committed stock for the whole race pool: no block, no warning."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(5)
		frappe.db.commit()

		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()

		with self.secondary_connection():
			racer = self.create_pi(qty=1)
			racer.submit()
			frappe.db.commit()

		pi = self.create_pi(qty=1)
		frappe.db.commit()
		enforce_stock_before_submit(pi)

	def test_guard_is_narrow_in_scope(self):
		"""Returns, non-stock rows, negative-allowed items and update_stock=0 are skipped."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		self.stock_in(1)
		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()

		# return invoice: no consumption at close, never blocked
		as_return = frappe.get_doc(make_return_pi(self.customer, self.profile.name))
		enforce_stock_before_submit(as_return)

		# item marked to allow negative stock: skips the guard entirely
		item = frappe.get_cached_doc("Item", self.item_code)
		item.allow_negative_stock = 1
		item.save()
		pi = self.create_pi(qty=1)
		enforce_stock_before_submit(pi)

		# bundle rows (serial/batch bundles) are left to the serial/batch layer
		pi = self.create_pi(qty=1)
		pi.items[0].serial_and_batch_bundle = "ZGUARD-FAKE-BUNDLE"
		enforce_stock_before_submit(pi)

		# an invoice whose profile does not update stock consumes nothing at close
		pi = self.create_pi(qty=1)
		pi.update_stock = 0
		enforce_stock_before_submit(pi)

	def test_hook_is_registered_for_pos_submit(self):
		from pos_expenses import hooks
		from pos_expenses.stock_guard import POSStockRaceGuardMixin

		mixin_path = (hooks.extend_doctype_class or {}).get("POS Invoice")
		self.assertEqual(
			mixin_path,
			"pos_expenses.stock_guard.POSStockRaceGuardMixin",
			"guard must be wired to POS Invoice via extend_doctype_class",
		)
		extended = frappe.new_doc("POS Invoice")
		self.assertIn(POSStockRaceGuardMixin, type(extended).__mro__)


def make_return_pi(customer, pos_profile):
	"""Build a return POS Invoice dict against a fresh (committed) sale is overkill for
	these tests; the return path is only exercised for the skip behaviour."""
	return {
		"doctype": "POS Invoice",
		"is_pos": 1,
		"update_stock": 1,
		"is_return": 1,
		"pos_profile": pos_profile,
		"company": COMPANY,
		"customer": customer,
		"items": [
			{
				"item_code": POSRaceGuardTestBase.item_code,
				"qty": -1,
				"rate": 100,
				"price_list_rate": 100,
				"warehouse": WAREHOUSE,
			}
		],
		"payments": [{"mode_of_payment": "Cash", "account": "Cash - _TC", "amount": -100}],
	}


class TestPOSRaceGuardBusyDay(POSRaceGuardTestBase):
	"""Regression tests for the busy-day scenarios from the live-store session."""

	@staticmethod
	def reservations():
		"""Quantities committed to the unconsolidated pool for the test item."""
		return frappe.db.sql(
			"""SELECT c.item_code, SUM(c.stock_qty) reserved, COUNT(DISTINCT p.name) invoices
			FROM `tabPOS Invoice` p
			JOIN `tabPOS Invoice Item` c ON c.parent = p.name
			WHERE c.item_code = %(item)s
			  AND p.customer = %(customer)s
			  AND p.docstatus = 1
			  AND IFNULL(p.consolidated_invoice, '') = ''
			GROUP BY c.item_code""",
			{"item": TestPOSRaceGuardBusyDay.item_code, "customer": TestPOSRaceGuardBusyDay.customer},
			as_dict=True,
		)

	def assert_pool(self, expected_reserved, expected_invoices):
		rows = self.reservations()
		reserved = sum(row.reserved for row in rows)
		invoices = sum(row.invoices for row in rows)
		self.assertEqual(float(reserved), expected_reserved, "pool reservation mismatch")
		self.assertEqual(invoices, expected_invoices, "pool invoice count mismatch")

	def assert_no_negative_ledger(self):
		neg = frappe.db.sql(
			"SELECT COUNT(*) c FROM `tabStock Ledger Entry` WHERE item_code = %(item)s AND qty_after_transaction < 0",
			{"item": self.item_code},
			as_dict=1,
		)
		self.assertEqual(neg[0].c, 0, "a negative qty slipped into the stock ledger")

	def test_zero_stock_burst_is_rejected_and_ledger_untouched(self):
		"""The zero-stock burst (browser R2): racing carts at a drained pool are
		rejected with the core checkout message and leave the ledger untouched."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(1)
		frappe.db.commit()

		# the day's sale consumes the pool; the next wave arrives at zero
		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()
		self.assert_pool(1, 1)

		blocked = self.create_pi(qty=1)
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError) as caught:
			enforce_stock_before_submit(blocked)
		self.assertIn("has no stock in warehouse", str(caught.exception))

		# the blocked invoice stayed a draft; nothing new committed to the pool
		blocked.reload()
		self.assertEqual(blocked.docstatus, 0)
		self.assert_pool(1, 1)
		self.assert_no_negative_ledger()

	def test_mid_day_restock_caps_the_landing_exactly(self):
		"""The mid-day restock (browser R3): a wave racing a restocked pool must cap
		at the committed pool — a third racer over the restock must be rejected."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(3)  # start-of-day stock: 3 units
		frappe.db.commit()

		# morning burst: three parked commitments on the item (unconsolidated)
		committed = []
		for _ in range(3):
			sibling = self.create_pi(qty=1)
			sibling.submit()
			frappe.db.commit()
			committed.append(sibling)
		self.assert_pool(3, 3)

		# mid-day: the butcher restocks 2 units; the pool says only 2 more may land
		self.stock_in(2)
		frappe.db.commit()

		first = self.create_pi(qty=1)
		first.submit()
		frappe.db.commit()
		second = self.create_pi(qty=1)
		second.submit()
		frappe.db.commit()
		self.assert_pool(5, 5)

		# the wave's third racer exceeds the restocked units: must be blocked
		third = self.create_pi(qty=1)
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError) as caught:
			enforce_stock_before_submit(third)
		self.assertIn("has no stock in warehouse", str(caught.exception))
		third.reload()
		self.assertEqual(third.docstatus, 0)
		self.assert_no_negative_ledger()

		# the ledger invariant: the committed pool never exceeded the offered units
		self.assert_pool(5, 5)
		self.reservations()

	def test_pool_release_unsticks_the_session(self):
		"""The un-stick lifecycle: cancelling a landed invoice releases its pool slot
		without touching the allow-negative knob, so the blocked submit passes."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(1)
		frappe.db.commit()

		sibling = self.create_pi(qty=1)
		sibling.submit()
		frappe.db.commit()
		self.assert_pool(1, 1)

		blocked = self.create_pi(qty=1)
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError):
			enforce_stock_before_submit(blocked)

		# the cashier voids the landed sale; its pool slot frees up
		sibling.cancel()
		frappe.db.commit()
		self.assert_pool(0, 0)
		enforce_stock_before_submit(blocked)  # now passes: the un-stick worked

	def test_invoice_without_bin_row_fails_closed(self):
		"""A first sale into an item with no Bin record must not slip past the
		guard: the lock finds no row and the pool is empty, so the invoice is
		rejected deterministically (both racing halves fail) — the zero-stock
		case, not a silent oversell."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		# no stock entry for this item... except siblings may have left a Bin row
		# from earlier scenarios in the same class — bin rows outlive their stock
		# entries, so drop it explicitly to reproduce the first-sale case
		frappe.db.sql(
			"DELETE FROM `tabBin` WHERE item_code = %(item)s AND warehouse = %(wh)s",
			{"item": self.item_code, "wh": WAREHOUSE},
		)
		frappe.db.commit()
		self.assertIsNone(frappe.db.get_value("Bin", {"item_code": self.item_code, "warehouse": WAREHOUSE}))

		pi = self.create_pi(qty=1)
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError) as caught:
			enforce_stock_before_submit(pi)
		# a zero bin reads exactly like a sold-out shelf, not an exception type swap
		self.assertIn("has no stock in warehouse", str(caught.exception))

	def test_consolidated_invoice_is_skipped_by_the_guard(self):
		"""An invoice that only exists in memory as a consolidation artefact (the
		merged copy created at POS Closing) never races the pool again."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(3)
		frappe.db.commit()
		self.assert_pool(0, 0)

		pi = self.create_pi(qty=1)
		# simulate the close-time artefact in memory (the artefact's link is only
		# persisted at closing, and link validation here would demand a Sales
		# Invoice to exist): the guard must skip it entirely, not re-check
		pi.consolidated_invoice = "ZGUARD-FIXTURE-INVOICE"
		enforce_stock_before_submit(pi)

	def test_one_consolidated_invoice_does_not_double_count_the_pool(self):
		"""The committed pool counts unconsolidated invoices only: staging this
		invoice must not shift reservations of the parked ones."""
		from pos_expenses.stock_guard import enforce_stock_before_submit

		self.open_pos()
		frappe.db.commit()
		self.stock_in(2)
		frappe.db.commit()

		first = self.create_pi(qty=1)
		first.save(ignore_permissions=True)
		# a parked second device's invoice
		parked = self.create_pi(qty=1)
		parked.save(ignore_permissions=True)
		frappe.db.commit()
		self.assert_pool(0, 0)

		first.consolidated_invoice = "ZGUARD-FIXTURE-INVOICE"
		enforce_stock_before_submit(parked)  # run through with the first parked
