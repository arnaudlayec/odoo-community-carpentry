# -*- coding: utf-8 -*-

from odoo import models, fields, api

class StockMove(models.Model):
    _name = 'stock.move'
    _inherit = ['stock.move']

    price_unit = fields.Float(
        help="For permanent valuation. Product cost at move's confirmation.",
    )
    standard_price = fields.Float(
        related='product_id.standard_price',
        string='Product Cost',
        help='For temporary valuation. Current product cost.'
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
    )

    @api.depends('product_id', 'partner_id', 'company_id')
    def _compute_analytic_distribution(self):
        """ Apply analytic distribution model """
        for move in self:
            distribution = self.env['account.analytic.distribution.model']._get_distribution({
                "product_id": move.product_id.id,
                "product_categ_id": move.product_id.categ_id.id,
                "partner_id": move.partner_id.id,
                "partner_category_id": move.partner_id.category_id.ids,
                "company_id": move.company_id.id,
            })
            move.analytic_distribution = distribution or move.analytic_distribution
        
        self._compute_analytic_distribution_carpentry()
    
    def _prepare_analytic_lines(self):
        """Conflict between:
        - stock_account: update analytic
        - hr_timesheet: AccessError in write() if user_id != context.user_id
        """
        return super(
            StockMove, self.sudo()
        )._prepare_analytic_lines()
    