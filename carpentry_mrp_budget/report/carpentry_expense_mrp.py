# -*- coding: utf-8 -*-

from odoo import models, fields

class CarpentryExpense(models.Model):
    _inherit = ['carpentry.budget.expense.detail']

    #===== View build =====#
    def _get_queries_models(self):
        """ == Stock moves==
            * `stock.picking`:  for stock.move estimation before validation
            * `mrp.production`: same, for raw material
            For those 2, expense is summed from `stock.valuation.layer`
            when they are done, for final/accountable value
            
            == Work orders ==
            * `mrp.workorder`: manufacturing times
        """
        return super()._get_queries_models() + (
            'stock.picking', # lines are stock.move (move_ids)
            'mrp.production', # lines are stock.move too (move_raw_ids)
            'mrp.workorder' # lines are mrp.workorders (actually: mrp.workcenter.productivity)
        )
    
    def _select(self, model, models):
        sql_active = "record.state NOT IN ('cancel')"
        if model in ('mrp.production', 'mrp.workorder'):
            sql_active + " AND record.active"
        
        if model in ('stock.picking', 'mrp.production'):
            sign = (
                "CASE WHEN picking_type.code = 'incoming' THEN -1 ELSE 1 END"
                if model == 'stock.picking'
                else 1
            )
            
            return f"""
                SELECT
                    CASE
                        WHEN record.state = 'done'
                        THEN 'expense_posted'
                        ELSE 'expense_unposted'
                    END AS state,

                    record.company_id,
                    record.project_id,
                    record.date_budget AS date,
                    {sql_active} AS active,
                    record.id AS record_id,
                    {models[model]} AS record_model_id,
                    analytic.id AS analytic_account_id,
                    analytic.budget_type,
                    analytic.sequence AS seq_analytic,

                    0.0 AS amount_reserved,
                    
                    -- expense: will be devaluated for workforce
                    'DEVALUE' AS value_or_devalue_workforce_expense,
                    SUM(
                        CASE
                            WHEN record.state = 'done'
                            THEN ABS(svl.value) -- accounting value
                            ELSE line.product_uom_qty::float * property.value_float::float -- estimation
                        END
                        * analytic_distribution.percentage::float
                        / 100.0
                    ) * {sign} * (
                        COUNT(DISTINCT line.id)::float / COUNT(*)::float
                    ) AS amount_expense,

                    -- valued expense: will be calculated from `amount_expense` (without devaluation)
                    NULL AS amount_expense_valued
            """
        
        elif model == 'mrp.workorder':
            return f"""
                SELECT
                    NULL AS state,

                    record.company_id,
                    record.project_id,
                    record.date_budget_workorders AS date,
                    {sql_active} AS active,
                    record.id AS record_id,
                    {models['mrp.production']} AS record_model_id,
                    reservation.analytic_account_id,
                    reservation.budget_type,
                    reservation.seq_analytic,
                    
                    -- amount_reserved:
                    -- if: MO's sum of effective_hours < sum of amount_reserved
                    -- then: displays expense == budget_reservation in the project's budget report
                    -- else: follow SUM from `carpentry.budget.reservation`
                    CASE
                        WHEN record.state != 'done'
                         AND record.production_real_duration / 60 < record.total_budget_reserved_workorders
                        THEN -- prorata per workorder's reserved budget
                            record.production_real_duration / 60 *
                            CASE -- prorata per workorder's reserved budget
                                WHEN record.total_budget_reserved_workorders != 0.0
                                THEN COALESCE(SUM(reservation.amount_reserved), 0.0)
                                     / record.total_budget_reserved_workorders
                                -- cannot prorata by reserved budget => do it by reservations count
                                ELSE (CASE
                                    WHEN count_budget_resa_workorders != 0
                                    THEN 1 / count_budget_resa_workorders::float * COUNT(DISTINCT line.id)
                                    ELSE 1.0
                                END)
                            END
                            -- cancel budget_reservation
                            - COALESCE(SUM(reservation.amount_reserved), 0.0)
                        ELSE 0.0
                    END / COUNT(DISTINCT line.id)
                    AS amount_reserved,
                    
                    -- expense
                    NULL AS value_or_devalue_workforce_expense,
                    record.production_real_duration / 60 * (
                        CASE -- prorata per workorder's reserved budget
                            WHEN record.total_budget_reserved_workorders != 0.0
                            THEN COALESCE(SUM(reservation.amount_reserved), 0.0)
                                 / record.total_budget_reserved_workorders
                            -- cannot prorata by reserved budget => do it by reservations count
                            ELSE (CASE
                                WHEN count_budget_resa_workorders != 0
                                THEN 1 / count_budget_resa_workorders::float
                                ELSE 1.0
                            END) * COUNT(DISTINCT line.id)
                        END / COUNT(DISTINCT line.id)
                    ) AS amount_expense,

                    -- expense valued
                    COALESCE(SUM(line.amount), 0.0) * (
                        CASE -- prorata per workorder's reserved budget
                            WHEN record.total_budget_reserved_workorders != 0.0
                            THEN COALESCE(SUM(reservation.amount_reserved), 0.0)
                                 / record.total_budget_reserved_workorders
                            -- cannot prorata by reserved budget => do it by reservations count
                            ELSE (CASE
                                WHEN count_budget_resa_workorders != 0
                                THEN 1 / count_budget_resa_workorders::float
                                ELSE 1.0
                            END) * COUNT(DISTINCT line.id)
                        END
                    ) / (CASE WHEN COALESCE(COUNT(DISTINCT reservation.id), 0.0) != 0.0
                        THEN COALESCE(COUNT(DISTINCT reservation.id), 0.0) ELSE 1.0 END)
                      / COUNT(DISTINCT line.id)
                    AS amount_expense_valued
            """

        return super()._select(model, models)
    
    def _from(self, model, models):
        if model in ('stock.picking', 'mrp.production'):
            return 'FROM stock_move AS line'
        elif model == 'mrp.workorder':
            return 'FROM mrp_production AS record'
        else:
            return super()._from(model, models)
    
    def _join(self, model, models):
        sql = ''

        if model in ('stock.picking', 'mrp.production'):
            sql += self._join_product_analytic_distribution()

            if model == 'stock.picking':
                sql += """
                    INNER JOIN stock_picking AS record
                        ON record.id = line.picking_id
                    INNER JOIN stock_picking_type AS picking_type
                        ON picking_type.id = record.picking_type_id
                """
            else:
                sql += """
                    INNER JOIN mrp_production AS record
                        ON record.id = line.raw_material_production_id
                """
            sql += f"""
                LEFT JOIN stock_valuation_layer AS svl
                    ON svl.stock_move_id = line.id
                
                INNER JOIN project_project AS project
                    ON project.id = record.project_id
                LEFT JOIN ir_property AS property
                    ON  property.res_id = 'product.product,' || product_product.id
                    AND property.company_id = project.company_id
            """
        
        elif model == 'mrp.workorder':
            budget_types = self.env['account.analytic.account']._get_budget_type_workforce()
            sql += f"""
                -- expense line = wo's aac line
                INNER JOIN mrp_workorder AS wo
                    ON wo.production_id = record.id
                INNER JOIN account_analytic_line AS line
                    ON line.id = wo.mo_analytic_account_line_id
                
                -- budget reservation: needed to spread the expense
                LEFT JOIN carpentry_budget_reservation AS reservation
                    ON  reservation.production_id = record.id
                    AND reservation.budget_type IN {tuple(budget_types)}
            """
        
        return sql + super()._join(model, models)
        
    
    def _where(self, model, models):
        sql = super()._where(model, models)

        if model == 'stock.picking':
            sql += """
                AND picking_type.code != 'internal'
                AND line.purchase_line_id IS NULL -- stock_move.purchase_line_id
                AND line.production_id IS NULL
                AND line.raw_material_production_id IS NULL
            """
        elif model == 'mrp.workorder':
            sql = ''
        
        return sql

    def _groupby(self, model, models):
        res = super()._groupby(model, models)
        
        if model == 'mrp.workorder':
            res = """
                GROUP BY
                    reservation.budget_type,
                    reservation.analytic_account_id,
                    reservation.seq_analytic,
                    record.id,
                    record.project_id
            """
        elif model == 'stock.picking':
            res += ', picking_type.code'
        
        return res
    
