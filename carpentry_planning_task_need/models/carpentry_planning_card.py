# -*- coding: utf-8 -*-

from odoo import models, fields

class CarpentryPlanningCard(models.Model):
    """ Add required field for specific Tasks cards """
    _inherit = ["carpentry.planning.card"]

    #===== Fields =====#
    project_task_id = fields.Many2one(
        # for research by launches
        comodel_name='project.task',
        string='Task',
    )
    # -- related --
    user_ids = fields.Many2many(
        comodel_name='res.users',
        compute='_compute_fields'
    )
    week_deadline = fields.Integer(compute='_compute_fields')
    need_default = fields.Boolean(compute='_compute_fields')
    week_end = fields.Integer(compute='_compute_fields')
    type_name = fields.Char(compute='_compute_fields')
    
    #===== Compute =====#
    def _get_fields(self):
        return super()._get_fields() + [
            'user_ids', 'week_deadline', 'need_default', 'week_end', 'type_name'
        ]

    # @api.model
    # def _search_launch_ids(self, operator, value):
        # """ Sticky Needs: don't filter by project (independant of filtered launch) """
        # return expression.OR([
        #     [('project_id', '=', False)],
        #     [(field, operator, value) for field in fields]
        # ])
    
    #===== Button =====#
    def action_activate_need(self):
        task = self.env['project.task'].browse(self.res_id)
        return task.action_activate_need()
