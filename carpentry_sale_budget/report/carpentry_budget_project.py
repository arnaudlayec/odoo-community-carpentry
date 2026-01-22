# -*- coding: utf-8 -*-

from odoo import models, fields

class CarpentryBudgetProject(models.Model):
    _inherit = ['carpentry.budget.project']

    margin_contributive_actual = fields.Monetary(
        related="project_id.margin_contributive_actual"
    )
