# -*- coding: utf-8 -*-

from odoo import api, fields, models

class SheetLine(models.TransientModel):
    _inherit = "hr_timesheet.sheet.line"

    effective_hours = fields.Float(
        compute="_compute_effective_hours",
    )
    reserved_budget = fields.Float(
        related="task_id.total_budget_reserved",
    )

    @api.depends("task_id", "sheet_id")
    def _compute_effective_hours(self):
        """We need `effective_hours` of the tasks without the times in the current
        timesheets, because they are added by OWL when displayed"""
        self.sheet_id.ensure_one()
        for line in self:
            timesheets = line.task_id.timesheet_ids.filtered(
                lambda x: x.sheet_id != line.sheet_id
            )
            line.effective_hours = sum(timesheets.mapped("unit_amount"))
