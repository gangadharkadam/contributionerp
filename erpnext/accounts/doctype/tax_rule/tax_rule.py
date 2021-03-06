# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

class IncorrectCustomerGroup(frappe.ValidationError): pass
class IncorrectSupplierType(frappe.ValidationError): pass
class ConflictingTaxRule(frappe.ValidationError): pass

class TaxRule(Document):
	def validate(self):
		self.validate_tax_template()
		self.validate_customer_group()
		self.validate_supplier_type()
		self.validate_date()
		self.validate_filters()

	def validate_tax_template(self):
		if self.tax_type== "Sales":
			self.purchase_tax_template = self.supplier = self.supplier_type= None
		else:
			self.sales_tax_template= self.customer = self.customer_group= None
		
		if not (self.sales_tax_template or self.purchase_tax_template):
			frappe.throw(_("Tax Template is mandatory."))

	def validate_customer_group(self):
		if self.customer and self.customer_group:
			if not frappe.db.get_value("Customer", self.customer, "customer_group") == self.customer_group:
				frappe.throw(_("Customer {0} does not belong to customer group {1}"). \
					format(self.customer, self.customer_group), IncorrectCustomerGroup)
	
	def validate_supplier_type(self):
		if self.supplier and self.supplier_type:
			if not frappe.db.get_value("Supplier", self.supplier, "supplier_type") == self.supplier_type:
				frappe.throw(_("Supplier {0} does not belong to Supplier Type {1}"). \
					format(self.supplier, self.supplier_type), IncorrectSupplierType)

	def validate_date(self):
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(_("From Date cannot be greater than To Date"))

	def validate_filters(self):
		filters = {
			"tax_type":			self.tax_type,
			"customer": 		self.customer,
			"customer_group": 	self.customer_group,
			"supplier":			self.supplier,
			"supplier_type":	self.supplier_type,
			"billing_city":		self.billing_city,
			"billing_state": 	self.billing_state,
			"billing_country":	self.billing_country,
			"shipping_city":	self.shipping_city,
			"shipping_state":	self.shipping_state,
			"shipping_country":	self.shipping_country,
			"company":			self.company
		}
		
		conds=""
		for d in filters:
			if conds:
				conds += " and "
			conds += """ifnull({0}, '') = '{1}'""".format(d, frappe.db.escape(cstr(filters[d])))
		
		if self.from_date and self.to_date:
			conds += """ and ((from_date > '{from_date}' and from_date < '{to_date}') or
					(to_date > '{from_date}' and to_date < '{to_date}') or
					('{from_date}' > from_date and '{from_date}' < to_date) or
					('{from_date}' = from_date and '{to_date}' = to_date))""".format(from_date=self.from_date, to_date=self.to_date)
					
		elif self.from_date and not self.to_date:
			conds += """ and to_date > '{from_date}'""".format(from_date = self.from_date)

		elif self.to_date and not self.from_date:
			conds += """ and from_date < '{to_date}'""".format(to_date = self.to_date)
		
		tax_rule = frappe.db.sql("select name, priority \
			from `tabTax Rule` where {0} and name != '{1}'".format(conds, self.name), as_dict=1) 
		
		if tax_rule:
			if tax_rule[0].priority == self.priority:
				frappe.throw(_("Tax Rule Conflicts with {0}".format(tax_rule[0].name)), ConflictingTaxRule)

@frappe.whitelist()
def get_party_details(party, party_type, args=None):
	out = {}
	if args:
		billing_filters=	{"name": args.get("billing_address")}
		shipping_filters=	{"name": args.get("shipping_address")}
	else:
		billing_filters=	{party_type: party, "is_primary_address": 1}
		shipping_filters=	{party_type:party, "is_shipping_address": 1}
		
	billing_address=	frappe.get_all("Address", fields=["city", "state", "country"], filters= billing_filters)
	shipping_address=	frappe.get_all("Address", fields=["city", "state", "country"], filters= shipping_filters)
	
	if billing_address:
		out["billing_city"]= billing_address[0].city
		out["billing_state"]= billing_address[0].state
		out["billing_country"]= billing_address[0].country

	if shipping_address:
		out["shipping_city"]= shipping_address[0].city
		out["shipping_state"]= shipping_address[0].state
		out["shipping_country"]= shipping_address[0].country
		
	return out

def get_tax_template(posting_date, args):
	"""Get matching tax rule"""
	args = frappe._dict(args)
	conditions = []

	for key, value in args.iteritems():
		conditions.append("ifnull({0}, '') in ('', '{1}')".format(key, frappe.db.escape(cstr(value))))

	matching = frappe.db.sql("""select * from `tabTax Rule`
		where {0}""".format(" and ".join(conditions)), as_dict = True)
		
	if not matching:
		return None
		
	for rule in matching:
		rule.no_of_keys_matched = 0
		for key in args:
			if rule.get(key): rule.no_of_keys_matched += 1
			
	rule = sorted(matching, lambda b, a: cmp(a.no_of_keys_matched, b.no_of_keys_matched) or cmp(a.priority, b.priority))[0]
	return rule.sales_tax_template or rule.purchase_tax_template