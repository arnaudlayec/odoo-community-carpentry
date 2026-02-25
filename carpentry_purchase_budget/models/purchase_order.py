# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ['purchase.order', 'carpentry.budget.mixin']
    _record_field = 'purchase_id'
    _record_fields_expense = ['order_line', 'invoice_ids']
    _carpentry_budget_notebook_page_xpath = '//page[@name="products"]'
    _carpentry_budget_last_valuation_step = _('billing')

    #====== Fields ======#
    reservation_ids = fields.One2many(inverse_name='purchase_id')
    expense_ids = fields.One2many(inverse_name='purchase_id',)
    budget_analytic_ids = fields.Many2many(
        relation='carpentry_budget_purchase_analytic_rel',
        column1='order_id',
        column2='analytic_id',
    )

    #====== CRUD ======#
    def _compute_reservation_ids(self, vals={}):
        if (
            not self
            or isinstance(fields.first(self).id, models.NewId)
            or self._context.get('carpentry_dont_refresh_reservations')
        ):
            return
        
        if 'budget_analytic_ids' in vals: # user choosed manually the budget centers
            # ctx: avoid calling twice `_compute_reservation_ids`,
            # since `line.analytic_distribution` is also in @depends
            ctx_self = self.with_context(carpentry_dont_refresh_reservations=True)
            ctx_self._cascade_order_budgets_to_line_analytic()
        
        return super()._compute_reservation_ids(vals)
    
    def _cascade_order_budgets_to_line_analytic(self):
        """ Manual budget choice => update line's analytic distribution """
        domain=[('is_project_budget', '=', True)]
        budget_analytics_ids = self.env['account.analytic.account'].search(domain).ids

        for order in self:
            project_budgets = order.project_id.budget_line_ids.analytic_account_id
            new_budgets = order.budget_analytic_ids & project_budgets # in the PO lines and the project

            order.order_line._cascade_order_budgets_to_line_analytic(new_budgets, budget_analytics_ids)

    #====== Budget reservation configuration ======#
    def _get_budget_types(self):
        return ['goods', 'other']
    
    def _should_value_budget_reservation(self):
        return True
    
    def _depends_reservation_refresh(self):
        return super()._depends_reservation_refresh() + [
            'order_line.analytic_distribution',
            'amount_untaxed',
        ]
    def _depends_expense_totals(self):
        return super()._depends_expense_totals() + [
            'invoice_ids.invoice_line_ids.analytic_line_ids',
        ]
    def _depends_can_reserve_budget(self):
        return super()._depends_can_reserve_budget() + ['order_line']
    def _get_domain_can_reserve_budget(self):
        """ Can't reserve budget of all lines are *storable* product """
        return super()._get_domain_can_reserve_budget() + [
            # will be True as soon as 1 line is != product
            ('order_line', '!=', False),
            ('order_line.product_id.type', 'in', ['consu', 'service']),
        ]
    def _get_domain_is_temporary_gain(self):
        return [('invoice_status', '!=', 'invoiced')]
    
    def _get_default_active(self):
        """ Default `active` for purchase **reservations** """
        return super()._get_default_active() and (
            self.state not in ('draft', 'sent', 'to approve', 'cancel')
        )

    def _flush_budget(self):
        super()._flush_budget()
        self.invoice_ids.line_ids.flush_recordset()

    # def _get_auto_budget_analytic_ids(self, _):
    #     """ Used in `_populate_budget_analytics`,
    #         for `budget_analytic_ids` to follow the expense
    #     """
    #     return (
    #         self.order_line.analytic_account_ids
    #         + self.invoice_ids.line_ids.analytic_account_ids
    #     ).filtered('is_project_budget').ids
    
    #===== Compute: date & amounts =====#
    @api.depends('date_approve')
    def _compute_date_budget(self):
        for order in self:
            order.date_budget = order.date_approve
        return super()._compute_date_budget()
    