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
							this.page.add_inner_button(
								__('Reprint Invoices'),
								this.open_reprint_invoices_modal.bind(this)
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
		
						open_reprint_invoices_modal() {
							this._reprint_dialog = new frappe.ui.Dialog({
								title: __('Reprint Invoices'),
								static: false,
								fields: [],
							});
		
							this._reprint_dialog.$wrapper.css({
								"max-width": "95vw",
								"width": "95vw",
							});
							this._reprint_dialog.$wrapper.find(".modal-dialog").css({
								"max-width": "95vw",
								"width": "95vw",
							});
							this._reprint_dialog.$wrapper.find(".modal-body").css({
								"padding": "0",
								"max-height": "85vh",
								"height": "85vh",
							});
		
							this._render_reprint_body();
							this._reprint_dialog.show();
						}
		
						_render_reprint_body() {
							var me = this;
							var body = this._reprint_dialog.$wrapper.find(".modal-body");
							body.empty();
		
							body.append(
								'<div class="reprint-container" style="display: flex; height: 100%; gap: 12px;">' +
									'<div class="reprint-left" style="flex: 0 0 38%; display: flex; flex-direction: column; overflow: hidden; border-right: 1px solid var(--border-color); padding-right: 12px;">' +
										'<div class="reprint-filters" style="padding: 12px; border-bottom: 1px solid var(--border-color); flex-shrink: 0;"></div>' +
										'<div class="reprint-invoice-list" style="flex: 1; overflow-y: auto; padding: 8px;"></div>' +
									'</div>' +
									'<div class="reprint-right" style="flex: 1; overflow-y: auto; padding: 12px;">' +
										'<div class="reprint-placeholder" style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-muted);">' +
											__('Select an invoice to view details') +
										'</div>' +
										'<div class="reprint-detail" style="display: none;"></div>' +
									'</div>' +
								'</div>'
							);
		
							this._build_filters(body.find(".reprint-filters"));
							this._reprint_selected_invoice_name = null;
		
							// Invoice row click handler
							this._reprint_dialog.$wrapper.find(".reprint-invoice-list").on(
								"click", ".reprint-invoice-row", function () {
									var invoice_name = $(this).attr("data-invoice");
									me._reprint_dialog.$wrapper.find(".reprint-invoice-row").css("background", "");
									$(this).css("background", "var(--bg-light-gray)");
									me._load_invoice_detail(invoice_name);
								}
							);
						}
		
						_build_filters(parent) {
							var me = this;
		
							var html =
								'<div class="row mb-2">' +
									'<div class="col-sm-12"><div class="filter-date-field"></div></div>' +
								'</div>' +
								'<div class="reprint-time-filters" style="display: none;">' +
									'<div class="row mb-2">' +
										'<div class="col-sm-6"><div class="filter-time-from-field"></div></div>' +
										'<div class="col-sm-6"><div class="filter-time-to-field"></div></div>' +
									'</div>' +
								'</div>' +
								'<div class="row mb-2">' +
									'<div class="col-sm-12">' +
										'<a class="toggle-time-filter small" style="cursor: pointer;">' + __('+ Add time filter') + '</a>' +
									'</div>' +
								'</div>' +
								'<div class="row mb-2">' +
									'<div class="col-sm-6"><div class="filter-status-field"></div></div>' +
									'<div class="col-sm-6"><div class="filter-search-field"></div></div>' +
								'</div>';
							parent.html(html);
		
							// Date
							this._date_field = frappe.ui.form.make_control({
								df: {
									label: __('Date'), fieldtype: "Date", fieldname: "reprint_date",
									default: frappe.datetime.get_today(),
									onchange: function () { me._refresh_invoice_list(); },
								},
								parent: parent.find(".filter-date-field"),
								render_input: true,
							});
							this._date_field.refresh();
		
							// Time from
							this._from_time_field = frappe.ui.form.make_control({
								df: {
									label: __('From Time'), fieldtype: "Time", fieldname: "reprint_from_time",
									onchange: function () { me._refresh_invoice_list(); },
								},
								parent: parent.find(".filter-time-from-field"),
								render_input: true,
							});
							this._from_time_field.refresh();
		
							// Time to
							this._to_time_field = frappe.ui.form.make_control({
								df: {
									label: __('To Time'), fieldtype: "Time", fieldname: "reprint_to_time",
									onchange: function () { me._refresh_invoice_list(); },
								},
								parent: parent.find(".filter-time-to-field"),
								render_input: true,
							});
							this._to_time_field.refresh();
		
							// Time filter toggle
							parent.find(".toggle-time-filter").on("click", function () {
								var $time = parent.find(".reprint-time-filters");
								var $link = $(this);
								if ($time.is(":visible")) {
									$time.hide();
									$link.text(__('+ Add time filter'));
									me._from_time_field.set_value("");
									me._to_time_field.set_value("");
									me._refresh_invoice_list();
								} else {
									$time.show();
									$link.text(__('- Remove time filter'));
								}
							});
		
							// Status
							this._status_field = frappe.ui.form.make_control({
								df: {
									label: __('Status'), fieldtype: "Select", fieldname: "reprint_status",
									options: ["All", "Paid", "Submitted", "Consolidated", "Return", "Partly Paid", "Unpaid", "Credit Note Issued"].join("\n"),
									default: "All",
									onchange: function () { me._refresh_invoice_list(); },
								},
								parent: parent.find(".filter-status-field"),
								render_input: true,
							});
							this._status_field.refresh();
		
							// Search
							this._search_field = frappe.ui.form.make_control({
								df: {
									label: __('Search'), fieldtype: "Data", fieldname: "reprint_search",
									placeholder: __('Name or customer'),
									onchange: function () {
										clearTimeout(me._search_timer);
										me._search_timer = setTimeout(function () { me._refresh_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-search-field"),
								render_input: true,
							});
							this._search_field.refresh();
						}
		
						_refresh_invoice_list() {
							var me = this;
							var parent = this._reprint_dialog.$wrapper.find(".reprint-invoice-list");
		
							frappe.call({
								method: "pos_expenses.api.get_pos_invoices_for_reprint",
								args: {
									date: this._date_field.get_value(),
									from_time: this._from_time_field.get_value(),
									to_time: this._to_time_field.get_value(),
									status: this._status_field.get_value(),
									search_term: this._search_field.get_value(),
									limit: 50,
								},
								callback: function (r) {
									parent.empty();
									if (!r.message || r.message.length === 0) {
										parent.append(
											'<div class="text-muted" style="padding: 20px; text-align: center;">' + __('No invoices found') + '</div>'
										);
										return;
									}
									r.message.forEach(function (inv) {
										parent.append(me._get_invoice_row_html(inv));
									});
								},
							});
						}
		
						_get_invoice_row_html(invoice) {
							var datetime = frappe.datetime.str_to_user(
								invoice.posting_date + " " + (invoice.posting_time || "00:00:00")
							);
		
							var status_color = "grey";
							if (["Paid", "Consolidated"].includes(invoice.status)) status_color = "green";
							else if (["Partly Paid"].includes(invoice.status)) status_color = "yellow";
							else if (["Unpaid", "Submitted"].includes(invoice.status)) status_color = "orange";
							else if (["Return", "Credit Note Issued"].includes(invoice.status)) status_color = "grey";
		
							return (
								'<div class="reprint-invoice-row" data-invoice="' + frappe.utils.escape_html(invoice.name) + '"' +
									' style="display: flex; justify-content: space-between; align-items: center; padding: 10px 8px; border-bottom: 1px solid var(--border-color); cursor: pointer; border-radius: 4px;">' +
									'<div style="flex: 1; min-width: 0;">' +
										'<div style="display: flex; align-items: center; gap: 6px;">' +
											'<svg width="12" height="12" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1" fill="none" style="flex-shrink: 0;">' +
												'<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>' +
											'</svg>' +
											'<span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + frappe.utils.escape_html(invoice.customer_name) + '</span>' +
										'</div>' +
										'<div style="font-size: 11px; color: var(--text-muted);">' + frappe.utils.escape_html(invoice.name) + '</div>' +
									'</div>' +
									'<div style="text-align: right; flex-shrink: 0; margin-left: 8px;">' +
										'<div style="font-weight: 500;">' + format_currency(invoice.grand_total, invoice.currency) + '</div>' +
										'<div style="font-size: 11px; color: var(--text-muted);">' + datetime + '</div>' +
										'<span class="indicator-pill ' + status_color + '" style="font-size: 10px; margin-top: 2px;">' + __(invoice.status) + '</span>' +
									'</div>' +
								'</div>'
							);
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
