# -*- coding: utf-8 -*-

from odoo import exceptions, fields, _, Command

from .test_00_position_budget_base import TestCarpentryPositionBudget_Base

from dateutil.relativedelta import relativedelta

class TestCarpentryPositionBudget_Budget(TestCarpentryPositionBudget_Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
    
    #===== Positions =====#
    def test_01_unitary_budget_value_code(self):
        """ Test valuation of unitary budget (with code) """
        self.assertEqual(self.budget_installation.value_unitary, self.amount_installation * self.HOUR_COST)
        self.assertEqual(self.budget_production.value_unitary, self.amount_production * self.HOUR_COST)

    def test_02_unitary_budget_value_sql_view(self):
        """ Test valuation of unitary budget (with SQL view)
            but no valuation (brut)
        """
        self.assertEqual(self.position.budget_installation, self.amount_installation)
        self.assertEqual(self.position.budget_production, self.amount_production)
    
    def test_03_project_budget_line(self):
        """ Test that creating the positions & budgets has
            updated the project's budget lines
        """
        # 3 per budget center: 'production', 'installation', 'other'
        lines = self.project.budget_line_ids
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(lines.filtered('is_computed_carpentry')), 2)

    def test_04_position_subtotal(self):
        """ Test position's budget subtotal (SQL view valuation)
            **WITH VALUATION** (subtotal)
        """
        subtotal = (
            + self.amount_production * self.HOUR_COST
            + self.amount_installation * self.HOUR_COST
        )
        self.assertEqual(self.position.budget_subtotal, subtotal)
    
    #===== Project =====#
    def test_05_project_totals(self):
        """ Test project totals computation """
        # Computed budget from carpentry's position
        for budget_type in ('installation', 'production'):
            self.assertEqual(
                self.project['budget_' + budget_type],
                sum([
                    position.quantity * position.position_budget_ids.filtered(
                        lambda x: x.budget_type == budget_type
                    ).amount_unitary
                    for position in self.project.position_ids
                ])
            )
        
        # Manual budget on project
        self.assertEqual(self.project.budget_other, self.amount_other)

    def test_06_project_budget_change_valuation(self):
        """ Test that project total changes on hour valuation changes"""
        # initial state
        position_budget = self.position.position_budget_ids.filtered(
            lambda x: x.analytic_account_id == self.aac_production
        )
        origin_project_total = self.project.budget_total
        origin_position_prod = position_budget.value_unitary

        # change
        history_entry = fields.first(self.aac_production.timesheet_cost_history_ids)
        history_entry.hourly_cost = self.HOUR_COST + 1.0
        self.assertNotEqual(position_budget.value_unitary, origin_position_prod)
        self.assertNotEqual(self.project.budget_total, origin_project_total)

    def test_07_project_budget_change_position_qty(self):
        """ Test that project total changes on position qty changes """
        origin_total = self.project.budget_total
        self.position.quantity += 10
        self.assertNotEqual(self.project.budget_total, origin_total)

    def test_08_project_budget_unlink_position(self):
        """ Test that project total changes when unlinking a position """
        # adding budget (start point)
        origin_total = self.project.budget_total
        new_position = self.position.copy() # **does** copy budgets!
        self.assertTrue(self.position.position_budget_ids) # copying position also copy its budgets
        self.assertNotEqual(self.project.budget_total, origin_total)

        # removing the position: budget should come back to origin
        new_position.unlink()
        self.env.invalidate_all()
        # print('new_position', new_position)
        # print('self.project.position_ids.position_budget_ids', self.project.position_ids.position_budget_ids.read(['position_id', 'analytic_account_id']))
        self.project.invalidate_recordset(['budget_total'])
        self.assertEqual(self.project.budget_total, origin_total)

    def test_09_project_budget_change_unitary_position_budget(self):
        """ Test that project total changes on position's budget change """
        origin_total = self.project.budget_total
        fields.first(self.position.position_budget_ids).amount_unitary += 10
        self.assertNotEqual(self.project.budget_total, origin_total)

    def test_10_project_budget_change_unit_line(self):
        """ Test that project total changes when adding manual
            global cost to the budget
        """
        total = self.project.budget_total
        self.budget.line_ids = [Command.create({
            'name': 'Line test 01',
            'date': self.budget.date_from,
            'debit': 100.0,
            'analytic_account_id': self.aac_other.id,
            'account_id': self.account.id,
        })]
        self.assertEqual(self.project.budget_total, total + 100.0)

    def test_11_project_budget_change_dates(self):
        """ Test that project total changes when changing dates """
        origin_date_start = self.project.date_start
        origin_total = self.project.budget_total
        self.project.date_start = origin_date_start - relativedelta(years=1) # 1 year without valuation
        self.assertNotEqual(self.project.budget_total, origin_total)
        
        # reset correct state
        self.project.date_start = origin_date_start

    def test_12_project_budget_line_update(self):
        """ Auto-removal of lines in project budget when removing positions' budgets """
        nb_lines = len(self.project.budget_line_ids.ids)
        domain = [('analytic_account_id', '=', self.aac_production.id)]
        self.project.position_budget_ids.search(domain).unlink()

        self.assertEqual(len(self.project.budget_line_ids.ids), nb_lines-1)

    #===== Phase & launchs =====#
    def test_13_phase_budget(self):
        """ Test computation of phase totals """
        self._reset_affectations(spread=True)
        self._create_budget_project()
        self.position.quantity = 3
        fields.first(self.phase.affectation_ids).quantity_affected = 3
        self.env.invalidate_all()

        self.assertEqual(
            self.phase.budget_installation,
            self.amount_installation * 3
        )

    def test_14_phase_available_positions_from_lots(self):
        """ Test the number appended to lot's name, in phase form """
        pass

    def test_15_launch_budget(self):
        self.assertEqual(self.launch.budget_total, self.phase.budget_total)

    def test_16_launch_available_affectation_from_phase(self):
        """ Test the number appended to phase's name, in launch form """
        pass

    def test_17_group_clean(self):
        self.launchs.affectation_ids.unlink()
        self.phases.affectation_ids.unlink()
        self.assertFalse(self.phase.budget_total)
        self.assertFalse(self.launch.budget_total)

    #===== Report =====#
    def test_16_available_position_qty(self):
        """ Test that position's `quantity_affected` is in position's `display_name`
            when grouping `carpentry.budget.available` per position
        """
        self._reset_affectations()
        self._create_budget_project()
        res = (
            self.env['carpentry.budget.available']
            .with_context({
                'display_model_shortname': True,
                'active_model': 'carpentry.group.launch',
                'active_id': self.launch.id,
            })
            .read_group(
                domain=[('launch_id', '=', self.launch.id)],
                fields=['quantity_affected:sum'],
                groupby=['position_id'],
                limit=1,
            )
        )

        display_name = res[0]['position_id'][1]
        self.assertEqual(
            display_name.split(' ')[-1].replace('(', '').replace(')', ''),
            str(self.position.quantity),
        )

    #===== Bug solving =====#
    def test_81_launch_budget_complex(self):
        """ 2025-11-07: COUNT(*) in SQL
            Situation:
             * a position's qty is splitted over several phases
             * each phase has a launch mirror, with the position affected in each launch
             * so the position has several *AFFECTED* launch affectation
            -> Ensure correction launch/phase/budget budget computation when its position
        """
        self.project.unlink()
        self._create_project('Project1')
        self._create_budget_project()

        # affect 1 qty of position3 in each 3 phases and launchs
        for i, phase in enumerate(self.phases):
            phase._create_affectations(self.positions[2])
            phase.affectation_ids.quantity_affected = 1
            self.launchs[i].phase_ids = phase
        self.launchs.affectation_ids.affected = True

        self.assertEqual(self.phase.budget_production,   self.amount_production) # 20h in each position
        self.assertEqual(self.launch.budget_production,  self.amount_production)
