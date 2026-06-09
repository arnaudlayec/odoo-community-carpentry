# -*- coding: utf-8 -*-
{
    'name': "MRP Orgadata Import",
    'summary': "Import components to Manufacturing Orders (from Orgadata)",
    'author': 'Arnaud LAYEC',
    'website': 'https://github.com/arnaudlayec/odoo-community-carpentry',
    'license': 'AGPL-3',

    'application': False,
    'installable': True,
    'auto_install': False,
    'category': 'Carpentry/Carpentry',
    'version': '16.0.1.0.2',

    'depends': [
        "utilities_file_management", # alayec
        'purchase_discount', # OCA
        'carpentry_mrp', # carpentry
    ],
    'data': [
        # security
        'security/ir.model.access.csv',
        # wizard
        'wizard/carpentry_mrp_import_wizard.xml',
        # views
        'views/mrp_production.xml',
        'views/product_views.xml',
        'views/product_substitution.xml',
        'views/stock_picking.xml',
    ]
}
