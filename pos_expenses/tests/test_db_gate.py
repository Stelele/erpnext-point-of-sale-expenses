"""The DB gate retries MariaDB 1040 with bounded backoff, and only 1040.

Characterization test for pos_expenses/db_gate.py. Pins the two behaviors the
production burst relies on: a transient "Too many connections" is absorbed within
the retry budget (the caller waits while holding no DB connection), and any other
OperationalError surfaces unchanged and immediately. When this test starts failing
because the upstream internals moved (frappe gaining a pre-connect hook, or
MariaDBConnectionUtil being restructured), the patch and its hooks.py wiring can be
dropped — see the module docstring.
"""

import time
import unittest
from unittest import mock

from frappe.database.mariadb.mysqlclient import MariaDBConnectionUtil

import pos_expenses.db_gate as db_gate
from pos_expenses.db_gate import BACKOFF, MAX_RETRIES, install_db_gate


def too_many():
	import MySQLdb

	return MySQLdb.OperationalError(1040, "Too many connections")


def server_gone():
	import MySQLdb

	return MySQLdb.OperationalError(2006, "MySQL server has gone away")


class DBGateTest(unittest.TestCase):
	"""Drives the gate installed on the real class with a stubbed connection factory.

	install_db_gate() swaps `MariaDBConnectionUtil.get_connection` for the gated
	wrapper exactly as hooks.py wiring does; the tests then swap the module's
	`_ORIGINAL_GET_CONNECTION` global for a mock so no real MariaDB is contacted.
	"""

	def setUp(self):
		install_db_gate()  # idempotent; no-ops if hooks.py already ran
		self.real_original = db_gate._ORIGINAL_GET_CONNECTION

	def tearDown(self):
		db_gate._ORIGINAL_GET_CONNECTION = self.real_original

	def stub_gate(self, side_effects):
		"""Swap the original for a stub; the gate then calls the stub."""
		stubbed = mock.Mock(side_effect=side_effects)
		db_gate._ORIGINAL_GET_CONNECTION = stubbed
		return stubbed

	def call(self):
		return MariaDBConnectionUtil.get_connection(mock.Mock())

	# -- behavior pins ---------------------------------------------------------

	def test_transient_1040_is_absorbed(self):
		"""Two 1040s then success: the gate retries and returns the connection."""
		conn = object()
		stubbed = self.stub_gate([too_many(), too_many(), conn])
		t0 = time.monotonic()
		result = self.call()
		elapsed = time.monotonic() - t0
		self.assertIs(result, conn)
		self.assertEqual(stubbed.call_count, 3)
		self.assertLess(elapsed, BACKOFF * 4)  # two sleeps: 0.4 + 0.8 = 1.2 s

	def test_backoff_is_bounded(self):
		"""Worst case adds BACKOFF x (1+2+3) ~ 2.4 s — never unbounded waiting."""
		self.stub_gate([too_many() for _ in range(MAX_RETRIES)] + [object()])
		t0 = time.monotonic()
		self.call()
		elapsed = time.monotonic() - t0
		self.assertLess(elapsed, BACKOFF * 7, "retries must stay bounded")
		self.assertGreaterEqual(elapsed, BACKOFF * 6 * 0.9)

	def test_exhausted_retries_surface_1040(self):
		"""A saturated allowance still fails loudly after the budget, not forever."""
		stubbed = self.stub_gate([too_many() for _ in range(MAX_RETRIES + 1)])
		t0 = time.monotonic()
		with self.assertRaises(type(too_many())):
			self.call()
		self.assertLess(time.monotonic() - t0, BACKOFF * 7)
		self.assertEqual(stubbed.call_count, MAX_RETRIES + 1)

	def test_other_operational_errors_propagate_immediately(self):
		"""Only errno 1040 retries; a 2006 must not be retried or delayed."""
		stubbed = self.stub_gate([server_gone()])
		t0 = time.monotonic()
		with self.assertRaises(type(server_gone())):
			self.call()
		self.assertEqual(stubbed.call_count, 1)
		self.assertLess(time.monotonic() - t0, BACKOFF)

	def test_install_is_idempotent(self):
		"""Double install (hooks.py import + package import) must not double-wrap."""
		before = MariaDBConnectionUtil.get_connection
		install_db_gate()
		self.assertIs(MariaDBConnectionUtil.get_connection, before)


if __name__ == "__main__":
	unittest.main()
