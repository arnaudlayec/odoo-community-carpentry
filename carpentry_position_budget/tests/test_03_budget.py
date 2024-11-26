# -*- coding: utf-8 -*-

from odoo import exceptions, fields, _, Command
from odoo.tests import common, Form

from odoo.tools import file_open
import base64

from .test_00_position_budget_base import TestCarpentryPositionBudget_Base

class TestCarpentryPositionBudget_Security(TestCarpentryPositionBudget_Base):

    BUDGET_ALUMINIUM = 100.0 # euros
    BUDGET_PROD = 20.0 # hours
    BUDGET_INSTALL = 10.0 # hours

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Each project's position: add some Aluminium, Prod and Install budgets
        for position in cls.project.position_ids:
            cls._add_budget(position, cls.aac_aluminium, cls.BUDGET_ALUMINIUM)
            cls._add_budget(position, cls.aac_install, cls.BUDGET_INSTALL)
            cls._add_budget(position, cls.aac_prod, cls.BUDGET_PROD)

    def _add_budget(position, analytic, amount):
        position.position_budget_ids = [Command.create({
            'analytic_account_id': analytic.id,
            'amount': amount
        })]


    def test_01_position_unitary_budget(self):
        """ Test totals on position """
        brut, valued = self.position.position_budget_ids._get_position_unitary_budget(
            groupby_budget='detailed_type'
        )
        self.assertEqual(brut.get(self.position.id), {
            'consu': self.BUDGET_ALUMINIUM,
            'service_prod': self.BUDGET_PROD,
            'service_install': self.BUDGET_INSTALL
        })
        self.assertEqual(valued.get(self.position.id), {
            'consu': self.BUDGET_ALUMINIUM,
            'service_prod': self.BUDGET_PROD * self.HOUR_COST,
            'service_install': self.BUDGET_INSTALL * self.HOUR_COST
        })

    def test_02_position_subtotal(self):
        subtotal = (
            self.BUDGET_ALUMINIUM
            + self.BUDGET_PROD * self.HOUR_COST
            + self.BUDGET_INSTALL * self.HOUR_COST
        )
        self.assertEqual(self.position.budget_subtotal, subtotal)
    


    def test_03_project_budget_change_product_cost(self):
        """ Test that project total changes on valuation changes"""
        total = self.project.budget_total
        self.product_prod_2023.standard_price = self.HOUR_COST + 1.0
        self.assertTrue(self.project.budget_total != total)

    def test_04_project_budget_change_position_qty(self):
        """ Test that project total changes on position qty changes"""
        total = self.project.budget_total
        self.position.quantity = 10
        self.assertTrue(self.project.budget_total != total)

    def test_05_project_budget_change_fix_line(self):
        """ Test that project total changes when adding manual
            fix lines (global cost) to the budget
        """
        total = self.project.budget_total
        self.budget.line_ids = [Command.create({
            'name': 'Fix Line test 01',
            'date': self.budget.date_from,
            'type': 'fix',
            'standard_price': 10.0,
            'qty_debit': 10.0,
            'analytic_account_id': self.aac_aluminium.id,
            'account_id': self.aac_aluminium.product_tmpl_id._get_product_accounts().get('expense').id,
        })]
        self.assertEqual(self.project.budget_total, total + 100.0)

    def test_06_project_budget_line_update(self):
        """ Auto-removal of lines in project budget when removing positions' budgets """
        nb_lines = len(self.project.budget_line_ids.ids)
        domain = [('analytic_account_id', '=', self.aac_prod.id)]
        self.project.position_budget_ids.search(domain).unlink()

        self.assertEqual(len(self.project.budget_line_ids.ids), nb_lines-1)


    def test_07_phase_budget(self):
        # Ensure a clean base to start
        self.Affectation.search([('project_id', '=', self.project.id)]).unlink()
        self.assertFalse(self.phase.budget_install)
        
        position2 = self.project.position_ids[1]
        self._write_affect(self.phase, position2, {'quantity_affected': 2})
        self.assertEqual(
            self.phase.budget_install,
            self.BUDGET_INSTALL * 2
        )

    def test_08_launch_budget(self):
        self.assertFalse(self.launch.budget_install)

        position2 = self.project.position_ids[1]
        self._write_affect(self.launch, self.project.phase_ids.affectation_ids[0])
        self.assertEqual(
            self.launch.budget_install,
            self.phase.budget_install
        )
