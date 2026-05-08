# -*- coding: utf-8 -*-
{
    'name': "Purchase",
    'summary': "Delivery to construction site",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': True,
    'installable': True,
    'auto_install': False,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.2.0',

    'depends': [
        'project', 'purchase', 'purchase_requisition', 'stock', # odoo
        'project_purchase_link', # OCA
        'purchase_stock_usability', # for 'delivery_partner_id'
        'project_favorite_switch', 'purchase_multiple_arrival_date', # other
        'carpentry_base', 'carpentry_planning_task_need', # carpentry
    ],
    'data': [
        # data
        'views/project_project.xml',
        'views/carpentry_launch.xml',
        'views/project_purchase_link.xml',
        'views/purchase_order.xml',
        'views/purchase_arrival_date.xml',
        'views/purchase_requisition.xml',
        # report
        'report/purchase_template.xml',
        # security
        'security/purchase_order.xml',
    ],
}
