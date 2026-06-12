# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.tools import float_round, float_compare

class ManufacturingOrder(models.Model):
    """ Budget Reservation on MOs """
    _name = 'mrp.production'
    _inherit = ['mrp.production', 'carpentry.budget.mixin']
    _record_field = 'production_id'
    _record_fields_expense = ['move_raw_ids', 'workorder_ids']
    _carpentry_budget_notebook_page_xpath = '//page[@name="components"]'
    _carpentry_budget_sheet_name = 'Budget (components)'
    _carpentry_budget_last_valuation_step = _('products revaluation')

    #====== Fields ======#
    reservation_ids = fields.One2many(
        inverse_name='production_id',
    )
    expense_ids = fields.One2many(inverse_name='production_id')
    reservation_ids_components = fields.One2many(
        comodel_name='carpentry.budget.reservation',
        inverse_name='production_id',
        domain=[('budget_type', 'in', ['goods', 'other'])],
        context={'active_test': False},
    )
    reservation_ids_workorders = fields.One2many(
        comodel_name='carpentry.budget.reservation',
        inverse_name='production_id',
        domain=[('budget_type', 'in', ['production'])],
        context={'active_test': False},
    )
    budget_analytic_ids = fields.Many2many(
        relation='carpentry_budget_mrp_analytic_rel',
        column1='production_id',
        column2='analytic_id',
    )
    budget_analytic_ids_components = fields.Many2many(
        comodel_name='account.analytic.account',
        compute='_compute_budget_analytic_ids_mrp',
        inverse='_inverse_budget_analytic_ids_mrp',
        string='Budgets (components)',
    )
    budget_analytic_ids_workorders = fields.Many2many(
        comodel_name='account.analytic.account',
        compute='_compute_budget_analytic_ids_mrp',
        inverse='_inverse_budget_analytic_ids_workorders',
        string='Budgets (work orders)',
    )
    total_budget_reserved = fields.Float(
        string='Budget (components)',
        help='Sum of budget reservation for components only',
    )
    total_budget_reserved_workorders = fields.Float(
        string='Budget (workorders)',
        help='Sum of budget reservation in hours for workorders only',
        compute='_compute_total_budget_reserved',
        store=True,
    )
    difference_workorder_duration_budget = fields.Float(
        compute='_compute_difference_workorder_duration_budget',
    )
    total_expense_valued = fields.Monetary(string='Total cost (components)',)
    total_expense_valued_workorders = fields.Monetary(
        string='Total cost (work orders)',
        compute='_compute_total_expense_gain',
        store=True,
    )
    budget_unit_workorders = fields.Char(default='h')
    amount_gain = fields.Monetary(string='Gain (components)',)
    amount_gain_workorders = fields.Monetary(
        compute='_compute_total_expense_gain',
        store=True,
    )
    other_expense_ids_components = fields.Many2many(
        comodel_name='carpentry.budget.expense',
        string='Other expenses (components)',
        compute='_compute_other_expense_ids',
        context={'active_test': False},
    )
    other_expense_ids_workorders = fields.Many2many(
        comodel_name='carpentry.budget.expense',
        string='Other expenses (workorders)',
        compute='_compute_other_expense_ids',
        context={'active_test': False},
    )
    date_budget_workorders = fields.Date(
        compute='_compute_date_budget',
        string='Last date time',
        store=True,
    )
    # expenses (needed in SQL view)
    count_budget_resa_workorders = fields.Integer(
        compute='_compute_count_budget_resa_workorders',
        store=True,
    )
    production_real_duration = fields.Float(store=True)
    production_real_duration_hours = fields.Float(compute_sudo=True,)
    # -- view fields --
    amount_loss_workorders = fields.Monetary(compute='_compute_view_fields')
    total_budgetable_workorders = fields.Float(compute='_compute_view_fields',)
    show_gain_workorders = fields.Boolean(compute='_compute_view_fields',)
    show_budget_banner_workorders = fields.Boolean(compute='_compute_view_fields',)
    text_no_reservation_workorders = fields.Char(compute='_compute_view_fields',)
    is_temporary_gain_workorders = fields.Boolean(
        store=False,
        default=False,
    )

    #===== Native =====#
    @api.depends('project_id')
    def _compute_analytic_account_id(self):
        """ Inherite: set a default analytic account on MO
            to enable analytic line per WO, which computes workforce costs
        """
        super()._compute_analytic_account_id()

        for mo in self:
            if not mo.analytic_account_id:
                mo.analytic_account_id = mo.project_id.analytic_account_id

    #===== Compute =====#
    @api.depends('budget_analytic_ids')
    def _compute_count_budget_resa_workorders(self):
        """ Used in MRP SQL view """
        for record in self:
            record.count_budget_resa_workorders = len(set(record.reservation_ids_workorders.analytic_account_id))
        
    @api.depends('budget_analytic_ids')
    def _compute_budget_analytic_ids_mrp(self):
        budget_types_components = self._get_component_budget_types()
        budget_types_workorders = self._get_workorder_budget_types()
        for mo in self:
            mo.budget_analytic_ids_components = mo.budget_analytic_ids.filtered(
                lambda x: x.budget_type in budget_types_components
            )
            mo.budget_analytic_ids_workorders = mo.budget_analytic_ids.filtered(
                lambda x: x.budget_type in budget_types_workorders
            )
    
    def _inverse_budget_analytic_ids_workorders(self):
        self = self.with_context(budget_analytic_ids_workorders_inverse=True)
        self._inverse_budget_analytic_ids_mrp()

    def _inverse_budget_analytic_ids_mrp(self):
        """ Populate workorders budget center in main field budget_analytic_ids,
            without refreshing component's `amount_reserved`
        """
        for mo in self:
            existing = mo.budget_analytic_ids
            budget_analytic_origin = mo.budget_analytic_ids_workorders._origin + mo.budget_analytic_ids_components._origin
            to_add = budget_analytic_origin - existing
            to_remove = existing - budget_analytic_origin

            if to_add:
                mo.budget_analytic_ids += to_add
            if to_remove:
                mo.budget_analytic_ids -= to_remove
        
        mo.invalidate_recordset(['budget_analytic_ids']) # ensure correct value in next logics
    
    #===== Budgets customization =====#
    def _compute_reservation_ids(self, vals={}):
        """ Don't update reservation matrix on MO validation """
        if self._context.get('button_mark_done_production_ids'):
            return
        
        return super()._compute_reservation_ids(vals)
    
    def _auto_update_budget_reservation(self, rg_result):
        """ 1. Don't update *components* amounts while updating workorders budgets
            2. Never update *workorder* amounts automatically
        """
        # 1.
        if self._context.get('budget_analytic_ids_workorders_inverse'):
            return
        # 2.
        self = self.with_context(filter_budget_types=self._get_component_budget_types())
        super()._auto_update_budget_reservation(rg_result)

    #===== Budgets configuration =====#
    def _get_budget_types(self):
        return self._get_workorder_budget_types() + self._get_component_budget_types()
    def _get_workorder_budget_types(self):
        return ['production']
    def _get_component_budget_types(self):
        return ['goods', 'other']

    def _depends_reservation_refresh(self):
        return super()._depends_reservation_refresh() + [
            'move_raw_ids.product_uom_qty',
            'move_raw_ids.analytic_distribution',
        ]
    def _depends_expense_totals(self):
        return super()._depends_expense_totals() + [
            'move_raw_ids.product_id.standard_price',
            # done
            'state',
            'move_finished_ids.product_uom_qty',
            'move_finished_ids.analytic_distribution',
            'move_finished_ids.stock_valuation_layer_ids.value',
            # workorders: don't use `workorder_ids.duration` so
            # that `production_real_duration` is flushed
            'production_real_duration',
        ]

    def _get_domain_is_temporary_gain(self):
        return [('state', '!=', 'done'),]
    
    def _get_reservations_components(self):
        """ Filter reservations of workorders so their amount is never updated """
        return self.reservation_ids.filtered(
            lambda x: x.budget_type in self._get_component_budget_types()
        )
    
    #===== Budget reservation: date & compute =====#
    @api.depends(
        'date_planned_start', 'date_finished',
        'workorder_ids.time_ids.date_end',
    )
    def _compute_date_budget(self):
        """ Manages both `date_budget` for components and workorders """
        for mo in self:
            mo.date_budget = mo.date_finished or mo.date_planned_start
            dates_end = mo.workorder_ids.time_ids.filtered('date_end').mapped('date_end')
            mo.date_budget_workorders = max(dates_end) if bool(dates_end) else False
            
            # update reservations' dates
            reservations_components = mo._get_reservations_components()
            reservations_components.date = mo.date_budget
            (mo.reservation_ids - reservations_components).date = mo.date_budget_workorders

    def _compute_other_expense_ids(self):
        super()._compute_other_expense_ids()
        
        budget_types_components = self._get_component_budget_types()
        for mo in self:
            mo.other_expense_ids_components = mo.other_expense_ids.filtered(lambda x: x.budget_type in budget_types_components)
            mo.other_expense_ids_workorders = mo.other_expense_ids - mo.other_expense_ids_components

    def _get_auto_budget_analytic_ids(self, _):
        """ Only for components
            For workcenters: keep manually chosen budgets
        """
        Analytic = self.env['account.analytic.account']
        workcenter_budgets = self.budget_analytic_ids.filtered(
            lambda x: x.budget_type not in self._get_component_budget_types()
        )
        components_budgets = self.move_raw_ids.analytic_account_ids if self.can_reserve_budget else Analytic
        return (workcenter_budgets + components_budgets)._origin.ids

    #====== Compute amount ======#
    @api.depends(
        'reservation_ids_workorders.amount_reserved',
        'workorder_ids.duration_expected',
    )
    def _compute_difference_workorder_duration_budget(self):
        """ Difference displayed in *workorders* tab
            Don't use `total_budget_reserved_workorders` because it
            is not always the sum of `amount_reserved`
        """
        prec = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for mo in self:
            mo.difference_workorder_duration_budget = float_round(
                mo.production_duration_expected / 60 -
                sum(mo.reservation_ids_workorders.mapped('amount_reserved')),
                precision_digits = prec
            )

    def _get_rg_result_expense(self, rg_fields=[]):
        return super()._get_rg_result_expense(rg_fields=['budget_type:array_agg'])
    def _flush_budget(self):
        """ Needed for correct computation of totals """
        self.env['ir.property'].flush_model(['value_float']) # standard_price
        return super()._flush_budget()

    def _compute_total_budget_reserved_one(self):
        """ Overwrite """
        components_reservations = self._get_reservations_components()
        workorders_reservations = self.reservation_ids - components_reservations
        self.total_budget_reserved = sum(components_reservations.mapped('amount_reserved_valued'))
        self.total_budget_reserved_workorders = sum(workorders_reservations.mapped('amount_reserved'))
    
    def _compute_total_expense_gain(self, groupby_analytic=False, rg_result=None):
        """ Group by analytic for xxx_one """
        return super()._compute_total_expense_gain(
            groupby_analytic=True, rg_result=rg_result,
        )
    
    def _compute_total_expense_gain_one(self, totals,
        pivot_analytic_to_budget_type, field_suffix=''
    ):
        """ 1. Split `totals` between components and workorders
            2. Computes both totals
        """
        # 1.
        components_budget_types = self._get_component_budget_types()
        totals_workorders = {}
        for aac_id in totals.copy():
            budget_type = pivot_analytic_to_budget_type.get(aac_id)
            if budget_type not in components_budget_types:
                totals_workorders[aac_id] = totals.pop(aac_id)

        # 2.
        super()._compute_total_expense_gain_one(totals)
        super()._compute_total_expense_gain_one(totals_workorders, field_suffix='_workorders')

    def _compute_view_fields_one(self, prec, field_suffix):
        """ 1. Compute UI fields for both components and workorders
            2. Specific workorders logics
        """
        # 1.
        super()._compute_view_fields_one(prec, field_suffix)
        if not field_suffix:
            super()._compute_view_fields_one(prec, '_workorders')
        
        # 2.
        self['total_budgetable_workorders'] = sum(self.workorder_ids.mapped('duration_expected_hours'))
        
        compare = float_compare(
            self.total_budget_reserved_workorders, self.total_budgetable_workorders,
            precision_digits=prec
        )
        self['show_budget_banner_workorders'] = bool(compare != 0)

    #===== Buttons =====#
    def action_confirm(self):
        """Module `stock_analytic`: also validate MO analytic, right at MO confirm"""
        self = self.with_context(validate_analytic=True)
        return super().action_confirm()

    #===== Views =====#
    def _get_view_carpentry_config(self):
        """ Add workorders tab """
        res = super()._get_view_carpentry_config()
        res[0]['params'] |= {
            'model_description': _('Components'),
            'fields_suffix': '_components',
            'budget_types': self._get_component_budget_types(),
        }
        return res + [
            {
                'templates': {
                    'alert_banner': self._carpentry_budget_alert_banner_xpath,
                    'notebook_page': '//page[@name="operations"]',
                },
                'params': {
                    'model_name': self._name,
                    'model_description': _('Work Orders'),
                    'fields_suffix': '_workorders',
                    'budget_types': self._get_workorder_budget_types(),
                    'budget_choice': self._carpentry_budget_choice,
                    'sheet_name': _('Budget (work orders)'),
                    'last_valuation_step': False,
                    'button_reservation_refresh': False,
                }
            }
        ]
