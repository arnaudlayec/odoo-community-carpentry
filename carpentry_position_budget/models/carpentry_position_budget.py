# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from collections import defaultdict

class CarpentryPositionBudget(models.Model):
    _name = 'carpentry.position.budget'
    _description = 'Position Budget'
    _order = "seq_analytic ASC"

    # primary keys
    project_id = fields.Many2one(
        related='position_id.project_id',
        store=True,
        index='btree_not_null',
        required=True,
        precompute=True,
        ondelete='cascade',
    )
    position_id = fields.Many2one(
        comodel_name='carpentry.position',
        string='Position',
        required=True,
        index='btree_not_null',
        ondelete='cascade',
        domain="[('project_id', '=', project_id)]"
    )
    analytic_account_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Budget Category',
        required=True,
        ondelete='restrict',
        index='btree_not_null',
        help='Used to rapproach incomes, charges and budget in accounting reports.',
        domain="""[
            ('is_project_budget', '=', True),
            '|', ('company_id', '=', company_id), ('company_id', '=', False)
        ]"""
    )
    seq_analytic = fields.Integer(
        string='Analytic account sequence',
        related="analytic_account_id.sequence",
        store=True,
    )
    # for search view
    lot_id = fields.Many2one(
        related='position_id.lot_id'
    )

    # budget amount/value
    budget_type = fields.Selection(
        # needed to discrepency `goods` vs `service`
        related='analytic_account_id.budget_type',
        store=True # for groupby
    )
    amount_unitary = fields.Float(
        # depending `budget_type`, either a currency amount, or a quantity
        string='Unitary Amount',
        default=0.0,
        required=True,
    )
    quantity = fields.Integer(
        related='position_id.quantity',
        readonly=False, # so it's exportable with *Importable field only*
                        # but XML view restore it with attr readonly="1"
        help="Position's quantity in the project",
    )
    value_unitary = fields.Monetary(
        string='Unit Value',
        currency_field='currency_id',
        compute='_compute_value_unitary',
        help='Only relevant for budget in hours',
    )

    company_id = fields.Many2one(
        related='project_id.company_id'
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id'
    )

    #===== Constrain =====#
    _sql_constraints = [(
        "position_analytic",
        "UNIQUE (position_id, analytic_account_id)",
        "A position cannot receive twice a budget from the same analytic account."
    )]

    #===== CRUD =====#
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.project_id._populate_account_move_budget_line('add', records.analytic_account_id)
        return records
    
    def copy(self, default={}):
        records = super().copy(default)
        records.project_id._populate_account_move_budget_line('add', records.analytic_account_id)
        return records

    def write(self, vals):
        res = super().write(vals)
        # after 'write'
        if 'amount_unitary' in vals:
            affectations = self.position_id.affectation_ids
            launchs = affectations._get_launchs_and_children_launchs()
            affectations._clean_reservation_and_constrain_budget(launchs.ids)
        # update project's budgets
        if 'analytic_account_id' in vals:
            self.position_id.project_id._refresh_account_move_budget_line()
        return res
    
    def unlink(self):
        """ 1. Trigger budget line cleaning
            2. Ensure no negative budget in reservation
        """
        # before `unlink`
        projects = self.position_id.project_id
        launchs = self.position_id.affectation_ids._get_launchs_and_children_launchs()
        res = super().unlink()
        
        # after `unlink`
        projects._refresh_account_move_budget_line()
        self.env['carpentry.affectation']._clean_reservation_and_constrain_budget(launchs.ids)
        return res

    #===== Compute =====#
    @api.depends(
        'amount_unitary',
        'analytic_account_id',
        'analytic_account_id.timesheet_cost_history_ids',
        'analytic_account_id.timesheet_cost_history_ids.hourly_cost',
        'analytic_account_id.timesheet_cost_history_ids.starting_date',
        'project_id.date_start', 'project_id.date',
    )
    def _compute_value_unitary(self):
        """ - Services (work-force) are valued as per company's value table (on project's lifetime)
            - Goods value is directly in `amount_unitary` 
        """
        for budget in self:
            analytic = budget.analytic_account_id
            budget.value_unitary = analytic and analytic._value_amount(
                budget.amount_unitary,
                budget.project_id.date_start,
                budget.project_id.date,
            )

    #===== Helpers: add or erase budget of a position (at budget import) =====#
    def _add_budget(self, vals_list_budget):
        self._write_budget(vals_list_budget, erase_mode=False)
    def _erase_budget(self, vals_list_budget, force=False):
        self._write_budget(vals_list_budget, erase_mode=True, erase_force=force)
    
    def _to_vals(self, replace_keys={}):
        """ Convert recordset of this model to its vals
            Useful to render `vals_list_budget` from a recordset of `carpentry.position.budget`
            
            :option replace_keys: vals dict to force-replace `vals` in `vals_list`
                                  E.g.: to re-affect budget of 1 position to another 
            :return: list of dict `vals_list`
        """
        return [{
            'position_id': replace_keys.get('position_id', budget.position_id.id),
            'analytic_account_id': replace_keys.get('analytic_account_id', budget.analytic_account_id.id),
            'amount_unitary': budget.amount_unitary
        } for budget in self]
    
    def _write_budget(self, vals_list_budget, erase_mode=False, erase_force=False):
        """ Write/add in existing budget or create new budgets 

            :param vals_list_budget: `vals_dict` of this model
            :param mode_erase:  if True,  `amount_unitary` is written in place of any existing
                                 budget, or created if no budget
                                if False, `amount_unitary` is added to existing budget
            :param erase_force: if True, the existing non-updated budgets are removed
        """

        # get existing budget, to route between `write()` or `create()`
        mapped_existing_ids = {(x.position_id.id, x.analytic_account_id.id): x for x in self}
        vals_list, to_delete = [], self

        # write/sum
        for vals in vals_list_budget:
            primary_key = (vals.get('position_id'), vals.get('analytic_account_id'))
            budget = mapped_existing_ids.get(primary_key)

            if budget:
                budget.amount_unitary = vals.get('amount_unitary') if erase_mode else budget.amount_unitary + vals.get('amount_unitary')
                to_delete -= budget # for `erase_force` if True
            else:
                vals_list.append(vals)
        
        # create
        if vals_list:
            self.create(vals_list)

        # delete
        if erase_mode and erase_force:
            to_delete.unlink()
