"""Bounded retry on MariaDB "Too many connections" (1040) when acquiring a connection.

Frappe opens one MariaDB connection per request and closes it at response end; the
web tier's concurrency is bounded by gunicorn's workerxthread count, and background
workers, the scheduler and every socket.io handshake consume connections from the
same allowance. On small Frappe Cloud site plans that allowance is tight, and the
morning open burst — many POS tabs reconnecting at once, initial profile/item loads,
PDF prints — briefly exceeds it. When it does, every connection attempt fails with
`MySQLdb.OperationalError: (1040, 'Too many connections')` and the request renders a
500 ("The application returned an error") at the worst possible moment: trading
hours. Reproduced and root-caused 2026-11-19 on washefashions (private bench, $5/mo
site plan): 15 of 21 captured error logs are this failure across get_items,
get_pos_profile_data, get_stock_availability, apply_price_list, getdoc, realtime
handshakes, a background job, and the POS Invoice print screen.

This gate does not raise the allowance — nothing app-side can. It turns the failure
mode from *reject* into *briefly wait*: while a retry is pending the caller holds a
gunicorn thread but **no database connection**, so waiting requests queue outside
the DB instead of competing for the very resource that is exhausted. That is the
"temporary queue at the DB gate" semantics, at the only layer an app can reach —
frappe has no pre-connect hook (`init_request` calls `frappe.connect()` before any
app code runs, so a hook-based gate is impossible; the monkeypatch is the only
seam).

Implementation: `MariaDBConnectionUtil.get_connection` (the MariaDB dialect's
connection factory — the exact frame every captured 1040 bottoms out in) is wrapped
with at most `MAX_RETRIES` attempts separated by `BACKOFF x attempt` seconds.
Worst-case added latency is therefore ~2.4 s, well under any gunicorn timeout. Only
errno 1040 retries; every other OperationalError propagates immediately unchanged.
If retries are exhausted the original error surfaces as before, so a genuinely
exhausted allowance still shows 500s rather than hanging — the patch absorbs the
*burst*, not a permanent shortfall (the fix for that is a bigger plan or allowance).

Wired from `hooks.py` at import time, guarded by a class flag so double-import is
harmless. Remove the `install_db_gate()` call and this module once the site's
connection allowance comfortably exceeds peak concurrency (bigger site plan, own
server, or frappe gaining a pre-connect/DB-gate hook). The characterization test in
tests/test_db_gate.py fails if the patch stops engaging — that is the signal to
drop it.
"""

from __future__ import annotations

import time

BACKOFF = 0.4
MAX_RETRIES = 3  # attempts beyond the first

# Module globals rather than class attributes: a plain function stored on the
# class would be bound as a method on instance lookup (silently double-passing
# `self`), and the flag must survive independently of any one class.
_ORIGINAL_GET_CONNECTION = None
_INSTALLED = False


def install_db_gate() -> None:
	"""Wrap MariaDB's connection factory with bounded 1040 retry. Idempotent."""
	global _ORIGINAL_GET_CONNECTION, _INSTALLED

	try:
		from frappe.database.mariadb.mysqlclient import MariaDBConnectionUtil
	except ImportError:  # non-MariaDB site or dialect module moved upstream
		return

	if _INSTALLED:
		return  # already installed in this process

	_ORIGINAL_GET_CONNECTION = MariaDBConnectionUtil.get_connection
	MariaDBConnectionUtil.get_connection = _gated_get_connection
	_INSTALLED = True


def _is_too_many_connections(e: Exception) -> bool:
	return getattr(e, "args", (None,))[0] == 1040


def _gated_get_connection(self):
	import MySQLdb

	original = _ORIGINAL_GET_CONNECTION  # swap-able in tests
	for attempt in range(MAX_RETRIES + 1):
		try:
			return original(self)
		except MySQLdb.OperationalError as e:
			if not _is_too_many_connections(e) or attempt == MAX_RETRIES:
				raise
			time.sleep(BACKOFF * (attempt + 1))
