# -*- coding: utf-8 -*-

from odoo import models, fields, api, _, exceptions

class CarpentryAffectationMixin(models.AbstractModel):
    """ Fields & methods for Carpentry Groups (projects, lots, phases, launchs)
         to handle affectations.
    """
    _name = "carpentry.affectation.mixin"
    _description = "Group Mixin for Affectations"
    _carpentry_field_parent_group = None
    _carpentry_field_record = None
    _carpentry_field_affectations = None

    #===== Model's methods =====#
    def _group_field(self):
        """ :return: 'project_id', 'lot_id', 'phase_id' or 'launch_id' """
        return self._name.split('.')[-1] + '_id'
    
    def _parent_group_field(self):
        """ :return:
            for phase: 'lot_id'
            for launch: 'phase_id'
        """
        return self._carpentry_field_parent_group or self._raise_not_supported()
    
    def _record_field(self):
        """ :return:
            for phase: 'position_id'
            for launch: 'parent_id'
        """
        return self._carpentry_field_record or self._raise_not_supported()

    def _affectations_field(self):
        """ :return:
            for lots: 'position_ids'
            for phases: 'affectation_ids'
        """
        if not self._carpentry_field_affectations:
            self._raise_not_supported()
        return self._carpentry_field_affectations
    
    def _raise_not_supported(self):
        raise exceptions.UserError(_("Operation not supported"))

    #===== Fields methods =====#
    def name_get(self):
        res = super().name_get()
        if self._context.get('display_remaining_affectation_count'):
            res = self._name_get_append_remaining_affectation(res)
        return res
    def _name_get_append_remaining_affectation(self, res):
        """ Appends number of remaining affectations available
            when displayed as of *parent group* in a child group form
        """
        domain = [('id', 'in', [id for (id, _) in res])]
        mapped_remaining_qties = {
            x['id']: x['quantity_remaining_to_affect']
            for x in self.search_read(domain, fields=['quantity_remaining_to_affect'])
        }

        res_updated = []
        for id, name in res:
            remaining_qty = mapped_remaining_qties.get(id, 0)
            suffix = (' ({})' . format(remaining_qty)) if remaining_qty > 0 else ''
            res_updated.append((id, name + suffix))
        
        return res_updated

    #===== Fields =====#
    affectation_ids = fields.One2many(
        comodel_name='carpentry.affectation',
        string='Affectations',
        inverse_name=None, # to be set on inheriting model
    )
    position_ids = fields.One2many(
        comodel_name='carpentry.position',
        string='Positions',
        compute='_compute_position_ids',
    )
    # groups
    lot_ids = fields.One2many(
        comodel_name='carpentry.group.lot',
        string='Lots',
        compute='_compute_lot_ids',
        domain="[('project_id', '=', project_id)]",
    )
    phase_ids = fields.One2many(
        comodel_name='carpentry.group.phase',
        string='Phases',
        compute='_compute_phase_ids',
        domain="[('project_id', '=', project_id)]",
    )
    launch_ids = fields.One2many(
        comodel_name='carpentry.group.launch',
        string='Launchs',
        compute='_compute_launch_ids',
        domain="[('project_id', '=', project_id)]",
    )
    # count
    position_count = fields.Integer(
        string='Positions Count',
        group_operator='sum',
        compute='_compute_position_count',
    )
    quantity_remaining_to_affect = fields.Integer(
        string='Remaining to affect',
        compute='_compute_quantity_remaining_to_affect',
    )
    # ui fields
    readonly_affectation = fields.Boolean(
        compute='_compute_readonly_affectation',
    )
    readonly_parent_group = fields.Boolean(
        compute='_compute_readonly_parent_group',
    )
    
    #===== Constraints =====#
    _sql_constraints = [(
        "name_per_project",
        "UNIQUE (name, project_id)",
        "This name already exists within the project."
    )]

    #====== Compute ======#
    # --- ui ---
    @api.depends('phase_ids', 'lot_ids')
    def _compute_readonly_affectation(self):
        """ Way to ask the users to save before continuing,
             so that `affectations_ids` is properly recomputed
             before any further user actions
            
            Logics:
            1. At page load, self == self._origin
            2. At any fields changes, self == <NewId ...>
        """
        self.readonly_affectation = (
            self.phase_ids._origin != self._origin.phase_ids
            or self.lot_ids._origin != self._origin.lot_ids
        )
    @api.depends('affectation_ids')
    def _compute_readonly_parent_group(self):
        self.readonly_parent_group = (
            self.affectation_ids != self._origin.affectation_ids
        )
    def _get_true_if_modified(self):
        """ Return `True` if any fields is changed,
            but `False` if new,
            so that warning banner is not displayed when
            creating new (phase|launch)
        """
        return self._origin.exists() and not bool(self == self._origin)

    # --- pseudo-related fields ---
    @api.depends('affectation_ids', 'affectation_ids.position_id')
    def _compute_position_ids(self):
        for group in self:
            group.position_ids = group.affectation_ids.position_id
    @api.depends('affectation_ids', 'affectation_ids.lot_id')
    def _compute_lot_ids(self):
        for group in self:
            group.lot_ids = group.affectation_ids.lot_id
    @api.depends('affectation_ids', 'affectation_ids.phase_id')
    def _compute_phase_ids(self):
        for group in self:
            group.phase_ids = group.affectation_ids.phase_id
    @api.depends('affectation_ids', 'affectation_ids.launch_id')
    def _compute_launch_ids(self):
        for group in self:
            group.launch_ids = group.affectation_ids.launch_id

    # --- quantities/counts ---
    @api.depends(lambda self:
        [self._carpentry_field_affectations + '.quantity_remaining_to_affect']
        if self._carpentry_field_affectations
        else []
    ) 
    def _compute_quantity_remaining_to_affect(self):
        """ For `_name_get_append_remaining_affectation`
            It's the remaining:
            - Positions to affect (for Lots)
            - Affectations to affect (for Phases)

            :self: lots or phases
        """
        if self._name == 'carpentry.group.launch':
            self.quantity_remaining_to_affect = 0
            return
        
        field = self._affectations_field() # 'position_ids' or 'affectation_ids'
        _lambda = self._get_filter_remaining_affectations(optimized=True)
        for group in self:
            group.quantity_remaining_to_affect = len(group[field].filtered(_lambda))

    @api.depends(
        'position_ids',
        'affectation_ids.quantity_affected',
    )
    def _compute_position_count(self):
        """ Number of positions related to the group
            - for Project and Lot: count related in `carpentry.position` (easy)
            - for Phases & Launchs: sum the `quantity_affected` in `carpentry.affectation`
        """
        field = self._group_field()
        domain = [(field, 'in', self._origin.ids)]
        if any(x == self._name for x in ('carpentry.group.lot', 'project.project')):
            model = 'carpentry.position'
            count = 'position_count:count(id)'
        elif any(x == self._name for x in ('carpentry.group.launch', 'carpentry.group.phase')):
            model = 'carpentry.affectation'
            count = 'position_count:sum(quantity_affected)'
            domain += [('affected', '=', True)]
        else:
            self.position_count = 0
            return
        
        rg_result = self.env[model].read_group(domain=domain, groupby=[field], fields=[count])
        mapped_count = {x[field][0]: x['position_count'] for x in rg_result}
        for group in self:
            group.position_count = mapped_count.get(group.id, 0)

    #===== Affectations provisioning =====#
    def _provision_affectations(self, records):
        """ Triggered back-end from:
            - for Phases: `carpentry.position`     | Trigger: position creation
            - for Launchs: `carpentry.affectation` | Trigger: `quantity_affected` != 0 of a phase affectation

            :arg `self`:  phases or launchs
            :arg records: positions (for phases), phase_affectations (for launch)
        """
        parent_groups = self._parent_group_field() + 's' # lot_ids, phase_ids
        _lambda = self[parent_groups]._get_filter_remaining_affectations()
        return self._create_affectations(records.filtered(_lambda))

    def _create_affectations(self, records):
        """ Transform:
            *Phases*:  Lots Positions      -> in Phases' affectations
            *Launchs*: Phases affectations -> in Launchs' affectations
            
            Called from:
            - Back-end: `_provision_affectations`
            - User action: both: `_inverse_[lot|phase]_ids`  | Trigger: user action (add/remove lots or phases)

            :arg `self`:  phases or launchs
            :arg records: positions (for phases), phase_affectations (for launch)
        """
        group_field = self._group_field()
        record_field = self._record_field()
        
        # prevent duplicates
        mode = self._name.replace('carpentry.group.', '')
        Affectation = self.env['carpentry.affectation']
        existing_ids = Affectation.search([
            ('mode', '=', mode),
            (group_field,  'in', self._origin.ids),
            (record_field, 'in', records._origin.ids),
        ])
        mapped_existings = [(x[group_field].id, x[record_field].id) for x in existing_ids]

        # create
        vals_list = [
            group._get_affectation_vals(record)
            for group in self
            for record in records
            if not (group.id, record.id) in mapped_existings
        ]

        return Affectation.create(vals_list)
    
    def _get_affectation_vals(self, record):
        """ Precomputed fields are not here
            :arg `self`:   phase or launch
            :arg `record`: position or phase affectation
        """
        mode = self._name.replace('carpentry.group.', '')
        if mode not in ('phase', 'launch'):
            self._raise_not_supported()

        position = record if mode == 'phase' else record.position_id
        phase    = self   if mode == 'phase' else record.phase_id
        
        vals = {
            'mode': mode,
            'project_id': position.project_id.id,
            'position_id': position.id,
            'lot_id': position.lot_id.id,
            'phase_id': phase.id,
            'sequence_position': position.sequence,
            'sequence_group': self.sequence,
            'sequence_parent_group': record[self._parent_group_field()].sequence,
            'active': all([
                position.active,
                position.project_id.active,
                position.lot_id.active,
                phase.active,
                self.active, # can be launch
                record.active, # can be phase affectation
            ]),
        }
        
        if mode == 'launch':
            vals |= {
                'launch_id': self.id,
                'parent_id': record.id,
                'quantity_affected': record.quantity_affected,
            }

        return vals
    
    def _inverse_parent_group_ids(self):
        """ On user trigger, provision `affectation_ids` of a (phase|launch),
             according to its selected (lots|phases)

            *ADD*
                When user choose a new (Lot|Phase), transform the selected:
                (for Phase):  Lots positions to Phases affectations
                (for Launch): Phases affectations to Launchs affectations
            
            *DELETION*
                When user unchecks a (lot|phase):
                (for Phase):  remove Lots Positions from Phase' affectations
                (for Launch): remove Phase affectations from Launch' affectations
            
            *WARNING*
                The main issue here is to leave alone the affectations
                of the (lots|phases) which remained idle/untouched, so
                not to erase the previous user inputs in (phases|launchs)
                affectations
        """
        parent_group = self._parent_group_field() # lot_id, phase_id
        parent_groups = parent_group + 's' # lot_ids, phase_ids
        
        for group in self:
            selected_parent_groups = group[parent_groups]._origin # user selection (lots or phase)
            existing_parent_groups = group.affectation_ids[parent_group]._origin
            new_parent_groups = selected_parent_groups - existing_parent_groups

            # 1. Unlink affectations of removed parent group
            to_unlink = group.affectation_ids.filtered(lambda x:
                x[parent_group]._origin not in selected_parent_groups
            )
            to_unlink.unlink()
            
            # 2. Add **affectable** affectations of **added** parent group (only)
            if new_parent_groups:
                affectation_field = new_parent_groups._affectations_field()
                _lambda = new_parent_groups._get_filter_remaining_affectations()
                remaining_affectations = new_parent_groups[affectation_field].filtered(_lambda) # positions or phase affectations

                if remaining_affectations:
                    group._create_affectations(remaining_affectations)
        
        # (!) required here to recompute `phase.lot_ids` and `launch.phase_ids`
        # so they don't stick to user inputs (which may not be the database reality)
        self.invalidate_recordset([parent_groups])

    def _get_filter_remaining_affectations(self, optimized=False):
        """ :arg self: lot or phase
            :option `optimized`: if True: filtering is harsh,
                                  for name_search of (lots|phases)
                                 if False: for provisioning
            :return: a lambda function for filtering:
                - For lots: positions with not fully affected
                - For phases: phase affectations affectable (qty > 0 or qty_remaining > 0)
                               and not already taken by another launch
        """
        if self._name == 'carpentry.group.lot':
            if optimized:
                _lambda = lambda x: x.quantity_remaining_to_affect != 0
            else:
                _lambda = lambda x: x.quantity != 0
        elif self._name == 'carpentry.group.phase':
            if optimized:
                _lambda = lambda x: (
                    x.quantity_affected != 0 and not any(x.children_ids.mapped('affected'))
                )
            else:
                # only add to launch the phase affectation with qty > 0
                _lambda = lambda x: x.quantity_affected != 0
        else:
            self._raise_not_supported()
        return _lambda

    #===== Buttons =====#
    def save_refresh(self):
        self.readonly_affectation = False
        self.readonly_parent_group = False
    