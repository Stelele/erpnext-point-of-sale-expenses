frappe.provide('erpnext.PointOfSale');

(function () {
	var _orig_on_page_load = frappe.pages["point-of-sale"].on_page_load;

	frappe.pages["point-of-sale"].on_page_load = function (wrapper) {
		var _orig_require = frappe.require;

		frappe.require = function (items, callback) {
			if (items === "point-of-sale.bundle.js") {
				return _orig_require(items, function () {
					var Orig = erpnext.PointOfSale.Controller;
					erpnext.PointOfSale.Controller = class extends Orig {
						prepare_btns() {
							super.prepare_btns();
							this.page.add_inner_button(
								__('Add Expense'),
								this.open_expense_modal.bind(this)
							);
						}

						open_expense_modal() {
							var d = new frappe.ui.Dialog({
								title: 'Add Expense',
								fields: [
									{
										label: 'Date',
										fieldname: 'posting_date',
										fieldtype: 'Date',
										default: frappe.datetime.get_today(),
										reqd: 1
									},
									{
										label: 'Expense Account',
										fieldname: 'expense_account',
										fieldtype: 'Link',
										options: 'Account',
										reqd: 1,
										only_select: 1,
										get_query: function () {
											return {
												query: "pos_expenses.api.indirect_expense_account_query",
												filters: {}
											};
										}
									},
									{
										label: 'Amount',
										fieldname: 'amount',
										fieldtype: 'Currency',
										reqd: 1
									},
									{
										label: 'Remarks',
										fieldname: 'remarks',
										fieldtype: 'Small Text',
										reqd: 1
									}
								],
								primary_action_label: 'Submit Expense',
								primary_action: function (values) {
									frappe.call({
										method: "pos_expenses.api.post_expense",
										args: {
											posting_date: values.posting_date,
											expense_account: values.expense_account,
											amount: values.amount,
											remarks: values.remarks
										},
										freeze: true,
										freeze_message: "Posting Journal Entry...",
										callback: function (r) {
											if (!r.exc) {
												frappe.show_alert({
													message: "Expense successfully posted!",
													indicator: "green"
												});
												d.hide();
											}
										}
									});
								}
							});
							d.show();
						}
					};
					callback();
				});
			}
			return _orig_require(items, callback);
		};

		_orig_on_page_load(wrapper);
		frappe.require = _orig_require;
	};
})();
