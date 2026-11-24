"""Serialize POS stock consumption at submit: lock bins, re-read committed reservations.

Stock for a POS Invoice is only consumed when the POS Closing Entry consolidates it
into a Sales Invoice (which inherits `update_stock` from the POS invoice and is
backdated to the invoice's own posting time). Between checkout and closing, the
availability check is a plain read of `bin_qty - pos_reserved_qty` with no lock, and
the reserved pool spans every POS profile sharing the warehouse. Two cashiers that
sell the last unit of the same item on two profiles both pass that check, both
submit, and the second session's close then reposts its consolidated invoice
backwards into a negative ledger position that no forward stock entry can repair —
leaving the closing entry stuck in "Failed".

`POSStockRaceGuardMixin.before_submit` runs after the usual validations have passed
and before the submit lands:

1. invoices that cannot consume stock are skipped (returns; consolidated copies;
   profiles whose `update_stock` is off; serial/batch bundle rows, which the
   serial/batch layer already handles; items with item-level negative stock
   allowed);
2. the request's transaction is committed and chained (`COMMIT AND CHAIN`) so the
   transaction's read view is fresh. Nothing had been written by the submit at
   this point, so this loses no atomicity. This must happen inside the document's
   own method rather than a doc_event hook, because Frappe disables transaction
   control inside doc_events handlers. A second, raw `COMMIT AND CHAIN` right
   before the locks guarantees no after-commit callback pinned a stale snapshot;
   the invoice's own row is re-locked and re-checked (the early commit released
   the lock frappe's `check_if_latest` held against duplicate submits); and for
   insert-and-submit requests the naming-series number is handed back if the
   submit is rolled back;
3. the `Bin` rows for every (item, warehouse) the invoice consumes are locked
   FOR UPDATE and held until the submit commits — concurrent submits of the same
   item/warehouse serialize on those locks, and no competitor can commit its
   reservation between the lock and the read that follows it. The wait for a
   sibling's lock is bounded to a few seconds (see `_bin_lock_wait_window`):
   while a waiter waits it holds its database connection, and an unbounded wait
   under cashier retries exhausted a small plan's connection pool in
   production (MariaDB 1040 "Too many connections");
4. against the bins held under lock, committed availability is re-read (bin minus
   stock reservations minus quantities already reserved by other submitted-but-
   not-yet-consolidated POS invoices) and the invoice's own requirement is checked
   row by row, with the same messages the core checkout check produces.

A sibling that committed in the window between this invoice's validation and its
submission is therefore rejected here instead of being sold twice.

The mixin is wired through `extend_doctype_class` in hooks.py, landing in front of
the ERPNext controller in the document class's MRO — the same placement an
`override_doctype_class` gives without capping the position at a single app.
"""

from collections import defaultdict
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.exceptions import QueryTimeoutError
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import cint, flt, get_datetime

# Seconds a submit may wait for another submit's bin-row lock before it is
# rejected with a retry message. Small enough that waiters release their
# database connections almost immediately, generous enough that momentary
# overlaps between two checkouts resolve without user-visible errors.
LOCK_WAIT_SECONDS = 5


class POSStockRaceGuardMixin:
	def before_submit(self):
		# POSInvoice.before_submit runs via the MRO: this is not a doc_event, so the
		# transaction is ours to control (frappe forces doc_events handlers off it).
		# This is deliberately NOT a doc_events handler: doc_events run with
		# transaction control disabled, and the guard needs commit-and-chain.
		super().before_submit()
		enforce_stock_before_submit(self, in_submit=True)


def stock_needed(row):
	"""The stock-converted consumption of one item row.

	Rows that never got a stock_qty are an anomaly the guard must not silently
	re-interpret: qty is in the selling UOM and would misstate the requirement.
	Fail closed instead.
	"""
	stock_qty = row.get("stock_qty")
	if stock_qty in (None, ""):
		frappe.throw(
			_("Row #{0}: no Stock Qty for item {1}; cannot verify stock for this invoice.").format(
				row.idx, frappe.bold(row.item_code)
			),
			title=_("Verification Error"),
		)
	return flt(stock_qty)


