# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.exceptions import ValidationError
from odoo.tools import config, float_compare

class StockQuant(models.Model):
    _inherit = ['stock.quant']

    quantity_without_outgoing_raw_material = fields.Float(
        string='Quantity (with real-time production)',
        compute='_compute_quantity_without_outgoing_raw_material',
    )

    @api.depends('quantity', 'product_id.stock_move_ids')
    def _compute_quantity_without_outgoing_raw_material(self):
        """ Consider outgoing qties of MRP raw_material (`Consumed` column in MO) as already *out* """
        qties_outgoing_raw_material = self.product_id._get_qties_outgoing_raw_material()
        for quant in self:
            consumed = qties_outgoing_raw_material.get(quant.product_id.id, 0.0)
            quant.quantity_without_outgoing_raw_material = quant.quantity - consumed

    def _compute_inventory_diff_quantity(self):
        """ Compare `inventory_quantity` with `quantity_without_outgoing_raw_material`
            instead of `quantity`
        """
        super()._compute_inventory_diff_quantity()

        for quant in self:
            quant.inventory_diff_quantity = quant.inventory_quantity - quant.quantity_without_outgoing_raw_material
    
    def _compute_is_outdated(self):
        super()._compute_is_outdated()

        self.is_outdated = False
        for quant in self:
            if quant.product_id and float_compare(
                quant.inventory_quantity - quant.inventory_diff_quantity,
                quant.quantity_without_outgoing_raw_material,
                precision_rounding=quant.product_uom_id.rounding
            ) and quant.inventory_quantity_set:
                quant.is_outdated = True
