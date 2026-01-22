# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _

class Project(models.Model):
    _inherit = ['project.project']

    position_budget_ids = fields.One2many(
        # required for @depends
        comodel_name='carpentry.position.budget',
        inverse_name='project_id',
    )
    # duplicate with `budget_line_sum` from `project_budget` (already stored)
    budget_total = fields.Monetary(store=False)
    # user-interface
    position_warning_name = fields.Boolean(
        related='position_ids.warning_name'
    )

    #===== User interface =====#
    def _get_warning_banner(self):
        """ Show alert banner in project's form in case of a warning on positions' names """
        return super()._get_warning_banner() | self.position_warning_name
    
    #===== Compute: budget sums =====#
    def _get_compute_budget_fields(self):
        return [
            # 1a. hour valuation per dates
            'budget_line_ids.analytic_account_id',
            'budget_line_ids.analytic_account_id.timesheet_cost_history_ids',
            'budget_line_ids.analytic_account_id.timesheet_cost_history_ids.hourly_cost',
            'budget_line_ids.analytic_account_id.timesheet_cost_history_ids.starting_date',
            # 1b. valuations of qties -> budget's dates
            'budget_ids', 'budget_ids.date_from', 'budget_ids.date_to',
            # 2. positions' budgets
            'position_budget_ids', 'position_budget_ids.amount_unitary',
            # 3. positions quantity
            'position_ids', 'position_ids.quantity',
            # 4. new or update on fix lines of project's budget, in `account.move.budget.line`
            'budget_line_ids',
            'budget_line_ids.qty_debit',
            'budget_line_ids.balance',
        ]
    
    @api.depends(lambda self: self._get_compute_budget_fields())
    def _compute_budget_line_sum(self):
        return super()._compute_budget_line_sum()

    @api.depends(lambda self: self._get_compute_budget_fields() + ['budget_line_sum'])
    def _compute_budgets(self):
        """ Compute project-level budgets from budget line
            (instead of from `carpentry.budget.available` which
            uses affectations logics)
        """
        budget_fields = {
            # budget_type: field in `account.move.budget.line`
            'service': 'qty_debit',
            'production': 'qty_debit',
            'installation': 'qty_debit',
            'goods': 'balance',
            'other': 'balance',
        }
        rg_result = self.env['account.move.budget.line'].read_group(
            domain=[('project_id', 'in', self._origin.ids)],
            fields=['qty_debit:sum', 'balance:sum'],
            groupby=['project_id', 'budget_type'],
            lazy=False,
        )
        mapped_data = {
            (x['project_id'][0], x['budget_type']):
            {'qty_debit': x['qty_debit'], 'balance': x['balance']}
            for x in rg_result
        }
        for project in self:
            project.budget_total = project.budget_line_sum # from module `project_budget`
            for budget_type, field in budget_fields.items():
                key = (project._origin.id, budget_type)
                project['budget_' + budget_type] = mapped_data.get(key, {}).get(field)


    #===== Compute/Populate: account_move_budget_line =====#
    def _populate_account_move_budget_line(self, method, analytics):
        """ Create/delete computed lines in `account.move.budget.line` according to
            budgets from positions
            Called from position's CRUD methods

            :arg method: 'create' or 'unlink'
            :arg analytics: analytic accounts to add or remove of project's budget lines
        """
        self.ensure_one()
        if self._context.get('import_budget_no_compute'):
            return
        
        # Ensure project.position_budget_ids exist, before any further calculations
        self._inverse_budget_template_ids()
        
        if method == 'remove':
            self.budget_line_ids.filtered(lambda x:
                x.is_computed_carpentry and x.analytic_account_id in analytics
            ).sudo().with_context(unlink_line_no_raise=True).unlink()
        
        elif method == 'add':
            aac_positions = self.budget_line_ids.filtered('is_computed_carpentry').analytic_account_id
            analytics = analytics.filtered(lambda x: x not in aac_positions)
            if not analytics:
                return
            
            self.budget_line_ids.create([{
                'name': analytic.name,
                'date': self._origin._get_default_project_budget_line_date(self.budget_id),
                'budget_id': self._origin.budget_id.id,
                'analytic_account_id': analytic.id,
                'is_computed_carpentry': True,
                # value with `_compute_debit_carpentry`
                'debit': 0,
                'qty_debit': 0,
            } for analytic in analytics])._compute_debit_carpentry()
        
        else:
            raise exceptions.UserError(_('Operation not supported'))

    def _refresh_account_move_budget_line(self):
        """ Identify which analytics are to be added/removed and 
            trigger `_populate_account_move_budget_line`
        """
        for project in self:
            aac_positions = project.position_budget_ids.analytic_account_id
            aac_lines = project.budget_line_ids.filtered('is_computed_carpentry').analytic_account_id
            
            to_add = aac_positions - aac_lines
            if to_add:
                project._populate_account_move_budget_line('add', to_add)
            
            to_remove = aac_lines - aac_positions
            if to_remove:
                project._populate_account_move_budget_line('remove', to_remove)
