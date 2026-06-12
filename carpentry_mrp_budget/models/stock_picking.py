# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class StockPicking(models.Model):
    """ Budget Reservation on pickings """
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'carpentry.budget.mixin']
    _record_field = 'picking_id'
    _record_fields_expense = ['move_ids']
    _carpentry_budget_notebook_page_xpath = '//page[@name="operations"]'
    _carpentry_budget_last_valuation_step = _('products revaluation')

    #====== Fields ======#
    reservation_ids = fields.One2many(inverse_name='picking_id')
    expense_ids = fields.One2many(inverse_name='picking_id')
    budget_analytic_ids = fields.Many2many(
        relation='carpentry_budget_picking_analytic_rel',
        column1='picking_id',
        column2='analytic_id',
    )
    
    #===== Budget reservation configuration =====#
    def _get_budget_types(self):
        return ['goods', 'other']
    
    def _depends_reservation_refresh(self):
        return super()._depends_reservation_refresh() + [
            'move_ids.product_uom_qty',
            'move_ids.analytic_distribution',
        ]
    def _depends_expense_totals(self):
        return super()._depends_expense_totals() + [
            'state',
            'move_ids.product_id.standard_price',
        ]
    def _flush_budget(self):
        """ Needed for correct computation of totals """
        self.env['ir.property'].flush_model(['value_float']) # standard_price
        return super()._flush_budget()
    
    def _should_value_budget_reservation(self):
        return True

    def _depends_can_reserve_budget(self):
        return super()._depends_can_reserve_budget() + ['picking_type_code', 'purchase_id']
    def _get_domain_can_reserve_budget(self):
        """ Prevent budget reservation on picking coming from:
            - internal, incoming, fab (returns from sconstruction field)
            - purchase orders
            - manufacturing orders
        """
        return super()._get_domain_can_reserve_budget() + [
            ('purchase_id', '=', False),
            ('picking_type_code', '=', 'outgoing'),
        ]
    
    def _get_domain_is_temporary_gain(self):
        return [('state', '!=', 'done'),]

    #===== Compute: date & amounts =====#
    @api.depends('scheduled_date', 'date_done')
    def _compute_date_budget(self):
        for picking in self:
            if picking.state == 'done':
                picking.date_budget = picking.date_done
            else:
                picking.date_budget = picking.scheduled_date
        return super()._compute_date_budget()

    #===== Buttons =====#
    def action_confirm(self):
        """Module `stock_analytic`: validate analytic right at picking confirm"""
        self = self.with_context(validate_analytic=True)
        return super().action_confirm()
