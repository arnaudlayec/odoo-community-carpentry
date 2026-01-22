# -*- coding: utf-8 -*-

from odoo import models

class CarpentryExpense(models.Model):
    _inherit = ['carpentry.budget.expense.detail']

    #===== View build =====#
    def _get_queries_models(self):
        return super()._get_queries_models() + ('project.task',)
    
    def _select(self, model, models):
        if model == 'project.task':
            return f"""
                SELECT
                    'expense_unposted' AS state,
                    
                    record.project_id,
                    record.date_budget AS date,
                    record.active,
                    record.id AS record_id,
                    {models[model]} AS record_model_id,
                    
                    -- cost center is **ALWAYS** task's one,
                    -- even for employees' timesheets of other departments
                    record.analytic_account_id,
                    analytic.budget_type,
                    analytic.sequence AS seq_analytic,

                    -- amount_reserved:
                    -- 1. if effective_hours < amount_reserved:
                    --    then: displays expense == budget_reservation in the project's budget report
                    --    else: follow SUM from `carpentry.budget.reservation`
                    -- 2. if planned_hours != amount_reserved:
                    --    fakely raise/reduce amount_reserved by the difference
                    CASE
                        WHEN record.is_closed IS FALSE AND record.effective_hours < record.total_budget_reserved
                        THEN record.effective_hours - record.total_budget_reserved
                        ELSE 0.0
                    END -
                    CASE
                        WHEN record.planned_hours != record.total_budget_reserved
                         AND record.effective_hours < record.planned_hours
                        THEN record.planned_hours - record.total_budget_reserved
                        ELSE 0.0
                    END AS amount_reserved,

                    -- expense
                    NULL AS value_or_devalue_workforce_expense,
                    COALESCE(SUM(line.unit_amount), 0.0) AS amount_expense,
                    COALESCE(SUM(line.amount), 0.0) * -1 AS amount_expense_valued
            """

        return super()._select(model, models)
    
    def _join(self, model, models):
        sql = ''

        if model == 'project.task':
            sql += f"""
                -- timesheet lines
                LEFT JOIN account_analytic_line AS line
                    ON line.task_id = record.id
                
                -- analytic
                LEFT JOIN account_analytic_account AS analytic
                    ON analytic.id = record.analytic_account_id
            """
        
        return sql + super()._join(model, models)
    
    def _where(self, model, models):
        """ Override to skip `WHERE budget_type IS NOT NULL`  """
        sql = super()._where(model, models)

        if model == 'project.task':
            sql += """
                AND record.active IS TRUE
                AND record.allow_timesheets IS TRUE
            """

        return sql
