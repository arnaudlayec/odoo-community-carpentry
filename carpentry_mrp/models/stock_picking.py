# -*- coding: utf-8 -*-

from odoo import api, models, fields, exceptions, _, Command

class StockPicking(models.Model):
    _inherit = ['stock.picking']

    #===== Fields methods =====#
    def _compute_display_name(self):
        for mo in self:
            mo.display_name = '[{}] {}' . format(mo.name, mo.description) if mo.description else mo.name
    
    #===== Fields =====#
    description = fields.Char(
        string='Description',
        compute='_compute_launch_ids_description',
        store=True,
        readonly=False,
    )
    launch_ids = fields.Many2many(
        string='Launches',
        comodel_name='carpentry.group.launch',
        relation='stock_picking_launch_rel',
        compute='_compute_launch_ids_description',
        store=True,
        readonly=False,
        domain="[('project_id', '=', project_id)]"
    )
    group_id = fields.Many2one(
        related=None, # cancel native, managed in compute
        compute="_compute_group_id",
        store=True,
    )
    mrp_production_ids = fields.One2many(
        # field from module `mrp_project_link`
        domain="[('project_id', '=', project_id), ('state', 'not in', ['done', 'cancel'])]",
        inverse="_inverse_mrp_production_ids",
    )
    unsatisfied_mrp_production_ids = fields.One2many(
        string="Unsatisfied Manufacturing Orders",
        comodel_name="mrp.production",
        compute="_compute_unsatisfied_mrp",
    )
    unsatisfied_mrp_product_ids = fields.One2many(
        string="Unsatisfied Components",
        comodel_name="product.product",
        compute="_compute_unsatisfied_mrp",
    )

    #===== Compute =====#
    @api.depends(
        'purchase_id', 'purchase_id.launch_ids', 'purchase_id.description',
        'mrp_production_ids', 'mrp_production_ids.launch_ids', 'mrp_production_ids.description',
    )
    def _compute_launch_ids_description(self):
        for picking in self:
            po = picking.purchase_id
            mo = picking.mrp_production_ids

            picking.launch_ids = [Command.set((po.launch_ids | mo.launch_ids)._origin.ids)]
            picking.description = (
                picking.description or
                po.description or
                mo.description
            )

    @api.model
    def _search_launch_ids(self, operator, value):
        return ['|',
            ('mrp_production_ids.launch_ids', operator, value),
            ('purchase_id.launch_ids', operator, value),
        ]

    def _compute_unsatisfied_mrp(self):
        """ Look for all opened MOs having (only for incoming/purchase reception):
            - at least 1 common component with the picking's product
            - this component not fully done/out
        """
        pickings = self.filtered(lambda x: x.picking_type_code == 'incoming')
        (self - pickings).update({
            "unsatisfied_mrp_production_ids": False,
            "unsatisfied_mrp_product_ids": False,
        })
        if not pickings:
            return

        rg_result = self.env["stock.move"]._read_group(
            domain=[
                ("is_done", "=", False),
                ("product_id", "in", self.product_id.ids),
                ("raw_material_production_id.state", "in", ["confirmed", "progress", "to_close"]),
            ],
            groupby=["product_id"],
            fields=["raw_material_production_id:array_agg"],
        )
        mapped_data = {
            x["product_id"][0]: x["raw_material_production_id"]
            for x in rg_result
        }
        for picking in pickings:
            mo_ids, product_ids = [], []
            for product_id in picking.product_id.ids:
                unsatisfied_mos = mapped_data.get(product_id, [])
                if unsatisfied_mos:
                    mo_ids += unsatisfied_mos
                    product_ids.append(product_id)
            picking.unsatisfied_mrp_production_ids = mo_ids or False
            picking.unsatisfied_mrp_product_ids = product_ids or False

    def _inverse_mrp_production_ids(self):
        """Link the MOs of `mrp_production_ids` with the picking
        through the Procurement Group (native)"""
        for picking in self:
            mos = picking.mrp_production_ids
            group_mo = fields.first(mos.procurement_group_id)
            group_mo.mrp_production_ids = [Command.link(x.id) for x in mos]
            picking._set_new_procurement_group(group_mo)
            picking.origin = ", " . join(mos.mapped("name"))
        # required, else not trigerred at form saving
        self._compute_launch_ids_description()

    def _set_new_procurement_group(self, group):
        """Force `group_id` on picking, if not already defined by its moves"""
        existing_group = self.move_ids.group_id
        if existing_group and existing_group != group:
            raise exceptions.UserError(_(
                "A different Procurement Group is already defined by the stock moves."
            ))

        # `stock_picking.group_id` is a stored related field from `move_ids`
        if existing_group:
            self.move_ids.group_id = group
        else:
            self.group_id = group

    @api.depends("move_ids.group_id", "mrp_production_ids")
    def _compute_group_id(self):
        """Replace native 'related' by this compute, to make `group_id`
        persistent when already set by `_inverse_mrp_production_ids`.
        Use-case: when creating a picking without moves."""
        for picking in self:
            picking.group_id = picking.move_ids.group_id or picking.group_id

    #===== Action =====#
    def action_open_unsatisfied_mrp_production(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
            "name": _("Unsatisfied Manufacturing Orders"),
            "domain": [("id", "in", self.unsatisfied_mrp_production_ids.ids)],
            "context": self._context | {
                "unsatisfied_mrp_product_ids": self.unsatisfied_mrp_product_ids.ids
            },
            "views": [
                (self.env.ref("carpentry_mrp.mrp_production_tree_view_unsatisfied").id, "tree"),
                (self.env.ref("mrp.mrp_production_form_view").id, "form"),
            ],
        }
