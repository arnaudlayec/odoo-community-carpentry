# -*- coding: utf-8 -*-
{
    'name': "Needs",
    'summary': "Manage templates of recurrent tasks, whose deadlines follow Launches production start (optional)",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.0.1',

    'depends': [
        'web_widget_numeric_step', 'project_type', 'project_role', # OCA
        'project_favorite_switch', 'project_task_default_assignee', # other
        'carpentry_base', 'carpentry_planning_task_type' # carpentry
    ],
    'data': [
        # default conf (required XML-ID)
        'data/project.type.xml',
        'data/carpentry.planning.column.xml',
        'data/carpentry.planning.milestone.type.xml',
        # views
        'views/carpentry_need.xml',
        'views/carpentry_planning.xml',
        'views/project_type.xml',
        'views/project_task_need.xml',
        'views/project_task_type.xml',
        'views/carpentry_planning_column.xml',
        # security
        'security/ir.model.access.csv',
    ],
    'post_init_hook': 'post_init_hook', # rebuild sql view
    'uninstall_hook': 'uninstall_hook',
}
