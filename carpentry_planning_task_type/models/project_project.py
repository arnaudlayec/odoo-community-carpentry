# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.addons.carpentry_planning_task_type.models.project_task import (
    XML_ID_INSTRUCTION, XML_ID_MILESTONE, XML_ID_MEETING
)

from collections import defaultdict
import datetime

class Project(models.Model):
    _inherit = ['project.project']

    #===== Planning =====#
    def get_planning_dashboard_data(self):
        """ Data for project's dashboard KPI """
        return (
            super().get_planning_dashboard_data()
            | self._get_planning_dashboard_task_meetings()
            | self._get_planning_dashboard_task_milestones()
        )

    def _get_planning_dashboard_task_meetings(self):
        fields = ['id', 'display_name', 'kanban_state', 'count_message_ids', 'message_last_date']
        meeting_ids = self.task_ids.filtered(
            lambda x: x.root_type_id.id == self.env.ref(XML_ID_MEETING).id
        ).sorted(
            key=lambda r: r.message_last_date or datetime.date.max,
            reverse=True
        )
        return {'meetings': meeting_ids.read(fields)}

    def _get_planning_dashboard_task_milestones(self):
        # parent_types
        fields = ['id', 'name', 'shortname']
        domain = [
            ('root_type_id', '=', self.env.ref(XML_ID_MILESTONE).id),
            ('task_ok', '=', False)
        ]
        parent_types_data = self.env['project.type'].sudo().with_context(display_short_name=True).search_read(domain, fields)

        # milestones, groupped by `parent_type_id`
        fields = ['id', 'display_name', 'kanban_state', 'date_deadline', 'date_end', 'parent_type_id']
        domain = [
            ('root_type_id', '=', self.env.ref(XML_ID_MILESTONE).id),
            ('project_id', 'in', self.ids)
        ]
        milestones_data = self.env['project.task'].search_read(domain, fields, order='type_sequence')

        __week = lambda date: bool(date) and _('W%s', date.isocalendar()[1])
        mapped_milestone_data = defaultdict(list)
        for x in milestones_data:
            parent_type_id = x['parent_type_id'][0]
            del(x['parent_type_id'])

            x['week_deadline'] = __week(x['date_deadline'])
            x['week_done'] = __week(x['date_end'])
            mapped_milestone_data[parent_type_id].append(x)
        
        return {
            'parent_types': parent_types_data, # 1st line (columns header)
            'milestones': mapped_milestone_data # rows
        }
    

    

    #===== Action (task menu-items srv action) =====#
    def _action_open_task_common(self, name, type_code, custom, switch, module='', context={}):
        module = module or 'carpentry_planning_task_type'
        search_view_id = self.env.ref(f'{module}.view_task_search_{type_code}', raise_if_not_found=False)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'name': name,
            'views': self.env['project.task']._get_task_views(type_code, custom, switch, module),
            'context': {
                'default_root_type_id': self.env.ref(module + '.task_type_' + type_code).id,
            } | context,
            'domain': [('root_type_id', '=', self.env.ref(module + '.task_type_' + type_code).id)]
        } | (
            {'search_view_id': (search_view_id.id, 'search')} if search_view_id else {}
        )
    
    # Instruction
    def action_open_task_instruction(self):
        return self._action_open_task_common(
            name=_('Instructions'),
            type_code='instruction',
            custom=['tree', 'form'],
            switch=['tree', 'form'],
            context={
                'display_type_ids': True, # hide `parent_type_id` and `type_ids` ; display `type_ids`
                'display_parent_type_id': False
            }
        )
    
    # Meeting
    def action_open_task_meeting(self):
        return self._action_open_task_common(
            name=_('Meetings'),
            type_code='meeting',
            custom=['tree', 'form'],
            switch=['tree', 'form', 'kanban', 'calendar', 'activity']
        )
    
    # Milestone
    def action_open_task_milestone(self):
        return self._action_open_task_common(
            name=_('Milestones'),
            type_code='milestone',
            custom=['tree'],
            switch=['tree', 'form', 'kanban', 'calendar', 'activity']
        )
