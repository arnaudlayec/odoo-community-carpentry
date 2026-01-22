# -*- coding: utf-8 -*-

from odoo import exceptions, fields, _, Command

from ...carpentry_position_budget.tests.test_05_analytic_project import TestCarpentryPositionBudget_AnalyticBase

class TestCarpentryPositionBudget_AccountMove(TestCarpentryPositionBudget_AnalyticBase):

    record_model = 'account.move'
    field_lines = 'line_ids'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record.action_post()
        cls.record.line_ids.analytic_distribution = {
            cls.project.analytic_account_id.id: 100.0,
            cls.aac_installation.id: 100.0,
        }

    @classmethod
    def _get_vals_record(cls):
        return {
            'partner_id': cls.env.user.partner_id.id,
            'move_type': 'entry',
            'invoice_date': '2025-01-01',
            'journal_id': cls.journal.id,
        }
    
    @classmethod
    def _get_vals_new_line(cls, product=None, qty=1.0):
        return {
            'account_id': cls.account.id,
            'debit': 100.0 if product == cls.product_storable else 0.0,
            'credit': 0.0  if product == cls.product_storable else 100.0,
        }
    
    def test_01_analytic_line(self):
        """ Ensure that account move are included in budget reports,
            through analytic lines
        """
        # test the situation
        self.assertEqual(self.record.line_ids.analytic_line_ids.budget_project_ids, self.project)

        # budget report
        expense = self.env['carpentry.budget.expense'].search([('move_id', '=', self.record.id)])
        self.assertEqual(expense.project_id, self.project)
