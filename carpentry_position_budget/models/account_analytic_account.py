# -*- coding: utf-8 -*-

from odoo import api, fields, models, exceptions, _
from odoo.tools.misc import format_amount

class AnalyticAccount(models.Model):
    _name = 'account.analytic.account'
    _inherit = ['account.analytic.account']

    #===== Fields methods =====#
    def name_get(self):
        """ Add:
            - prefix: [Budget Type] ...
            - suffix: ... remaining budget 0,00€
        """
        record_id = self._context.get('record_id')
        record_res_model = self._context.get('record_res_model')
        if not record_id or not record_res_model or not record_res_model in self.env:
            return super().name_get()
        
        res = super(
            # optim trick: don't play 'name_get' searches in 'project_budget_timesheet'
            AnalyticAccount, self.with_context(display_analytic_budget=False)
        ).name_get()
        
        analytics = self.browse(list(dict(res).keys()))
        record = self.env[record_res_model].browse(record_id)
        remaining_budget = self._get_remaining_budget_by_analytic(
            record.project_id.id, record.launch_ids.ids, record.id, record._record_field,
        )
        budget_type_selection = dict(self._fields['budget_type']._description_selection(self.env))
        
        res_updated = []
        for id_, name in res:
            analytic = analytics.browse(id_)

            # prefix [Budget Type]
            budget_type = _(budget_type_selection.get(analytic.budget_type))
            name = f'[{budget_type}] {analytic.name}'

            # suffix budget & clock
            amount_subtotal = remaining_budget.get(id_)
            if amount_subtotal != None:
                amount_str = format_amount(self.env, amount_subtotal, analytic.currency_id)
                if analytic.budget_unit == 'h':
                    amount_str = amount_str.replace('€', 'h')
                name += f' ({amount_str})'

            res_updated.append((id_, name))
        
        return res_updated

    #===== Fields =====#
    reservation_ids = fields.One2many(
        comodel_name='carpentry.budget.reservation',
        inverse_name='analytic_account_id',
    )
    budget_type = fields.Selection(
        selection_add=[
            ('production', 'Production'),
            ('installation', 'Installation'),
            ('other', 'Other costs'),
        ],
        ondelete={
            'production': 'set service',
            'installation': 'set service',
            'other': 'set goods',
        }
    )
    budget_unit = fields.Char(
        compute='_compute_budget_unit',
    )
    template_line_ids = fields.One2many(
        # for domain in Interface
        comodel_name='account.move.budget.line.template',
        inverse_name='analytic_account_id'
    )

    def _get_budget_type_workforce(self):
        return ['service', 'production', 'installation']

    def _get_default_line_type(self):
        return (
            'workforce' if self.budget_type in self._get_budget_type_workforce()
            else super()._get_default_line_type()
        )
    
    def _compute_budget_unit(self):
        for analytic in self:
            analytic.budget_unit = 'h' if analytic._get_default_line_type() == 'workforce' else '€' 
    
    def _value_amount(self, amount, date_start, date_end, mapped_hourly_cost=[]):
        """ Just a conditionaly method to convert h to € *when needed*:
            - position available budget
            - reserved budget

            :option mapped_hourly_cost: There is 2 mode to value:
                a) if given (from _get_hourly_cost()) => value on a specific date, for PO, MO, ...
                b) else (no specific date): assume `amount` is spread on all `project_id`'s time
                    => use hourly_cost table between date range of project's budget
        """
        self.ensure_one()

        line_type = self._get_default_line_type() or 'amount'

        if line_type == 'workforce':
            # if not mapped_hourly_cost:
            return self._value_workforce(amount, date_start, date_end)
        else:
            return amount
    
    def _get_hourly_cost(self, date):
        """ Return the last `hourly_cost` per analytic account """
        pass
    
    #==== Budget sums computation =====#
    @api.model
    def _get_remaining_budget_by_analytic(self, project_id, launch_ids, record_id, record_field):
        """ Group remaining budget by `analytic`, according to required `launchs` & `record`
            (!!!) Always in *BRUT*

            :arg record_field: like 'purchase_id'
            :arg record_id: like ID for `purchase.order`
            :arg launch_ids: explicit
            :arg project_id: explicit
            :return: Dict like {analytic_id: amount}
        """
        rg_result = self.env['carpentry.budget.remaining'].read_group(
            domain=[
                ('project_id', '=', project_id),
                ('launch_id', 'in', [False] + launch_ids),
                ('analytic_account_id', '!=', False),
                (record_field, '!=', record_id),
            ],
            fields=['amount_subtotal:sum'],
            groupby=['analytic_account_id'],
        )
        return {x['analytic_account_id'][0]: x['amount_subtotal'] for x in rg_result}
