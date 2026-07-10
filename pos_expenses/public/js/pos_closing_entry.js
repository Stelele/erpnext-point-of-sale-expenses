frappe.ui.form.on("POS Closing Entry", {
	on_submit: function (frm) {
		frappe.set_route("point-of-sale");
	},
});
