import frappe
from frappe.model.document import Document


class POSExpenseAccount(Document):
    def validate(self):
        self._validate_unique_mapping()

    def _validate_unique_mapping(self):
        filters = {
            "company": self.company,
            "account": self.account,
            "pos_profile": self.pos_profile or ["is", "not set"],
            "name": ["!=", self.name],
        }
        if self.pos_profile:
            filters["pos_profile"] = self.pos_profile

        existing = frappe.db.exists("POS Expense Account", filters)
        if existing:
            profile_label = self.pos_profile or "system-wide default"
            frappe.throw(
                f"A mapping for account '{self.account}' in company '{self.company}' "
                f"already exists for {profile_label}."
            )
