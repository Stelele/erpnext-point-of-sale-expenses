import frappe
from frappe import _
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

		existing = frappe.db.exists("POS Expense Account", filters)
		if existing:
			profile_label = self.pos_profile or _("system-wide default")
			frappe.throw(
				_("A mapping for account {0} in company {1} already exists for {2}.").format(
					frappe.bold(self.account), frappe.bold(self.company), frappe.bold(profile_label)
				)
			)