def enforce_stock_before_submit(doc, in_submit=False):
	"""Lock and re-check stock for `doc`.

	`in_submit` marks a call from inside `Document.save` (the mixin), where
	`_doc_before_save` is the row check_if_latest just loaded; only then is it a
	valid baseline for re-verifying the invoice row.
	"""
	if not can_consume_stock(doc):
		return

	item_codes = list({row.item_code for row in doc.items})
	item_details = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", "is_stock_item", "allow_negative_stock"],
		ignore_permissions=True,  # a POS cashier may not hold Item read; the guard decides on real stock
	)
	items = {item.name: item for item in item_details}

	# fail closed if an item vanished mid-submit or was renamed: the guard cannot
	# vouch for stock it cannot see, so the submit must not proceed quietly
	missing = [code for code in item_codes if code not in items]
	if missing:
		frappe.throw(
			_("Items {0} not found; cannot verify stock for this invoice.").format(
				frappe.bold(", ".join(sorted(missing)))
			),
			title=_("Verification Error"),
		)

	# which bins the invoice consumes, so they can be locked in one pass
	required = defaultdict(float)
	for row in doc.get("items"):
		detail = items.get(row.item_code)
		if not detail or not detail.is_stock_item or detail.allow_negative_stock:
			continue
		if row.get("serial_and_batch_bundle"):
			continue
		if not row.get("warehouse"):
			# no consumption target; the core warehouse validation owns that error
			continue
		required[(row.item_code, row.warehouse)] += stock_needed(row)

	if not required:
		return

	# Everything the request did before submit is committed and the transaction
	# restarted (`COMMIT AND CHAIN`), through frappe so its before/after-commit
	# callbacks fire for the work they belong to. Nothing was written to the
	# database by this submit yet; its own writes (docstatus, ledger) all happen
	# after, so they roll back as one on failure as usual. The read-view reset
	# that freshness actually depends on happens inside the window below.
	frappe.db.commit(chain=True)

	stock_item_codes = sorted({item_code for item_code, _warehouse in required})
	with _bin_lock_wait_window(stock_item_codes):
		# Fresh read view. The availability read below is a plain (consistent) read,
		# and under REPEATABLE READ InnoDB pins the transaction's snapshot at its first
		# consistent read. frappe.db.commit() runs after-commit callbacks once the
		# new transaction has begun, and any of them reading a table would pin the
		# snapshot *before* the bin lock — a submit that then waits out a sibling
		# would never see that sibling's reservation, the very oversell this guard
		# prevents. A raw COMMIT AND CHAIN here (no callbacks; only session-variable
		# statements follow before the locking read) starts a transaction with no
		# snapshot yet, so the first consistent read happens after the lock.
		_restart_transaction()
		_register_series_revert(doc)

		# The early commit released the invoice-row lock frappe took in
		# check_if_latest, so a duplicate submit of this same invoice could have
		# slipped past that check. Re-take the row lock and re-verify.
		if in_submit:
			_recheck_invoice_row(doc)

		# lock the bins for the whole submit; ordered so concurrent invoices always
		# acquire them in the same sequence and cannot deadlock on each other — and
		# so that no competitor can commit its reservation between our lock and our
		# read
		bins = _lock_bins(required)
		committed_reserved = get_committed_pos_reserved_qty_map(
			{item_code for item_code, _warehouse in required},
			{warehouse for _item_code, warehouse in required},
		)

		# iterate rows in document order; each row of a key spends from what is
		# left of that bin's committed availability, matching how the ledger will
		# see them. remaining[key] holds what is left for THIS invoice after the
		# rows already accounted for, so a repeated key is not double-charged with
		# the bin's reservations or other sessions' reservations.
		remaining = {}
		for row in doc.get("items"):
			key = (row.item_code, row.warehouse)
			if key not in required:
				# rows the aggregation pass skipped (non-stock, bundles, negative-
				# allowed items) consume nothing; their stock_qty must not block
				continue
			needed = stock_needed(row)
			if needed <= 0:
				continue

			if key not in remaining:
				bin_row = bins.get(key) or frappe._dict(actual_qty=0, reserved_stock=0)
				remaining[key] = flt(
					flt(flt(bin_row.get("actual_qty")) - flt(bin_row.get("reserved_stock")))
					- flt(committed_reserved.get(key, 0)),
					2,
				)

			available = remaining[key]
			if available <= 0:
				frappe.throw(
					_("Row #{0}: Item {1} has no stock in warehouse {2}.").format(
						row.idx, frappe.bold(row.item_code), frappe.bold(row.warehouse)
					),
					title=_("Insufficient Stock"),
				)
			elif available < needed:
				frappe.throw(
					_("Row #{0}: Item {1} in warehouse {2}: Available {3}, Needed {4}.").format(
						row.idx,
						frappe.bold(row.item_code),
						frappe.bold(row.warehouse),
						frappe.bold(available),
						frappe.bold(needed),
					),
					title=_("Insufficient Stock"),
				)

			remaining[key] = available - needed


