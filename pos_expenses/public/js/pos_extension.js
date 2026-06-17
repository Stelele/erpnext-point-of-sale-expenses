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
							this.page.clear_primary_action();
							this.page.clear_secondary_action();
							this.page.clear_menu();
							this.page.clear_inner_toolbar();
							this.page.add_inner_button(
								__('Add Expense'),
								this.open_expense_modal.bind(this)
							);
							this.page.add_inner_button(
								__('Reprint Invoices'),
								this.open_reprint_invoices_modal.bind(this)
							);
							this.page.add_inner_button(
								__('New Invoice'),
								this.new_invoice_event.bind(this),
								null,
								"primary"
							);
							this.page.add_inner_button(
								__('Close POS'),
								this.close_pos.bind(this),
								null,
								"danger",
								true
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
		
							this._reprint_dialog.$wrapper.find(".modal-dialog").css({
								"max-width": "95vw",
								"width": "95vw",
								"margin": "0 auto",
							});
							this._reprint_dialog.$wrapper.find(".modal-body").css({
								"padding": "0",
								"max-height": "85vh",
								"height": "85vh",
							});
		
							this._date_filter_active = false;
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
							this._refresh_invoice_list();
		
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
								onchange: function () {
									me._date_filter_active = true;
									clearTimeout(me._filter_timer);
									me._filter_timer = setTimeout(function () { me._refresh_invoice_list(); }, 300);
								},
							},
								parent: parent.find(".filter-date-field"),
								render_input: true,
							});
							this._date_field.refresh();
							this._date_field.set_value(frappe.datetime.get_today());
		
						// Time from
						this._from_time_field = frappe.ui.form.make_control({
							df: {
								label: __('From Time'), fieldtype: "Time", fieldname: "reprint_from_time",
								onchange: function () {
									clearTimeout(me._filter_timer);
									me._filter_timer = setTimeout(function () { me._refresh_invoice_list(); }, 300);
								},
							},
								parent: parent.find(".filter-time-from-field"),
								render_input: true,
							});
							this._from_time_field.refresh();
		
						// Time to
						this._to_time_field = frappe.ui.form.make_control({
							df: {
								label: __('To Time'), fieldtype: "Time", fieldname: "reprint_to_time",
								onchange: function () {
									clearTimeout(me._filter_timer);
									me._filter_timer = setTimeout(function () { me._refresh_invoice_list(); }, 300);
								},
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
								onchange: function () {
									clearTimeout(me._filter_timer);
									me._filter_timer = setTimeout(function () { me._refresh_invoice_list(); }, 300);
								},
							},
								parent: parent.find(".filter-status-field"),
								render_input: true,
							});
							this._status_field.refresh();
							this._status_field.set_value("All");
		
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
							var status = this._status_field.get_value();
							var search = this._search_field.get_value();
							var from_time = this._from_time_field.get_value();
							var to_time = this._to_time_field.get_value();

							var args = {
								status: status,
								search_term: search,
								limit: 50,
							};
							if (this._date_filter_active) {
								args.date = this._date_field.get_value();
							}
							if (from_time) args.from_time = from_time;
							if (to_time) args.to_time = to_time;

							frappe.call({
								method: "pos_expenses.api.get_pos_invoices_for_reprint",
								args: args,
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
		
					_get_status_color(status) {
						if (["Paid", "Consolidated"].includes(status)) return "green";
						if (["Partly Paid"].includes(status)) return "yellow";
						if (["Unpaid", "Submitted"].includes(status)) return "orange";
						return "grey";
					}

					_get_invoice_row_html(invoice) {
						var datetime = frappe.datetime.str_to_user(
							invoice.posting_date + " " + (invoice.posting_time || "00:00:00")
						);

						var status_color = this._get_status_color(invoice.status);
		
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

						_load_invoice_detail(invoice_name) {
							var me = this;
							this._reprint_selected_invoice_name = invoice_name;

							frappe.call({
								method: "pos_expenses.api.get_invoice_detail_for_reprint",
								args: { invoice_name: invoice_name },
								callback: function (r) {
									if (r.message) {
										me._render_invoice_detail(r.message);
									}
								},
							});
						}

						_render_invoice_detail(data) {
							var me = this;
							var right = this._reprint_dialog.$wrapper.find(".reprint-right");
							right.find(".reprint-placeholder").hide();
							var detail = right.find(".reprint-detail");
							detail.show();
						this._reprint_invoice_data = data;

						var status_color = this._get_status_color(data.status);

							var header =
								'<div class="upper-section" style="display: flex; justify-content: space-between; margin-bottom: 12px;">' +
									'<div>' +
										'<div style="font-weight: 600;">' + frappe.utils.escape_html(data.customer_name) + '</div>' +
										(data.customer !== data.customer_name ? '<div style="font-size: 12px; color: var(--text-muted);">' + frappe.utils.escape_html(data.customer) + '</div>' : '') +
										'<div style="font-size: 11px; color: var(--text-muted);">' + __('Sold by') + ': ' + frappe.utils.escape_html(data.owner) + '</div>' +
									'</div>' +
									'<div style="text-align: right;">' +
										'<div style="font-weight: 600;">' + format_currency(data.paid_amount, data.currency) + '</div>' +
										'<div style="font-size: 12px; color: var(--text-muted);">' + frappe.utils.escape_html(data.name) + '</div>' +
										'<span class="indicator-pill ' + status_color + '" style="font-size: 10px; margin-top: 2px;">' + __(data.status) + '</span>' +
									'</div>' +
								'</div>';

							// Items with checkboxes
							var items_html = '<div class="label" style="font-weight: 600; margin-bottom: 6px;">' + __('Items') + '</div>';
							if (data.items && data.items.length) {
								data.items.forEach(function (item) {
									items_html +=
										'<div class="item-row" style="display: flex; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--border-color);">' +
											'<input type="checkbox" class="reprint-item-check" data-item-name="' + frappe.utils.escape_html(item.name) + '" style="margin-right: 8px;">' +
											'<div style="flex: 1; min-width: 0;">' +
												'<div>' + frappe.utils.escape_html(item.item_name) + '</div>' +
												(item.discount_percentage ? '<div style="font-size: 11px; color: var(--text-muted);">(' + parseFloat(item.discount_percentage) + '% off) ' + format_currency(item.rate, data.currency) + '</div>' : '') +
											'</div>' +
											'<div style="text-align: right; flex-shrink: 0;">' +
												'<div>' + item.qty + ' ' + frappe.utils.escape_html(item.uom) + '</div>' +
												'<div style="font-weight: 500;">' + format_currency(item.amount, data.currency) + '</div>' +
											'</div>' +
										'</div>';
								});
							}

							// Totals
							var totals_html =
								'<div class="label" style="font-weight: 600; margin: 12px 0 6px;">' + __('Totals') + '</div>' +
								'<div style="display: flex; justify-content: space-between; font-size: 13px;">' +
									'<div>' + __('Net Total') + '</div>' +
									'<div>' + format_currency(data.net_total, data.currency) + '</div>' +
								'</div>';
							if (data.discount_amount) {
								totals_html +=
									'<div style="display: flex; justify-content: space-between; font-size: 13px; color: var(--text-muted);">' +
										'<div>' + __('Discount') + ' (' + data.additional_discount_percentage + '%)</div>' +
										'<div>' + format_currency(data.discount_amount, data.currency) + '</div>' +
									'</div>';
							}
							if (data.taxes && data.taxes.length) {
								data.taxes.forEach(function (t) {
									totals_html +=
										'<div style="display: flex; justify-content: space-between; font-size: 13px;">' +
											'<div>' + frappe.utils.escape_html(t.description) + '</div>' +
											'<div>' + format_currency(t.tax_amount_after_discount_amount, data.currency) + '</div>' +
										'</div>';
								});
							}
							totals_html +=
								'<div style="display: flex; justify-content: space-between; font-weight: 600; padding-top: 4px; border-top: 1px solid var(--border-color);">' +
									'<div>' + __('Grand Total') + '</div>' +
									'<div>' + format_currency(data.grand_total, data.currency) + '</div>' +
								'</div>';

							// Payments
							var payments_html = '<div class="label" style="font-weight: 600; margin: 12px 0 6px;">' + __('Payments') + '</div>';
							if (data.payments && data.payments.length) {
								data.payments.forEach(function (p) {
									payments_html +=
										'<div style="display: flex; justify-content: space-between; font-size: 13px;">' +
											'<div>' + __(p.mode_of_payment) + '</div>' +
											'<div>' + format_currency(p.amount, data.currency) + '</div>' +
										'</div>';
								});
							} else {
								payments_html += '<div class="text-muted">' + __('No payments recorded') + '</div>';
							}

							// Action buttons
							var btns_html =
								'<div style="margin-top: 16px; display: flex; gap: 8px;">' +
									'<button class="btn btn-primary btn-print-full">' + __('Print Full Invoice') + '</button>' +
									'<button class="btn btn-default btn-print-selected" style="display: none;">' + __('Print Selected Items') + '</button>' +
								'</div>';

							detail.html(header + items_html + totals_html + payments_html + btns_html);

						// Bind checkbox change to toggle selected-items button
						detail.off("change", ".reprint-item-check").on("change", ".reprint-item-check", function () {
								var checked = detail.find(".reprint-item-check:checked").length;
								detail.find(".btn-print-selected").toggle(checked > 0);
							});

							// Bind print buttons
							detail.find(".btn-print-full").on("click", function () {
								me._print_full_invoice(data);
							});

							detail.find(".btn-print-selected").on("click", function () {
								me._print_selected_items(data);
							});
						}

						_print_full_invoice(data) {
							frappe.utils.print(
								"POS Invoice",
								data.name,
								(this.frm && this.frm.pos_print_format) || "Standard",
								data.letter_head,
								data.language || frappe.boot.lang
							);
						}

						_print_selected_items(data) {
							var me = this;
							var checked = this._reprint_dialog.$wrapper.find(".reprint-item-check:checked");
							var selected = [];
							checked.each(function () {
								selected.push($(this).attr("data-item-name"));
							});

							if (!selected.length) {
								frappe.show_alert({ message: __('Please select at least one item.'), indicator: "orange" });
								return;
							}

							frappe.call({
								method: "pos_expenses.api.get_partial_print_url",
								args: {
									invoice_name: data.name,
									selected_items: JSON.stringify(selected),
								},
								freeze: true,
								freeze_message: __('Preparing print...'),
								callback: function (r) {
									if (r.message && r.message.url) {
										var w = window.open(frappe.urllib.get_full_url(r.message.url));
										if (!w) {
											frappe.msgprint(__("Please enable pop-ups for printing."));
										}
									}
								},
							});
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
