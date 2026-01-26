# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command

class PurchaseOrderLine(models.Model):
    _inherit = ['purchase.order.line']
    _rec_name = 'display_name'

    @api.depends('product_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = (
                (line.product_id.name or '') +
                ' (%s)' % line.product_qty if line.product_qty else ''
            )
