# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api

def pre_init_hook(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _prebuild_budget_analytic_project_rel(cr, env)

def _prebuild_budget_analytic_project_rel(cr, _):
    """ Needed at install because `report` sql is committed before `models` """
    cr.execute("""
        CREATE TABLE IF NOT EXISTS public.carpentry_budget_analytic_line_project_rel (
            line_id integer NOT NULL,
            project_id integer NOT NULL
        );
    """)
