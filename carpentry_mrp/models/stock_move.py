# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from odoo.tools import float_compare

class StockMoveLine(models.Model):
    _inherit = ['stock.move.line']

    launch_ids = fields.Many2many(related='move_id.launch_ids')

class StockMove(models.Model):
    _name = 'stock.move'
    _inherit = ['stock.move', 'carpentry.planning.mixin']

    #===== ORM methods =====#
    def _compute_display_name(self):
        """ Planning's card layout """
        if not self._context.get('carpentry_planning'):
            return super()._compute_display_name()

        for move in self:
            move.display_name = move.product_id.display_name

    #===== Fields =====#
    launch_ids = fields.Many2many(
        comodel_name='carpentry.group.launch',
        compute='_compute_launch_ids',
        search='_search_launch_ids',
        string='Launches'
    )
    # -- for planning --
    project_id = fields.Many2one(store=True)
    active = fields.Boolean(default=True)
    product_default_code = fields.Char(related='product_id.default_code')
    product_name = fields.Char(related='product_id.name')

    #===== CRUD =====#
    def write(self, vals):
        """ For MO's components, ensure `product_uom_qty` is >= `quantity_done`
            Because `product_uom_qty` is used for for stock forecast
            (just do like when the `stock.move` is validated)
        """
        res = super().write(vals)
        raw_material_ids = self.filtered('raw_material_production_id')
        raw_material_ids._synch_product_uom_qty_done()
        raw_material_ids.product_id.stock_quant_ids.check_negative_qty() # ALY - 2025-08-21 : to be removed when `mrp_raw_material_confirmation` is ready
        return res
    
    def _synch_product_uom_qty_done(self):
        """ Updates any `product_uom_qty` >= `quantity_done` to `quantity_done` """
        for move in self:
            if move.quantity_done > move.product_uom_qty:
                move.product_uom_qty = move.quantity_done

    def unlink(self):
        """ *Delete* button is always displayed for `move_raw_ids` and behaves like:
            - unlinks `move_raw_ids` if possible ;
            - else (if move is `done`), sets qty to 0 instead
        """
        move_raw_ids = self.filtered('raw_material_production_id')
        to_cancel = move_raw_ids.filtered(lambda x: x.state != 'cancel')
        to_unlink = self - to_cancel

        # Unlink normally if possible (or if not raw material)
        super(StockMove, to_unlink).unlink()
        
        if to_cancel:
            # Not cancellable components: quantity_done = 0
            to_zero = to_cancel.filtered(lambda x: x.state == 'done')
            to_zero.quantity_done = 0.0

            # If components can be canceled: cancel & delete
            (to_cancel - to_zero)._action_cancel()
            super(StockMove, to_cancel - to_zero).unlink()

    #===== Compute =====#
    def _compute_launch_ids(self):
        """ Computes `launch_ids` from Picking or MO """
        for move in self:
            move.launch_ids = move.picking_id.launch_ids | move.raw_material_production_id.launch_ids
    
    def _search_launch_ids(self, operator, value):
        return ['|',
            ('picking_id.launch_ids', operator, value),
            ('raw_material_production_id.launch_ids', operator, value),
        ]
    
    @api.depends('quantity_done')
    def _compute_is_done(self):
        """ Overrwrite native field to order move_raw_ids by `done` """
        super()._compute_is_done()
        prec = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for move in self:
            comp = float_compare(move.quantity_done, move.product_uom_qty, precision_digits=prec)
            move.is_done = bool(comp >= 0)

    #===== Planning =====#
    def _get_planning_domain(self):
        """ Filter the records displayed in the planning view """
        return [('state', 'in', ['confirmed', 'partially_available'])]
    
    def action_open_planning_card(self):
        """ Opens conditionally the MO or the Picking """
        if self.raw_material_production_id:
            model = 'mrp.production'
            res_id = self.raw_material_production_id.id
        else:
            model = 'stock.picking'
            res_id = self.picking_id.id
        
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': model,
            'res_id': res_id,
            'view_mode': 'form',
            'target': 'new',
        }
<<<<<<< HEAD

    #===== Move to Delivery picking =====#
    def button_move_to_onsite_picking(self):
        """ Moves components (`stock.move`) from a MO (`mrp.production`)
            to a Picking (`stock.picking`)
        """
        for move in self:
            picking = move.raw_material_production_id.delivery_picking_id
            if not picking:
                raise exceptions.UserError(_(
                    'You must first define a Delivery picking.'
                ))
            if picking.state in ['done', 'cancel']:
                raise exceptions.UserError(_(
                    'The Delivery picking defined on the Manufacturing Order is already '
                    'closed. Update it to an open one to continue.'
                ))
            
            move.write(move._reset_mo_vals() | {
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
    
    def _reset_mo_vals(self):
        return {
            'created_production_id': False,
            'raw_material_production_id': False,
            'unbuild_id': False,
            'consume_unbuild_id': False,
            'operation_id': False,
            'workorder_id': False,
            'bom_line_id': False,
            'byproduct_id': False,
            'unit_factor': False,
            'is_done': False,
            'cost_share': False,
            'manual_consumption': False,
        }
=======
>>>>>>> 88c87e8 ([CLEAN] Remove unused field 'delivery_picking_id')
