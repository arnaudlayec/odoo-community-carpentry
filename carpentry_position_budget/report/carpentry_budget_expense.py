# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools
from psycopg2.extensions import AsIs


class CarpentryBudgetExpenseDetail(models.Model):
    """ Should be overriden in each Carpentry module with expense
        Detail because with `date` and `is_temporary` field
    """
    _name = 'carpentry.budget.expense.detail'
    _inherit = ['carpentry.budget.remaining']
    _description = 'Expenses Detail'
    _order = "seq_analytic"
    _auto = False
    
    #===== Fields =====#
    state = fields.Selection(
        selection_add=[('expense_unposted', 'Unposted expense'), ('expense_posted', 'Posted expense'),],
    )
    currency_id = fields.Many2one(
        related='project_id.currency_id',
    )
    date = fields.Date(
        string='Date',
        readonly=True,
    )
    launch_ids = fields.Many2many(
        string='Launchs',
        comodel_name='carpentry.group.launch',
        compute='_compute_launch_ids',
    )
    amount_reserved = fields.Float(
        string='Reserved budget (brut)',
    )
    amount_reserved_valued = fields.Monetary(
        string='Reserved budget',
        readonly=True,
    )
    amount_expense = fields.Float(
        string='Real expense (brut)',
        digits='Product Unit of Measure',
        readonly=True,
    )
    amount_expense_valued = fields.Monetary(
        string='Real expense',
        readonly=True,
    )
    amount_gain = fields.Monetary(
        string='Gain or Loss',
        readonly=True,
        help='Budget reservation - Real expense',
    )
    # record fields with expense through analytic (without budget reservation)
    move_id = fields.Many2one(
        string='Account Move',
        comodel_name='account.move',
        readonly=True,
    )
    move_line_id = fields.Many2one(
        string='Account Move Line',
        comodel_name='account.move.line',
        readonly=True,
    )
    analytic_line_id = fields.Many2one(
        string='Analytic Line',
        comodel_name='account.analytic.line',
        readonly=True,
    )
    # cancel fields
    position_id = fields.Many2one(store=False)
    launch_id = fields.Many2one(store=False)
    amount_subtotal = fields.Float(store=False)

    #===== View build =====#
    def _get_queries_models(self):
        """ Inherited in sub-modules (purchase, mrp, timesheet) """
        return ('carpentry.budget.reservation','account.analytic.line',)
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        
        queries = self._get_queries()
        if queries:
            budget_types = self.env['account.analytic.account']._get_budget_type_workforce()
            self._cr.execute("""
                CREATE VIEW %(view_name)s AS (
                    SELECT
                        row_number() OVER (ORDER BY
                            expense.record_id,
                            expense.record_model_id,
                            expense.analytic_account_id,
                            expense.state,
                            expense.date
                        ) AS id,
                        expense.company_id,
                        expense.project_id,
                        CASE
                            WHEN expense.state IS NULL -- times
                            THEN CASE
                                WHEN expense.date <= COALESCE(company.budget_date_times_posted, CURRENT_DATE)
                                THEN 'expense_posted'
                                ELSE 'expense_unposted'
                            END
                            ELSE expense.state
                        END AS state,
                        expense.date,
                        expense.active,
                        
                        expense.record_id,
                        expense.record_model_id,
                        %(sql_record_fields)s
                        expense.analytic_account_id,
                        expense.budget_type,
                        expense.seq_analytic,
                        hourly_cost.coef AS hourly_cost_coef, -- for `carpentry.budget.expense.distributed`
                        
                        -- reserved budget
                        SUM(expense.amount_reserved) AS amount_reserved,
                        SUM(expense.amount_reserved) * (
                            CASE
                                WHEN expense.budget_type IS NULL
                                THEN 0.0
                                ELSE CASE
                                    WHEN expense.budget_type IN %(budget_types)s
                                    THEN hourly_cost.coef
                                    ELSE 1.0
                                END
                            END
                        ) AS amount_reserved_valued,
                        
                        -- expense
                        SUM(expense.amount_expense) *
                        CASE
                            WHEN expense.budget_type IS NULL
                            THEN 0.0
                            ELSE CASE
                                WHEN expense.budget_type IN %(budget_types)s AND 'DEVALUE' = ANY(ARRAY_AGG(value_or_devalue_workforce_expense))
                                THEN CASE
                                    WHEN COALESCE(hourly_cost.coef, 0.0) != 0.0
                                    THEN 1 / hourly_cost.coef
                                    ELSE 0.0
                                END
                                ELSE 1.0
                            END
                        END AS amount_expense,
                        
                        -- expense valued: computed from `amount_expense` if NULL, and valued from it if needed
                        CASE 
                            WHEN TRUE = ANY(ARRAY_AGG(amount_expense_valued IS NULL)) -- if need computation from `amount_expense`
                            THEN SUM(expense.amount_expense) *
                                CASE
                                    WHEN expense.budget_type IS NULL
                                    THEN 0.0
                                    ELSE CASE
                                        WHEN expense.budget_type IN %(budget_types)s AND 'VALUE' = ANY(ARRAY_AGG(value_or_devalue_workforce_expense))
                                        THEN hourly_cost.coef
                                        ELSE 1.0
                                    END
                                END
                            ELSE SUM(expense.amount_expense_valued)
                        END AS amount_expense_valued,
                        
                        -- gain
                        COALESCE(SUM(expense.amount_reserved) * (
                            CASE
                                WHEN expense.budget_type IS NULL
                                THEN 0.0
                                ELSE CASE
                                    WHEN expense.budget_type IN %(budget_types)s
                                    THEN hourly_cost.coef
                                    ELSE 1.0
                                END
                            END
                        ), 0.0)
                        - COALESCE(CASE 
                            WHEN TRUE = ANY(ARRAY_AGG(amount_expense_valued IS NULL)) -- if need computation from `amount_expense`
                            THEN SUM(expense.amount_expense) *
                                CASE
                                    WHEN expense.budget_type IS NULL
                                    THEN 0.0
                                    ELSE CASE
                                        WHEN expense.budget_type IN %(budget_types)s AND 'VALUE' = ANY(ARRAY_AGG(value_or_devalue_workforce_expense))
                                        THEN hourly_cost.coef
                                        ELSE 1.0
                                    END
                                END
                            ELSE SUM(expense.amount_expense_valued)
                        END, 0.0) AS amount_gain
                    
                    FROM (
                        (%(union)s)
                    ) AS expense
                    
                    -- for (h) to (€) (de)valuation when needed (on PO: € -> h)
                    LEFT JOIN carpentry_budget_hourly_cost AS hourly_cost
                        ON  hourly_cost.project_id = expense.project_id
                        AND hourly_cost.analytic_account_id = expense.analytic_account_id
                        AND expense.budget_type IN %(budget_types)s
                    
                    LEFT JOIN res_company AS company
                        ON company.id = expense.company_id
                    
                    GROUP BY
                        expense.company_id,
                        expense.project_id,
                        expense.state,
                        expense.date,
                        expense.active,
                        expense.record_id,
                        expense.record_model_id,
                        expense.analytic_account_id,
                        expense.budget_type,
                        expense.seq_analytic,
                        hourly_cost.coef,
                        company.budget_date_times_posted
                    
                    ORDER BY
                        expense.seq_analytic,
                        expense.record_id
                )""", {
                    'view_name': AsIs(self._table),
                    'sql_record_fields': AsIs(self._sql_record_fields('expense.')),
                    'budget_types': tuple(budget_types),
                    'union': AsIs(') UNION ALL (' . join(queries)),
            })
    
    def _sql_record_fields(self, view=''):
        """ SQL for balance_id, purchase_id, production_id, task_id, ... """
        sql_record_fields = ''
        for field in self._get_record_fields():
            model = self[field]._name
            if model == 'carpentry.budget.balance':
                model_id = f"(SELECT id FROM ir_model WHERE model = '{model}')"
            else:
                model_id = self.env['ir.model']._get_id(model)
            
            sql_record_fields += f"""
                CASE
                    WHEN {view}record_model_id = {model_id}
                    THEN {view}record_id
                    ELSE NULL
                END AS {field},
            """
        return sql_record_fields
    
    def _sql_record_model_id(self, model, models,
                             relational_fields, default_model_id,
                             prefix=''
    ):
        """ SQL for `record_model_id` """
        sql_record_model_id = ''
        for field in relational_fields:
            record_model_id = bool(model in self.env) and self.env[model]._fields[field].comodel_name
            sql_record_model_id += f"""
                CASE
                    WHEN {prefix}{field} IS NOT NULL
                    THEN {models.get(record_model_id, default_model_id)}
                    ELSE
            """
        return sql_record_model_id + ' NULL ' + ('END ' * len(relational_fields))

    def _select(self, model, models):
        sql = ''

        if model == 'carpentry.budget.reservation':
            record_fields = self.env[model]._get_record_fields()
            sql_record_model_id = self._sql_record_model_id(
                model, models, record_fields,
                default_model_id=f"(SELECT id FROM ir_model WHERE model = 'carpentry.budget.balance')",
            )

            sql = f"""
                SELECT
                    'reservation' AS state,
                    company_id,
                    project_id,
                    date,
                    active AS active,
                    COALESCE({', ' . join (record_fields)}) AS record_id,
                    {sql_record_model_id} AS record_model_id,
                    analytic_account_id,
                    budget_type,
                    seq_analytic,

                    amount_reserved,

                    NULL AS value_or_devalue_workforce_expense,
                    0.0 AS amount_expense,
                    0.0 AS amount_expense_valued
            """
        
        elif model == 'account.analytic.line':
            comodel_fields = self._select_analytic_comodel_fields()
            sql_record_id = ', ' . join(['analytic.' + field for field in comodel_fields])
            sql_record_model_id = self._sql_record_model_id(
                model, models, comodel_fields, default_model_id=models[model], prefix='analytic.'
            )

            sql = f"""
                SELECT
                    'expense_posted' AS state,
                    analytic.company_id,
                    analytic_projects.project_id,
                    analytic.date,
                    TRUE AS active,
                    COALESCE({sql_record_id}) AS record_id,
                    {sql_record_model_id} AS record_model_id,
                    analytic.account_id AS analytic_account_id,
                    analytic.budget_type,
                    account.sequence AS seq_analytic,

                    0.0 AS amount_reserved,

                    'DEVALUE' AS value_or_devalue_workforce_expense,
                    -1 * analytic.amount AS amount_expense,
                    NULL AS amount_expense_valued
            """
        
        return sql
    
    def _select_analytic_comodel_fields(self):
        """ Inherited in module 'carpentry_purchase_budget' """
        return ['id']

    def _from(self, model, models):
        if model == 'carpentry.budget.reservation':
            return "FROM carpentry_budget_reservation AS reservation"
        elif model == 'account.analytic.line':
            return "FROM account_analytic_line AS analytic"
        else:
            return f"FROM {model.replace('.', '_')} AS record"

    def _join(self, model, models):
        if model == 'account.analytic.line':
            return """
                INNER JOIN carpentry_budget_analytic_line_project_rel AS analytic_projects
                    ON analytic_projects.line_id = analytic.id
                INNER JOIN account_analytic_account AS account
                    ON account.id = analytic.account_id
            """
        else:
            return ''

    def _join_product_analytic_distribution(self):
        return """
            INNER JOIN product_product
                ON product_product.id = line.product_id
            INNER JOIN product_template
                ON product_template.id = product_product.product_tmpl_id
            
            INNER JOIN LATERAL
                jsonb_each_text(line.analytic_distribution)
                AS analytic_distribution (aac_id, percentage)
                ON true

            -- analytic
            INNER JOIN account_analytic_account AS analytic
                ON analytic.id = analytic_distribution.aac_id::integer
        """

    def _where(self, model, models):
        if model == 'carpentry.budget.reservation':
            return 'WHERE TRUE'
        elif model == 'account.analytic.line':
            return 'WHERE TRUE' # see INNER JOIN
        else:
            return 'WHERE analytic.budget_type IS NOT NULL'
    
    def _groupby(self, model, models):
        if model == 'carpentry.budget.reservation':
            return ''
        elif model == 'account.analytic.line':
            return """
                GROUP BY
                    analytic.budget_type,
                    analytic.account_id,
                    account.sequence,
                    analytic.company_id,
                    analytic_projects.project_id,
                    analytic.date,
                    analytic.id
            """
        else:
            return """
                GROUP BY
                    analytic.budget_type,
                    analytic.id,
                    analytic.sequence,
                    record.id,
                    record.company_id,
                    record.project_id
            """
    
    def _orderby(self, model, models):
        return ''

    def _having(self, model, models):
        return ''

    #===== Compute =====#
    @api.depends('record_model_id')
    def _compute_launch_ids(self):
        for expense in self:
            record = expense.record_ref
            expense.launch_ids = bool(
                record and record._name != 'project.project' and hasattr(record, 'launch_ids')
            ) and record.launch_ids