@contextmanager
def _bin_lock_wait_window(item_codes):
	"""Bound how long this submit waits for a sibling's bin-row lock.

	The guard holds the bin locks until the submit commits, so a sibling checkout
	of the same (item, warehouse) waits on that row lock — and while it waits it
	holds its database connection. MariaDB's default 50 s wait let a few cashier
	retries stack enough held connections to exhaust a small plan's connection
	allowance, and the whole site then failed with MariaDB 1040 "Too many
	connections" (production, 2026-11-19).

	This shrinks the session's `innodb_lock_wait_timeout` around the guard's
	locking reads and restores the site default afterwards. Serialization is
	unchanged — the first submit to reach the lock validates and commits, the
	loser fails fast and releases its connection immediately — and the wait
	timeout surfaces as a retryable message instead of a raw database error.
	"""
	previous = cint(frappe.db.sql("SELECT @@session.innodb_lock_wait_timeout")[0][0])
	frappe.db.sql("SET SESSION innodb_lock_wait_timeout = %s", LOCK_WAIT_SECONDS)
	try:
		yield
	except QueryTimeoutError as err:
		# keep the underlying 1205 in the error log: the friendly throw the user
		# sees does not carry the database error, and recurring contention is
		# diagnosed from this trail
		# deferred: the throw below rolls the request back, and a log inserted in
		# this transaction would be rolled back with it
		frappe.log_error(title="POS stock guard lock wait timed out", message=repr(err), defer_insert=True)
		frappe.throw(
			_("Items {0} are being sold at another till right now; please retry in a few seconds.").format(
				frappe.bold(", ".join(sorted(item_codes)))
			),
			title=_("Please Retry"),
		)
	finally:
		# never let a failed restore mask the original error: a dead connection
		# (dropped during the lock wait) fails this SET SESSION, and the request
		# is failing with the real cause already — swallow and log to the file
		# logger, since a database-backed log write would raise on the same
		# broken connection
		try:
			frappe.db.sql("SET SESSION innodb_lock_wait_timeout = %s", previous)
		except Exception:
			frappe.logger("stock_guard").exception(
				"could not restore innodb_lock_wait_timeout after the stock guard"
			)


def _transaction_control_enabled():
	# inside doc_events handlers frappe disables transaction control and its
	# commit() is a no-op; the guard must not commit around it either
	return not getattr(frappe.db, "_disable_transaction_control", 0)


def _restart_transaction():
	"""COMMIT AND CHAIN without frappe's commit callbacks (see the call site)."""
	if not _transaction_control_enabled():
		return
	frappe.db.sql("commit and chain")
	frappe.db.value_cache.clear()


def _register_series_revert(doc):
	"""Give the naming-series number back if this submit ends up rolled back.

	When an invoice is inserted and submitted in one request (API, import — the POS
	screen always saves a draft first), its name was drawn from the naming series
	before this guard ran, and the guard's early commit made that bump permanent.
	A failed submit (e.g. the retry message below) would otherwise leave a hole in
	the invoice numbering. `revert_series_if_last` only steps the series back when
	this invoice still holds its last number, so a sibling that drew the next one
	in the meantime is never disturbed. frappe.db.commit() clears after-rollback
	callbacks, so this is registered after the guard's own commits and is dropped
	by the request's final commit on success.
	"""
	if not doc.flags.in_insert or not doc.get("naming_series") or not doc.get("name"):
		return
	if not _transaction_control_enabled():
		return

	naming_series, name = doc.naming_series, doc.name

	def revert():
		from frappe.model.naming import revert_series_if_last

		try:
			revert_series_if_last(naming_series, name, doc)
			# the request's rollback already ran; this runs in its fresh chained
			# transaction, which nothing else will commit
			frappe.db.sql("commit and chain")
		except Exception:
			frappe.logger("stock_guard").exception(
				"could not revert naming series %s after rolled-back submit of %s", naming_series, name
			)

	frappe.db.after_rollback.add(revert)


