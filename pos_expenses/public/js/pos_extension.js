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
								__('Refund'),
								this.open_refund_invoices_modal.bind(this)
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
							const pos_profile = this.pos_profile;
							const company = this.company;
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
										options: 'POS Expense Account',
										reqd: 1,
										only_select: 1,
										get_query: function () {
											return {
												query: "pos_expenses.api.pos_expense_account_query",
												filters: {
													pos_profile: pos_profile,
													company: company
												}
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

						open_refund_invoices_modal() {
							this._refund_dialog = new frappe.ui.Dialog({
								title: __('Refund Invoices'),
								static: false,
								fields: [],
							});

							this._refund_dialog.$wrapper.find(".modal-dialog").css({
								"max-width": "95vw",
								"width": "95vw",
								"margin": "0 auto",
							});
							this._refund_dialog.$wrapper.find(".modal-body").css({
								"padding": "0",
								"max-height": "85vh",
								"height": "85vh",
							});

							this._refund_date_filter_active = false;
							this._render_refund_body();
							this._refund_dialog.show();
						}

						_render_refund_body() {
							var me = this;
							var body = this._refund_dialog.$wrapper.find(".modal-body");
							body.empty();

							body.append(
								'<div class="refund-container" style="display: flex; height: 100%; gap: 12px;">' +
									'<div class="refund-left" style="flex: 0 0 38%; display: flex; flex-direction: column; overflow: hidden; border-right: 1px solid var(--border-color); padding-right: 12px;">' +
										'<div class="refund-filters" style="padding: 12px; border-bottom: 1px solid var(--border-color); flex-shrink: 0;"></div>' +
										'<div class="refund-invoice-list" style="flex: 1; overflow-y: auto; padding: 8px;"></div>' +
									'</div>' +
									'<div class="refund-right" style="flex: 1; overflow-y: auto; padding: 12px;">' +
										'<div class="refund-placeholder" style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-muted);">' +
											__('Select an invoice to process a return') +
										'</div>' +
										'<div class="refund-detail" style="display: none;"></div>' +
									'</div>' +
								'</div>'
							);

							this._build_refund_filters(body.find(".refund-filters"));
							this._refund_selected_invoice_name = null;
							this._refresh_refund_invoice_list();

							this._refund_dialog.$wrapper.find(".refund-invoice-list").on(
								"click", ".refund-invoice-row", function () {
									var invoice_name = $(this).attr("data-invoice");
									me._refund_dialog.$wrapper.find(".refund-invoice-row").css("background", "");
									$(this).css("background", "var(--bg-light-gray)");
									me._load_refund_invoice_detail(invoice_name);
								}
							);
						}

						_build_refund_filters(parent) {
							var me = this;

							var html =
								'<div class="row mb-2">' +
									'<div class="col-sm-12"><div class="filter-date-field"></div></div>' +
								'</div>' +
								'<div class="refund-time-filters" style="display: none;">' +
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
							this._refund_date_field = frappe.ui.form.make_control({
								df: {
									label: __('Date'), fieldtype: "Date", fieldname: "refund_date",
									default: frappe.datetime.get_today(),
									onchange: function () {
										me._refund_date_filter_active = true;
										clearTimeout(me._refund_filter_timer);
										me._refund_filter_timer = setTimeout(function () { me._refresh_refund_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-date-field"),
								render_input: true,
							});
							this._refund_date_field.refresh();
							this._refund_date_field.set_value(frappe.datetime.get_today());

							// Time from
							this._refund_from_time_field = frappe.ui.form.make_control({
								df: {
									label: __('From Time'), fieldtype: "Time", fieldname: "refund_from_time",
									onchange: function () {
										clearTimeout(me._refund_filter_timer);
										me._refund_filter_timer = setTimeout(function () { me._refresh_refund_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-time-from-field"),
								render_input: true,
							});
							this._refund_from_time_field.refresh();

							// Time to
							this._refund_to_time_field = frappe.ui.form.make_control({
								df: {
									label: __('To Time'), fieldtype: "Time", fieldname: "refund_to_time",
									onchange: function () {
										clearTimeout(me._refund_filter_timer);
										me._refund_filter_timer = setTimeout(function () { me._refresh_refund_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-time-to-field"),
								render_input: true,
							});
							this._refund_to_time_field.refresh();

							// Time filter toggle
							parent.find(".toggle-time-filter").on("click", function () {
								var $time = parent.find(".refund-time-filters");
								var $link = $(this);
								if ($time.is(":visible")) {
									$time.hide();
									$link.text(__('+ Add time filter'));
									me._refund_from_time_field.set_value("");
									me._refund_to_time_field.set_value("");
									me._refresh_refund_invoice_list();
								} else {
									$time.show();
									$link.text(__('- Remove time filter'));
								}
							});

							// Status
							this._refund_status_field = frappe.ui.form.make_control({
								df: {
									label: __('Status'), fieldtype: "Select", fieldname: "refund_status",
									options: ["All", "Paid", "Submitted", "Consolidated", "Partly Paid", "Unpaid"].join("\n"),
									default: "All",
									onchange: function () {
										clearTimeout(me._refund_filter_timer);
										me._refund_filter_timer = setTimeout(function () { me._refresh_refund_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-status-field"),
								render_input: true,
							});
							this._refund_status_field.refresh();
							this._refund_status_field.set_value("All");

							// Search
							this._refund_search_field = frappe.ui.form.make_control({
								df: {
									label: __('Search'), fieldtype: "Data", fieldname: "refund_search",
									placeholder: __('Name or customer'),
									onchange: function () {
										clearTimeout(me._refund_search_timer);
										me._refund_search_timer = setTimeout(function () { me._refresh_refund_invoice_list(); }, 300);
									},
								},
								parent: parent.find(".filter-search-field"),
								render_input: true,
							});
							this._refund_search_field.refresh();
						}

						_refresh_refund_invoice_list() {
							var me = this;
							var parent = this._refund_dialog.$wrapper.find(".refund-invoice-list");
							var status = this._refund_status_field.get_value();
							var search = this._refund_search_field.get_value();
							var from_time = this._refund_from_time_field.get_value();
							var to_time = this._refund_to_time_field.get_value();

							var args = {
								status: status,
								search_term: search,
								limit: 50,
							};
							if (this._refund_date_filter_active) {
								args.date = this._refund_date_field.get_value();
							}
							if (from_time) args.from_time = from_time;
							if (to_time) args.to_time = to_time;

							frappe.call({
								method: "pos_expenses.api.get_pos_invoices_for_refund",
								args: args,
								callback: function (r) {
							parent.empty();
							if (!r.message || r.message.length === 0) {
								parent.append(
							'<div class="text-muted" style="padding: 20px; text-align: center;">' + __('No returnable invoices found') + '</div>'
								);
								return;
							}
							r.message.forEach(function (inv) {
								parent.append(me._get_refund_invoice_row_html(inv));
							});
								},
							});
						}

						_get_refund_invoice_row_html(invoice) {
							var datetime = frappe.datetime.str_to_user(
								invoice.posting_date + " " + (invoice.posting_time || "00:00:00")
							);

							var status_color = this._get_status_color(invoice.status);

							return (
								'<div class="refund-invoice-row" data-invoice="' + frappe.utils.escape_html(invoice.name) + '"' +
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
						_load_refund_invoice_detail(invoice_name) {
							var me = this;
							this._refund_selected_invoice_name = invoice_name;

							frappe.call({
								method: "pos_expenses.api.get_invoice_detail_for_refund",
								args: { invoice_name: invoice_name },
								callback: function (r) {
									if (r.message) {
										me._render_refund_invoice_detail(r.message);
									}
								},
							});
						}

						_render_refund_invoice_detail(data) {
							var me = this;
							var right = this._refund_dialog.$wrapper.find(".refund-right");
							right.find(".refund-placeholder").hide();
							var detail = right.find(".refund-detail");
							detail.show();
							this._refund_invoice_data = data;

							var status_color = this._get_status_color(data.status);

							// Header
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

							// Items with checkboxes and quantity inputs
							var items_html = '<div class="label" style="font-weight: 600; margin-bottom: 6px;">' + __('Items to Return') + '</div>';
							if (data.items && data.items.length) {
								data.items.forEach(function (item) {
									var can_return = item.returnable_qty > 0;
									items_html +=
										'<div class="refund-item-row" data-item-name="' + frappe.utils.escape_html(item.name) + '"' +
											' style="display: flex; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-color);' + (can_return ? '' : ' opacity: 0.5;') + '">' +
											'<input type="checkbox" class="refund-item-check" data-item-name="' + frappe.utils.escape_html(item.name) + '"' +
												(can_return ? '' : ' disabled') + ' style="margin-right: 8px;"' + '>' +
											'<div style="flex: 1; min-width: 0;">' +
												'<div>' + frappe.utils.escape_html(item.item_name) + '</div>' +
												'<div style="font-size: 11px; color: var(--text-muted);">' + item.item_code + '</div>' +
											'</div>' +
											'<div style="text-align: right; flex-shrink: 0; margin-left: 8px;">' +
												'<div style="display: flex; align-items: center; gap: 4px; justify-content: flex-end;">' +
													'<span style="font-size: 11px; color: var(--text-muted);">' + __('Qty') + ':</span>' +
													'<input type="number" class="refund-item-qty" data-item-name="' + frappe.utils.escape_html(item.name) + '"' +
														' value="' + item.returnable_qty + '"' +
														' min="1" max="' + item.returnable_qty + '"' +
														' style="width: 60px; text-align: center;"' +
														(can_return ? '' : ' disabled') + '>' +
												'</div>' +
												'<div style="font-size: 11px; color: var(--text-muted);">' + __('Orig') + ': ' + item.qty + '</div>' +
												'<div style="font-weight: 500; font-size: 13px;">' + format_currency(item.amount, data.currency) + '</div>' +
											'</div>' +
										'</div>';
								});
							}

							// Estimated totals (updated dynamically)
							var totals_html =
								'<div class="label" style="font-weight: 600; margin: 12px 0 6px;">' + __('Return Totals') + '</div>' +
								'<div class="refund-totals-container">' +
									'<div style="display: flex; justify-content: space-between; font-size: 13px;">' +
										'<div>' + __('Net Total') + '</div>' +
										'<div><span class="refund-net-total">' + format_currency(0, data.currency) + '</span></div>' +
									'</div>' +
									'<div style="display: flex; justify-content: space-between; font-weight: 600; padding-top: 4px; border-top: 1px solid var(--border-color);">' +
										'<div>' + __('Grand Total') + '</div>' +
										'<div><span class="refund-grand-total">' + format_currency(0, data.currency) + '</span></div>' +
									'</div>' +
								'</div>';

							// Original payments display
							var payments_html = '<div class="label" style="font-weight: 600; margin: 12px 0 6px;">' + __('Original Payments') + '</div>';
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
									'<button class="btn btn-primary btn-return-everything" style="flex: 1;">' + __('Return Everything') + '</button>' +
									'<button class="btn btn-default btn-return-selected" style="flex: 1; display: none;">' + __('Return Selected Items') + '</button>' +
								'</div>';

							detail.html(header + items_html + totals_html + payments_html + btns_html);

							// Bind events
							var update_totals_and_buttons = function () {
								var total = 0;
								detail.find(".refund-item-row").each(function () {
									var $row = $(this);
									var checked = $row.find(".refund-item-check").is(":checked");
									var qty = parseFloat($row.find(".refund-item-qty").val()) || 0;
									var item_name = $row.attr("data-item-name");
									if (checked && qty > 0) {
										var orig_item = data.items.find(function (i) { return i.name === item_name; });
										if (orig_item) {
											var rate = orig_item.rate || 0;
											total += rate * qty;
										}
									}
								});
								detail.find(".refund-net-total").text(format_currency(total, data.currency));
								detail.find(".refund-grand-total").text(format_currency(total, data.currency));

								var has_checked = detail.find(".refund-item-check:checked").length > 0;
								detail.find(".btn-return-selected").toggle(has_checked);
							};

							detail.on("change", ".refund-item-check", update_totals_and_buttons);
							detail.on("input", ".refund-item-qty", update_totals_and_buttons);

							// When checkbox is toggled, enable/disable qty input
							detail.on("change", ".refund-item-check", function () {
								var $row = $(this).closest(".refund-item-row");
								var $qty = $row.find(".refund-item-qty");
								if ($(this).is(":checked")) {
									$qty.prop("disabled", false);
								} else {
									$qty.prop("disabled", true);
								}
							});

							// Init totals (all unchecked by default = 0)
							update_totals_and_buttons();

							// Return Everything button
							detail.find(".btn-return-everything").on("click", function () {
								me._process_refund_full(data);
							});

							// Return Selected Items button
							detail.find(".btn-return-selected").on("click", function () {
								me._process_refund_selected(data);
							});
						}

						_process_refund_full(data) {
							var me = this;
							var items = [];
							data.items.forEach(function (item) {
								if (item.returnable_qty > 0) {
									items.push({
										item_name: item.name,
										qty: item.returnable_qty,
									});
								}
							});

							if (!items.length) {
								frappe.show_alert({ message: __('No items available for return.'), indicator: "orange" });
								return;
							}

							this._execute_refund(data.name, items);
						}

						_process_refund_selected(data) {
							var me = this;
							var items = [];
							var detail = this._refund_dialog.$wrapper.find(".refund-detail");

							detail.find(".refund-item-check:checked").each(function () {
								var item_name = $(this).attr("data-item-name");
								var $row = $(this).closest(".refund-item-row");
								var qty = parseFloat($row.find(".refund-item-qty").val()) || 0;
								if (qty > 0) {
									items.push({
										item_name: item_name,
										qty: qty,
									});
								}
							});

							if (!items.length) {
								frappe.show_alert({ message: __('Please select at least one item and specify a quantity.'), indicator: "orange" });
								return;
							}

							this._execute_refund(data.name, items);
						}

						_execute_refund(invoice_name, return_items) {
							var me = this;

							frappe.confirm(
								__('Are you sure you want to process this return?'),
								function () {
									frappe.call({
										method: "pos_expenses.api.process_pos_refund",
										args: {
											invoice_name: invoice_name,
											return_items: JSON.stringify(return_items),
										},
										freeze: true,
										freeze_message: __('Processing return...'),
										callback: function (r) {
											if (r.message) {
												frappe.show_alert({
													message: __('Return invoice {0} created successfully.', [r.message.return_invoice]),
													indicator: "green",
												}, 5);
												me._refund_dialog.hide();
											}
										},
									});
								}
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
