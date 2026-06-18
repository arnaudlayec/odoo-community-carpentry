# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from lxml import etree

class PlanningMilestone(models.Model):
    """ Is filled-in by end-users on Carpentry Planning, per Launch """ 
    _name = "carpentry.planning.milestone"
    _description = "Planning Milestone"
    _order = "launch_id, column_id, milestone_type_id"

    #===== Fields =====#
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        related='launch_id.project_id',
    )
    launch_id = fields.Many2one(
        comodel_name='carpentry.group.launch',
        string='Launch',
        required=True,
        ondelete='cascade'
    )
    milestone_type_id = fields.Many2one(
        comodel_name='carpentry.planning.milestone.type',
        string='Milestone type',
        required=True,
        ondelete='cascade'
    )
    date = fields.Date(
        string='Date',
        default=False,
    )
    date_week = fields.Char(
        string='Week',
        compute='_compute_date_week',
    )
    is_done = fields.Boolean(
        default=False,
    )
    is_last = fields.Boolean(
        compute="_compute_is_last",
    )

    # related fields
    name = fields.Char(
        related='milestone_type_id.name'
    )
    icon = fields.Char(
        related='milestone_type_id.icon'
    )
    type = fields.Selection(
        related='milestone_type_id.type',
        store=True
    )
    shortcut = fields.Boolean(
        related='milestone_type_id.shortcut',
    )
    sequence = fields.Integer(
        related='milestone_type_id.sequence',
    )
    column_id = fields.Many2one(
        related='milestone_type_id.column_id',
        store=True,
    )

    #===== Constrain =====#
    _sql_constraints = [
        ("type_per_column_launch",
        "UNIQUE (launch_id, column_id, type)",
        "This type of milestone already exists on this launch and column."
    )]

    @api.constrains('date', 'milestone_type_id', 'launch_id')
    def _start_end_constraint(self):
        if self._context.get('planning_milestone_no_start_end_constrain'):
            return

        self = self.filtered(lambda x: x.milestone_type_id.type in ['start', 'end'])
        mapped_dates = {
            (x.launch_id.id, x.column_id.id, x.type): x.date
            for x in self.launch_id.milestone_ids
        }
        
        for x in self:
            start_date = mapped_dates.get((x.launch_id.id, x.column_id.id, 'start'))
            end_date = mapped_dates.get((x.launch_id.id, x.column_id.id, 'end'))

            if not start_date or not end_date:
                continue

            if end_date < start_date:
                raise exceptions.ValidationError(_('End date must be after the start date.'))

    #===== Compute =====#
    @api.depends('date')
    def _compute_date_week(self):
        """ Compute the week of the date """
        for milestone in self:
            milestone.date_week = milestone.date and _('W%s', milestone.date.isocalendar()[1])
    
    @api.depends("sequence", "launch_id")
    def _compute_is_last(self):
        for milestone in self:
            milestone.is_last = bool(
                milestone == milestone.launch_id.milestone_ids._get_last()
            )

    #===== Logics =====#
    def _should_shift(self):
        return self.type in ['start', 'end']

    def _get_last(self):
        """Return last milestone (as per sequence) in the recordset"""
        return self.filtered(
            lambda x: x.sequence == max(self.mapped("sequence"))
        )
