# -*- coding: utf-8 -*-

from odoo import models, fields
from datetime import date

class BudgetExpenseUnpostedWizard(models.TransientModel):
    _name = "carpentry.budget.expense.unposted.wizard"
    _description = "Wizard to open Unposted Expense report"

    #===== Fields methods =====#
    def _default_date_times_posted(self):
        """ Last day in previous accounting exercice, if modules are installed
            Fall back on last day of previous year
        """
        if 'date.range' in self.env:
            range = self.env['date.range'].search([], limit=1, order='date_end DESC')
            return range.date_end
        else:
            return date(fields.Date.context_today.year - 1, 12, 31)
    
    #===== Fields =====#
    date = fields.Date(
        string='As of date...',
        help="Expenses after this date will not be shown in the report.",
        default=fields.Date.context_today,
        required=True,
    )
    date_times_posted = fields.Date(
        string='Threshold date for posted times',
        help="Date until which the expensed times will be considered as "
             "posted. Times after this date will appear with 'Unposted' "
             "state.",
        default=_default_date_times_posted,
        required=True,
    )

    #===== Action =====#
    def action_open(self):
        """ Configure the company before, and open the report """
        self.env.company.budget_date_times_posted = self.date_times_posted

        xmlid = "carpentry_position_budget.action_open_budget_report_expense_unposted"
        action = self.env.ref(xmlid).sudo().read()[0]
        action['name'] += " {}".format(
            fields.Date.context_today(self)
        )
        action['domain'] = [
            ('state', 'in', ['expense_unposted', 'expense_posted']),
            ('date', '<=', self.date)
        ]
        return action
