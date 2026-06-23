frappe.ui.form.on("POS Expense Account", {
    onload: function (frm) {
        frm.set_query("account", function () {
            return {
                query: "pos_expenses.api.indirect_expense_account_query",
                filters: {
                    company: frm.doc.company
                }
            };
        });
    }
});
