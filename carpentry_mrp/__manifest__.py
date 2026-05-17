# -*- coding: utf-8 -*-
{
    'name': "MRP Positions",
    'summary': "Manufacture positions as final products",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'auto_install': False,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.1.1',

    'depends': [
        'mrp', # Odoo CE
        'purchase_order_no_zero_price', 'stock_valuation_layer_inventory_filter', 'stock_no_negative', # OCA
        'project_role_visibility', # for access rules
        'mrp_project_link', 'mrp_attendance', 'mrp_productivity_qty', 'stock_move_comment', # other
        'stock_valuation_no_zero',
        'carpentry_purchase', # carpentry
    ],
    'data': [
        # security
        'security/ir.model.access.csv',
        'security/project_security.xml',
        # views
        'views/mrp_production.xml',
        'views/mrp_workorder.xml',
        'views/product_template.xml',
        'views/stock_picking.xml',
        'views/carpentry_planning.xml',
        'views/carpentry_launch.xml',
        # report
        'report/stock_report_picking_operations.xml',
        'report/mrp_production_templates.xml',
    ]
}
