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
   control inside doc_events handlers;
3. the `Bin` rows for every (item, warehouse) the invoice consumes are locked
   FOR UPDATE and held until the submit commits — concurrent submits of the same
   item/warehouse serialize on those locks, and no competitor can commit its
   reservation between the lock and the read that follows it;
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

import frappe
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import cint, flt


class POSStockRaceGuardMixin:
	def before_submit(self):
		# POSInvoice.before_submit runs via the MRO: this is not a doc_event, so the
		# transaction is ours to control (frappe forces doc_events handlers off it).
		# This is deliberately NOT a doc_events handler: doc_events run with
		# transaction control disabled, and the guard needs commit-and-chain.
		super().before_submit()
		enforce_stock_before_submit(self)


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


def enforce_stock_before_submit(doc):
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
	# restarted (`COMMIT AND CHAIN`). This matters for freshness: the submit
	# transaction's snapshot was taken at the request's first query, and under
	# REPEATABLE READ it would never show a sibling reservation committed since —
	# exactly the race this guard closes. Nothing was written to the database
	# between validation and this point; the submit's own writes (docstatus, GL,
	# ledger) all happen after, so they roll back as one on failure as usual.
	frappe.db.commit(chain=True)

	# lock the bins for the whole submit; ordered so concurrent invoices always
	# acquire them in the same sequence and cannot deadlock on each other — and so
	# that no competitor can commit its reservation between our lock and our read
	bins = _lock_bins(required)
	committed_reserved = get_committed_pos_reserved_qty_map(
		{item_code for item_code, _warehouse in required},
		{warehouse for _item_code, warehouse in required},
	)

	# iterate rows in document order; each row of a key spends from what is left of
	# that bin's committed availability, matching how the ledger will see them.
	# remaining[key] holds what is left for THIS invoice after the rows already
	# accounted for, so a repeated key is not double-charged with the bin's
	# reservations or other sessions' reservations.
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
