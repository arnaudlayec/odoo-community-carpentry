# -*- coding: utf-8 -*-
{
    'name': "Purchase Budget",
    'summary': "Consume positions budget from purchases expense",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'auto_install': False,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.0.1',

    'depends': ['carpentry_purchase', 'carpentry_position_budget'],
    'data': [
        # security
        'security/ir.model.access.csv',
        # views
        'views/purchase_order.xml',
    ],
    'post_init_hook': 'post_init_hook', # rebuild budget expense sql view
    'uninstall_hook': 'uninstall_hook',
}
