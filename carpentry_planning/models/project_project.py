# -*- coding: utf-8 -*-

from odoo import models, fields, exceptions, _

class Project(models.Model):
    _inherit = ["project.project"]

    #===== Fields =====#
    planning_milestone_ids = fields.One2many(
        comodel_name='carpentry.planning.milestone',
        inverse_name='project_id',
        string='Planning Milestones',
    )

    #===== Planning =====#
    def _compute_display_name(self):
        """ Add current week to display_name """
        super()._compute_display_name()
        
        if self._context.get('display_with_week'):
            for project in self:
                project.display_name += _(
                    ' (W%s)', fields.Date.context_today(self).isocalendar()[1]
                )

    def get_planning_dashboard_data(self):
        """ To be overritten to add Cards in project's top-bar dashboard """
        return self._get_planning_dashboard_next_projects()
    
    def _get_planning_dashboard_next_projects(self):
        """ Buttons to quickly open the project's planning of next project,
            per user role (only for *primary* assignments)
        """
        # 1. Find all projects where user is assigned with a primary role to show on plannings
        domain = [
            ('user_id', 'in', self.assignment_ids.filtered(
                lambda x:
                    x.config_planning_next_project and x.primary
                ).user_id.ids),
            ('primary', '=', True),
            ('project_fold', '=', False),
            ('role_id', '!=', False),
            ('project_id', '!=', False),
        ]
        Assignment = self.env['project.assignment']
        all_assignments = Assignment.search(domain, order='project_id DESC')
        all_users = all_assignments.user_id
        res_assignments = Assignment

        # 2. Filter `all_assignments` to get only the next-project assignment, per user
        start = None
        for assignment in all_assignments:
            # ignore the previous projects
            if assignment.project_id == self:
                start = True
            elif start:
                # if all users found
                if res_assignments.user_id == all_users:
                    break
                # user already found
                elif assignment.user_id in res_assignments.user_id:
                    continue
                else:
                    res_assignments |= assignment
        
        return {'next_projects': res_assignments.read(['user_id', 'project_id', 'role_id'])}
    
    #===== Milestones =====#
    def open_planning_milestone_table(self):
        project_id_ = self.id or self.env['project.default.mixin']._get_project_id()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': self._name,
            'res_id': project_id_,
            'views': [(self.env.ref('carpentry_planning.carpentry_planning_project_milestone_table').id, 'form')],
            'target': 'new',
        }
