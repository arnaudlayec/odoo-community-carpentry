# -*- coding: utf-8 -*-

from odoo import models, _

class Project(models.Model):
    _inherit = ["project.project"]
    
    def action_open_task_need(self):
        return self._action_open_task_common(
            name=_('View and adapt needs'),
            type_code='need',
            custom=['tree', 'form'],
            switch=['tree', 'form', 'kanban', 'calendar', 'activity'],
            module='carpentry_planning_task_need',
            context={
                'search_default_filter_my_role': 1,
                'display_with_prefix': False,
            }
        ) | {
            'search_view_id': [self.env.ref('carpentry_planning_task_need.view_task_search_form').id, 'search'],
            'domain': [('root_type_id', '=', self.env.ref('carpentry_planning_task_need.task_type_need').id)]
        }
