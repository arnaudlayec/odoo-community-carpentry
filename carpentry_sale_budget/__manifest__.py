# -*- coding: utf-8 -*-
{
    'name': 'Carpentry Margins',
    'summary': "Add margins calculations on project form and follow budget update status from Quotations & Sales Order (auto-install).",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'auto_install': False,
    'category': 'Carpentry',
    'version': '16.0.1.0.1',

    'depends': ['carpentry_base', 'carpentry_sale', 'carpentry_position_budget'],
    'data': [
        'views/project_project.xml',
        'views/sale_order.xml',
    ],
}
