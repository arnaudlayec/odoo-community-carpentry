# -*- coding: utf-8 -*-
{
    'name': "Position Budget",
    'summary': "Import budget on positions and manage goods and worktime budgets per project (core module)",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.2.3',

    'depends': [
        # odoo
        'analytic',
        'hr_timesheet', # only for company.internal_project_id
        'sales_team', # for security access
        'web_notify', # OCA
        'analytic_mixin_analytic_account', # OCA, for field `account_analytic_ids`
        'project_role_visibility', # other (for security access)
        'project_task_analytic_hr', # other (for 🕓 in analytic display_name)
        'project_favorite_switch', 'project_budget_workforce', 'utilities_file_management', # other
        'carpentry_base', 'carpentry_project', 'carpentry_position', 'carpentry_planning', # carpentry
    ],
    'data': [
        # security
        'security/ir.model.access.csv',
        # wizard
        'wizard/carpentry_position_merge_wizard.xml',
        'wizard/carpentry_position_budget_import_wizard.xml',
        # views
        'views/carpentry_group_phase.xml',
        'views/carpentry_position_budget_interface.xml',
        'views/carpentry_position_budget.xml',
        'views/carpentry_position.xml',
        'views/carpentry_planning_column.xml',
        'views/project_project.xml',
        'views/account_move_budget_line.xml',
        'views/carpentry_budget_reservation.xml',
        'views/carpentry_budget_balance.xml',
        'views/account_analytic_line.xml',
        # templates
        'templates/carpentry_budget_template.xml',
        # report
        'report/carpentry_budget_available.xml',
        'report/carpentry_budget_remaining.xml',
        'report/carpentry_budget_expense.xml',
        'report/carpentry_budget_expense_unposted_wizard.xml',
        'report/carpentry_budget_project.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'carpentry_position_budget/static/src/**/*',
        ],
    },
    'pre_init_hook': 'pre_init_hook',
}