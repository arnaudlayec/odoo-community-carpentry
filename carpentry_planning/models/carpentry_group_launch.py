# -*- coding: utf-8 -*-

from odoo import models, fields, api

class CarpentryLaunch(models.Model):
    _inherit = ['carpentry.group.launch']

    milestone_ids = fields.One2many(
        comodel_name='carpentry.planning.milestone',
        inverse_name='launch_id',
        string='Milestones'
    )
    is_done = fields.Boolean(
        compute="_compute_milestone_shortcut",
    )
    milestone_shortcut = fields.Json(
        compute="_compute_milestone_shortcut",
    )
    carpentry_planning = fields.Boolean(
        compute='_compute_carpentry_planning'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """ Pre-fill planning's launch milestones with empty milestones """
        launch_ids = super().create(vals_list)
        self.env['carpentry.planning.milestone.type'].sudo().search([])._prefill_milestone_ids(launch_ids)
        return launch_ids

    #===== Compute =====#
    @api.depends_context('carpentry_planning')
    def _compute_carpentry_planning(self):
        self.carpentry_planning = self._context.get('carpentry_planning')

    @api.depends(
        "milestone_ids.shortcut",
        "milestone_ids.date",
        "milestone_ids.column_id.icon"
    )
    def _compute_milestone_shortcut(self):
        """Used in planning launch's search pannel"""
        for launch in self:
            launch.write({
                "milestone_shortcut": {"data": launch._get_milestone_shortcut_data()},
                "is_done": bool(launch.milestone_ids._get_last().is_done),
            })

    def _get_milestone_shortcut_data(self):
        return [
            {
                "id": milestone.id,
                "column_name": milestone.column_id.name,
                "column_icon": milestone.column_id.icon,
                "is_done": milestone.is_done,
                "is_last": milestone.is_last,
            }
            for milestone in self.milestone_ids.sorted("sequence")
            if milestone.shortcut
        ]