class CarpentryBudgetExpense(models.Model):
    """ *Not* grouped by `date` neither `state`, for *Loss/Gains* report """
    _name = 'carpentry.budget.expense'
    _inherit = ['carpentry.budget.expense.detail']
    _description = 'Expenses'
    _order = "seq_analytic"
    _auto = False

    state = fields.Selection(store=False)
    date = fields.Date(store=False)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self._cr.execute("""
            CREATE or REPLACE VIEW %(view_name)s AS (
                SELECT
                    row_number() OVER (ORDER BY
                        record_id,
                        record_model_id,
                        analytic_account_id
                    ) AS id,
                    company_id,
                    project_id,
                    active,
                    
                    record_id,
                    record_model_id,
                    %(sql_record_fields)s
                    analytic_account_id,
                    seq_analytic,
                    budget_type,
                    -- AVG(hourly_cost_coef) AS hourly_cost_coef, -- for `carpentry.budget.expense.distributed`
                    
                    SUM(amount_reserved) AS amount_reserved,
                    SUM(amount_reserved_valued) AS amount_reserved_valued,
                    SUM(amount_expense) AS amount_expense,
                    SUM(amount_expense_valued) AS amount_expense_valued,
                    SUM(amount_gain) AS amount_gain
                
                FROM carpentry_budget_expense_detail
                
                GROUP BY
                    company_id,
                    project_id,
                    record_id,
                    record_model_id,
                    analytic_account_id,
                    seq_analytic,
                    budget_type,
                    active
                
                ORDER BY seq_analytic
            )""", {
                'view_name': AsIs(self._table),
                'sql_record_fields': AsIs(self._sql_record_fields())
            }
        )
