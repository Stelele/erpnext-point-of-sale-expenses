import frappe


@frappe.whitelist()
def get_parent_item_group(pos_profile):
	"""Deterministic default item group for POS.

	The lowest common ancestor of the POS Profile's configured item groups.
	Upstream returns an arbitrary member of list(set(...)), which can be a
	narrow subtree and hide most of the catalog from the opening grid.
	"""
	root = frappe.db.get_value("Item Group", {"is_group": 1, "lft": 1}, "name")

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	groups = [row.item_group for row in profile.get("item_groups") or []]
	if not groups:
		return root

	rows = frappe.get_all("Item Group", filters={"name": ("in", groups)}, fields=["lft", "rgt"])
	if not rows:
		return root

	return frappe.get_all(
		"Item Group",
		filters={
			"lft": ("<=", min(r.lft for r in rows)),
			"rgt": (">=", max(r.rgt for r in rows)),
		},
		pluck="name",
		order_by="lft desc",
		limit=1,
	)[0]
