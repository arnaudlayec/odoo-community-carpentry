# -*- coding: utf-8 -*-

from odoo import models, fields, api, _, exceptions

class AccountMoveBudgetLine(models.Model):
    _inherit = ["account.move.budget.line"]

    is_computed_carpentry = fields.Boolean(
        default=False,
        # A project's line of `account.move.budget.line` is either:
        # - a computed line of budget (`production`, `installation`, `goods`):
        #   > existance managed in `project_project._compute_position_budget_ids()`
        #   > groupping project's budget by `analytic_account_id`
        #   => all fields are `readonly`
        # - a manual line:
        #   > added by default from budget's template (`service`, `consu_project_global`) 
        #   > added by user (only for `consu_project_global`')
        #   => fields are writable (especially `qty_debit`)
    )
    date = fields.Date(
        compute='_compute_date',
        store=True,
        readonly=False,
    )

    #===== Constrain =====#
    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_computed_carpentry(self):
        if self._context.get('unlink_line_no_raise'):
            return
        
        if self.filtered(lambda x: x.is_computed_carpentry):
            raise exceptions.ValidationError(
                _('Budget lines computed from Positions cannot be removed (%s)')
                % self.analytic_account_id.mapped('display_name')
            )

    #===== CRUD: no negative budgets (for project-global budgets) =====#
    def _get_fields_budget_constrain(self):
        return ('qty_debit', 'debit', 'credit', 'qty_credit', 'qty_balance', 'balance')
    
    def write(self, vals):
        """ Prevent lowering a global-project budget qty,
            regarding already existing budgets reservations
        """
        res = super().write(vals)

        # after `write`
        fields = self._get_fields_budget_constrain()
        if any(x in vals for x in fields):
            projects = self.filtered(lambda x: not x.is_computed_carpentry).project_id
            if projects:
                self.env['carpentry.affectation']._clean_reservation_and_constrain_budget(
                    project_ids=projects.ids
                )
        
        return res
    
    def unlink(self):
        """ Prevent deleting a budget line if it results
            a negative *remaining budget* on a PO, MO, ...
        """
        projects = self.filtered(lambda x: not x.is_computed_carpentry).project_id
        res = super().unlink()

        # after `unlink`
        if projects:
            self.env['carpentry.affectation']._clean_reservation_and_constrain_budget(
                project_ids=projects.ids
            )
        
        return res

    #===== Compute =====#
    @api.depends('budget_id.date_from')
    def _compute_date(self):
        """ Update computed line's `date` on budget's date """
        lines_carpentry = self.filtered('is_computed_carpentry')
        for line in lines_carpentry:
            line.date = line.budget_id.date_from
    
    @api.depends(
        # 1. positions' budgets
        'project_id.position_budget_ids',
        'project_id.position_budget_ids.amount_unitary',
        # 2. positions quantity
        'project_id.position_ids',
        'project_id.position_ids.quantity',
        # standard `@api.depends` for `debit`
        'qty_debit', 'standard_price',
        # 1b. valuations of qties -> budget's dates
        'budget_id', 'budget_id.date_from', 'budget_id.date_to',
        # 1a. price per dates table
        'analytic_account_id',
        'timesheet_cost_history_ids',
        'timesheet_cost_history_ids.hourly_cost',
        'timesheet_cost_history_ids.starting_date',
    )
    def _compute_debit_credit_balance(self):
        """ When position's budgets are updated (import or manually),
            update amount(*) in `account.move.budget.line` accordingly
            (*) is `qty_debit` or `debit` depending on product's type (service or goods)
        """
        lines_carpentry = self.filtered('is_computed_carpentry')

        # compute `debit` standardly
        super(AccountMoveBudgetLine, self - lines_carpentry)._compute_debit_credit_balance()

        # perf early quit
        if not lines_carpentry:
            return
        
        # Ensure correct values in database
        # (!) needed here, because `read_group` on view
        #                           & write of storable fields
        self.env.flush_all()

        # Get budget project's groupped by analytic account
        domain = [
            ('project_id', 'in', self.project_id._origin.ids),
            ('record_res_model', '=', 'carpentry.position'),
            ('analytic_account_id', '!=', False),
        ]
        rg_result = self.env['carpentry.budget.available']._read_group(
            domain=domain,
            groupby=['project_id', 'analytic_account_id'],
            fields=['amount_subtotal:sum'],
            lazy=False,
        )
        budget_brut = {
            (x['project_id'][0], x['analytic_account_id'][0]): x['amount_subtotal']
            for x in rg_result
        }

        # Write in budget lines
        for line in lines_carpentry:
            key = (line.project_id._origin.id, line.analytic_account_id._origin.id)
            amount_brut = budget_brut.get(key, 0.0)
            if line.type == "amount":
                line.debit = amount_brut
            else: # workforce
                line.qty_debit = amount_brut
                line._compute_debit_credit_balance_one() # re-valuate 'debit' (only 'qty_debit' was set)
            line.balance = line.debit - line.credit
