# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.tools import formatLang

class Project(models.Model):
    _inherit = ['project.project']

    #---- fees ----
    fees_prorata = fields.Monetary(
        string='Prorata',
        compute='_compute_budget_fees_and_margins',
    )
    fees_structure = fields.Monetary(
        string='Structure',
        compute='_compute_budget_fees_and_margins',
    )
    # fees' rates
    fees_prorata_rate = fields.Float(
        string='Prorata (%)',
        default=0.0,
    )
    fees_structure_rate = fields.Float(
        string='Structure (%)',
        default=0.0,
    )
    #---- initial margins: [Market - Budget] ----
    margin_contributive = fields.Monetary(
        string='Contributive margin',
        compute='_compute_budget_fees_and_margins',
        help='Total market - All budgets - Only prorata fees (i.e. not structure fees)'
    )
    margin_costs = fields.Monetary(
        string='Margin on costs',
        compute='_compute_budget_fees_and_margins',
        help='Total market - All budgets - All fees',
    )
    # margins' rates
    margin_contributive_rate = fields.Integer(
        string='Contributive margin (%)',
        compute='_compute_budget_fees_and_margins'
    )
    margin_costs_rate = fields.Integer(
        string='Margin on costs (%)',
        compute='_compute_budget_fees_and_margins'
    )
    #---- actual margins: [Reserved Budget - Real Expense] ----
    margin_contributive_actual = fields.Monetary(
        string='Contributive margin (actual)',
        compute='_compute_budget_fees_and_margins',
        help='[Reserved Budget] - [Real Expense] - [Only prorata fees (i.e. not structure fees)]'
    )
    margin_costs_actual = fields.Monetary(
        string='Margin on costs (actual)',
        compute='_compute_budget_fees_and_margins',
        help='[Reserved Budget] - [Real Expense] - [All fees]',
    )
    # actuel margins' rates
    margin_contributive_actual_rate = fields.Integer(
        string='Contributive margin (actual) (%)',
        compute='_compute_budget_fees_and_margins'
    )
    margin_costs_actual_rate = fields.Integer(
        string='Margin on costs (actual) (%)',
        compute='_compute_budget_fees_and_margins',
    )
    budget_reservation_progress = fields.Integer(
        string='Budget reservation progress (%)',
        compute='_compute_budget_fees_and_margins',
    )

    # sale order line updated status (for warning)
    budget_up_to_date = fields.Boolean(
        compute='_compute_budget_up_to_date',
        help='Reliability score of actuals indicator, computed as [Reserved budget / Available budget]',
    )

    #===== Compute: fees, margins =====#
    @api.depends('fees_prorata_rate', 'fees_structure_rate')
    # 'market_reviewed', 'budget_line_sum': skippable to avoid expensive SQL call,
    # as long as computed field are not stored
    def _compute_budget_fees_and_margins(self):
        keys = ['gain', 'reserved_valued']
        rg_expense = self.env['carpentry.budget.expense'].with_context(active_test=True)._read_group(
            domain=[('project_id', 'in', self.ids)],
            fields=['amount_' + k + ':sum' for k in keys],
            groupby=['project_id'],
        )
        mapped_expense = {
            x['project_id'][0]: {k: x['amount_' + k] for k in keys}
            for x in rg_expense
        }
        for project in self:
            expense = mapped_expense.get(project._origin.id, {k: 0.0 for k in keys})
            project._compute_budget_fees_and_margins_one(expense)
        
    def _compute_budget_fees_and_margins_one(self, expense_dict):
        # fees
        self.fees_prorata   = self.fees_prorata_rate * self.market_reviewed / 100
        self.fees_structure = self.fees_structure_rate * self.market_reviewed / 100

        # initial margins
        self.margin_costs        = self.market_reviewed - self.budget_line_sum - self.fees_prorata - self.fees_structure
        self.margin_contributive = self.market_reviewed - self.budget_line_sum - self.fees_prorata # ie. on direct costs only
        # actual margins
        self.margin_costs_actual           = self.margin_costs + expense_dict['gain']
        self.margin_contributive_actual    = self.margin_contributive + expense_dict['gain']

        # rates
        if self.market_reviewed:
            # initial margins
            self.margin_costs_rate        = self.margin_costs / self.market_reviewed * 100
            self.margin_contributive_rate = self.margin_contributive / self.market_reviewed * 100
            # actual margins
            self.margin_costs_actual_rate        = self.margin_costs_actual / self.market_reviewed * 100
            self.margin_contributive_actual_rate = self.margin_contributive_actual / self.market_reviewed * 100
        else:
            # initial margins
            self.margin_costs_rate        = 0.0
            self.margin_contributive_rate = 0.0
            # actual margins
            self.margin_costs_actual_rate        = 0.0
            self.margin_contributive_actual_rate = 0.0
        
        self.budget_reservation_progress = (
            bool(self.budget_line_sum) and
            expense_dict['reserved_valued'] / self.budget_line_sum * 100
        )

    #===== Compute : sale order line budget updated status =====#
    @api.depends('sale_order_ids.order_line', 'sale_order_ids.order_line.budget_updated', 'sale_order_ids.state')
    def _compute_budget_up_to_date(self):
        domain = [('project_id', 'in', self.ids), ('budget_updated', '=', False), ('state', '!=', 'cancel')]
        partial_updated_project_ids_ = self.env['sale.order.line'].sudo().search(domain).project_id.ids
        
        for project in self:
            project.budget_up_to_date = not (project.id in partial_updated_project_ids_)

    #===== Carpentry Planning =====#
    def get_planning_dashboard_data(self):
        return super().get_planning_dashboard_data() | {"margins": self.get_budget_margins_data()}

    def get_budget_margins_data(self):
        """ Format data for project budget report & planning views """
        keys = [
            "market_reviewed",
            "margin_costs_actual", "margin_contributive_actual",
        ]
        data_list = []
        currency = self.company_id.currency_id # can be empty
        for key, attrs in self.fields_get(keys, attributes=['string']).items():
            data = {
                "amount": formatLang(self.env, round(self[key]), currency_obj=currency),
                "label": attrs["string"],
            }
            # compare actual to budget (for class color)
            budget_field = key.replace('_actual', '')
            if hasattr(self, budget_field):
                compare_to = self[budget_field]
                result = bool(currency) and currency.compare_amounts(self[key], compare_to)
                data['class'] = (
                    'text-success' if result == 1 else
                    'text-danger'  if result == -1 else ''
                )
            # rate
            if hasattr(self, key + '_rate'):
                data["rate"] = self[key + '_rate']
            
            data_list.append(data)
        
        # gain/loss
        gain = round(self.margin_costs_actual - self.margin_costs)
        data_list.append({
            "amount": formatLang(self.env, round(gain), currency_obj=currency),
            "label": _("Gain") if gain >= 0 else _("Loss"),
            "class": "text-success" if gain > 0 else "text-danger" if gain < 0 else "",
        })

        return data_list

    def action_open_planning_dashboard_card(self):
        """ Called from planning card """
        if self._context.get("budget_report"):
            action = self.sudo().env.ref("carpentry_position_budget.action_open_budget_report_project").read()[0]
            action.update({
                "domain": [("project_id", "=", self.id)],
                "context": self._context | {"default_project_id": self.id},
                "target": "new",
            })
            return action
        elif hasattr(super, "action_open_planning_dashboard_card"):
            return super().action_open_planning_dashboard_card()
