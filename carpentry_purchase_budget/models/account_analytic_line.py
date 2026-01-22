# -*- coding: utf-8 -*-

from odoo import api, fields, models

class AccountAnalyticLine(models.Model):
    _inherit = ['account.analytic.line']

    # for SQL view
    move_id = fields.Many2one(
        string='Account Move',
        related='move_line_id.move_id',
        store=True,
    )
    purchase_id = fields.Many2one(
        string='Purchase Order',
        related='move_line_id.purchase_line_id.order_id',
        store=True,
    )
