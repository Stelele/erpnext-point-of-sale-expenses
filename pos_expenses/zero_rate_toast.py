"""Suppress the false zero-valuation-rate toast on POS Invoice saves.

Upstream bug frappe/erpnext#66738: `StockController.check_zero_rate` (called from
`on_update`, so on every draft save) warns about stock rows whose `incoming_rate`
is zero — but `SellingController.set_incoming_rate` only computes incoming rates
for Delivery Note and Sales Invoice, so POS Invoice rows always carry zero and
the warning fires on every save of every stock item, whatever the selling rate.
Valuation itself is computed correctly when the SLE posts at POS closing; only
the toast's premise is never computed for POS.

This mixin implements the issue's suggested fix of dropping POS Invoice from the
check's doctype list, locally, without patching the erpnext checkout: it shadows
`check_zero_rate` for POS Invoice only, through `extend_doctype_class`. Every
other doctype keeps the core check. POS Invoice Item has no `valuation_rate`
field either, so no branch of the core check can produce a true positive here —
skipping it loses no real warning. It is deliberately not the other suggested
fix (computing incoming rates for POS): that would add per-row stock queries to
every cart save on the hot POS path to feed a check whose answer cannot change
the ledger.

Remove this mixin and its hooks.py entry once upstream releases a fix for
frappe/erpnext#66738 — either `set_incoming_rate` covers POS Invoice sales or
POS Invoice leaves `check_zero_rate`'s doctype list. The characterization test
in tests/test_pos_zero_rate_toast.py starts failing when that happens: that is
the signal to drop this patch.
"""


class POSZeroRateToastMixin:
	def check_zero_rate(self):
		# POS rows never carry a computed incoming_rate (see module docstring),
		# so the core check can only false-positive here. Skip it entirely.
		return
