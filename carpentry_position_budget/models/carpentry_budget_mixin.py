# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.tools import float_round, float_is_zero
from odoo.tools.safe_eval import safe_eval
from odoo.osv import expression

from lxml import etree
from odoo.tools.misc import frozendict

import calendar
from collections import defaultdict
from datetime import datetime

class CarpentryBudgetMixin(models.AbstractModel):
    """ Budget reservation fields & methods for inheriting models (records*)
        to reserve budget in `carpentry.budget.reservation`
        (*) records are like: Purchase Orders, Manufacturing Orders, Pickings, Tasks and Budget Balances

        This mixin is the equivalent of `carpentry.affectation.mixin` for `carpentry.group.(phase|launch)`
    """
    _name = 'carpentry.budget.mixin'
    _description = 'Carpentry Budget Reservation Mixin'
    _record_field = '' # to inherit, like 'balance_id'
    _record_fields_expense = [] # to inherit, like 'order_line'

    _carpentry_budget_alert_banner_xpath = "//div[hasclass('oe_title')]"
    _carpentry_budget_notebook_page_xpath = '//page[@name="products"]'
    _carpentry_budget_sheet_name = 'Budget'
    _carpentry_budget_choice = True
    _carpentry_budget_last_valuation_step = False # whether temporary alert may be displayed

    #===== Fields =====#
    reservation_ids = fields.One2many(
        comodel_name='carpentry.budget.reservation',
        inverse_name='balance_id', # to overwitte
        string='Budget reservations',
        context={'active_test': False},
        compute='_compute_reservation_ids',
        store=True,
        readonly=False,
        copy=False,
    )
    budget_analytic_ids = fields.Many2many(
        comodel_name='account.analytic.account',
        string='Budgets',
        copy=False,
    )
    expense_ids = fields.One2many(
        comodel_name='carpentry.budget.expense',
        inverse_name='balance_id', # to overwitte
        string='Expense',
        depends=['project_id'],
        context={'active_test': False},
    )
    other_expense_ids = fields.Many2many(
        comodel_name='carpentry.budget.expense',
        string='Other expenses',
        compute='_compute_other_expense_ids',
        context={'active_test': False},
    )
    date_budget = fields.Date(
        compute='_compute_date_budget',
        string='Budget date',
        store=True,
    )
    # amount
    total_budget_reserved = fields.Float(
        # brut *or* valued
        compute='_compute_total_budget_reserved',
        string='Reserved budget',
        store=True,
    )
    total_budgetable = fields.Float(
        # brut *or* valued
        # amount shown in budget reservation alert
        # expense for PO, picking, components
        # planned hours for tasks & work orders
        compute='_compute_view_fields',
    )
    total_expense_valued = fields.Monetary(
        string="Real expense",
        compute='_compute_total_expense_gain',
        help="Total cost imputed to the budgets",
        store=True,
    )
    budget_unit = fields.Char(
        string='Budget unit',
        default='€',
        store=False,
    )
    amount_gain = fields.Monetary(compute='_compute_total_expense_gain',store=True,)
    amount_loss = fields.Monetary(compute='_compute_view_fields',)
    budget_verified = fields.Boolean(
        string='Budget verified?',
        help="Whether the budget reservation has been verified by a tier.",
        default=False,
    )
    # -- view fields --
    readonly_reservation = fields.Boolean(
        compute='_compute_readonly_reservation',
    )
    readonly_budget_analytic_ids = fields.Boolean(
        compute='_compute_readonly_budget_analytic_ids',
    )
    can_reserve_budget = fields.Boolean(
        compute='_compute_can_reserve_budget',
        search='_search_can_reserve_budget',
    )
    show_gain = fields.Boolean(compute='_compute_view_fields',)
    show_budget_banner = fields.Boolean(compute='_compute_view_fields',)
    is_temporary_gain = fields.Boolean(compute='_compute_view_fields',)
    text_no_reservation = fields.Char(compute='_compute_view_fields',)
    # currency
    project_id = fields.Many2one(comodel_name='project.project')
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        readonly=True,
        default=lambda self: self.env.company.currency_id.id
    )
    
    #===== CRUD : reservations populate & line's analytic_distribution =====#
    def write(self, vals):
        res = super().write(vals)

        # -- after `write` --
        if 'launch_ids' in vals or (
            'budget_analytic_ids' in vals and not self._context.get('carpentry_budget_analytics_auto')
        ):
            # we don't want `launch_ids` and `budget_analytic_ids` in @depends of `_compute_reservation_ids`
            # so that `budget_analytic_ids` is not recomputed automatically
            self._compute_reservation_ids(vals=vals)
        
        # cascade some record's fields to reservations
        fields = ('state', 'sequence', 'active', 'date_budget')
        if any(field in vals for field in fields):
            self.reservation_ids._update_record_fields()

        return res
    
    def _depends_reservation_refresh(self):
        """ To inherite. Fields that triggers automatic budget reservation.
            Used by `reservation_ids._compute_amount_reserved`, which process in order:
             1. `_refresh_budget_analytic_ids`
             2. `_auto_update_budget_reservation`
             3. `_compute_total_expense_gain`
            Example: ['order_line.analytic_distribution', 'amount_untaxed']
        """
        return []
    def _depends_expense_totals(self):
        """ To inherite. Fields that only trigger `_compute_total_expense_gain` (*permanent* expenses)
            
            (!) MUST NOT includes field of `_depends_reservation_refresh`,
             for `rg_result` optim. Indeed, `_compute_total_expense_gain` is already called
             from `reservation_ids._compute_amount_reserved` with the `rg_result` cursor
        """
        return []
    
    #====== Analytic mixin ======#
    @api.onchange('project_id')
    def _cascade_project_to_line_analytic_distrib(self, new_project_id=None):
        return super()._cascade_project_to_line_analytic_distrib(new_project_id)
    
    #===== Compute =====#
    def _compute_state(self):
        """ Ensure `reservation_ids.active` follows `record.state`,
            which mostly is a computed stored field and thus not catched in `write`
        """
        if hasattr(super(), '_compute_state'):
            res = super()._compute_state()
            self.reservation_ids._update_record_fields()
            return res
    
    #--- Date & other expenses ---#
    @api.depends('create_date')
    def _compute_date_budget(self):
        """ [To overwritte]
            Date's field on which budget reports can be filtered (expense & project result)
        """
        for record in self:
            if not record.date_budget:
                record.date_budget = record.create_date
            record.reservation_ids.date = record.date_budget
    
    @api.depends('project_id', 'launch_ids', 'budget_analytic_ids')
    def _compute_other_expense_ids(self):
        # optim: only compute at 'Save'
        if isinstance(fields.first(self).id, models.NewId):
            self.other_expense_ids = bool(self._origin) and self._origin.other_expense_ids
            return
        
        for record in self:
            record.other_expense_ids = record.expense_ids._origin.filtered(
                lambda x: x.analytic_account_id not in record.reservation_ids.analytic_account_id
            )
    
    #--- Readonly fields ---#
    @api.depends(lambda self: (
        self._depends_reservation_refresh() + 
        ['project_id', 'launch_ids', 'budget_analytic_ids']
    ))
    def _compute_readonly_reservation(self):
        """ Way to inform users the budget matrix must be re-computed
            1. At page load, self == self._origin
            2. At any fields changes, self == <NewId ...>
        """
        self.readonly_reservation = not bool(self == self._origin)

    @api.depends(lambda self: (
        self._depends_reservation_refresh() + 
        ['project_id', 'launch_ids'] # (!) without 'budget_analytic_ids'
    ))
    def _compute_readonly_budget_analytic_ids(self):
        """ Same than `readonly_reservation`, but
             leave `budget_analytic_ids` writable when
             modifying `budget_analytic_ids` itself
        """
        self.readonly_budget_analytic_ids = not bool(self == self._origin)

    #--- View fields ---#
    def _depends_can_reserve_budget(self):
        return ['state']

    def _get_domain_is_temporary_gain(self):
        """ Whether to show alert about *temporary gain/loss* estimation """
        return []
    
    @api.depends(lambda self: self._depends_can_reserve_budget())
    def _compute_can_reserve_budget(self):
        domain_budget = self._get_domain_can_reserve_budget()
        for record in self:
            record.can_reserve_budget = bool(record.filtered_domain(domain_budget))

    @api.model
    def _search_can_reserve_budget(self, operator, value):
        domain = self._get_domain_can_reserve_budget()
        if (
            operator not in expression.NEGATIVE_TERM_OPERATORS and value
            or operator in expression.NEGATIVE_TERM_OPERATORS and not value
        ):
            return domain
        else:
            return expression.distribute_not(['!'] + domain)

    def _get_domain_can_reserve_budget(self):
        """ Prevent budget reservation under some conditions """
        return [('state', '!=', 'cancel'),]
    
    def _depends_view_fields(self):
        return (
            ['reservation_ids', 'budget_analytic_ids', 'launch_ids',
             'total_expense_valued', 'amount_gain'
            ]
            + [part[0] for part in self._get_domain_is_temporary_gain()]
        )
    @api.depends(lambda self: self._depends_view_fields())
    def _compute_view_fields(self, field_suffix=''):
        """ After computation of totals, configures the UI layout of record' form
            This must stay simple logic quick to execute (called twice in MRP)
        """
        prec = self.env['decimal.precision'].precision_get('Product Price')

        for record in self:
            record._compute_view_fields_one(prec, field_suffix)
    
    def _compute_view_fields_one(self, prec, field_suffix):
        domain_temporary = self._get_domain_is_temporary_gain()
        is_temporary = bool(self.filtered_domain(domain_temporary))
        is_gain_zero = float_is_zero(self['amount_gain' + field_suffix], precision_digits=prec)
        reservations = self['reservation_ids' + field_suffix]

        self['amount_loss' + field_suffix] = -1 * self['amount_gain' + field_suffix]
        self['total_budgetable' + field_suffix] = self['total_expense_valued' + field_suffix]
        self['show_gain' + field_suffix] = self.can_reserve_budget and not is_gain_zero
        self['show_budget_banner' + field_suffix] = self['show_gain' + field_suffix]
        self['is_temporary_gain' + field_suffix] = is_temporary

        # text when no affectation due to launchs or budget centers
        text = ''
        if not reservations:
            budgets, launchs = self['budget_analytic_ids' + field_suffix], self['launch_ids']
            if budgets and launchs:
                text = _('Verify if selected budget center(s) have budget in the project.')
            else:
                if not budgets and not launchs:
                    word = _('budget center(s) and possibly launch(s)')
                elif not budgets:
                    word = _('budget center(s)')
                else:
                    word = _('launch(s)')
                text = _('Please select %s in order to reserve budget.', word)
        self['text_no_reservation' + field_suffix] = text

    #===== Compute records's total amounts =====#
    def _should_value_budget_reservation(self):
        """ True on PO and picking: always in € """
        return False

    @api.depends(
        'launch_ids',
        'reservation_ids.amount_reserved', 'reservation_ids.amount_reserved_valued',
    )
    def _compute_total_budget_reserved(self, rg_result=None):
        """ Sum(reservation_ids.amount_reserved), brut or valued
            :option rg_result: for cost_history
        """
        debug = False
        if debug:
            print(' == _compute_total_budget_reserved == ')
            print('self', self)
        
        # optim: don't call the heavy SQL on user action and wait for the form to be saved
        if (isinstance(fields.first(self).id, models.NewId)
            or self._context.get('carpentry_budget_no_compute')
        ):
            if debug: print('stopped')
            return
        
        # shortcut
        records = self.filtered('reservation_ids')
        (self - records).total_budget_reserved = 0.0
        if not records:
            return
        
        for record in records:
            record._compute_total_budget_reserved_one()
        
        # update reservation's expense & gain
        if rg_result:
            self.reservation_ids._compute_amount_expense_gain_valued(rg_result)
        else:
            self._get_rg_result_expense() # _compute is included in it
    
    def _compute_total_budget_reserved_one(self):
        """ Inherited in MRP """
        _valued = '_valued' if self._should_value_budget_reservation() else ''
        self.total_budget_reserved = sum(self.reservation_ids.mapped('amount_reserved' + _valued))

    @api.depends(lambda self:
        ['launch_ids',
         'reservation_ids.amount_reserved', 'reservation_ids.amount_reserved_valued']
        + self._depends_expense_totals()
    )
    def _compute_total_expense_gain(self, groupby_analytic=False, rg_result=None):
        """ Call `carpentry.budget.expense` to compute:
            - total_expense_valued
            - amount_gain

            :option groupby_analytic: for MRP
            :option `rg_result`:
        """
        debug = False
        if debug:
            print(' === _compute_total_expense_gain (start) ===')
            print('self', self)

        # optim: don't call the heavy SQL on user action and wait for the form to be saved
        if (
            not self
            or isinstance(fields.first(self).id, models.NewId)
            or self._context.get('carpentry_budget_no_compute')
        ):
            if debug: print('stopped')
            return
        
        mapped_totals = defaultdict(dict) if groupby_analytic else {}
        pivot_analytic_to_budget_type = {}

        total_fields = ['amount_expense_valued', 'amount_gain']
        rg_result = rg_result or self._get_rg_result_expense()

        for x in rg_result:
            record_id = x[self._record_field][0]
            totals = [x[field] for field in total_fields]
            if groupby_analytic: # MRP
                aac_id = x['analytic_account_id'][0] if x['analytic_account_id'] else False
                mapped_totals[record_id][aac_id] = totals
                if x['budget_type']:
                    pivot_analytic_to_budget_type[aac_id] = x['budget_type'][0]
            else: # PO, picking, ...
                old_totals = mapped_totals.get(record_id, [0.0, 0.0])
                mapped_totals[record_id] = [
                    totals[0] + old_totals[0],
                    totals[1] + old_totals[1],
                ]
    
        for record in self:
            if debug:
                print(' === _compute_total_expense_gain (result) === ')
                print('rg_result', rg_result)
                print('search_read', self.env['carpentry.budget.expense'].search_read(
                    domain=[(record._record_field, '=', record._origin.id)],
                    fields=['amount_reserved', 'amount_expense', 'amount_gain'],
                ))
                print('mapped_totals', mapped_totals.get(record.id, []))
                # print("analytics", self.env["account.analytic.line"].search_read(
                #     domain=[(record._record_field, '=', record._origin.id)],
                #     fields=['amount', 'budget_project_ids', 'account_id'],
                # ))
            
            record._compute_total_expense_gain_one(
                mapped_totals.get(record.id, {} if groupby_analytic else [0.0, 0.0]),
                pivot_analytic_to_budget_type,
            )

    def _compute_total_expense_gain_one(
            self, totals,
            pivot_analytic_to_budget_type = {}, field_suffix = '' # for MRP
        ):
        """ Totals calculation of single `self` so it can be
            overwritten in MRP

            :arg totals: {aac_id: sum_expense, sum_gain}
            :option pivot_analytic_to_budget_type: {aac_id: budget_type} for MRP
            :option field_suffix: for MRP
        """
        # totals
        if isinstance(totals, list):
            (sum_expense, sum_gain) = totals
        elif isinstance(totals, dict): # for MRP
            (sum_expense, sum_gain) = (0.0, 0.0)
            for (expense, gain) in totals.values():
                sum_expense += expense
                sum_gain += gain
        else:
            raise exceptions.UserError("Operation not supported.")

        # set sums fields
        fields = {
            'total_expense_valued': sum_expense,
            'amount_gain': sum_gain,
        }
        for k, v in fields.items():
            if k + field_suffix in self:
                self[k + field_suffix] = v
            else:
                self[k] = v
        
        debug = False
        if debug:
            print(' == _compute_total_expense_gain_one == ')
            print('fields', fields)
            print('field_suffix', field_suffix)
            print('totals', totals)
    
    def _get_rg_result_expense(self, rg_fields=[]):
        """ Return `rg_result` for `_compute_total_expense_gain` and `_get_total_budgetable_by_analytic`
            :option `record_ids`: `carpentry.budget.reservation`
            :option `rg_fields`: for MRP
        """
        debug = False
        if debug:
            print(' === _get_rg_result_expense (start) ===')
        
        # read_group (-> this call is very expensive)
        self._flush_budget()
        Expense = self.env['carpentry.budget.expense'].with_context(active_test=False).sudo()
        rg_result = Expense._read_group(
            domain=[(self._record_field, 'in', self._origin.ids)],
            groupby=['analytic_account_id', self._record_field],
            fields=rg_fields + [
                'amount_expense:sum', 'amount_expense_valued:sum',
                'amount_gain:sum',
            ],
            lazy=False,
        )
        
        # update reservation's expense & gain (without recomputing! else it recomputes budget_analytic_ids)
        self_ctx = self.with_context(carpentry_reservation_no_compute=True)
        if self_ctx.reservation_ids:
            self_ctx.reservation_ids._compute_amount_expense_gain_valued(rg_result)

        if debug:
            print(' == _get_rg_result_expense (result) == ')
            print('_record_field, self.ids', self._record_field, self.ids)
            print('reservations', self.reservation_ids.read(['analytic_account_id', 'amount_reserved', self._record_field]))
            print('expense_all', Expense.search_read(
                [(self._record_field, 'in', self.ids)],
                ['analytic_account_id', 'amount_expense', 'amount_expense_valued', 'amount_reserved', 'amount_gain']
            ))
            print('rg_result', rg_result)
        return rg_result
    
    def _flush_budget(self):
        # Record
        record_fields = (
            self._depends_expense_totals() + self._depends_reservation_refresh() +
            ['active', 'state', 'project_id', 'budget_analytic_ids', 'total_budget_reserved']
        )
        self_one = fields.first(self)
        self.flush_recordset([x for x in record_fields if hasattr(self_one, x)])
        # Reservations
        self.reservation_ids.flush_recordset(['amount_reserved'])
        # Expenses
        self.env["account.analytic.line"].flush_model() # can't guess all fields (added in other modules)
        for field in self._record_fields_expense:
            self[field].flush_recordset()
        # Valuation
        self.project_id.flush_recordset(['date_start', 'date'])
        self.env['hr.employee.timesheet.cost.history'].flush_model(['hourly_cost', 'starting_date', 'date_to'])
    
    #===== Reservation provisioning, budgets centers refresh, auto-reservation amounts =====#
    def _refresh_budget_analytic_ids(self, rg_result):
        """ Automatically choose budget analytics on document update
            and populate reservations table
        """
        debug = False
        
        with_project = self.filtered('project_id')
        (self - with_project).budget_analytic_ids = False
        if not with_project:
            return

        mapped_analytics = with_project._get_mapped_project_analytics()
        for record in with_project:
            project_budgets = mapped_analytics.get(record.project_id.id, []) if record.project_id else []
            auto_budget_centers = record._get_auto_budget_analytic_ids(rg_result)
            record.budget_analytic_ids = list(set(auto_budget_centers) & set(project_budgets)) or False
            # `or False` is needed to remove all budget if empty

            if debug:
                print(' == _refresh_budget_analytic_ids == ')
                print('project_budgets', project_budgets)
                print('rg_result', rg_result)
                print('record._get_auto_budget_analytic_ids()', record._get_auto_budget_analytic_ids(rg_result))
                print('list(set(record._get_auto_budget_analytic_ids()) & set(project_budgets))', list(set(record._get_auto_budget_analytic_ids(rg_result)) & set(project_budgets)))
                print('record.budget_analytic_ids', record.budget_analytic_ids)

    def _get_mapped_project_analytics(self, domain_arg=[]):
        """ Get available budgets, per project
            :option `domain_arg`: used in `carpentry.budget.balance`
        """
        return {
            # don't use `read_group` to benefit caching
            project.id: project.budget_line_ids.filtered_domain(domain_arg).analytic_account_id.ids
            for project in self.project_id
        }

    @api.depends(lambda self: ['project_id'] + self._depends_reservation_refresh())
    def _compute_reservation_ids(self, vals={}):
        """ Populate lines of budget reservation table
            and refresh automatically amount of reserved budget

            :option vals: when called from `write`
        """
        debug = False

        if self._context.get('carpentry_reservation_no_compute'):
            if debug: print('kill _compute_reservation_ids')
            return
        self = self.with_context(carpentry_reservation_no_compute=True) # avoid looping

        # ctx is to not update yet:
        # - record.total_budget_reserved
        # - reservations's amounts (see `_compute_amounts`)
        # This allow passing `rg_result` programatically
        self = self.with_context(carpentry_budget_no_compute=True)
        
        update_budget_centers = not vals or all(not x in vals for x in ('launch_ids', 'budget_analytic_ids'))
        if debug:
            print(' ===== _compute_reservation_ids (start) ===== ')
            print('self', self)
            print('vals', vals)
            print('self._context', self._context)
            print('update_budget_centers', update_budget_centers)
            print('self.budget_analytic_ids', self.budget_analytic_ids.read(['name']), bool(self.budget_analytic_ids))

        # optim: wait for form saving by user
        if not self or isinstance(fields.first(self).id, models.NewId):
            if debug:
                print('stopped')
            return
        
        # prerequisites: update `budget_analytic_ids` first
        rg_result = self._get_rg_result_expense()
        if update_budget_centers:
            # ctx: to avoid infinite loop with `write`
            ctx_self = self.with_context(carpentry_budget_analytics_auto=True)
            ctx_self._refresh_budget_analytic_ids(rg_result)
        
        # shortcut: no reservations
        if (
            not self.filtered_domain(self._get_domain_can_reserve_budget())
            or not self.budget_analytic_ids
        ):
            if debug: print('shortcut, self.budget_analytic_ids', self.budget_analytic_ids)
            self = self.with_context(carpentry_budget_no_compute=False) # allow compute
            self.reservation_ids = [Command.clear()]
            return
        
        mapped_possibles = self._get_mapped_possible_reservations() # from Available
        mapped_existings = self._get_mapped_existing_reservations() # from Reservation
        Reservation = self.env['carpentry.budget.reservation']
        to_unlink = Reservation

        if debug:
            print('rg_result', rg_result)
            print('mapped_possibles', mapped_possibles)
            print('mapped_existings', mapped_existings)

        vals_list = []
        for record in self:
            # 1. Provision reservation_ids
            for aac_id in record.budget_analytic_ids.ids:
                for launch_or_project_id in record._get_launch_ids(): # launch or project
                    # don't create reservation line if not possible or already existing
                    key_budget = (record.project_id.id, launch_or_project_id, aac_id)
                    key_resa = tuple(list(key_budget) + [record.id])
                    if not key_budget in mapped_possibles or key_resa in mapped_existings:
                        continue

                    vals_list += [record._get_reservation_vals(*key_budget)]
                    mapped_existings.append(key_resa) # for next iter
            
            # 2. Remove reservations of unselected budget centers,
            #    or where there is no 'initially available' budget anymore
            to_unlink |= record.reservation_ids.filtered(lambda resa: (
                self._get_key(resa, mode='budget') not in mapped_possibles
                or resa.analytic_account_id not in record.budget_analytic_ids
                or resa.project_id != record.project_id
            ))

        if debug:
            print('vals_list', vals_list)
            print('to_unlink', to_unlink)
        
        if vals_list:
            Reservation.create(vals_list)
        if to_unlink:
            to_unlink.unlink()
        
        # allow computation and recompute
        self = self.with_context(carpentry_budget_no_compute=False)
        self._auto_update_budget_reservation(rg_result)

        if debug:
            print('self.reservation_ids', self.read(['reservation_ids']))

    def _get_reservation_vals(self, project_id, launch_id, aac_id, amount_reserved=0.0):
        self.ensure_one()
        aac = self.budget_analytic_ids.browse(aac_id)
        launch = self.launch_ids.browse(launch_id)

        return {
            # m2o
            'project_id': project_id,
            'launch_id': launch_id,
            'analytic_account_id': aac_id,
            self._record_field: self.id,
            'project_budget': not bool(launch_id),
            'budget_type': aac.budget_type,
            'date': self.date_budget,
            # sequence
            'sequence_launch': launch.sequence,
            'seq_analytic': aac.sequence,
            'sequence_record': self.sequence if hasattr(self, 'sequence') else self._get_default_sequence(),
            # values
            'amount_reserved': amount_reserved,
            'active': all([
                self._get_default_active(),
                self.project_id.active,
                launch.active if launch else True,
                aac.active,
            ]),
        }
    
    def _get_default_sequence(self):
        """ Default `sequence` for records's **reservations**
            If not `sequence` field: `create_date` to int
        """
        self.ensure_one()
        if hasattr(self, 'sequence'):
            return self.sequence
        else:
            date_seq = self._origin.create_date if self.id else datetime.now()
            return calendar.timegm(date_seq.timetuple())
    
    def _get_default_active(self):
        """ Default `active` for records's **reservations**
            This includes state: *cancel* records are not taken into account
            (both expense & reservations)
        """
        active = self.active if hasattr(self, 'active') else True
        if hasattr(self, 'state'):
            active &= self.state not in ('cancel')
        return active

    def _get_mapped_existing_reservations(self):
        """ Return existing reservation lines in `self` records,
            to prevent duplicates reservation lines
        """
        debug = False
        if debug:
            print(' === _get_mapped_existing_reservations === ')
        return [
            self._get_key(reservation, mode='full')
            for reservation in self.reservation_ids
        ]

    def _get_mapped_possible_reservations(self):
        """ Ensure not dummy reservations lines are created
            in the matrix launchs*budget centers,
            i.e. we only create lines where budget can
            actually *exists*
        """
        debug = False
        if debug:
            print(' == _get_mapped_possible_reservations (start) ==')
        
        # optim
        if not self.budget_analytic_ids._origin:
            return [tuple()]

        Available = self.env['carpentry.budget.available']
        domain = self._domain_mapped_possible_reservations()
        rg_result = Available._read_group(
            domain=domain,
            groupby=['project_id', 'launch_id', 'analytic_account_id'],
            fields=[],
            lazy=False,
        )
        mapped_available = [
            self._get_key(vals=x, mode='budget')
            for x in rg_result
        ]
        
        if debug:
            print(' == _get_mapped_possible_reservations (debug) ==')
            print('domain', domain)
            print('rg_result', rg_result)
            print('mapped_available', mapped_available)
            print('analytics', self.env['account.analytic.account'].search_read(
                [('is_project_budget', '=', True)], ['name']
            ))
            print('availables', Available.search_read(
                domain=domain,
                fields=['analytic_account_id', 'amount_subtotal_valued'],
            ))

        return mapped_available
    
    def _domain_mapped_possible_reservations(self):
        return [
            ('record_res_model', 'in', ['project.project', 'carpentry.group.launch']),
            ('launch_id', 'in', self._get_launch_ids()),
            ('analytic_account_id', 'in', self.budget_analytic_ids._origin.ids),
        ]

    @api.model
    def _get_key(self, rec=None, vals={}, mode='budget', mask=[]):
        """ Return a tuple like:
            (project_id, launch_id, aac_id, [record_id])

            :option `rec`:  record of `reservation`, `available` or `remaining`, ...
            :option `vals`: same, from a _read_group
                            either `rec` or `vals` must be provided
            :option `mask`: list of fields to append
            
            :return: tuple like: (project_id, launch_id, aac_id, [record_id])
                     computed from `rec` or `vals` depending asked `fields`
        """
        debug = False
        if debug:
            print(' ==== start _get_key ==== ')
        
        if mode == 'budget':
            fields = ['project_id', 'launch_id', 'analytic_account_id']
        elif mode == 'full':
            fields = ['project_id', 'launch_id', 'analytic_account_id', self._record_field]
        elif mode == 'planning':
            fields = ['launch_id'] # +mask
        else:
            raise exceptions.UserError(_("Operation not supported."))

        if mask:
            fields += mask

        key = []
        for field in fields:
            has_field = hasattr(rec, field) if rec else field in vals
            if has_field:
                if rec:
                    id_ = rec[field].id if hasattr(rec[field], 'id') else rec[field]
                else:
                    id_ = vals[field][0] if isinstance(vals[field], tuple) else vals[field]
                key.append(id_)
        
        return tuple(key)
    
    def _get_launch_ids(self):
        """ Overwritten in `carpentry.budget.balance` """
        return self.launch_ids._origin.ids + [False]

    #===== Business logics =====#
    def _auto_update_budget_reservation(self, rg_result):
        """ Automatically fill in amounts of budget reservations,
            spreading the record's expense (per budget & launch)
            according to remaining budget.

            It considers:
             - total real cost, per budget analytic (e.g. in the order_line or stock moves),
                for `budget_analytic_ids`
             - maximized to the remaining budget of selected launches, per analytic
        """
        debug = False
        if debug:
            print(' === _auto_update_budget_reservation (start) === ')
        
        self.budget_verified = False
        prec = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        mapped_remaining_budget = self._get_remaining_budget() # independant of `self.id`
        total_by_analytic = self._get_total_budgetable_by_analytic(rg_result)
        filter_budget_types = self._context.get('filter_budget_types', [])

        for record in self:
            mapped_budget_ratio = self._get_budget_distribution(mapped_remaining_budget)

            # for MRP
            reservations = record.reservation_ids
            if filter_budget_types:
                reservations = reservations.filtered(lambda x: x.budget_type in filter_budget_types)
            
            for reservation in reservations:
                key_budget = reservation._get_key(rec=reservation, mode='budget')
                key_resa = tuple(list(key_budget) + [record.id])

                # in € or h
                key_expense = (record.id, reservation.analytic_account_id.id)
                total_price = total_by_analytic.get(key_expense, 0.0)
                remaining_budget = mapped_remaining_budget.get(key_budget, 0.0)

                # 1. Spread the expense over launch (if needed)
                expense_spread = total_price * mapped_budget_ratio.get(key_budget, 0.0)
                
                # 2. Maximize expense to remaining available budget
                amount = float_round(
                    min(expense_spread, remaining_budget),
                    precision_digits=prec, rounding_method='HALF-UP',
                )
                amount = max(0.0, amount) # prevent negative reservation
                reservation.amount_reserved = amount

                # update cursors for next iter
                if key_budget in mapped_remaining_budget:
                    mapped_remaining_budget[key_budget] -= amount

                if debug:
                    print(' === _auto_update_budget_reservation (result) === ')
                    print('key', key_resa)
                    print('expense_spread', expense_spread)
                    print('reservation.amount_reserved', reservation.amount_reserved)
    
    def _get_total_budgetable_by_analytic(self, rg_result):
        """ :return: Dict like {analytic_id: real cost} where *real cost* is:
            - for PO: untaxed total of lines with *consumable* products only
            - for MO: addition of:
                > move_raw_ids values
                > workcenter hours
            - etc.
            :return: Dict like {(record_id, analytic_id): charged amount (brut)}
        """
        debug = False
        if debug:
            print(' === _get_total_budgetable_by_analytic ==== ')
        
        return {
            (
                x[self._record_field][0],
                x['analytic_account_id'] and x['analytic_account_id'][0],
            ): x['amount_expense']
            for x in rg_result
            if bool(x['amount_expense']) # filter existing reservation without expense (anymore)
        }
    
    def _get_auto_budget_analytic_ids(self, rg_result):
        """ In `_refresh_budget_analytic_ids`, for `budget_analytic_ids` to follow the expense
            (!) result is not yet filtered with *only* the budgets existing in the `project_id` 
            Can be overriden if needed
        """
        return [
            aac_id
            for (_, aac_id) in self._get_total_budgetable_by_analytic(rg_result)
            if aac_id
        ]

    def _get_remaining_budget(self):
        """ Calculate [Initial Budget] - [Reservation], per launch & analytic
             without record's reservation
             (!) Always in *BRUT*
             
            :return: mapped_dict with `key_budget`
        """
        debug = False
        if debug:
            print(' === _get_remaining_budget === ')

        domain = [
            ('project_id', 'in', self.project_id.ids),
            ('launch_id', 'in', self._get_launch_ids()),
            (self._record_field, 'not in', self.ids),
        ]
        rg_result = self.env['carpentry.budget.remaining'].read_group(
            domain=domain,
            groupby=['project_id', 'launch_id', 'analytic_account_id'],
            fields=['amount_remaining:sum(amount_subtotal)'],
            lazy=False,
        )
        return {
            self._get_key(vals=x, mode='budget'): x['amount_remaining']
            for x in rg_result
        }
    
    def _get_budget_distribution(self, mapped_budget):
        """ Returns a coef per launch to spread `mapped_budget` on its launch.
            Useful when an available/remaining/reserved budget
            of a same budget center is distributed on several launch.

            :arg mapped_budget: output of of `_get_remaining_budget`
            :return: dict like {(project_id, launch_id, aac_id): coef}
        """
        # 1st group-sum the total per analytic
        total_aac_budget = defaultdict(float)
        for (project_id, launch_id, aac_id), launch_aac_budget in mapped_budget.items():
            if launch_id:
                total_aac_budget[(project_id, aac_id)] += launch_aac_budget
        
        # then compute distribution coef '{launch & aac} / aac budget'
        mapped_coef = {}
        for key_budget, launch_aac_budget in mapped_budget.items():
            (project_id, launch_id, aac_id) = key_budget

            if not launch_id:
                # project budget: not distributed over launchs
                coef = 1.0
            else:
                total_aac = total_aac_budget.get((project_id, aac_id), 1.0)
                coef = launch_aac_budget / total_aac if bool(total_aac) else 0.0

            mapped_coef[key_budget] = coef

        return mapped_coef

    #===== Button =====#
    def save_refresh(self):
        self.readonly_budget_analytic_ids = False
        self.readonly_reservation = False
    
    def action_open_budget(self, xml_id, context={}):
        """ From the document (PO, MO, picking)
            open *Available budget* or *Remaining budget* pivot view
            filtered on launches
        """
        action = self.env['ir.actions.act_window']._for_xml_id('carpentry_position_budget.' + xml_id)

        budget_types = self._get_budget_types()
        action['context'] = context | safe_eval(action['context'] or '{}') | {
            f'search_default_filter_{budget_type}': 1
            for budget_type in budget_types
        }
        action['domain'] = [
            ('record_res_model', 'in', ['project.project', 'carpentry.group.launch']),
            ('project_id', '=', self.project_id.id),
            ('launch_id', 'in', self._get_launch_ids()),
        ]
        return action
    
    def open_budget_available(self):
        return self.action_open_budget('action_open_budget_report_available')
    
    def open_remaining_budget(self):
        return self.action_open_budget('action_open_budget_report_remaining')
    
    def button_reservation_refresh(self):
        """ Recomputes budget reservation amounts with
            automatic distribution of expense to budget centers
        """
        rg_result = self._get_rg_result_expense()
        self._auto_update_budget_reservation(rg_result)
        self.budget_verified = True

    def button_reservation_maximum(self):
        """ Help user to balance all remaining budget """
        reservations = self.reservation_ids
        # filter: for MRP
        filter_budget_types = self._context.get('filter_budget_types', [])
        if filter_budget_types:
            reservations = reservations.filtered(lambda x: x.budget_type in filter_budget_types)

        for reservation in reservations:
            reservation.amount_reserved += reservation.amount_remaining
        
        self.budget_verified = True

    #===== Views =====#
    def _get_view_carpentry_config(self):
        """
            Let possibility of several templating in same form, for MRP
            :return: list of dict
        """
        return [
            {
                'templates': {
                    'alert_banner': self._carpentry_budget_alert_banner_xpath,
                    'notebook_page': self._carpentry_budget_notebook_page_xpath,
                },
                'params': {
                    'model_name': self._name,
                    'model_description': self.env["ir.model"]._get(self._name).name,
                    'fields_suffix': '', # for MRP
                    'budget_types': self._get_budget_types(),
                    'budget_choice': self._carpentry_budget_choice,
                    'sheet_name': self._carpentry_budget_sheet_name,
                    'last_valuation_step': self._carpentry_budget_last_valuation_step,
                    'button_reservation_refresh': True,
                }
            },
        ]

    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        res = super().get_view(view_id=view_id, view_type=view_type, **options)

        View = self.env["ir.ui.view"]
        arch = etree.XML(res["arch"])
        all_models = res["models"].copy() # {modelname(str) ➔ fields(tuple)}

        if view_type == 'form':
            res = self._get_view_form(res, View, arch, all_models)
        elif view_type == 'tree':
            res = self._get_view_add_element(res, View, arch, all_models, '//tree', 'field', {
                'name': 'budget_verified',
                'widget': 'boolean_toggle',
                'optional': 'hide',
            })
        elif view_type == 'search':
            options = [{
                'name': 'budget_verified_ok',
                'string': _('Budget verified'),
                'domain': "[('budget_verified', '=', True)]" 
            }, {
                'name': 'budget_verified_nok',
                'string': _('Budget not verified'),
                'domain': "[('budget_verified', '=', False)]" 
            }]
            for option in options:
                res = self._get_view_add_element(res, View, arch, all_models, '//search', 'filter', option)
        return res

    def _get_view_add_element(self, res, View, arch, all_models, xpath, elem, options):
        """ Add fields/filters in 'tree' and 'search' view """
        root_node = arch.xpath(xpath)
        for node in root_node:
            field_element = etree.SubElement(node, elem, options)
            _, new_models = View.postprocess_and_fields(field_element, self._name)
            _merge_view_fields(all_models, new_models)
        
        res["arch"] = etree.tostring(arch)
        res["models"] = frozendict(all_models)
        return res

    def _get_view_form(self, res, View, arch, all_models):
        changed = False

        for config in self._get_view_carpentry_config():
            # add the 3 templates to the `form` view
            for template, xpath in config['templates'].items():
                # custom layout (e.g. tasks)
                nodes = xpath and arch.xpath(xpath)
                if not nodes:
                    continue

                # configurable fields (for MRP)
                # fields names are passed as `params` so it's almost transparent
                # to call the param in the Qweb view, like `t-att-name="reservation_ids"`
                fields = [
                    'reservation_ids', 'total_budget_reserved', 'other_expense_ids',
                    'budget_analytic_ids',
                    'amount_gain', 'amount_loss', 'total_expense_valued', 'total_budgetable',
                    'readonly_reservation', 'readonly_budget_analytic_ids',
                    'is_temporary_gain', 'show_gain', 'show_budget_banner', 'budget_unit',
                    'text_no_reservation',
                ]
                config['params']['fields'] = {}
                for f in fields:
                    f_suffixed = f + config['params']['fields_suffix']
                    config['params']['fields'][f] = f_suffixed if f_suffixed in self else f
                
                # generate the template's arch
                template = 'carpentry_position_budget.carpentry_budget_template_' + template
                str_element = self.env["ir.qweb"]._render(template, config['params'])
                new_node = etree.fromstring(str_element)
                new_arch, new_models = View.postprocess_and_fields(new_node, self._name)
                new_node = etree.fromstring(new_arch)

                # place it
                for node in nodes:
                    for new_element in new_node:
                        node.addnext(new_element)
                _merge_view_fields(all_models, new_models)

                changed = True
        
        if changed:
            res["arch"] = etree.tostring(arch)
            res["models"] = frozendict(all_models)
        
        return res

def _merge_view_fields(all_models: dict, new_models: dict):
    """Merge new_models into all_models. Both are {modelname(str) ➔ fields(tuple)}."""
    for model, view_fields in new_models.items():
        if model in all_models:
            all_models[model] = tuple(set(all_models[model]) | set(view_fields))
        else:
            all_models[model] = tuple(view_fields)
