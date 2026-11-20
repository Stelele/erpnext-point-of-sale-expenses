"""Reprint honours the POS Profile's print format and letter head.

Pins the print-settings resolution of get_partial_print_url (the server side of
the reprint modal's "Print Selected Items"): the invoice's POS Profile supplies
the print format, and its letter head is the fallback when the invoice carries
none. A profile deleted after the invoice was posted must not crash the reprint
— it falls through to the "POS Invoice" format chain instead.

Runs without a site: frappe collaborators are mocked, mirroring test_db_gate.py.
"""

import unittest
from unittest import mock

import frappe

from pos_expenses.api import get_partial_print_url


class FakeItemRow:
	def __init__(self, name):
		self.name = name


class FakeInvoice:
	"""Just the attributes get_partial_print_url touches."""

	def __init__(self, pos_profile=None, letter_head=""):
		self.pos_profile = pos_profile
		self.letter_head = letter_head
		self.items = [FakeItemRow("row-1"), FakeItemRow("row-2")]

	def calculate_taxes_and_totals(self):
		pass


class FakeProfile:
	def __init__(self, print_format=None, letter_head=None):
		self.print_format = print_format
		self.letter_head = letter_head


class ReprintPrintSettingsTest(unittest.TestCase):
	def setUp(self):
		# the URL builder touches the print call, the cache, the session user,
		# the Print Format disabled flag and permissions — stub them all out.
		self.get_print = mock.Mock(return_value="<html>receipt</html>")
		patches = [
			mock.patch("frappe.utils.print_utils.get_print", self.get_print),
			mock.patch("frappe.has_permission", mock.Mock()),
			mock.patch("frappe.db.get_value", mock.Mock(return_value=0)),
			mock.patch(
				"frappe.cache",
				mock.Mock(return_value=mock.Mock(set_value=mock.Mock(), get_value=mock.Mock())),
			),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self._old_user = frappe.session.user
		frappe.session.user = "reprint-test@example.com"
		self.addCleanup(setattr, frappe.session, "user", self._old_user)

	def call(self, invoice, get_doc):
		with mock.patch("frappe.get_doc", get_doc):
			return get_partial_print_url(
				invoice_name="ACC-PSINV-0001",
				selected_items='["row-1", "row-2"]',
			)

	def test_uses_profile_print_format_and_letter_head(self):
		"""A live profile supplies the print format and the letter-head fallback."""
		invoice = FakeInvoice(pos_profile="Demo")
		profile = FakeProfile(print_format="Voucher Receipt", letter_head="Company LH")
		get_doc = mock.Mock(side_effect=lambda dt, name: invoice if dt == "POS Invoice" else profile)

		self.call(invoice, get_doc)

		kwargs = self.get_print.call_args.kwargs
		self.assertEqual(kwargs["print_format"], "Voucher Receipt")
		self.assertEqual(kwargs["letterhead"], "Company LH")
		self.assertEqual(kwargs["no_letterhead"], 0)

	def test_deleted_profile_falls_back_to_pos_invoice_format(self):
		"""A profile deleted after posting must not 500 the reprint: fall through."""
		invoice = FakeInvoice(pos_profile="ZGONE Profile 123", letter_head="")

		def get_doc(doctype, name):
			if doctype == "POS Invoice":
				return invoice
			raise frappe.exceptions.DoesNotExistError

		self.call(invoice, get_doc)

		kwargs = self.get_print.call_args.kwargs
		self.assertEqual(kwargs["print_format"], "POS Invoice")
		# no letter head anywhere: invoice has none, the profile is gone
		self.assertEqual(kwargs["letterhead"], "")
		self.assertEqual(kwargs["no_letterhead"], 1)

	def test_invoice_letter_head_beats_profile_fallback(self):
		"""An invoice with its own letter head keeps it; the profile fills gaps."""
		invoice = FakeInvoice(pos_profile="Demo", letter_head="Invoice LH")
		profile = FakeProfile(print_format=None, letter_head="Company LH")
		get_doc = mock.Mock(side_effect=lambda dt, name: invoice if dt == "POS Invoice" else profile)

		self.call(invoice, get_doc)

		kwargs = self.get_print.call_args.kwargs
		self.assertEqual(kwargs["letterhead"], "Invoice LH")
		self.assertEqual(kwargs["no_letterhead"], 0)
