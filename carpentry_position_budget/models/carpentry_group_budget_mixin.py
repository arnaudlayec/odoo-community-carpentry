# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _

class CarpentryGroupBudgetMixin(models.AbstractModel):
    """ Budget sums from Affectations
        Relevant for Phases, Launches, Positions (and Project)
    """
    _name = 'carpentry.group.budget.mixin'
    _description = 'Carpentry Group Budget Mixin'

    project_id = fields.Many2one(comodel_name='project.project')
    currency_id = fields.Many2one(related='project_id.company_id.currency_id')
    # in (h)
    budget_office = fields.Float(string='Office', compute='_compute_budgets')
    budget_prod = fields.Float(string='Prod', compute='_compute_budgets')
    budget_install = fields.Float(string='Install', compute='_compute_budgets')
    # in (€)
    budget_goods = fields.Monetary(string='Goods', compute='_compute_budgets', currency_field='currency_id')
    budget_global_cost = fields.Monetary(string='Other', compute='_compute_budgets', currency_field='currency_id')
    # total
    budget_total = fields.Monetary(string='Total', compute='_compute_budgets', currency_field='currency_id')
    
    
    #===== Compute (budgets) =====#
    def _get_budgets_brut_valued(self):
        return self.env['carpentry.position.budget'].sudo().sum(
            quantities=self._get_quantities(),
            groupby_group=['group_id'],
            groupby_budget='budget_type',
            domain_budget=self._get_domain_budget_ids(),
            brut_or_valued='both', # for `total` valuation
        )
    
    def _get_domain_budget_ids(self):
        """ [For overwriting] Optional """
        return []
    
    def _compute_budgets_one(self, brut, valued):
        """ Allows to be overriden, e.g. for position to change `total` and `subtotal` computation """
        self.ensure_one()
        self.budget_office = self._get_budget_one(brut, 'office')
        self.budget_prod = self._get_budget_one(brut, 'production')
        self.budget_install = self._get_budget_one(brut, 'installation')
        self.budget_goods = self._get_budget_one(valued, 'goods')
        self.budget_global_cost = self._get_budget_one(valued, 'project_global_cost')
        self.budget_total = self._get_budget_one(valued, ['office', 'production', 'installation', 'goods', 'project_global_cost'])
    
    def _get_budget_one(self, budget, budget_types):
        budget_types = [budget_types] if isinstance(budget_types, str) else budget_types
        return sum([
            budget.get(self.id, {}).get(x, 0.0)
            for x in budget_types
        ])

    def _compute_budget_fields(self):
        return [
            # 1a. products template/variants price & dates
            'project_id.position_budget_ids.analytic_account_id.timesheet_cost_history_ids',
            'project_id.position_budget_ids.analytic_account_id.timesheet_cost_history_ids.hourly_cost',
            'project_id.position_budget_ids.analytic_account_id.timesheet_cost_history_ids.starting_date',
            # 1b. valuations of qties -> budget's dates
            'project_id.budget_ids', 'project_id.budget_ids.date_from', 'project_id.budget_ids.date_to',
            # 2. positions' budgets
            'project_id.position_budget_ids',
            'project_id.position_budget_ids.amount',
            # 3. positions affectations
            'affectation_ids',
            'affectation_ids.quantity_affected'
        ]
    
    @api.depends(lambda self: self._compute_budget_fields())
    def _compute_budgets(self):
        if self._context.get('import_budget_no_compute'):
            return
    
        brut, valued = self._get_budgets_brut_valued()
        for group in self:
            group.sudo()._compute_budgets_one(brut, valued)
