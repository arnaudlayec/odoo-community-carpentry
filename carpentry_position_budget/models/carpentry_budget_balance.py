# -*- coding: utf-8 -*-

from re import A
from odoo import models, fields, api, Command, exceptions, _
from odoo.tools import float_compare

class CarpentryBudgetBalance(models.Model):
    """ This model acts like PO, MO, ...
        to adjust budget and make balances
    """
    _name = "carpentry.budget.balance"
    _inherit = ['project.default.mixin', 'carpentry.budget.mixin']
    _description = "Budget Balance"
    _order = "write_date DESC"
    _record_field = 'balance_id'
    _carpentry_budget_alert_banner_xpath = False # don't use budget view templates
    _carpentry_budget_notebook_page_xpath = False

    #===== Fields =====#
    name = fields.Char()
    project_id = fields.Many2one(readonly=True)
    reservation_ids = fields.One2many(inverse_name='balance_id')
    expense_ids = fields.One2many(inverse_name='balance_id')
    launch_ids = fields.Many2many(
        string='Launchs',
        comodel_name='carpentry.group.launch',
        compute='_compute_launch_ids',
        inverse='_inverse_launch_ids',
        readonly=False,
        domain="[('project_id', '=', project_id)]",
    )

    #===== Budget reservation methods =====#
    def _depends_can_reserve_budget(self):
        return []
    def _get_domain_can_reserve_budget(self):
        return []
    
    def _get_budget_types(self):
        return [x[0] for x in self.env['account.analytic.account']._fields['budget_type'].selection]
    
    def _get_domain_is_temporary_gain(self):
        return []
    
    @api.depends('reservation_ids.launch_id')
    def _compute_launch_ids(self):
        """ `launch_ids` are not stored. They are:
            * selected by user
            * computed back from reservations
        """
        for balance in self:
            balance.launch_ids = balance.reservation_ids.launch_id
    
    def _inverse_launch_ids(self):
        """ Recompute both `budget_analytic_ids` and `reservation_ids` """
        self._compute_reservation_ids({})
    
    def _compute_reservation_ids(self, vals={}):
        """ Cancel refresh from `write`, so it's managed by
            `_inverse_launch_ids` with proper `launch_ids` in cache
        """
        if not 'launch_ids' in vals:
            super()._compute_reservation_ids({})
    
    def _get_launch_ids(self):
        """ For balance: either launchs, either project """
        return self.launch_ids._origin.ids or [False]
    
    def _get_auto_budget_analytic_ids(self, _):
        """ Budget centers are either all launch's or project's:
             a) all launch's budgets, if at least 1 `launch_ids` is selected
             b) all project's global budgets, if no launch selected
            Thus: budget balance are either for project's or launchs' budgets.
        """
        if self.launch_ids:
            # Select budgets related to the launchs
            return (
                self.launch_ids.affectation_ids.position_id
                .position_budget_ids.analytic_account_id
            ).ids
        else:
            # Select project's budgets
            domain = [('is_computed_carpentry', '=', False)]
            mapped_data = self._get_mapped_project_analytics(domain)
            return mapped_data.get(self.project_id.id, [])

    def _get_total_budgetable_by_analytic(self, _):
        """ [OVERRIDE]
            Balance => budget to reserve is *all* remaining budget (instead of expense)
        """
        self.ensure_one()
        Analytic = self.env['account.analytic.account']
        remaining_budget = Analytic._get_remaining_budget_by_analytic(
            project_id=self.project_id._origin.id,
            launch_ids=self.launch_ids._origin.ids,
            record_id=self._origin.id,
            record_field=self._record_field,
        )

        res = {
            (self._origin.id, aac_id): amount_subtotal
            for aac_id, amount_subtotal in remaining_budget.items()
            if bool(amount_subtotal)
        }

        debug = False
        if debug:
            print(' == _get_total_budgetable_by_analytic (balance) == ')
            print('remaining_budget', remaining_budget)
            print('res', res)
        
        return res

    def _get_mapped_possible_reservations(self):
        """ [OVERRIDE] Don't provision reservation line where
            *Remaining budget == 0.0*, since we don't need them on balances
            => use `carpentry.budget.remaining` instead of `carpentry.budget.available`
        """
        # optim
        if not self.budget_analytic_ids._origin:
            return [tuple()]

        rg_result = self.env['carpentry.budget.remaining']._read_group(
            domain=self._domain_mapped_possible_reservations(),
            groupby=['project_id', 'launch_id', 'analytic_account_id'],
            fields=['amount_subtotal:sum'],
            lazy=False,
        )
        return [
            self._get_key(vals=x, mode='budget')
            for x in rg_result
            if float_compare(x["amount_subtotal"], 0.0, precision_rounding=self.currency_id.rounding) != 0
        ]
