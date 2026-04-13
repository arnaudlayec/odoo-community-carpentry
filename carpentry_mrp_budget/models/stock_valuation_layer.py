# -*- coding: utf-8 -*-

from odoo import api, fields, models, tools

class StockValuationLayer(models.Model):
    _inherit = ['stock.valuation.layer']

    # for optimized `groupby`-sum in `stock.picking` and `mrp.production`
    stock_picking_id = fields.Many2one(
        related='stock_move_id.picking_id',
        store=True
    )
    raw_material_production_id = fields.Many2one(
        related='stock_move_id.raw_material_production_id',
        store=True
    )

    # for searchpanel
    stock_picking_type_id = fields.Many2one(
        related='stock_move_id.picking_type_id',
        store=True,
    )
