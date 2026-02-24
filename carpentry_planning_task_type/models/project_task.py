# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.tools import date_utils
from odoo.osv import expression
from collections import defaultdict
from lxml import etree

XML_ID_MILESTONE = 'carpentry_planning_task_type.task_type_milestone'
XML_ID_MEETING = 'carpentry_planning_task_type.task_type_meeting'
XML_ID_INSTRUCTION = 'carpentry_planning_task_type.task_type_instruction'

class Task(models.Model):
    """ Manages special tasks: Instructions, Meetings, Milestones """
    _inherit = ['project.task']
    _rec_name = 'display_name'
    _rec_names_search = ['name']

    #===== Fields' methods =====#
    @api.model
    def default_get(self, field_names):
        vals = super().default_get(field_names)
        
        # Default `type_id`
        if 'type_id' in field_names and not self._context.get('default_type_id'):
            vals['type_id'] = self._get_default_type_id()
        return vals

    def _get_default_type_id(self, vals={}):
        """ Set a default `type_id` within the possible allowed
            by `root_type_id` and `parent_type_id`
        """
        # Get possible `type_ids`
        root_type_id = self.root_type_id.id or self._context.get('default_root_type_id')
        domain = [
            ('root_type_id', '=', root_type_id),
            ('task_ok', '=', True),
        ] + ([('parent_id', '=', self.parent_type_id.id)] if self.parent_type_id.id else [])
        type_ids = self.env['project.type'].search(domain)

        # If some seems more relevant/compatible with roles of current user
        # auto-suggest this default in preference
        domain_role = [('role_id.assignment_ids.user_id', '=', self.env.uid)]
        filtered_type_ids = type_ids.sudo().filtered_domain(domain_role)
        if filtered_type_ids.ids:
            type_ids = filtered_type_ids

        # If some seems more relevant/compatible with **ANALYTIC ACCOUNT** (see `project_task_analytic_hr`)
        # auto-suggest in last preference
        if len(type_ids.ids) > 1:
            analytic = self.env.user.employee_id._get_analytic_account_id()
            domain_analytic = [('analytic_account_id', '=', analytic.id)]
            filtered_type_ids = type_ids.filtered_domain(domain_analytic)
            if filtered_type_ids.ids:
                type_ids = filtered_type_ids

        return fields.first(type_ids).id
    
    @api.model
    def _read_group_types(self, records, domain, order, task_ok=True):
        return self.env['project.type'].search([
            ('task_ok', 'in', records.mapped('task_ok')), # of the same hierarchy level
            ('root_type_id', 'in', records.root_type_id.ids), # in the same type category
        ])


    #===== Fields =====#
    root_type_id = fields.Many2one(
        comodel_name='project.type',
        string='Task Type',
        related='type_id.root_type_id',
        store=True,
        readonly=True,
        domain=[('parent_id', '=', False), ('task_ok', '=', False)]
    )
    parent_type_id = fields.Many2one(
        # in N-levels type hierarchy:
        # - `type_id` is the N (last/bottom) --> Need category
        # - `parent_type_id` is the N-1 --> e.g. "Needs (method)"
        # - `root_type_id` is the 1st (top) --> e.g. "Needs"
        comodel_name='project.type',
        string='Parent Category',
        related='type_id.parent_id',
        readonly=True,
        store=True,
        domain="[('root_type_id', '=', root_type_id), ('task_ok', '=', False)]",
        group_expand='_read_group_types'
    )
    type_id = fields.Many2one(
        # from module `project_type`
        string='Category',
        required=True,
        domain="""[
            ('root_type_id', '=', root_type_id),
            ('parent_id', '=', parent_type_id),
            ('task_ok', '=', True)
        ]""",
        group_expand='_read_group_types',
    )
    type_sequence = fields.Integer(
        related='type_id.sequence',
        store=True,
        string='Type Sequence',
    )

    # -- Original --
    name = fields.Char(
        required=False
    )
    partner_id = fields.Many2one(
        # `partner_id` is already hidden on view: not relevant for Vertical construction
        # to have it in tasks. Disable also the ORM field, so it is never added to chatter
        default=False,
        tracking=False,
        compute=False,
    )

    # -- Specific --
    # instructions: may have many types
    type_ids = fields.Many2many(
        comodel_name='project.type',
        relation='project_task_subtype_rel',
        string='Categories',
        domain="[('root_type_id', '=', root_type_id), ('task_ok', '=', True)]",
    )
    launch_ids = fields.Many2many(
        comodel_name='carpentry.group.launch',
        string='Launches',
        relation='carpentry_group_launch_project_task_rel',
        column1='task_id',
        column2='launch_id',
    )
    # meetings
    message_last_date = fields.Date(
        string='Last Message',
        compute='_compute_message_fields'
    )
    count_message_ids = fields.Integer(
        string='Message Count',
        compute='_compute_message_fields'
    )

    # -- User-interface --
    copy_task_id = fields.Many2one(
        # quick overrite, see module `project_task_copy`
        domain="[('project_id', '=', copy_project_id), ('root_type_id', '=', root_type_id)]"
    )
    name_required = fields.Boolean(
        compute='_compute_name_required'
    )
    attachment_count = fields.Integer(
        string='Total Attachment Count',
        compute='_compute_attachment_count',
    )

    #===== Constrain =====#
    @api.constrains('root_type_id', 'parent_type_id', 'type_id')
    def _constrain_type_id(self):
        """ Ensure `task.type_id` follow type hierarchy (i.e. is a child of `task.parent_type_id`) """
        for task in self:
            error = (
                task.type_id.parent_id != task.parent_type_id
                or task.type_id.root_type_id != task.root_type_id
            )
            if error:
                raise exceptions.ValidationError(
                    _("Task Category must be in Parent's Category.")
                )


    #===== Compute: user-interface =====#
    @api.depends('root_type_id')
    def _compute_name_required(self):
        """ Required for:
            1. standard Task ; `default_root_type_id = False`
            2. instruction
            3. need (see module `carpentry_planning_task_need`)
        """
        required_list = self._get_name_required_type_list()
        default_root_type_id = self._context.get('default_root_type_id')
        required_by_ctx = not default_root_type_id or default_root_type_id in required_list # for new task, without id yet
        for task in self:
            task.name_required = required_by_ctx or task.root_type_id.id in required_list
    def _get_name_required_type_list(self):
        return [self.env.ref(XML_ID_INSTRUCTION).id]
    
    def _compute_attachment_count(self):
        """ Count both `task.attachment_ids` and chatter's attachments """
        rg_result = self.env['ir.attachment'].sudo().read_group(
            domain=[('res_id', 'in', self.ids), ('res_model', '=', self._name)],
            fields=['res_id'],
            groupby=['res_id']
        )
        mapped_data = {x['res_id']: x['res_id_count'] for x in rg_result}
        for task in self:
            task.attachment_count = mapped_data.get(task.id)

    #===== Compute: display_name =====#
    @api.depends('name', 'type_id', 'root_type_id')
    def _compute_display_name(self):
        """ `name` can be optional: set `display_name` to task or type `name` """
        for task in self:
            task.display_name = task.name or task.type_id.name
    @api.model
    def _search_display_name(self, operator, value):
        return [('name', operator, value)]
    
    #===== Onchange: type =====#
    @api.onchange('root_type_id', 'parent_type_id')
    def _onchange_root_parent_type_id(self):
        """ Update pre-select `type_id` to follow its parent """
        for task in self:
            task.type_id = task._get_default_type_id()

    #===== Specific: meetings =====#
    @api.depends('type_id', 'message_ids')
    def _compute_message_fields(self):
        rg_result = self.env['mail.message'].sudo().read_group(
            domain=[('id', 'in', self.message_ids.ids), ('message_type', '=', 'comment')],
            fields=['create_date:max', 'res_id'],
            groupby=['res_id']
        )
        mapped_data = {
            x['res_id']: {'last_date': x['create_date'], 'count': x['res_id_count']}
            for x in rg_result
        }
        for task in self:
            task.message_last_date = mapped_data.get(task.id, {}).get('last_date')
            task.count_message_ids = mapped_data.get(task.id, {}).get('count')

    #===== Action =====#
    def _get_task_views(self, type_code, custom, switch=[], module=''):
        """
            :arg type_code: `code` fields of `project.type`, like 'meeting',
                            'need', ...
            :arg custom:    list like ['tree', 'form'] of views type to load
                            as custom views by tasks type
            :option switch: list of standard or customs task views to display
                            to the user (in right-bottom ControlPannel)
            :option module: to pass `carpentry_planning_task_need` prefix for view XMLID
        """
        switch = switch or custom
        module = module or 'carpentry_planning_task_type'

        standard_views = {
            'tree': self.env.ref('project.view_task_tree2').id,
            'form': self.env.ref('project.view_task_form2').id,
            'kanban': self.env.ref('project.view_task_kanban').id,
            'calendar': self.env.ref('project.view_task_calendar').id,
            'activity': self.env.ref('project.project_task_view_activity').id,
        }
        
        # Loads custom view if requested and available, else standard Task views by default
        views = []
        for view_mode in switch:
            view_id = standard_views[view_mode]
            
            if type_code and view_mode in custom:
                custom_xml_id = self.env.ref(
                    f'{module}.view_task_{view_mode}_{type_code}',
                    raise_if_not_found=False
                )
                if custom_xml_id:
                    view_id = custom_xml_id.id
            
            views.append((view_id, view_mode))
        
        return views


    #===== Buttons / action =====#
    def action_open_planning_dashboard_card(self):
        """ Called on Planning's Dashboard card items click """
        return self.action_open_planning_form()

    def action_open_planning_form(self):
        """ Redirect to task' specific form on tree's button `Details` """
        type_code = self.root_type_id.code
        views_form = self.env['project.task']._get_task_views(type_code, ['form'])

        # return specific Task Form, if available
        action = super().action_open_planning_form() | {
            'views': views_form
        }
        action['context'] |= {
            # required for correct `name_required` computation
            'default_root_type_id': self.root_type_id.id
        }
        
        return action
