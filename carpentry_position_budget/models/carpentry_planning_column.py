# -*- coding: utf-8 -*-

from odoo import models, fields
from collections import defaultdict

def human_readable(num, scale=1000.0):
    return round(num) if num else 0.0
    # for unit in ("", "k", "m"):
    #     if abs(num) < scale:
    #         return f"{num:3.0f}{unit}"
    #     num /= scale
    # return f"{num:.0f}M"

class CarpentryPlanningColumn(models.Model):
    _inherit = ["carpentry.planning.column"]

    budget_types = fields.Char(
        string='Budget Type(s)',
        help='Technical names of budget types separated by a coma',
    )

    #===== RPC calls (columns' sub-headers) =====#
    def get_headers_data(self, launch_id_):
        """ Add budget information to planning's columns headers """
        res = super().get_headers_data(launch_id_)
        budget_types = list(set([
            budget_type
            for budget_types_char in self.filtered('budget_types').mapped('budget_types')
            for budget_type in budget_types_char.split(',')
        ]))
        if not budget_types:
            return res
        
        # 1. Available (brut)
        project = self.env['carpentry.group.launch'].browse(launch_id_).project_id
        domain_budget = [('budget_type', 'in', budget_types)]
        domain_project = domain_budget + [('project_id', '=', project.id)]
        domain_launch = domain_budget + [('launch_id', '=', launch_id_)]
        rg_available = self.env['carpentry.budget.available']._read_group(
            domain=domain_launch, groupby=['budget_type'], fields=['amount_subtotal:sum'],
        )
        mapped_available = {x['budget_type']: x['amount_subtotal'] for x in rg_available}

        # 2. Reserved (brut or valued)
        # + for expense distribution per launch (only)
        BudgetMixin = self.env['carpentry.budget.mixin']
        Reservation = self.env['carpentry.budget.reservation']
        fields = ['amount_reserved', 'amount_reserved_valued']
        record_fields = Reservation._get_record_fields()
        rg_reserved = Reservation._read_group(
            domain=domain_project + [('launch_id', '!=', False), ('amount_reserved', '!=', 0.0)],
            fields=[field + ':sum' for field in fields],
            groupby=['launch_id', 'budget_type'] + record_fields,
            lazy=False,
        )
        mapped_reserved = mapped_reserved_detail = mapped_reserved_per_record = {}
        for x in rg_reserved:
            budget_type = x['budget_type']

            # for KPI: sum reserved budget per budget_type, for the launch being displayed on Kanban
            if x['launch_id'][0] == launch_id_:
                if not budget_type in mapped_reserved:
                    mapped_reserved[budget_type] = {field: 0.0 for field in fields}
                for field in fields:
                    mapped_reserved[budget_type][field] += x[field]
            
            # for expenses ratio: budget per budget_type, launch & records
            # 'planning' key: (launch, records..., budget_type)
            key_planning = BudgetMixin._get_key(vals=x, mode='planning', mask=record_fields + ['budget_type'])
            key_record = tuple(list(key_planning)[1:]) # skip launch_id (item 0)
            mapped_reserved_detail[key_planning] = x['amount_reserved']
            if not key_record in mapped_reserved_per_record:
                mapped_reserved_per_record[key_record] = 0.0
            mapped_reserved_per_record[key_record] += x['amount_reserved']

        # 3. Expense, distributed for launch_id as per its reserved budget within each section
        fields = ['amount_expense', 'amount_expense_valued']
        rg_expense = self.env['carpentry.budget.expense']._read_group(
            domain=domain_project,
            fields=[field + ':sum' for field in fields],
            groupby=['budget_type'] + record_fields,
            lazy=False,
        )
        mapped_expense = {}
        for x in rg_expense:
            # 1st compute share of launch in the expense, at prorata of
            #  its reserved budget in the record on a given `budget_type`
            key_planning = tuple([launch_id_] + list(
                BudgetMixin._get_key(vals=x, mode='planning', mask=record_fields + ['budget_type'])
            ))
            key_record = tuple(list(key_planning)[1:]) # skip launch_id (item 0)
            launch_reserved = mapped_reserved_detail.get(key_planning, 0.0)
            total_reserved = mapped_reserved_per_record.get(key_record, 0.0)
            prorata_reserved = launch_reserved / total_reserved if total_reserved else 0.0

            if prorata_reserved:
                budget_type = x['budget_type']
                if not budget_type in mapped_expense:
                    mapped_expense[budget_type] = {field: 0.0 for field in fields}
                for field in fields:
                    mapped_expense[budget_type][field] += x[field] * prorata_reserved

        # 4. Format data per column
        budget_types_workforce = self.env['account.analytic.account']._get_budget_type_workforce()
        for column in self.filtered('budget_types'):
            # valued ?
            budget_types = column.budget_types.split(',')
            is_hour = all([
                budget_type in budget_types_workforce
                for budget_type in budget_types
            ])
            valued = '' if is_hour else '_valued'

            # sums
            available, reserved, expense = 0.0, 0.0, 0.0
            for budget_type in budget_types:
                available += mapped_available.get(budget_type, 0.0)
                reserved += mapped_reserved.get(budget_type, {}).get('amount_reserved' + valued, 0.0)
                expense += mapped_expense.get(budget_type, {}) .get('amount_expense'  + valued, 0.0)

            res[column.id]['budget'] = {
                'unit': 'h' if is_hour else '€',
                'available': human_readable(available),
                'reserved': human_readable(reserved),
                'expense': human_readable(expense),
            }

        return res
