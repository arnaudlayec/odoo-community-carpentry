# -*- coding: utf-8 -*-

from odoo import models, fields, api
from collections import defaultdict

class ManufacturingOrder(models.Model):
    _name = 'mrp.production'
    _inherit = ['mrp.production', 'carpentry.planning.mixin']
    _rec_name = 'display_name'
    _rec_names_search = ['name', 'description']

    #===== Fields methods =====#
    def _compute_display_name(self):
        for mo in self:
            mo.display_name = '[{}] {}' . format(mo.name, mo.description) if mo.description else mo.name
    
    #===== Fields =====#
    description = fields.Char(string='Description')
    launch_ids = fields.Many2many(
        comodel_name='carpentry.group.launch',
        relation='mrp_production_launch_rel',
        string='Launches',
        domain="[('project_id', '=', project_id)]",
    )
    move_raw_unsatified_product_ids = fields.One2many(
        string="Unsatisfied components",
        comodel_name="product.product",
        compute="_compute_move_raw_unsatified_product_ids",
    )
    # -- related POs --
    purchase_ids = fields.Many2many(
        string='Related Purchase Orders',
        related='launch_ids.purchase_ids'
    )
    purchase_order_count = fields.Integer(
        # from `purchase_mrp`
        string='Count of linked PO'
    )
    # -- for planning --
    active = fields.Boolean(default=True, string='Active?')
    sequence = fields.Integer(string='Sequence')
    
    #===== Linked Purchase Orders =====#
    @api.depends('launch_ids')
    def _compute_purchase_order_count(self):
        for production in self:
            production.purchase_order_count = len(production._get_purchase_ids())
    
    def _get_purchase_ids(self):
        return (
            self.procurement_group_id.stock_move_ids.created_purchase_line_id.order_id |
            self.procurement_group_id.stock_move_ids.move_orig_ids.purchase_line_id.order_id |
            self.launch_ids.purchase_ids
        )
    
    def action_view_purchase_orders(self):
        return super().action_view_purchase_orders() | {
            'domain': [('id', 'in', self._get_purchase_ids().ids)]
        }
    
    #===== Picking =====#
    @api.depends_context("unsatisfied_mrp_product_ids")
    @api.depends("move_raw_ids.product_id")
    def _compute_move_raw_unsatified_product_ids(self):
        product_ids = self._context.get("unsatisfied_mrp_product_ids")
        if not product_ids:
            self.move_raw_unsatified_product_ids = False
            return
        
        for mo in self:
            mo.move_raw_unsatified_product_ids = list(
                set(mo.move_raw_ids.product_id.ids) &
                set(product_ids)
            )

    #===== Logics =====#
    def _action_cancel(self):
        """ Forces the cancelling of `done` move_raw_ids """
        super()._action_cancel()
        move_done = self.move_raw_ids.filtered(lambda x: x.state in ('done'))
        move_done.quantity_done = 0.0

    #===== Planning =====#
    def _get_planning_domain(self):
        return [('state', '!=', 'cancel')]
    
    @api.depends('reservation_state', 'components_availability_state')
    def _compute_planning_card_color_class(self):
        for mo in self:
            if mo.reservation_state == 'assigned' or mo.components_availability_state == 'available':
                color = 'success'
            elif mo.reservation_state != 'assigned' and mo.components_availability_state in ('expected', 'available'):
                color = 'warning'
            elif mo.reservation_state != 'assigned' and mo.components_availability_state == 'late':
                color = 'danger'
            else:
                color = 'muted'
            
            mo.planning_card_color_class = color
