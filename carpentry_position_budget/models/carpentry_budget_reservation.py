# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from odoo.osv import expression

from odoo.tools import float_is_zero

class CarpentryBudgetReservation(models.Model):
    """ This model is quite similar to `carpentry.affectation`,
        but for budget reservation from Launchs & Project
        instead than position's quantity affectation from Lots & Phases
    """
    _name = "carpentry.budget.reservation"
    _description = "Budget reservation"
    _order = "project_budget DESC, seq_analytic, sequence_launch, sequence_record"
    _log_access = False

    #===== Fields =====#
    company_id = fields.Many2one(
        related='project_id.company_id',
        store=True,
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        readonly=True,
        required=True,
        ondelete='cascade',
    )
    launch_id = fields.Many2one(
        comodel_name='carpentry.group.launch',
        string='Launch',
        required=False,
        ondelete='restrict',
    )
    analytic_account_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Budget',
        required=True,
        ondelete='restrict',
    )
    budget_unit = fields.Char(compute='_compute_budget_unit_type', compute_sudo=True)
    budget_type = fields.Selection(
        selection=lambda self: self.env['account.analytic.account']._fields['budget_type'].selection,
        compute='_compute_budget_unit_type',
        store=True,
    )
    currency_id = fields.Many2one(related='project_id.currency_id')
    # sequence
    project_budget = fields.Boolean(
        # used in _order
        compute='_compute_project_budget',
        store=True,
    )
    sequence_launch = fields.Integer(
        string='Launch sequence',
        related='launch_id.sequence',
        store=True,
    )
    seq_analytic = fields.Integer(
        string='Analytic account sequence',
        related='analytic_account_id.sequence',
        store=True,
    )
    # records
    balance_id = fields.Many2one(
        comodel_name='carpentry.budget.balance',
        string='Balance',
        ondelete='cascade',
    )
    # record fields
    record_field = fields.Char(string='Record field', compute='_compute_record_field')
    sequence_record = fields.Integer(string='Record sequence',)
    date = fields.Date(string='Date', copy=False,)
    active = fields.Boolean(string='Active', copy=False,)
    # amounts
    amount_reserved = fields.Float(
        string="Reservation",
        digits='Product Unit of Measure',
        group_operator='sum',
    )
    amount_reserved_valued = fields.Monetary(
        string="Reservation (valued)",
        group_operator='sum',
        compute='_compute_amount_reserved_valued',
        store=True,
    )
    amount_initially_available = fields.Float(
        string="Initially available",
        digits='Product Unit of Measure',
        group_operator='sum',
        compute='_compute_amount_initial_siblings',
    )
    amount_reserved_siblings = fields.Float(
        string="Reserved by other records",
        digits='Product Unit of Measure',
        group_operator='sum',
        compute='_compute_amount_initial_siblings',
    )
    amount_remaining = fields.Float(
        string="Remaining",
        digits='Product Unit of Measure',
        group_operator='sum',
        compute='_compute_amount_remaining',
    )
    amount_expense_valued = fields.Monetary(
        string="Expense",
        group_operator='sum',
        help="Distribution of expense on this launch and budget center",
        compute='_compute_amount_expense_gain_valued',
        store=True,
    )
    amount_gain = fields.Monetary(
        string='Gain',
        group_operator='sum',
        help='Budget reservation - Real expense',
        compute='_compute_amount_expense_gain_valued',
        store=True,
    )

    #===== Index (+unique) & constraints =====#
    def init(self):
        super().init()
        
        # project & launch reservations index (also ensures unicity)
        fields = self._get_record_fields()
        for field in fields:
            model = field.replace('_id', '')
            self.env.cr.execute(f"""
                -- launch
                DROP INDEX IF EXISTS idx_carpentry_budget_reservation_integrity_launch_{model};
                CREATE UNIQUE INDEX idx_carpentry_budget_reservation_integrity_launch_{model} 
                ON carpentry_budget_reservation (project_id, launch_id, analytic_account_id, {field})
                WHERE launch_id IS NOT NULL;;
                
                -- project
                DROP INDEX IF EXISTS idx_carpentry_budget_reservation_integrity_project_{model};
                CREATE UNIQUE INDEX idx_carpentry_budget_reservation_integrity_project_{model}
                ON carpentry_budget_reservation (project_id, analytic_account_id, {field})
                WHERE launch_id IS NULL;
            """)
    
    #===== Constrain: no overconsumption =====#
    @api.constrains('amount_reserved')
    def _constrain_amount_reserved(self):
        if self._context.get('silence_constrain_amount_reserved'):
            # was useful for migration, left it, can be useful afterwards
            return
        
        reservation = fields.first(self.filtered(lambda x: x.amount_remaining < 0))
        if reservation:
            raise exceptions.ValidationError(_(
                "The reserved budget is higher than the one available in the project:\n\n"
                "Launchs: %(launchs)s\n"
                "Budget centers: %(analytics)s\n"
                "Initial budget in the project: %(initial_budget)s\n"
                "Budget reserved on other documents: %(reservation_other)s\n"
                "Temptative of budget reservation: %(reservation_current)s\n"
                "Overconsumption: %(overconsumption)s",
                launchs=' ,' . join(reservation.launch_id.mapped('name')),
                analytics=' ,' . join(reservation.analytic_account_id.mapped('name')),
                initial_budget=reservation.amount_initially_available,
                reservation_other=reservation.amount_reserved_siblings,
                reservation_current=reservation.amount_reserved,
                overconsumption=-1.0 * reservation.amount_remaining,
            ))

    #===== Compute =====#
    @api.depends('launch_id')
    def _compute_project_budget(self):
        for reservation in self:
            reservation.project_budget = not bool(reservation.launch_id)
    
    @api.depends('analytic_account_id')
    def _compute_budget_unit_type(self):
        budget_unit_forced = '€' if self._context.get('brut_or_valued') == 'valued' else None
        
        for reservation in self:
            reservation.budget_unit = budget_unit_forced or reservation.analytic_account_id.budget_unit
            reservation.budget_type = reservation.analytic_account_id.budget_type
    
    #===== Compute: record field =====#
    def _get_record_fields(self):
        """ To inherit """
        return ['balance_id']
    
    @api.model
    def _get_key(self, **kwargs):
        return self.env['carpentry.budget.mixin']._get_key(**kwargs)
    
    @api.depends(lambda self: self._get_record_fields())
    def _compute_record_field(self):
        """ :return: like 'balance_id' or 'purchase_id' or ... """
        record_fields = self._get_record_fields()
        first = fields.first(self)._found_record_field_one(record_fields)
        if first and record_fields[0] != first: # optim: put 1st record_field at beginning of fields
            record_fields = [first] + [x for x in record_fields if x != first]
        
        for reservation in self:
            reservation.record_field = reservation._found_record_field_one(record_fields)
    def _found_record_field_one(self, fields):
        for field in fields:
            if self[field].exists():
                return field
        return False

    def _update_record_fields(self):
        """ Called from `carpentry.budget.mixin` """
        for reservation in self:
            record = reservation._origin[reservation.record_field]

            reservation['sequence_record'] = record._get_default_sequence()
            reservation['active'] = record._get_default_active()
            reservation['date'] = (
                record.date_budget
                if record and hasattr(record, 'date_budget')
                else False
            )

    #===== Compute: amounts =====#
    def _get_domain_budget_reservation(self, exclude=False, with_record=True):
        operator = 'not in' if exclude else 'in'
        base_domain = [
            ('project_id', 'in', self.project_id._origin.ids),
            ('analytic_account_id', 'in', self.analytic_account_id._origin.ids),
            ('launch_id', 'in', [False] + self.launch_id._origin.ids),
        ]
        if not with_record:
            return base_domain
        
        domain_records = []
        record_fields = [x for x in set(self.mapped('record_field')) if bool(x)]
        for record_field in record_fields:
            domain_records = expression.OR([
                domain_records,
                [(record_field, operator, self[record_field]._origin.ids)]
            ])
        return base_domain + domain_records

    @api.depends('project_id')
    def _compute_amount_initial_siblings(self):
        """ Budget mode: default to 'brut'
            can be enforced in the view with context="{'brut_or_valued': 'brut' or 'valued'}"
        """
        debug = False
        if debug:
            print(' == _compute_amount_initial_siblings == ')
            print('self', self)
            print('record', self[fields.first(self).record_field])
        
        self = self.with_context(active_test=True)

        self.flush_model(['amount_reserved'])
        domain=self._get_domain_budget_reservation(with_record=False) + [
            '|',
            ('record_res_model', 'in', ['project.project', 'carpentry.group.launch']), # exclude positions
            ('state', '=', 'reservation'),
        ]
        _valued = '_valued' if self._context.get('brut_or_valued', 'brut') == 'valued' else ''
        amount_field = 'amount_subtotal' + _valued
        rg_fields = ['project_id', 'launch_id', 'analytic_account_id']
        rg_result = self.env['carpentry.budget.remaining']._read_group(
            domain=domain,
            groupby=['state'] + rg_fields,
            fields=[amount_field + ':sum', 'ids:array_agg(id)', 'aggr:array_agg(' + amount_field + ')'],
            lazy=False,
        )
        mapped_budgets = {'budget': {}, 'reservation': {}}
        for x in rg_result:
            key = tuple([x[field] and x[field][0] for field in rg_fields])
            mapped_budgets[x['state']][key] = x[amount_field]

        if debug:
            print('reservation', self.read(rg_fields + ['balance_id', 'purchase_id', 'amount_reserved']))
            print('domain', domain)
            print('search_domain', self.env['carpentry.budget.remaining'].search_read(domain, ['state'] + rg_fields + [amount_field]))
            print('rg_result', rg_result)
            print('mapped_budgets', mapped_budgets)
        
        for reservation in self:
            key = tuple([reservation[field]._origin.id for field in rg_fields])

            reservation.amount_initially_available = mapped_budgets['budget'].get(key, 0.0)
            reservation.amount_reserved_siblings = (
                -1 * mapped_budgets['reservation'].get(key, 0.0)
                - reservation._origin.amount_reserved
            )

            # if debug:
            #     print('amount_reserved', amount_reserved)
            #     print('amount_inially_available', mapped_budgets['budget'].get(key, 0.0))
            #     print('mapped_budget[reservation]', mapped_budgets['reservation'].get(key, 0.0))
            #     print('amount_reserved_siblings', reservation.amount_reserved_siblings)
            #     print('amount_remaining', reservation.amount_remaining)

    @api.depends('amount_initially_available', 'amount_reserved_siblings', 'amount_reserved')
    def _compute_amount_remaining(self):
        for reservation in self:
            reservation.amount_remaining = (
                reservation.amount_initially_available
                - reservation.amount_reserved_siblings
                - reservation.amount_reserved
            )
    
    @api.depends(
        'amount_reserved',
        'project_id', 'project_id.date', 'project_id.date_start',
        # moved to `cost_history.py` CRUD
        # 'analytic_account_id.timesheet_cost_history_ids.starting_date',
        # 'analytic_account_id.timesheet_cost_history_ids.date_to',
        # 'analytic_account_id.timesheet_cost_history_ids.hourly_cost',
    )
    def _compute_amount_reserved_valued(self):
        reservations = self.filtered('id')
        (self - reservations).amount_reserved_valued = 0.0
        if not reservations:
            return
        
        # flush
        reservations.flush_recordset(['amount_reserved'])
        reservations.project_id.flush_recordset(['date_start', 'date'])
        self.env['hr.employee.timesheet.cost.history'].flush_model()

        budget_types = self.env['account.analytic.account']._get_budget_type_workforce()
        self._cr.execute("""
            SELECT
                reservation.id,
                SUM(reservation.amount_reserved * (
                    CASE
                        WHEN reservation.budget_type IN %(budget_types)s
                        THEN hourly_cost.coef
                        ELSE 1.0
                    END
                ))
            FROM carpentry_budget_reservation AS reservation
            LEFT JOIN carpentry_budget_hourly_cost AS hourly_cost
                ON  hourly_cost.project_id = reservation.project_id
                AND hourly_cost.analytic_account_id = reservation.analytic_account_id
            WHERE reservation.id IN %(reservation_ids)s
            GROUP BY reservation.id
        """, {
            'budget_types': tuple(budget_types),
            'reservation_ids': tuple(reservations._origin.ids),
        })
        mapped_data = {row[0]: row[1] for row in self._cr.fetchall()}
        for reservation in reservations:
            reservation.amount_reserved_valued = mapped_data.get(reservation.id, 0.0)

    # no depends: called from record's _compute methods
    def _compute_amount_expense_gain_valued(self, rg_result=[]):
        """ Allow to Display *real* expense (and gain) for information,
            in budget reservation table.

            Called when updating either record's
             `amount_expense_valued` or `total_budget_reserved`
        """
        debug = False
        if debug:
            print(' == _compute_amount_expense_gain_valued == ')
            print('self', self)
            print('rg_result', rg_result)
        
        # format expenses (not per launch yet)
        record_fields = set(self.mapped('record_field'))
        rg_groupby = ['analytic_account_id'] + list(record_fields)
        mapped_expense_gain = {
            tuple([x[field] and x[field][0] for field in rg_groupby]):
            (x['amount_expense_valued'], x['amount_gain'])
            for x in rg_result
        }
        
        # group-sum the total of budget reserved per launch
        # already in cache => don't call `read_group` for this
        mapped_reserved_budget = {}
        for reservation in self:
            key = tuple([reservation[field]._origin.id for field in rg_groupby])
            if not key in mapped_reserved_budget:
                mapped_reserved_budget[key] = 0.0
            mapped_reserved_budget[key] += reservation.amount_reserved
        
        # compute
        prec = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for reservation in self:
            # total expense / gain at record level
            key = tuple([reservation[field]._origin.id for field in rg_groupby])
            (expense_valued, amount_gain) = mapped_expense_gain.get(key, (0.0, 0.0))
            
            # spread expense & gain by launch, as per:
            # * reserved budget per aac
            # * if 0.0 reserved, by number of launchs on this budget
            total_reserved = mapped_reserved_budget.get(key, 0.0)
            if float_is_zero(total_reserved, prec) and reservation.record_field:
                record = reservation[reservation.record_field]
                siblings = record.reservation_ids.filtered(lambda x:
                    x.analytic_account_id == reservation.analytic_account_id and x.launch_id
                )
                ratio = 1 / len(siblings) if len(siblings) else 0.0
            else:
                ratio = reservation.amount_reserved / total_reserved if total_reserved else 0.0
            reservation.amount_expense_valued = expense_valued * ratio
            reservation.amount_gain = amount_gain * ratio
        
        if debug:
            print('mapped_expense_gain', mapped_expense_gain)
            print('mapped_reserved_budget', mapped_reserved_budget)
