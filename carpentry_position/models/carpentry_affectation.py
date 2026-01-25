# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _

class CarpentryAffectation(models.Model):
    """ This model holds *all* relations between:
        - Phases-with-Positions, and
        - Launchs-with-Positions (through Phases)

        This is a single table because M2M classic fields does not allow additional field
         in the relation table, which is needed (eg. qty, sequences, ...)

        Two kinds of affectations (Phases & Launchs):
         Displayed form  >  `parent_group`    `group`     `record`      `affectations`
         (- Lots)               /               /           /            position_ids
         - Phases            lot_id            phase_id    position_id   affectation_ids
         - Launchs           phase_id          launch_id   parent_id      /
    """
    _name = "carpentry.affectation"
    _description = "Position Affectation"
    _order = "sequence_parent_group, sequence_group, sequence_position"
    _log_access = False

    #===== Model methods =====#
    def _split(self):
        """ :return: tuple like (phase_affectations, launch_affectations) """
        launch_affectations = self.filtered('launch_id')
        return (self - launch_affectations, launch_affectations)

    #===== Fields =====#
    # Base
    mode = fields.Selection(
        selection=[('phase', 'Phase'), ('launch', 'Launch')],
        required=True,
    )
    project_id = fields.Many2one(
        related='position_id.project_id',
        store=True,
        required=True,
        ondelete='cascade',
        index='btree_not_null',
    )
    lot_id = fields.Many2one(
        comodel_name='carpentry.group.lot',
        string='Lot',
        related='position_id.lot_id',
        store=True,
        recursive=True,
        ondelete='set null', # only required to order phase affectations
    )
    phase_id = fields.Many2one(
        comodel_name='carpentry.group.phase',
        string='Phase',
        compute='_compute_child_fields',
        store=True,
        required=True,
        readonly=True,
        recursive=True,
        ondelete='cascade',
    )
    launch_id = fields.Many2one(
        comodel_name='carpentry.group.launch',
        string='Launch',
        required=False, # required only for launch affectations, else null for phases
        readonly=True,
        ondelete='cascade',
    )
    position_id = fields.Many2one(
        comodel_name='carpentry.position',
        string='Position',
        compute='_compute_child_fields',
        store=True,
        readonly=True,
        recursive=True,
        required=True, # direct in phase affectations, else computed
        ondelete='cascade', # will raise if needed (cf. budget)
    )
    parent_id = fields.Many2one(
        # only exists on launch affectations
        comodel_name='carpentry.affectation',
        string='Parent affectation',
        required=False, # required only for launchs affectations
        readonly=True,
        ondelete='restrict', # don't allow unlink of phase affectations if there are used for launch affectations
    )
    children_ids = fields.One2many(
        # only exists on phase affectations
        comodel_name='carpentry.affectation',
        inverse_name='parent_id',
        string='Children affectations',
    )
    phase_sibling_ids = fields.One2many(
        related='position_id.affectation_ids',
        string='Sibling positions',
    )
    launch_sibling_ids = fields.One2many(
        related='parent_id.children_ids',
        string='Sibling affectations',
    )
    affected = fields.Boolean(
        default=False,
        index=False,
        # search='_search_affected', # only in v18.0 ?
    )
    is_affectable = fields.Boolean(
        compute='_compute_is_affectable',
        # store=True,
        # precompute=True,
    )
    active = fields.Boolean(
        compute='_compute_active',
        store=True,
        recursive=True,
    )
    # -- sequences --
    sequence_parent_group = fields.Integer(
        # lot's (for phase's affectations), or
        # phase's (for launch's affectation)
        compute='_compute_sequences',
        store=True,
        readonly=True,
    )
    sequence_group = fields.Integer(
        # lot's (for phase's affectations), or
        # phase's (for launch's affectation)
        compute='_compute_sequences',
        store=True,
        readonly=True,
    )
    sequence_position = fields.Integer(
        related='position_id.sequence',
        store=True,
        recursive=True,
        readonly=True,
    )
    # -- quantities --
    quantity_affected = fields.Integer(
        string="Affected quantity",
        compute='_compute_quantity_affected',
        default=0,
        store=True,
        recursive=True,
        precompute=True,
        group_operator='sum',
        readonly=False, # managed in view
    )
    quantity_position = fields.Integer(
        string="Position's quantity",
        related='position_id.quantity',
        group_operator='sum',
        help="Quantity initially available in the project",
    )
    quantity_remaining_to_affect = fields.Integer(
        string='Remaining to affect',
        compute='_compute_quantity_remaining_to_affect',
        group_operator='sum',
        help="[Available quantity in the project] - [Quantities already affected]",
    )
    sum_affected_siblings = fields.Integer(
        string='Quantity affected to siblings',
        compute='_compute_sum_affected_siblings',
    )

    #===== Index (+unique) & constraints =====#
    def init(self):
        super().init()
        
        # phase index (which also ensure unicity)
        self.env.cr.execute("""
            DROP INDEX IF EXISTS idx_carpentry_affectation_lot_phase_position;
            
            CREATE UNIQUE INDEX idx_carpentry_affectation_lot_phase_position 
            ON carpentry_affectation (lot_id, phase_id, position_id)
            WHERE (mode = 'phase');
        """)

        # launch index (which also ensure unicity)
        self.env.cr.execute("""
            DROP INDEX IF EXISTS idx_carpentry_affectation_phase_launch_parent;
            
            CREATE UNIQUE INDEX idx_carpentry_affectation_phase_launch_parent 
            ON carpentry_affectation (phase_id, launch_id, parent_id)
            WHERE (mode = 'launch');
        """)
    
    @api.constrains('affected', 'active')
    def _constrain_is_affectable(self):
        """ Prevent two launch affectations to use the same phase affectation
            (Equivalent formulation: prevent a phase affectation to be affected twice)
        """
        if self._context.get('no_constrain_is_affectable'):
            return
        
        self = self.with_context(active_test=False)
        __, launch_affectations = self._split()
        affectations = launch_affectations.filtered(
            lambda x: x.affected and not x.is_affectable
        )
        if bool(affectations):
            raise exceptions.ValidationError(_(
                    "A position from a phase cannot be affected to several launchs.\n"
                    "- Position: %(position)s \n"
                    "- Phase: %(phase)s \n"
                    "- Other launch: %(other_launchs)s \n"
                    "- Current launch: %(launch)s "
                ,
                position = ', '. join(affectations.position_id.mapped('display_name')),
                phase = ', '. join(affectations.phase_id.mapped('display_name')),
                other_launchs = ', '. join(affectations.launch_sibling_ids.launch_id.mapped('display_name')),
                launch = ', '. join(affectations.launch_id.mapped('display_name')),
            ))

    #===== CRUD:
    # - Launchs affectations provisioning from Phases affectations
    # - Cascade affectation deletion (only if children affectation are not affected)
    # =====#
    @api.model_create_multi
    def create(self, vals_list):
        affectations = super().create(vals_list)
        affectations._constrain_quantity_affected()
        return affectations
    
    def write(self, vals):
        """ Cascade/transform Phases affectations into Launchs affectations
            and delete (clean) Launchs affectations if Phases' one are like `quantity_affected == 0`
        """
        res = super().write(vals)
        if 'quantity_affected' in vals:
            # after `write`
            self._constrain_quantity_affected()
            phase_affectations, _ = self._split()
            if phase_affectations:
                phase_affectations._update_launch_affectations(vals['quantity_affected'])
        return res
    
    def _update_launch_affectations(self, qty):
        """ :arg `self`: `phase_affectations`
            :arg `qty`: Wether to create or remove launchs affectations
                        If `qty`:
                        a) is 0 -> remove
                        b) else -> create
        """
        if not bool(qty):
            self._unlink_if_no_children_affected()
            self.children_ids.unlink()
        else:
            # pre-create empty affectation in the launchs already linked with the phase
            self.phase_id.affectation_ids.children_ids.launch_id._provision_affectations(self)

    def unlink(self):
        """ Allow unlinking phase affectation *ONLY IF*
            children's launch affectation are not affected
        """
        if self.children_ids:
            self.children_ids.filtered(lambda x: not x.affected).unlink()
        return super().unlink()
    
    @api.ondelete(at_uninstall=False)
    def _unlink_if_no_children_affected(self):
        if self.children_ids.filtered('affected'):
            raise exceptions.ValidationError(_(
                "This position is affected to a launch, so"
                " it cannot be unaffected from this phase"
            ))

    @api.depends(
        # (!) stored
        # must includes at least the @api.depends of `quantity_remaining_to_affect`
        'affected', 'launch_sibling_ids.affected', # for launchs
        'quantity_affected', 'phase_sibling_ids.quantity_affected', 'quantity_position', # for phases
    )
    def _compute_is_affectable(self):
        """ Tells if the affectation state in the group can be changed or not
            It happens (a lot) when affectations are populated but their siblings
            - is already affected (for launch)
            - takes all quantity (for phase)

            We don't remove non-affectable affectations of the database, because:
            - users actually prefer to see them in `affectation_ids`
            - it keeps the code the simplest
            
            This field helps:
            - in the `_constrain_is_affectable` (for launchs)
            - make rows readonly in `affectation_ids`
        """
        # avoid infinite loops on new records
        self = self.with_context(no_constrain_is_affectable=True)

        for affectation in self:
            field_siblings = affectation.mode + '_sibling_ids'
            siblings = affectation[field_siblings]._origin - affectation._origin

            # phase
            if affectation.mode == 'phase':
                affectation.is_affectable = bool(
                    affectation.quantity_affected != 0 or not (
                        affectation.quantity_remaining_to_affect == 0
                        and affectation.quantity_affected == 0
                ))
            # launch
            else:
                is_one_sibling_affected = any(siblings.mapped('affected'))
                affectation.is_affectable = not is_one_sibling_affected
    
    def _get_fields_active(self):
        return ['project_id', 'phase_id', 'launch_id', 'position_id', 'parent_id']
    @api.depends(lambda self: [x + '.active' for x in self._get_fields_active()])
    def _compute_active(self):
        """ Unactive affectations as soon as 1 parent record is unactive """
        fields = self._get_fields_active()
        for affectation in self:
            affectation.active = all(
                affectation[field].active for field in fields
                if affectation[field]
            )
    
    @api.depends('lot_id.sequence', 'phase_id.sequence', 'launch_id.sequence')
    def _compute_sequences(self, parent=None, group=None):
        if not parent or not group:
            phase_affectations, launch_affectations = self._split()
            phase_affectations ._compute_sequences(parent='lot_id',   group='phase_id')
            launch_affectations._compute_sequences(parent='phase_id', group='launch_id')
            return

        for affectation in self:
            affectation.sequence_parent_group = affectation[parent].sequence
            affectation.sequence_group = affectation[group].sequence

    @api.depends('parent_id.position_id', 'parent_id.sequence_position',)
    def _compute_child_fields(self):
        """ For launch affectations, compute fields of parent phase's affectation """
        _, launch_affectations = self._split()
        for child in launch_affectations:
            parent = child.parent_id
            child.phase_id = parent.phase_id
            child.position_id = parent.position_id
            child.sequence_position = parent.position_id.sequence
    
    @api.depends('parent_id.quantity_affected')
    def _compute_quantity_affected(self):
        """ In a different _compute method than previous fields,
            because of different `precompute` field
        """
        self = self.with_context(no_constrain_qty_affected=True)
        _, launch_affectations = self._split()
        for child in launch_affectations:
            child.quantity_affected = child.parent_id.quantity_affected

    #===== Quantities: compute & constrain =====#
    @api.onchange('quantity_affected')
    @api.constrains('quantity_affected')
    def _constrain_quantity_affected(self):
        """ Ensure `quantity_remaining_to_affect > 0`
            Only for phases
        """
        if self._context.get("no_constrain_qty_affected"):
            return
        
        phase_affectations, _ = self._split()
        if not phase_affectations: # optim
            return
        
        affectation = fields.first(
            phase_affectations.filtered(lambda x: x.quantity_remaining_to_affect < 0)
        )
        if affectation:
            raise exceptions.ValidationError(affectation._get_error_constrain_qty_affected())
    
    def _get_error_constrain_qty_affected(self):
        """ Can be inheritted """
        self.ensure_one()
        return _(
            "The affected quantity is higher than the one available in the project:\n\n"
            "Position: %(position)s\n"
            "Phase: %(phase)s\n"
            "Lot: %(lot)s\n"
            "Available total in the project: %(quantity_initially_available)s\n"
            "Affected quantity in the current item: %(quantity_affected)s\n"
            "Affected quantity on neighbors: %(quantity_siblings)s\n"
            "Overconsumption: %(overconsumption)s",
            position = self.position_id.name or '',
            phase = self.phase_id.name or '',
            lot = self.lot_id.name or '',
            quantity_initially_available = self.quantity_position,
            quantity_affected = self.quantity_affected,
            quantity_siblings = self.sum_affected_siblings,
            overconsumption = -1*self.quantity_remaining_to_affect,
        )
    
    @api.depends('quantity_affected', 'quantity_position', 'phase_sibling_ids.quantity_affected')
    def _compute_quantity_remaining_to_affect(self):
        """ Compute remaining qty to affect for phases affectation,
            in real-time (no database call)

            For phases only
        """
        phase_affectations, launch_affectations = self._split()
        launch_affectations.quantity_remaining_to_affect = 0
        for affectation in phase_affectations:
            affectation.quantity_remaining_to_affect = (
                affectation.quantity_position # initially available in the project
                - affectation.sum_affected_siblings # already affected
                - affectation.quantity_affected # currently affected
            )

    @api.depends('phase_sibling_ids.quantity_affected')
    def _compute_sum_affected_siblings(self):
        """ For phase only """
        for affectation in self:
            siblings = affectation.phase_sibling_ids._origin - affectation._origin
            affectation.sum_affected_siblings = sum(siblings.mapped('quantity_affected'))