def _recheck_invoice_row(doc):
	"""Re-lock the invoice row and verify it is still the draft this submit loaded.

	frappe's check_if_latest locks the row FOR UPDATE and checks docstatus/modified,
	which makes a concurrent duplicate submit of the same invoice wait and then fail.
	The guard's early commit releases that lock, so a duplicate (a network or proxy
	retry, a second tab) could pass check_if_latest while this submit is in flight
	and then run on_submit a second time — doubling livestock allocations, loyalty
	points, coupon use and vouchers. The row is locked again here, before the bins,
	so every submit of one invoice takes its locks in the same order.
	"""
	previous = getattr(doc, "_doc_before_save", None)
	if doc.flags.in_insert or not previous:
		# insert-and-submit: the row does not exist yet, and a duplicate insert
		# fails on the primary key
		return

	try:
		invoice = frappe.qb.DocType(doc.doctype)
		rows = (
			frappe.qb.from_(invoice)
			.select(invoice.docstatus, invoice.modified)
			.where(invoice.name == doc.name)
			.for_update()
		).run(as_dict=True)
	except QueryTimeoutError as err:
		frappe.log_error(
			title="POS stock guard invoice lock wait timed out", message=repr(err), defer_insert=True
		)
		frappe.throw(
			_("{0} {1} is already being submitted by another request. Wait a moment, then refresh.").format(
				_(doc.doctype), frappe.bold(doc.name)
			),
			title=_("Please Retry"),
		)

	current = rows[0] if rows else None
	if (
		not current
		or cint(current.docstatus) != cint(previous.docstatus)
		or get_datetime(current.modified) != get_datetime(previous.modified)
	):
		frappe.throw(
			_(
				"{0} {1} was changed or submitted by another request while this one was in progress. Please refresh."
			).format(_(doc.doctype), frappe.bold(doc.name)),
			exc=frappe.TimestampMismatchError,
			title=_("Invoice Changed"),
		)


def can_consume_stock(doc):
	"""True only for non-return POS invoices that will consume stock at closing."""
	if doc.get("is_return") or doc.get("consolidated_invoice"):
		return False
	if frappe.get_cached_doc("Stock Settings").allow_negative_stock:
		return False
	return cint(doc.get("update_stock")) == 1


def _lock_bins(required):
	"""Lock the Bin rows the invoice consumes, FOR UPDATE, in a stable order.

	Returns a `{(item, warehouse): row}` mapping. A key without a Bin row maps to a
	zero bin: the stock was never there, and both racing submits must be rejected
	rather than invented into existence. The query is fully parameterized and locks
	exactly the consumed (item, warehouse) pairs — not a cross-product.
	"""
	bin_table = frappe.qb.DocType("Bin")
	pair_conditions = None
	for item_code, warehouse in required:
		condition = (bin_table.item_code == item_code) & (bin_table.warehouse == warehouse)
		pair_conditions = condition if pair_conditions is None else pair_conditions | condition

	rows = (
		frappe.qb.from_(bin_table)
		.select(bin_table.item_code, bin_table.warehouse, bin_table.actual_qty, bin_table.reserved_stock)
		.where(pair_conditions)
		.orderby(bin_table.item_code)
		.orderby(bin_table.warehouse)
		.for_update()
	).run(as_dict=True)
	bins = {(row.item_code, row.warehouse): row for row in rows}

	for key in required:
		bins.setdefault(key, frappe._dict(actual_qty=0, reserved_stock=0))

	return {key: frappe._dict(bin_row) for key, bin_row in bins.items()}


def get_committed_pos_reserved_qty_map(item_codes, warehouses):
	"""Quantities reserved for (item, warehouse) by POS invoices that are already
	submitted and not yet consolidated — the pool the close will consume.

	Same semantics as the core checkout check (`get_pos_reserved_qty` on this
	erpnext/`get_pos_reserved_qty_map` on newer), reimplemented here so the guard
	does not depend on erpnext internals that differ across v15/v16 patch releases.
	Must be read only after the bin rows are locked: with the lock held, no
	competitor can commit, so this read is guaranteed to see every reservation
	that matters.
	"""
	reserved = defaultdict(float)
	p_inv = frappe.qb.DocType("POS Invoice")
	for child_table, qty_column in (("POS Invoice Item", "stock_qty"), ("Packed Item", "qty")):
		p_item = frappe.qb.DocType(child_table)
		rows = (
			frappe.qb.from_(p_inv)
			.from_(p_item)
			.select(p_item.item_code, p_item.warehouse, Sum(p_item[qty_column]).as_("qty"))
			.where(
				(p_inv.name == p_item.parent)
				& (IfNull(p_inv.consolidated_invoice, "") == "")
				& (p_inv.docstatus == 1)
				& (p_item.docstatus == 1)
				& (p_item.item_code.isin(list(item_codes)))
				& (p_item.warehouse.isin(list(warehouses)))
			)
			.groupby(p_item.item_code, p_item.warehouse)
		).run(as_dict=True)
		for row in rows:
			reserved[(row.item_code, row.warehouse)] += flt(row.qty)

	return reserved
