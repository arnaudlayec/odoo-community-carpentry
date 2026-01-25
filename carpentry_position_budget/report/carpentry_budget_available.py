# -*- coding: utf-8 -*-

from odoo import models, fields, tools, api
from psycopg2.extensions import AsIs

class CarpentryBudgetAvailable(models.Model):
    """ Union of:
        - phase & launch budgets (carpentry.affectation) and
        - project budgets (account.move.budget.line)
        
        for:
        - list view of Phases & Launchs
        - report of *Initially available budget*,
                aka *Where does the budget comes from?*
    """
    _name = 'carpentry.budget.available'
    _description = 'Project & launches budgets'
    _order = "seq_analytic"
    _auto = False
    
    #===== Fields methods =====#
    def _selection_record_ref(self):
        return [
            (x['model'], x['name'])
            for x in self.env['ir.model'].sudo().search_read([], ['model', 'name'])
        ]
    
    #===== Fields =====#
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        readonly=True,
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        readonly=True,
    )
    project_stage_id = fields.Many2one(
        related='project_id.stage_id',
        string='Project stage',
    )
    position_id = fields.Many2one(
        comodel_name='carpentry.position',
        string='Position',
        readonly=True,
    )
    launch_id = fields.Many2one(
        comodel_name='carpentry.group.launch',
        string='Launch',
        readonly=True,
    )
    phase_id = fields.Many2one(
        comodel_name='carpentry.group.phase',
        string='Phase',
        readonly=True,
    )
    analytic_account_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Budget type',
        readonly=True,
    )
    seq_analytic = fields.Integer(
        string='Analytic account sequence',
        readonly=True,
    )
    active = fields.Boolean(
        readonly=True,
    )
    # affectation
    quantity_affected = fields.Integer(
        string='Qty of affected positions',
        group_operator='sum',
        readonly=True,
    )
    # budget
    budget_type = fields.Selection(
        string='Budget category',
        selection=lambda self: self.env['account.analytic.account'].fields_get()['budget_type']['selection'],
        readonly=True,
    )
    amount_unitary = fields.Float(
        string='Unitary Budget',
        readonly=True,
    )
    amount_subtotal = fields.Float(
        # amount * quantity_affected
        string='Budget',
        readonly=True,
    )
    amount_subtotal_valued = fields.Monetary(
        # amount * quantity_affected * hourly_cost
        string='Budget (valued)',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='project_id.currency_id',
        readonly=True,
    )
    # model
    record_model_id = fields.Many2one(
        comodel_name='ir.model',
        string='Document ID',
        readonly=True,
    )
    record_res_model = fields.Char(
        string='Document (model)',
        related='record_model_id.model',
    )

    #===== View build =====#
    def _get_queries_models(self):
        return (
            'project.project', 'carpentry.group.launch', 'carpentry.group.phase', 'carpentry.position',
        )
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        
        queries = self._get_queries()
        if queries:
            budget_types = self.env['account.analytic.account']._get_budget_type_workforce()

            self._cr.execute("""
                CREATE or REPLACE VIEW %(table_name)s AS (
                    
                    SELECT
                        row_number() OVER (ORDER BY result.unique_key) AS id,
                        result.company_id,
                        result.project_id,
                        result.launch_id,
                        result.phase_id,
                        result.position_id,
                        result.record_model_id,
                        result.analytic_account_id,
                        result.seq_analytic,
                        result.budget_type,
                        result.active,
                        SUM(result.quantity_affected) AS quantity_affected,
                        SUM(result.amount_unitary) AS amount_unitary,
                        SUM(result.amount_subtotal) AS amount_subtotal,
                        CASE
                            WHEN result.budget_type = ANY(%(budget_types)s)
                            THEN SUM(result.amount_subtotal) * hourly_cost.coef
                            ELSE SUM(result.amount_subtotal)
                        END AS amount_subtotal_valued
                    
                    FROM (
                        (%(sql_union)s)
                    ) AS result
                    
                    LEFT JOIN carpentry_budget_hourly_cost AS hourly_cost
                        ON  hourly_cost.project_id = result.project_id
                        AND hourly_cost.analytic_account_id = result.analytic_account_id

                    GROUP BY
                        result.unique_key,
                        result.company_id,
                        result.project_id,
                        result.launch_id,
                        result.phase_id,
                        result.position_id,
                        result.record_model_id,
                        result.analytic_account_id,
                        result.budget_type,
                        result.seq_analytic,
                        result.active,
                        hourly_cost.coef
                    
                    ORDER BY seq_analytic
                
                )""", {
                    'table_name': AsIs(self._table),
                    'sql_union': AsIs(') UNION ALL (' . join(queries)),
                    'budget_types': budget_types
                }
            )
    
    def _get_queries(self):
        return (
            self._init_query(model)
            for model in self._get_queries_models()
        )
    
    def _init_query(self, model):
        # (!) Warning: `models` only contains models created before module `carpentry_position_budget`
        models = {x['model']: x['id'] for x in self.env['ir.model'].sudo().search_read([], ['model'])}

        return """
            {select}
            {from_table}
            {join}
            {where}
            {groupby}
            {orderby}
            {having}
        """ . format(
            select=self._select(model, models),
            from_table=self._from(model, models),
            join=self._join(model, models),
            where=self._where(model, models),
            groupby=self._groupby(model, models),
            orderby=self._orderby(model, models),
            having=self._having(model, models),
        )

    def _select(self, model, models):
        if model == 'project.project':
            return f"""
                SELECT
                    'project-' || budget_project.id AS unique_key,

                    -- project & carpentry group
                    project.company_id,
                    project.id AS project_id,
                    NULL AS launch_id,
                    NULL AS phase_id,
                    {models['project.project']} AS record_model_id,
                    TRUE AS active,

                    -- affectation: position & qty affected
                    NULL AS position_id,
                    NULL AS quantity_affected,

                    -- budget
                    budget_project.analytic_account_id,
                    budget_project.budget_type,
                    budget_project.seq_analytic,

                    -- amounts
                    CASE
                        WHEN budget_project.type = 'amount'
                        THEN budget_project.balance
                        ELSE budget_project.qty_balance
                    END AS amount_unitary,

                    CASE
                        WHEN budget_project.type = 'amount'
                        THEN budget_project.balance
                        ELSE budget_project.qty_balance
                    END AS amount_subtotal
                
            """

        else:
            shortname = model.replace('carpentry.', '').replace('group.', '')
            return f"""
                SELECT
                    '{shortname}-' || carpentry_group.id || '-' || budget.id AS unique_key,

                    -- project_id, phase_id, launch_id
                    carpentry_group.company_id,
                    carpentry_group.project_id,
                    {'carpentry_group.id' if model == 'carpentry.group.launch' else 'NULL::integer'} AS launch_id,
                    {'carpentry_group.id' if model == 'carpentry.group.phase'  else 'NULL::integer'} AS phase_id,
                    {models[model]} AS record_model_id,
                    carpentry_group.active,

                    -- affectation: position & qty affected
                    budget.position_id,
                    {
                        'SUM(carpentry_group.quantity)'
                        if model == 'carpentry.position' else
                        'SUM(affectation.quantity_affected)'
                    } AS quantity_affected,

                    -- budget
                    budget.analytic_account_id,
                    budget.budget_type,
                    budget.seq_analytic,

                    -- amounts
                    SUM(budget.amount_unitary) AS amount_unitary,
                    {
                        'SUM(carpentry_group.quantity * budget.amount_unitary)' if model == 'carpentry.position' else
                        'SUM(affectation.quantity_affected * budget.amount_unitary)'
                    } AS amount_subtotal
            """

    def _from(self, model, models):
        if model == 'project.project':
            return 'FROM account_move_budget_line AS budget_project'
        elif model == 'carpentry.position':
            return 'FROM carpentry_position AS carpentry_group'
        else:
            return 'FROM carpentry_affectation AS affectation'

    def _join(self, model, models):
        if model == 'project.project':
            return """
                INNER JOIN project_project AS project
                    ON project.id = budget_project.project_id
            """
        elif model in ('carpentry.group.launch', 'carpentry.group.phase'):
            field = model.replace('carpentry.group.', '') + '_id'
            return f"""
                INNER JOIN carpentry_position_budget AS budget
                    ON budget.position_id = affectation.position_id
                INNER JOIN {model.replace('.', '_')} AS carpentry_group
                    ON carpentry_group.id = affectation.{field}
            """
        elif model == 'carpentry.position':
            return """
                INNER JOIN carpentry_position_budget AS budget
                    ON budget.position_id = carpentry_group.id
            """
    
    def _where(self, model, models):
        sql_where = ''

        if model == 'project.project':
            sql_where += """
                WHERE
                    budget_project.balance != 0 AND
                    is_computed_carpentry IS FALSE
                """

        elif model in ('carpentry.group.launch', 'carpentry.group.phase'):
            mode = model.replace('carpentry.group.', '')
            sql_where += f"""
                WHERE
                    affectation.quantity_affected != 0 AND
                    affectation.active IS TRUE AND
                    affectation.mode = '{mode}'
                """
            
            if mode == 'launch':
                sql_where += ' AND affectation.affected IS TRUE'

        return sql_where

    def _groupby(self, model, models):
        if model == 'project.project':
            return ''
        else:
            return """
                GROUP BY 
                    carpentry_group.company_id,
                    carpentry_group.project_id,
                    carpentry_group.id,
                    budget.id,
                    budget.position_id,
                    budget.budget_type,
                    budget.analytic_account_id
            """
    
    def _orderby(self, model, models):
        return ''
    
    def _having(self, model, models):
        return ''

    #===== ORM method =====#
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """ Add position's `quantity_affected` in position's `display_name`
            when grouping per position
        """
        res = super().read_group(domain, fields, groupby, offset, limit, orderby, lazy)
        
        mode = self._context.get('active_model', '').replace('carpentry.group.', '')
        record_id = self._context.get('active_id')
        if (
            bool(res) and 'position_id' in res[0] # groupby by `position_id`
            and self._context.get('display_model_shortname') # not programatic call
            and bool(mode) and bool(record_id) # pivot view on a single launch or phase
        ):
            field = mode + '_id'
            # count position's affected quantities per launch
            position_ids_ = [x['position_id'][0] for x in res if x.get('position_id')]
            rg_result = self.env['carpentry.affectation'].read_group(
                domain=[
                    ('mode', '=', mode),
                    (field, '=', record_id),
                    ('position_id', 'in', position_ids_)
                ],
                fields=['quantity_affected:sum'],
                groupby=[field, 'position_id'],
                lazy=False,
            )
            mapped_quantities = {
                # (launch_id or phase_id, position_id): qty:sum
                (x[field][0], x['position_id'][0]): x['quantity_affected']
                for x in rg_result
            }

            # modifiy content of inherited `res`
            for data in res:
                res_position = data.get('position_id')
                if not res_position:
                    continue

                position_id, position_name = res_position
                display_name = '{} ({})' . format(
                    position_name,
                    round(mapped_quantities.get((record_id, position_id), 0.0))
                )
                data['position_id'] = (position_id, display_name)
        
        return res
    
    #===== Button =====#
    def open_position_budget(self, position_id=None):
        """ Open document providing budget (position or project) """
        position_id_ = position_id.id if position_id else self.position_id.id

        if not position_id_:
            return self.project_id.button_open_budget_lines()
        else:
            return self.env['ir.actions.act_window']._for_xml_id(
                'carpentry_position_budget.action_open_position_budget_add'
            ) | {
                'domain': [('position_id', '=', position_id_)],
                'context': {'default_position_id': position_id_},
            }
