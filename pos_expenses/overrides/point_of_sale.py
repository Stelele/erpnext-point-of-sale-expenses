import frappe


@frappe.whitelist()
def get_parent_item_group(pos_profile):
	"""Deterministic default item group for POS.

	Upstream returns list(set(...))[0] which is unordered; after the v16.34
	escaping fix this can resolve to an empty leaf group, making the POS
	item grid load empty.
	"""
	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	if profile.get("item_groups"):
		return profile.item_groups[0].item_group

	from erpnext.accounts.doctype.pos_profile.pos_profile import get_item_groups

	item_groups = get_item_groups(pos_profile)
	if not item_groups:
		item_groups = frappe.get_all("Item Group", {"lft": 1, "is_group": 1}, pluck="name")

	return sorted(item_groups)[0] if item_groups else None
