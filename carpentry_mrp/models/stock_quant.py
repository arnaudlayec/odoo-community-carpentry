# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.exceptions import ValidationError
from odoo.tools import config, float_compare

class StockQuant(models.Model):
    """ These logics are quite ugly, c.f. plan of the module `mrp_raw_material_confirmation`
        to rather update `stock.quant`.`quantity`
    """
    _inherit = 'stock.quant'

    quantity_minus_outgoing_raw_material = fields.Float(
        string='Quantity (with real-time production)',
        compute='_compute_quantity_minus_outgoing_raw_material',
    )

    @api.depends('quantity', 'product_id.stock_move_ids')
    def _compute_quantity_minus_outgoing_raw_material(self):
        """ Consider outgoing qties of MRP raw_material (`Consumed` column in MO) as already *out* """
        qties_outgoing_raw_material = self.product_id._get_qties_outgoing_raw_material()
        for quant in self:
            consumed = qties_outgoing_raw_material.get(quant.product_id.id, 0.0)
            quant.quantity_minus_outgoing_raw_material = quant.quantity - consumed

    def _compute_inventory_diff_quantity(self):
        """ Compare `inventory_quantity` with `quantity_minus_outgoing_raw_material`
            instead of `quantity`
        """
        super()._compute_inventory_diff_quantity()

        for quant in self:
            quant.inventory_diff_quantity = quant.inventory_quantity - quant.quantity_minus_outgoing_raw_material
    
    def _compute_is_outdated(self):
        super()._compute_is_outdated()

        self.is_outdated = False
        for quant in self:
            if quant.product_id and float_compare(
                quant.inventory_quantity - quant.inventory_diff_quantity,
                quant.quantity_minus_outgoing_raw_material,
                precision_rounding=quant.product_uom_id.rounding
            ) and quant.inventory_quantity_set:
                quant.is_outdated = True


    # === OVERRIDE OCA'S METHOD OF MODULE `stock_no_negative` ===
    @api.constrains("product_id", "quantity")
    def check_negative_qty(self):
        # To provide an option to skip the check when necessary.
        # e.g. mrp_subcontracting_skip_no_negative - passes the context
        # for subcontracting receipts.
        if self.env.context.get("skip_negative_qty_check"):
            return
        p = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        check_negative_qty = (
            config["test_enable"] and self.env.context.get("test_stock_no_negative")
        ) or not config["test_enable"]
        if not check_negative_qty:
            return

        for quant in self:
            disallowed_by_product = (
                not quant.product_id.allow_negative_stock
                and not quant.product_id.categ_id.allow_negative_stock
            )
            disallowed_by_location = not quant.location_id.allow_negative_stock
            if (
                float_compare(quant.quantity_minus_outgoing_raw_material, 0, precision_digits=p) == -1
                and quant.product_id.type == "product"
                and quant.location_id.usage in ["internal", "transit"]
                and disallowed_by_product
                and disallowed_by_location
            ):
                msg_add = ""
                if quant.lot_id:
                    msg_add = _(" lot {}").format(quant.lot_id.name_get()[0][1])
                raise ValidationError(
                    _(
                        "You cannot validate this stock operation because the "
                        "stock level of the product '{name}'{name_lot} would "
                        "become negative "
                        "({q_quantity}) on the stock location '{complete_name}' "
                        "and negative stock is "
                        "not allowed for this product and/or location."
                    ).format(
                        name=quant.product_id.display_name,
                        name_lot=msg_add,
                        q_quantity=quant.quantity_minus_outgoing_raw_material,
                        complete_name=quant.location_id.complete_name,
                    )
                )
