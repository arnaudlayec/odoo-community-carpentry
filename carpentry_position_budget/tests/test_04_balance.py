# -*- coding: utf-8 -*-

from odoo import exceptions, fields, _, Command
from odoo.tests.common import Form

from .test_00_position_budget_base import TestCarpentryPositionBudget_Base
from odoo.addons.carpentry_position_budget.models.carpentry_planning_column import human_readable

class TestCarpentryPositionBudget_Balance(TestCarpentryPositionBudget_Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        cls._spread_affect()

        cls.balance = cls.env['carpentry.budget.balance'].create({
            'name': 'Balance',
            'project_id': cls.project.id,
        })
        cls.column = cls.env['carpentry.planning.column'].create([{
            'name': 'Installation',
            'budget_types': 'installation',
        }])

        cls.fields = ['launch_id', 'analytic_account_id', 'amount_reserved']

    @classmethod
    def _print_debug(cls):
        print('cls.balance', cls.balance.read(['budget_analytic_ids']))
        print('cls.project.budget_line_ids', cls.project.budget_line_ids.read(['analytic_account_id', 'is_computed_carpentry']))
        print('reservations', cls.balance.reservation_ids.read(['analytic_account_id', 'launch_id', 'amount_reserved']))
        print('expenses', cls.env['carpentry.budget.expense'].search_read([], ['analytic_account_id', 'balance_id', 'amount_reserved', 'amount_expense', 'amount_gain']))

    #===== Balance's reservations =====#
    @classmethod
    def _sum_report_remaining_budget(cls, mode):
        operator = '=' if mode == 'project' else '!='
        domain = [('project_id', '=', cls.project.id), ('launch_id', operator, False),]
        cls.env.flush_all()
        cls.Remaining.invalidate_model()
        remainings = cls.Remaining.search(domain)
        return sum(remainings.mapped('amount_subtotal'))

    def test_01_new_balance_budget_project(self):
        """ Ensure new balance consume by default all remaining project's budget """
        self.assertEqual(self.balance.budget_analytic_ids, self.aac_other)
        self.assertFalse(self.balance.launch_ids)
        resa = self.balance.reservation_ids
        self.assertEqual(len(resa), 1)
        self.assertEqual(resa.analytic_account_id, self.aac_other)
        self.assertEqual(resa.amount_reserved, self.amount_other)
        self.assertEqual(resa.amount_reserved, resa.amount_initially_available)

        # no remaining budget on global project's budgets
        self.assertFalse(resa.amount_remaining)
        self.assertTrue (self._sum_report_remaining_budget(mode='launch')) # on launch: still budget
        self.assertFalse(self._sum_report_remaining_budget(mode='project'))

    def test_02_reservation_lines(self):
        """ Tests `carpentry.group.reservation` amounts:
            - remaining budget
            - distributed expense
            - gain (distributed too)
        """
        reservation = fields.first(self.balance.reservation_ids)
        self.assertEqual(reservation.amount_remaining, 0.0)
        self.assertEqual(reservation.amount_expense_valued, 0.0)
        self.assertEqual(reservation.amount_gain, reservation.amount_reserved)
    
    def test_03_project_budget_constrain(self):
        """ Ensure it raises if removing or lowering too much a
            *global* project-budget (if below existing reservations amount)
        """
        # start state: all project budget is reserved
        self.assertFalse(self._sum_report_remaining_budget(mode='project'))
        self.assertEqual(self.balance.reservation_ids.analytic_account_id, self.aac_other)

        # raise budget: should not raise
        line = self.project.budget_line_ids.filtered(lambda x: not x.is_computed_carpentry)
        try:
            line.debit += 1.0
        except exceptions.RedirectWarning:
            self.fail('Should be OK to raise budget')

        # lower budget: should raise
        with self.assertRaises(exceptions.RedirectWarning):
            line.unlink()
        with self.assertRaises(exceptions.RedirectWarning):
            line.debit -= 2.0

    #===== Balance's launchs reservations =====#
    @classmethod
    def _create_balance2(cls):
        cls.balance2 = cls.balance.copy({'name': 'Balance2'})
    
    def test_04_switch_to_launch(self):
        """ Test when choosing 1 launch, it passes in 'launch-only' mode """
        self.balance.launch_ids = self.launchs
        
        self.assertEqual(self.balance.budget_analytic_ids, self.aac_installation + self.aac_production)
        self.assertFalse(self.balance.reservation_ids.filtered(
            # all reservation are on launch(s)
            lambda x: not x.launch_id
        ))

        # no remaining budget on launchs budgets
        reservations = self.balance.reservation_ids
        self.assertFalse(any(reservations.mapped('amount_remaining')))
        self.assertFalse(self._sum_report_remaining_budget(mode='launch'))
        self.assertTrue (self._sum_report_remaining_budget(mode='project')) # on project: still budget

    def test_05_budget_partial(self):
        """ Ensure *remaining* budget view computation of remaining budget """
        # don't balance yet the 1st launch in 1st budget balance
        reservation = fields.first(self.balance.reservation_ids)
        reservation.amount_reserved = 0.0
        self.assertTrue(reservation.amount_remaining) # start state: should be positive
        self.assertTrue(self._sum_report_remaining_budget(mode='launch'))

        # then, balance 1st launch in a 2nd balance => no remaining budget
        self._create_balance2()
        self.balance2.launch_ids = self.launchs
        self.assertFalse(self._sum_report_remaining_budget(mode='launch'))
        
        reservation.invalidate_recordset(['amount_remaining'])
        self.assertFalse(reservation.amount_remaining)

    def test_06_reservation_lines_sibling(self):
        """ Tests again amounts of `carpentry.group.reservation`
            when having 2 balances
        """
        reservation = fields.first(self.balance2.reservation_ids)
        self.assertEqual(reservation.amount_remaining, 0.0)
        self.assertEqual(reservation.amount_expense_valued, 0.0)
        self.assertEqual(reservation.amount_gain, reservation.amount_reserved * self.HOUR_COST)
    
    def test_07_reservation_budget_constrain(self):
        """ Ensure it's not possible to reserve more budget than available """
        reservation = fields.first(self.balance.reservation_ids)
        self.assertFalse(reservation.amount_remaining) # start state: should be null
        with self.assertRaises(exceptions.ValidationError):
            reservation.amount_reserved += 1.0

    #===== Budget negative constrain & reservations clean (using balances) =====#
    def test_08_affectation_constrain(self):
        """ Ensure it raises if removed affectation creates a <0 remaining budget """
        # start state: all launch budget is reserved
        self.assertFalse(self._sum_report_remaining_budget(mode='launch'))
        self.assertTrue(
            self.aac_installation in self.balance.reservation_ids.analytic_account_id
        )

        # position's budget delete or lowered qty
        try:
            self.budget_installation.amount_unitary += 1.0
        except exceptions.RedirectWarning:
            self.fail('Should be OK to raise budget')
        
        with self.assertRaises(exceptions.RedirectWarning):
            self.budget_installation.unlink()
        with self.assertRaises(exceptions.RedirectWarning):
            self.budget_installation.amount_unitary = 0.0
        
        # position's delete or lowered qty
        try:
            self.position.quantity += 1.0
        except exceptions.RedirectWarning:
            self.fail('Should be OK to raise position qty')
        with self.assertRaises(exceptions.RedirectWarning):
            self.position.unlink()
        with self.assertRaises(exceptions.ValidationError): # ValidationError because actually blocked in `carpentry_position`
            self.position.quantity = 0.0

        # phase unlink, removing linked lot's, lowering affectation's qty
        affectation = fields.first(self.phase.affectation_ids)
        try:
            affectation.quantity_affected += 1.0
        except:
            self.fail('Should be OK to raise position affected quantity')
        with self.assertRaises(exceptions.RedirectWarning):
            self.phase.unlink()
        with self.assertRaises(exceptions.ValidationError):
            self.phase.lot_ids = [Command.clear()]
        with self.assertRaises(exceptions.ValidationError):
            affectation.quantity_affected = 0.0

        # launch: unlink, affectation's unaffacting
        with self.assertRaises(exceptions.RedirectWarning):
            self.launch.unlink()
        with self.assertRaises(exceptions.RedirectWarning):
            fields.first(self.launch.affectation_ids).affected = False

    def test_09_affectation_constrain_param(self):
        """ Ensure budget constrain can be silenced with an ir.config_parameter """
        param = 'carpentry.allow_negative_budget'
        IrConfig = self.env['ir.config_parameter'].sudo()
        
        IrConfig.set_param(param, 'True')
        prev = self.budget_installation.amount_unitary
        try:
            self.budget_installation.amount_unitary = 0.0
        except:
            self.fail('Should be OK to create negative budget')

        # back to normal
        IrConfig.search([('key', '=', param)]).unlink()
        self.budget_installation.amount_unitary = prev
    
    def test_10_lower_reservation_ok(self):
        """ Test it's OK to lower the reservation if there are remaining budget """
        # unreserve known amount of budget
        _lambda = lambda x: x.analytic_account_id == self.budget_production
        for reservation in self.balance.reservation_ids.filtered(_lambda):
            reservation.amount_reserved -= 10
        
        try:
            for budget in self.position.position_budget_ids.filtered(_lambda):
                budget.amount_unitary -= 1
        except:
            self.fail('Lowering budget of acceptable amount should be OK')

    def test_11_access_right(self):
        try:
            self.balance.reservation_ids.read([])
        except exceptions.AccessError:
            self.fail('User access rights issue')
    
    #===== Planning columns =====#
    def _get_planning_result(self, launch):
        return (
            self.column.get_headers_data(launch.id)
            .get(self.column.id, {}).get('budget', {})
        )

    def test_20_planning_column_unit(self):
        """ Test units of budget columns: 'h' if only 'h' ; else '€' """
        self.env['carpentry.budget.balance'].search([]).unlink()
        # affect everything to 1st phase, position & launch
        self._reset_affectations()
        self._create_budget_project()

        result = self._get_planning_result(self.launch)
        self.assertEqual(result.get('unit'), 'h') # installation only
        
        self.column.budget_types += ',production,other'
        result = self._get_planning_result(self.launch)
        self.assertEqual(result.get('unit'), '€')

    def test_21_planning_column_totals(self):
        """ Test total amounts in planning columns """
        self.column.budget_types = 'installation,production'

        # launch2: with no budget
        self.assertFalse(self.launchs[1].budget_total) # situation check
        result = self._get_planning_result(self.launchs[1])
        self.assertEqual(result.get('available'), human_readable(0.0))

        
        # launch1: has all project's budget, with no reservations yet
        launch_available = self.launch.budget_installation + self.launch.budget_production
        self.assertTrue(launch_available) # situation check
        result = self._get_planning_result(self.launch)
        self.assertEqual(result.get('available'), launch_available)
        self.assertFalse(result.get('reserved'))

        # make a reservation (balance all budget of launch1)
        balance3 = self.balance.create({'name': 'Balance3', 'project_id': self.project.id})
        balance3.launch_ids = self.launch
        result = self._get_planning_result(self.launch)
        self.assertEqual(result.get('reserved'), launch_available)

    #===== Final tests =====#
    def test_90_reservation_clean_on_affectation_removal(self):
        """ Ensure when a budget is removed, *empty/ghost* reservation
            linked to it but not reserving budget should be cleaned
            (see `_clean_reservation_and_constrain_budget`)
        """
        # set some *empty/ghost* reservation
        domain = [('analytic_account_id', '=', self.budget_production.id)]
        reservations = self.env['carpentry.budget.reservation'].search(domain)
        reservations.amount_reserved = 0.0

        position_budgets = self.env['carpentry.position.budget'].search(domain)
        try:
            position_budgets.unlink()
        except:
            self.fail('Unlinking budgets with no reservations should be OK')

        self.assertFalse(reservations)
