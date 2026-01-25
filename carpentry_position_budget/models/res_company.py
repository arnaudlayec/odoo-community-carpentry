# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _

class Company(models.Model):
    _inherit = ['res.company']

    budget_date_times_posted = fields.Date(
        string='Threshold date for budget times',
    )
