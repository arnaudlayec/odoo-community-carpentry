# -*- coding: utf-8 -*-
{
    'name': "Planning",
    'summary': "Steer project's tasks, milestones and budget per launch in a customized dashboard (core module).",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.0.2',

    'depends': [
        'web_widget_numeric_step', # OCA
        'project_favorite_switch', # others
        'carpentry_base', 'carpentry_position' # carpentry
    ],
    'data': [
        # wizard
        'wizard/carpentry_planning_milestone_wizard.xml',
        # views
        'views/carpentry_planning_card.xml',
        'views/carpentry_planning_column.xml',
        'views/carpentry_planning_milestone.xml',
        'views/carpentry_group_launch.xml',
        'views/project_role.xml',
        # security
        'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'carpentry_planning/static/src/**/*',
        ]
    }
}

