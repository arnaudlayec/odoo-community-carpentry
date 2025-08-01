# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.tools import float_round
from collections import defaultdict

class ManufacturingOrder(models.Model):
    """ Budget Reservation on MOs """
    _name = 'mrp.production'
    _inherit = ['mrp.production', 'carpentry.budget.reservation.mixin']

    #====== Fields ======#
    affectation_ids = fields.One2many(domain=[('section_res_model', '=', _name)])
    affectation_ids_components = fields.One2many(
        comodel_name='carpentry.group.affectation',
        inverse_name='section_id',
        domain=[('section_res_model', '=', _name), ('budget_type', 'in', ['goods', 'project_global_cost'])]
    )
    affectation_ids_workorders = fields.One2many(
        comodel_name='carpentry.group.affectation',
        inverse_name='section_id',
        domain=[('section_res_model', '=', _name), ('budget_type', 'in', ['production'])]
    )
    budget_analytic_ids = fields.Many2many(
        relation='carpentry_group_affectation_budget_mrp_analytic_rel',
        column1='production_id',
        column2='analytic_id',
        store=True,
        readonly=False,
    )
    budget_analytic_ids_workorder = fields.Many2many(
        related='budget_analytic_ids',
        string='Budget (work orders)',
        readonly=False,
        domain="""[
            ('budget_project_ids', '=', project_id),
            ('budget_type', 'in', ['production'])
        ]"""
    )
    amount_budgetable = fields.Monetary(string='Total cost (components)')
    amount_gain = fields.Monetary(string='Gain (components)')
    sum_quantity_affected = fields.Float(
        string='Budget (components)',
        help='Sum of budget reservation for components only'
    )
    currency_id = fields.Many2one(related='project_id.currency_id')
    sum_quantity_affected_workorders = fields.Float(
        string='Budget (workorders)',
        help='Sum of budget reservation in hours for workorders only',
        compute='_compute_sum_quantity_affected_workorders'
    )
    difference_workorder_duration_budget = fields.Float(
        compute='_compute_sum_quantity_affected_workorders'
    )
    amount_gain_workorders = fields.Monetary(
        compute='_compute_sum_quantity_affected_workorders'
    )

    #===== Affectations configuration =====#
    def _get_budget_types(self):
        return ['production'] + self._get_component_budget_types()
    
    def _should_mo_reserve_budget(self):
        return self.state not in ['cancel']
    
    def _get_component_budget_types(self):
        return ['goods', 'project_global_cost']
    
    def _get_fields_affectation_refresh(self):
        return super()._get_fields_affectation_refresh() + ['move_raw_ids', 'affectation_ids_production']

    @api.depends('date_planned_start', 'date_finished')
    def _compute_date_budget(self):
        for mo in self:
            mo.date_budget = mo.date_finished or mo.date_planned_start
        return super()._compute_date_budget()
    
    #===== Affectations: compute =====#
    @api.depends('affectation_ids', 'affectation_ids.quantity_affected')
    def _compute_sum_quantity_affected_workorders(self):
        prec = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for mo in self:
            mo.sum_quantity_affected_workorders = sum(mo.affectation_ids_workorders.mapped('quantity_affected'))
            mo.difference_workorder_duration_budget = float_round(
                mo.production_duration_hours_expected -
                mo.sum_quantity_affected_workorders,
                precision_digits = prec
            )
            mo.amount_gain_workorders = float_round(
                mo.sum_quantity_affected_workorders -
                mo.production_real_duration_hours,
                precision_digits = prec
            )

    @api.depends('move_raw_ids', 'move_raw_ids.product_id')
    def _compute_budget_analytic_ids(self):
        """ MO's budgets are updated automatically from:
            - component's analytic distribution model
            (- workcenter's analytics [STOPPED - ALY 2025-03-12] -> now only manual)

            (!) Let's be careful to keep manually chosen analytics (for workcenters)
        """
        to_clean = self.filtered(lambda x: not x._should_mo_reserve_budget())
        to_clean.budget_analytic_ids = False

        to_compute = (self - to_clean).filtered('project_id')
        if to_compute:
            mapped_analytics = self._get_mapped_project_analytics()
            budget_types = self._get_component_budget_types()

            for mo in to_compute:
                project_budgets = set(mapped_analytics.get(mo.project_id.id, []))

                existing = set(mo.budget_analytic_ids.filtered(lambda x: x.budget_type in budget_types)._origin.ids)
                to_add = set(mo.move_raw_ids.analytic_ids._origin.ids) & project_budgets
                to_remove = existing - to_add
                if to_add:
                    mo.budget_analytic_ids = [Command.link(x) for x in to_add]
                if to_remove:
                    mo.budget_analytic_ids = [Command.unlink(x) for x in to_remove]

        return super()._compute_budget_analytic_ids()
    
    def _get_total_by_analytic(self):
        """ Group-sum real cost of components for automated budget reservation
            Component's cost is `qty * move._get_price_unit()`
            => At reservation's time, the OF is not validated (draft or in progress)
               thus the move most likely not valuated, so `_get_price_unit()` will return
               `product.standard_cost`

            :return: Dict like {analytic_id: charged amount}
        """
        self.ensure_one()
        to_compute_move_raw = self.filtered(lambda x: x._should_mo_reserve_budget())
        if not to_compute_move_raw:
            return {}

        mapped_analytics = to_compute_move_raw._get_mapped_project_analytics()
        mapped_cost = defaultdict(float)

        # Components
        for move in to_compute_move_raw.move_raw_ids:
            if not move.analytic_distribution:
                continue
            
            for analytic_id, percentage in move.analytic_distribution.items():
                analytic_id = int(analytic_id)

                # Ignore cost if analytic not in project's budget
                if not analytic_id in mapped_analytics.get(move.project_id.id, []):
                    continue
                # qty in product.uom_id
                qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id)
                unit_price = (
                    move.product_id.standard_price
                    if move.raw_material_production_id.state in ['waiting', 'confirmed', 'partially_available', 'assigned']
                    else move._get_price_unit()
                )
                mapped_cost[analytic_id] += qty * unit_price * percentage / 100
        
        # [STOPPED - ALY 2025-03-12] -> Workcenter budget reservation is
        #  now only manual for workcenter and 0,00h by default
        # for wo in self.workorder_ids:
        #     analytic = wo.workcenter_id.costs_hour_account_id
        #     # Ignore cost if analytic not in project's budget
        #     if analytic.id in mapped_analytics.get(wo.project_id.id, []):
        #         mapped_cost[analytic.id] += wo.duration_expected / 60 # in hours

        return mapped_cost

    #====== Compute amount ======#
    @api.depends(
        'move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.product_id.standard_price',
        'move_raw_ids.price_unit', 'move_raw_ids.stock_valuation_layer_ids',
    )
    def _compute_amount_budgetable(self):
        """ MO's **COMPONENTS-ONLY** cost is like for picking:
            - its moves valuation when valuated
            - else, estimation via products' prices
        """
        to_compute = self.filtered(lambda x: x._should_mo_reserve_budget())
        (self - to_compute).amount_budgetable = False
        if not to_compute:
            return
        
        rg_result = self.env['stock.valuation.layer'].sudo().read_group(
            domain=[('raw_material_production_id', 'in', to_compute.ids)],
            fields=['value:sum'],
            groupby=['raw_material_production_id']
        )
        mapped_svl_values = {x['raw_material_production_id'][0]: x['value'] for x in rg_result}
        for production in to_compute:
            production.amount_budgetable = abs(mapped_svl_values.get(
                production._origin.id,
                sum(production._get_total_by_analytic().values())
            ))
    
    def _compute_sum_quantity_affected(self):
        """ [Overwritte] `sum_quantity_affected` and `gain` are for filtered for components only (goods), not workorder (hours) """
        budget_types = self._get_component_budget_types()
        for production in self:
            affectations_goods = production.affectation_ids.filtered(lambda x: x.group_ref and x.group_ref.budget_type in budget_types)
            production.sum_quantity_affected = sum(affectations_goods.mapped('quantity_affected'))
    
    @api.depends('move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.stock_valuation_layer_ids')
    def _compute_amount_gain(self):
        return super()._compute_amount_gain()
