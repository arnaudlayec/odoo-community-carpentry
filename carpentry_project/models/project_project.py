# -*- coding: utf-8 -*-

from odoo import fields, models, api, exceptions, _, Command
from odoo.tools.safe_eval import safe_eval

def _resolve_string_to_python(string):
    return safe_eval(string) if isinstance(string, str) else string or {}

class ProjectProject(models.Model):
    _inherit = ["project.project"]

    #===== Fields =====#
    project_template_id = fields.Many2one(
        comodel_name='project.project',
        string='Template Project',
        compute='_compute_project_template_id',
        inverse='_inverse_project_template_id',
        help='Copy project type, dates, tasks and roles assignations.',
    )
    # User-interface
    warning_banner = fields.Boolean(
        compute='_compute_warning_banner'
    )
    
    #===== Compute =====#
    def _compute_warning_banner(self):
        for project in self:
            project.warning_banner = project._get_warning_banner()
    def _get_warning_banner(self):
        """ Inherite to add conditions to display the warning banner """
        self.ensure_one()
        return False
    
    #===== Project copy =====#
    def _compute_project_template_id(self):
        """ Fake compute, we only need `inverse` """
        self.project_template_id = False
    
    @api.onchange('project_template_id')
    def _inverse_project_template_id(self):
        template = self.project_template_id

        # copy
        for field_name in self._get_copied_fields():
            if self.id and isinstance(self._fields[field_name], fields.One2many):
                for record in template[field_name]:
                    record.copy({'project_id': self.id})
            else:
                self[field_name] = template[field_name]
    
    def _get_copied_fields(self):
        return [
            'date_start', 'date', 'type_id',
            'task_ids', 'assignment_ids'
        ]
    

    #===== Button / Action =====#
    def open_project_list_or_form(self):
        project_id_ = self.env['project.default.mixin']._get_project_id()

        # Project List
        if not project_id_:
            # 2 views depending configuration of project's group by stage or not
            group = '_group_stage' if self.env.user.has_group('project.group_project_stages') else ''
            xml_id = 'project.open_view_project_all' + group
            action = self.env['ir.actions.act_window'].sudo()._for_xml_id(xml_id)

            projects_fav = self.env.user._get_favorite_projects()
            # If users has favorite projects, filter the view on them
            if projects_fav.ids:
                context = _resolve_string_to_python(action.get('context'))
                action['context'] = context | {'search_default_my_projects': True}

        # Project Form
        else:
            action = {
                'type': 'ir.actions.act_window',
                'res_model': 'project.project',
                'view_mode': 'form',
                'res_id': project_id_,
            }

        return action
