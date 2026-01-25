# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from collections import defaultdict

class Position(models.Model):
    _name = "carpentry.position"
    _inherit = ['carpentry.group.phase']
    _description = "Position"
    _order = "sequence_lot, sequence"
    _rec_names_search = ['name']
    
    #===== Fields =====#
    # basic fields
    lot_id = fields.Many2one(
        comodel_name='carpentry.group.lot',
        domain="[('project_id', '=', project_id)]",
        ondelete='restrict',
        required=True,
    )
    sequence_lot = fields.Integer(
        related='lot_id.sequence',
        string='Lot sequence',
        store=True,
    )
    quantity = fields.Integer(
        string='Quantity',
        required=True,
    )
    surface = fields.Float(
        string='Surface',
        digits=(6,2)
    )
    range = fields.Char(
        string='Range'
    )
    description = fields.Char(
        string='Description'
    )
    # affectations
    affectation_ids = fields.One2many(
        inverse_name='position_id',
        domain=[('mode', '=', 'phase')]
    )
    quantity_remaining_to_affect = fields.Integer(
        string='Remaining', 
        compute='_compute_quantities_and_state', 
        compute_sudo=True,
        help='Quantity remaining for affection in phases',
    )
    state = fields.Selection(
        selection=[
            ('na', 'n/a'),
            ('none', 'None'),
            ('warning_phase', 'Partial on phase(s)'),
            ('warning_launch', 'Partial on launch(es)'),
            ('done', 'OK')
        ],
        string='Affectation status',
        default='na',
        compute='_compute_quantities_and_state',
        store=True,
        help='Whether quantity is fully affected or not in phases and launches',
    )

    #===== Constrain =====#
    @api.constrains('quantity')
    def _constrain_quantity_affected(self):
        """ Cannot lower quantity under affected qty in phases """
        self.affectation_ids._constrain_quantity_affected()

    #===== CRUD: for Affectations provisioning =====#
    @api.model_create_multi
    def create(self, vals_list):
        """ Automatically pre-provision Phases' affectations by created Positions
            (i.e. update the affectations of Phases already linked to Lots of the created Positions)
        """
        positions = super().create(vals_list)
        positions.lot_id.phase_ids._provision_affectations(positions)
        return positions
    
    def write(self, vals):
        """ Cascade change of position's qty:
             - if 0: unlink affectations (clean)
             - else: create affectations, if previous qty was 0
        """
        res = super().write(vals)
        
        # after `write`
        if 'quantity' in vals and vals['quantity'] == 0:
            # unlink unnecessary 'empty' affectation
            self.affectation_ids.unlink()
        if any([x in vals for x in ['quantity', 'lot_id']]):
            # pre-create empty affectations
            self.lot_id.phase_ids._provision_affectations(self)
        
        return res

    #===== Compute =====#
    @api.depends('quantity', 'project_id.affectation_ids.quantity_affected')
    def _compute_quantities_and_state(self):
        # For a given position, get its quantity already affected in phases and launches (separatly)
        rg_result = self.env['carpentry.affectation'].read_group(
            domain=[
                ('position_id', 'in', self._origin.ids),
                '|', ('mode', '!=', 'launch'), ('affected', '=', True), 
            ],
            groupby=['position_id', 'mode'],
            fields=['quantity_affected:sum'],
            lazy=False,
        )
        sum_affected = defaultdict(dict)
        for x in rg_result:
            sum_affected[x['mode']][x['position_id'][0]] = x['quantity_affected']
        
        # update fields
        for position in self:
            position.quantity_remaining_to_affect = position.quantity - sum_affected['phase'].get(position.id, 0)
            
            state = 'done'
            if position.quantity == 0:
                state = 'na'
            elif position.quantity_remaining_to_affect == position.quantity:
                state = 'none'
            elif position.quantity_remaining_to_affect > 0:
                state = 'warning_phase'
            elif position.quantity > sum_affected['launch'].get(position.id, 0):
                state = 'warning_launch'
            position.state = state

    #===== Action & Button =====#
    def copy(self, default=None):
        return super().copy((default or {}) | {
            'name': self.name + _(' (copied)')
        })
