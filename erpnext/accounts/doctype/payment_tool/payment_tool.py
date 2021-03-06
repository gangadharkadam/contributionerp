# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _, scrub
from frappe.utils import flt
from frappe.model.document import Document
import json

class PaymentTool(Document):
	def make_journal_entry(self):
		from erpnext.accounts.utils import get_balance_on
		total_payment_amount = 0.00

		jv = frappe.new_doc('Journal Entry')
		jv.voucher_type = 'Journal Entry'
		jv.company = self.company
		jv.cheque_no = self.reference_no
		jv.cheque_date = self.reference_date

		if not self.total_payment_amount:
			frappe.throw(_("Please enter Payment Amount in atleast one row"))

		for v in self.get("vouchers"):
			if not frappe.db.get_value(v.against_voucher_type, {"name": v.against_voucher_no}):
				frappe.throw(_("Row {0}: {1} is not a valid {2}").format(v.idx, v.against_voucher_no,
					v.against_voucher_type))

			if v.payment_amount:
				d1 = jv.append("accounts")
				d1.account = self.party_account
				d1.party_type = self.party_type
				d1.party = self.party
				d1.balance = get_balance_on(self.party_account)
				d1.set("debit_in_account_currency" if self.received_or_paid=="Paid" \
					else "credit_in_account_currency", flt(v.payment_amount))
				d1.set("reference_type", v.against_voucher_type)
				d1.set("reference_name", v.against_voucher_no)
				d1.set('is_advance', 'Yes' if v.against_voucher_type in ['Sales Order', 'Purchase Order'] else 'No')
				total_payment_amount = flt(total_payment_amount) + \
					flt(d1.debit_in_account_currency) - flt(d1.credit_in_account_currency)

		d2 = jv.append("accounts")
		d2.account = self.payment_account
		d2.set('debit_in_account_currency' if total_payment_amount < 0 \
			else 'credit_in_account_currency', abs(total_payment_amount))
		if self.payment_account:
			d2.balance = get_balance_on(self.payment_account)

		return jv.as_dict()

@frappe.whitelist()
def get_outstanding_vouchers(args):
	from erpnext.accounts.utils import get_outstanding_invoices

	if not frappe.has_permission("Payment Tool"):
		frappe.throw(_("No permission to use Payment Tool"), frappe.PermissionError)

	args = json.loads(args)

	party_account_currency = frappe.db.get_value("Account", args.get("party_account"), "account_currency")
	company_currency = frappe.db.get_value("Company", args.get("company"), "default_currency")

	if args.get("party_type") == "Customer" and args.get("received_or_paid") == "Received":
		amount_query = "ifnull(debit_in_account_currency, 0) - ifnull(credit_in_account_currency, 0)"
	elif args.get("party_type") == "Supplier" and args.get("received_or_paid") == "Paid":
		amount_query = "ifnull(credit_in_account_currency, 0) - ifnull(debit_in_account_currency, 0)"
	else:
		frappe.throw(_("Please enter the Against Vouchers manually"))

	# Get all outstanding sales /purchase invoices
	outstanding_invoices = get_outstanding_invoices(amount_query, args.get("party_account"),
		args.get("party_type"), args.get("party"), with_journal_entry=False)

	# Get all SO / PO which are not fully billed or aginst which full advance not paid
	orders_to_be_billed = get_orders_to_be_billed(args.get("party_type"), args.get("party"),
		party_account_currency, company_currency)
	return outstanding_invoices + orders_to_be_billed

def get_orders_to_be_billed(party_type, party, party_account_currency, company_currency):
	voucher_type = 'Sales Order' if party_type == "Customer" else 'Purchase Order'

	ref_field = "base_grand_total" if party_account_currency == company_currency else "grand_total"

	orders = frappe.db.sql("""
		select
			name as voucher_no,
			ifnull({ref_field}, 0) as invoice_amount,
			(ifnull({ref_field}, 0) - ifnull(advance_paid, 0)) as outstanding_amount,
			transaction_date as posting_date
		from
			`tab{voucher_type}`
		where
			{party_type} = %s
			and docstatus = 1
			and ifnull(status, "") != "Stopped"
			and ifnull({ref_field}, 0) > ifnull(advance_paid, 0)
			and abs(100 - ifnull(per_billed, 0)) > 0.01
		""".format(**{
			"ref_field": ref_field,
			"voucher_type": voucher_type,
			"party_type": scrub(party_type)
		}), party, as_dict = True)

	order_list = []
	for d in orders:
		d["voucher_type"] = voucher_type
		order_list.append(d)

	return order_list

@frappe.whitelist()
def get_against_voucher_amount(against_voucher_type, against_voucher_no, party_account, company):
	party_account_currency = frappe.db.get_value("Account", party_account, "account_currency")
	company_currency = frappe.db.get_value("Company", company, "default_currency")
	ref_field = "base_grand_total" if party_account_currency == company_currency else "grand_total"

	if against_voucher_type in ["Sales Order", "Purchase Order"]:
		select_cond = "{0} as total_amount, ifnull({0}, 0) - ifnull(advance_paid, 0) as outstanding_amount"\
			.format(ref_field)
	elif against_voucher_type in ["Sales Invoice", "Purchase Invoice"]:
		select_cond = "{0} as total_amount, outstanding_amount".format(ref_field)
	elif against_voucher_type == "Journal Entry":
		ref_field = "total_debit" if party_account_currency == company_currency else "total_debit/exchange_rate"
		select_cond = "{0} as total_amount".format(ref_field)

	details = frappe.db.sql("""select {0} from `tab{1}` where name = %s"""
		.format(select_cond, against_voucher_type), against_voucher_no, as_dict=1)

	return details[0] if details else {}
