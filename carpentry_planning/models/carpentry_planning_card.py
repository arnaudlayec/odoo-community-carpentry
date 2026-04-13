# -*- coding: utf-8 -*-

from odoo import models, fields, api, _, Command, tools, exceptions
from odoo.osv import expression

from collections import defaultdict

class CarpentryPlanningCard(models.Model):
    _name = 'carpentry.planning.card'
    _description = 'Planning Cards'
    _auto = False
    _order = 'sequence'

    #===== Fields methods =====#
    def _group_expand_column_id(self, records, domain, order):
        return self.env['carpentry.planning.column'].sudo().search([('fold', '=', False)])

    #===== Fields =====#
    # base (view)
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project'
    )
    sequence = fields.Integer()
    active = fields.Boolean(
        readonly=True
    )
    res_id = fields.Many2oneReference(
        string='Real record ID',
        model_field='res_model',
        readonly=True
    )
    column_id = fields.Many2one(
        comodel_name='carpentry.planning.column',
        string='Planning column',
        index=True,
        readonly=True,
        group_expand='_group_expand_column_id'
    )

    # column related
    res_model = fields.Char(related='column_id.res_model_id.model')
    res_model_shortname = fields.Char(related='column_id.res_model_shortname')

    # real record infos
    display_name = fields.Char(compute='_compute_fields')
    shortname = fields.Char(compute='_compute_fields')
    state = fields.Char(compute='_compute_fields')
    state_value = fields.Char(compute='_compute_state_value')
    description = fields.Char(compute='_compute_fields')
    launch_ids = fields.One2many(
        comodel_name='carpentry.group.launch',
        string='Launches',
        compute=True, # needed for `search` not to be ignored
        search='_search_launch_ids', # needed for standard search to work
    )

    # color of body's template (button)
    planning_card_color_class = fields.Char(
        string='Planning Card Color Class',
        compute='_compute_fields',
    )
    # color of card's left bar
    planning_card_color_is_auto = fields.Boolean(compute='_compute_fields')
    planning_card_color_int = fields.Integer(
        compute='_compute_fields',
        inverse='_inverse_planning_card_color_int'
    )

    #===== View build =====#
    def init(self):
        """ Don't create any table. Indeed:
            We need it as a view, but view definition (SQL) depends on table on other modules
            that don't exist in registry yet.
            If we let a table be created, it can't be deleted afterwards (because of foreign keys)

            Odoo will throw an error in console if this module is installed alone (which is useless)
            but as soon as another module adds a `carpentry.planning.column`, this method
            `_rebuild_sql_view()` is trigger which (re)creates the needed view
        """
        return

    def _rebuild_sql_view(self):
        self.env['carpentry.planning.column'].flush_model()
        self.env['carpentry.planning.card'].flush_model()

        column_ids = self.env['carpentry.planning.column'].search([('fold', '=', False)])
        if not column_ids.ids:
            return

        tools.drop_view_if_exists(self._cr, self._table)

        # Parts of the UNION request
        queries = [
            """
                %s -- SELECT
                %s -- FROM
                %s -- JOIN
                %s -- WHERE
                %s -- GROUP BY
                %s -- ORDER BY
            """ % (
                self._select(column, column_ids),
                self._from(column),
                self._join(column),
                self._where(column),
                self._groupby(column),
                self._orderby(column)
            )
            for column in column_ids
        ]

        # Concat subpart into 1 query
        self._cr.execute(f"""
            CREATE or REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() OVER (ORDER BY column_id, res_id) AS id,
                    *
                FROM (
                    ({  ') UNION ALL ('.join(queries)  })
                ) AS result
            )"""
        )

    def _select(self, column, column_ids):
        # 1 relational field per model in the planning
        rel_fields = {}
        for col in column_ids:
            field = f"{col.res_model_shortname}_id"
            value = "card.id" if col.res_model_id == column.res_model_id else "NULL::integer"
            rel_fields[field] = f"{value} AS {field}"
        
        return f"""
            SELECT
                card.id AS res_id,
                {column.id} AS column_id,
                card.active AS active,
                card.sequence AS sequence,
                card.project_id AS project_id,
                {','.join(rel_fields.values())}
        """
    
    def _from(self, column):
        model = column.res_model.replace('.', '_')
        return f'FROM {model} AS card'
    
    def _join(self, column):
        return ''
        # return f"LEFT JOIN carpentry_planning_column AS col ON col.id = {column.id}"
    
    def _where(self, column):
        # No relevant available model when doing tests: skip WHERE clause 
        if self._context.get('test_mode'):
            return ''
        
        # `identifier` is required if 2 columns source cards from same model
        # => in such case, the original model must have a `column_id` field
        #    which we use now to route cards between columns
        identifier = bool(
            column.identifier_res_id
            and column.identifier_res_model_id.id
        )
        return f'WHERE card.column_id = {column.id}' if identifier else ''
    
    def _groupby(self, column):
        return 'GROUP BY card.id'
    
    def _orderby(self, column):
        return ''
    

    #===== ORM overwrite =====#
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """ 1. **Optimization**
                - don't load any data if `launch_ids` is not in domain filter
            2. **Column filtering with specific domain**
                - ensure correct count of record per column
        """
        # 1.
        if not self._get_domain_part(domain, 'launch_ids'):
            return []

        # 2.
        columns = self.env['carpentry.planning.column'].search(
            [('fold', '=', False), ('res_model', '!=', False)]
        )
        for column in columns:
            if not column.res_model or not column.res_model in self.env:
                continue
            
            # Add specific domain per column
            Column = self.env[column.res_model]
            domain_specific = Column._get_planning_domain() if hasattr(Column, '_get_planning_domain') else []
            if domain_specific:
                domain = expression.AND([
                    domain,
                    expression.OR([[('column_id', '!=', column.id)], domain_specific])
                ])

        res = super(CarpentryPlanningCard, self.sudo()).read_group(
            domain, fields, groupby, offset, limit, orderby, lazy
        )
        return res
    
    @api.model
    def search(self, domain=None, offset=0, limit=None, order=None, **kwargs):
        """ Allow specific domain to filter the column's cards """
        # 1. Retrieve the column_id from the domain
        column_id_ = self._get_domain_part(domain, 'column_id')
        domain_column = [] if not column_id_ else [('id', '=', column_id_)]
        column = self.env['carpentry.planning.column'].search(domain_column)
        
        # 2. Get the column's domain (if any) and add it to the current domain
        domain_card = []
        for res_model in column.mapped('res_model'):
            Model = self.env[res_model]
            if hasattr(Model, 'get_planning_domain'):
                domain_card = expression.OR([domain, Model._get_planning_domain()])
        if domain_card:
            domain = expression.AND([domain, domain_card])

        return super(CarpentryPlanningCard, self.sudo()).search(
            domain, offset, limit, order, **kwargs
        )
    
    def _get_domain_part(self, domain, field):
        """ Search and return a tuple (i.e. `domain_part`) in a `domain`
            according to tuples' 1st item (i.e. `field`)
        """
        domain_part = [part for part in domain if part[0] == field]
        return bool(domain_part) and domain_part[0][2]

    #===== Compute related of card's real record =====#
    def _real_record_one(self, mapped_record_ids=None):
        """ Get 1 related records specifically
            This delegates call to `_get_real_records()`, but passing
            the arg `mapped_record_ids` should be mandatory at least within loops
        """
        self.ensure_one()
        mapped_record_ids = mapped_record_ids or self._get_real_records()
        return mapped_record_ids.get(self.id)
    def _get_real_records(self):
        """ Loads related records (*real record*) of a cards
            recordset, in bunch for performance.

            :return: {card_id_: }
        """
        # Loads all related records, per model
        model_to_ids, model_to_recordset = defaultdict(list), {}
        for card in self:
            model_to_ids[card.res_model].append(card.res_id)
        for model, ids in model_to_ids.items():
            model_to_recordset[model] = self.env[model].browse(ids)
        
        return {
            card.id: model_to_recordset.get(
                card.res_model, self.env[card.res_model]
            ).browse(card.res_id)
            for card in self
        }
    
    def _compute_state_value(self):
        mapped_record_ids = self._get_real_records()
        for card in self:
            record = card._real_record_one(mapped_record_ids)
            card.state_value = 'state' in record and dict(record._fields['state'].selection).get(record.state)

    def _get_fields(self):
        return [
            'display_name',
            'state', 'description', 'shortname',
            'planning_card_color_class', 'planning_card_color_is_auto', 'planning_card_color_int',
        ]
    def _compute_fields(self):
        mapped_record_ids = self._get_real_records()
        fields = self._get_fields()
        for card in self:
            record = card._real_record_one(mapped_record_ids).with_context(carpentry_planning=True)
            for field in fields:
                card[field] = record[field] if field in record else False

    @api.model
    def _search_launch_ids(self, operator, value):
        return self._search_by_field('launch_ids', operator, value)

    def _search_by_field(self, field, operator, value):
        """ Replace `launch_ids` by `[related_field]_id.launch_ids` (see `_select()` method)
            example: `plan_set_id.launch_ids`
            (except for *Needs*, which ignores project & launch filters)
        """
        # Calculate list of the related fields, from active columns `res_model_shortname`
        columns = self.env['carpentry.planning.column'].search([('fold', '=', False)])
        fields = [] # e.g. `plan_set_id`, ...
        for column in columns:
            model_shortname = column.res_model_shortname
            m2o_field = model_shortname + '_id'
            rel_field = m2o_field + '.' + field

            if (
                m2o_field in self and
                field in self.env[column.res_model] and
                not rel_field in fields
            ):
                fields.append(rel_field)
        
        return expression.OR([[(field, operator, value)] for field in fields])


    #===== Planning Features =====#
    def _inverse_planning_card_color_int(self):
        """ `planning_card_color_int` may be:
            1. auto:
                (a) if value from card's real record, use it
                (b) else, compute from task status (will backward to (a) if set on real record afterward)
            2. not auto (by default):
                (c) real record field `planning_card_color_int` stores the data (real model must inheriting from `carpentry.planning.mixin`)
        """
        mapped_record_ids = self._get_real_records()
        for card in self.filtered(lambda x: not x.planning_card_color_is_auto):
            record = card._real_record_one(mapped_record_ids)
            if 'planning_card_color_int' in record:
                record.planning_card_color_int = card.planning_card_color_int
    