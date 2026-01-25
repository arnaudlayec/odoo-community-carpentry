# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command

class Phase(models.Model):
    _name = "carpentry.group.phase"
    _inherit = ['project.default.mixin', 'carpentry.affectation.mixin']
    _description = "Phase"
    _order = "sequence"
    # affectations config
    _carpentry_field_parent_group = 'lot_id'
    _carpentry_field_record = 'position_id'
    _carpentry_field_affectations = 'affectation_ids'
    
    #===== Fields ======#
    company_id = fields.Many2one(
        related='project_id.company_id',
        store=True,
    )
    name = fields.Char(
        string='Name',
        required=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        compute='_compute_sequence',
        store=True,
        copy=False
    )
    active = fields.Boolean(
        string="Active?",
        default=True
    )
    # from `affectation.mixin`
    affectation_ids = fields.One2many(
        inverse_name='phase_id',
        domain=[('mode', '=', 'phase')],
    )
    lot_ids = fields.One2many(
        inverse='_inverse_parent_group_ids',
    )

    #===== Compute =====#
    @api.depends('project_id')
    def _compute_sequence(self):
        """ `sequence` is incremental for all phases within the project
            We could use `ir.sequence` object but this would create 1 `ir.sequence`
            record per project & carpentry group (lot, phase, launch, ...)
            which is too spaming
            => we manage the incremental it manually
        """
        self = self.with_context(active_test=False)
        rg_result = self._read_group(
            domain=[('project_id', 'in', self.project_id.ids)],
            groupby=['project_id'],
            fields=['sequence:max']
        )
        mapped_sequence_max = {x['project_id'][0]: x['sequence'] for x in rg_result}
        for group in self:
            group.sequence = mapped_sequence_max.get(group.project_id.id, 0) + 1

            # increment, in case we create several phases at once
            mapped_sequence_max[group.project_id.id] = group.sequence

    #====== Actions & Buttons ======#
    def convert_to_launch(self):
        """ Create launchs from phases
            :return: tree view of created launchs
        """
        Launch = self.env['carpentry.group.launch']
        launchs = Launch.create([
            phase._get_vals_converted_launch()
            for phase in self
        ])

        return {
            'type': 'ir.actions.act_window',
            'res_model': Launch._name,
            'name': _(Launch._description),
            'view_mode': 'tree',
            'domain': [('id', 'in', launchs.ids)]
        }
    
    def _get_vals_converted_launch(self):
        """ :arg `self`: phase
            :return: launch's vals
        """
        self.ensure_one()
        return {
            'name': self.name,
            'project_id': self.project_id.id,
            'phase_ids': [Command.set([self.id])]
        }
