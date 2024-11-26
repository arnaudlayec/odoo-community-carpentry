# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, exceptions, _
from collections import defaultdict

class PositionMerge(models.TransientModel):
    _name = "carpentry.position.merge.wizard"
    _description = "Position Merge"
    _inherit = ['project.default.mixin']

    #===== Fields' methods =====#
    @api.model
    def default_get(self, field_names):
        """ Wizard opening, 2 opposite workflow:
            a) if 1 position selected (i.e. button tree row): consider it as *the target*
                and search conflicting positions to be merged to this one
            b) if several: consider them as *the to-be-merged* and let the user choose the target
        """
        defaults_dict = super().default_get(field_names)

        Position = self.env['carpentry.position']
        position_ids_selected = Position.browse(self._context.get('active_ids', []))

        # from button in tree's row
        if len(position_ids_selected.ids) == 1:
            defaults_dict['position_id_target'] = position_ids_selected
            # pre-fill to_merge list by the positions on conflicting name with this one
            domain_same_name = [
                ('project_id', '=', position_ids_selected.project_id.id),
                ('name', 'ilike', position_ids_selected.name)
            ]
            position_ids_to_merge = Position.search(domain_same_name) - position_ids_selected
        else:
            position_ids_to_merge = position_ids_selected
        
        defaults_dict.update({
            'project_id': position_ids_selected.project_id.id,
            'position_ids_to_merge': [Command.set([x.id for x in position_ids_to_merge])],
        })

        return defaults_dict
    
    #===== Fields methods =====#
    # `project_id` from `project.default.mixin`
    position_ids_to_merge = fields.Many2many(
        comodel_name='carpentry.position',
        string='Duplicates to be merged',
        required=True,
        domain="[('project_id', '=', project_id)]"
    )
    position_id_target = fields.Many2one(
        comodel_name='carpentry.position',
        string='Position to keep',
        required=True,
        domain="[('id', 'in', position_ids_to_merge)]"
    )

    #===== Constrain =====#
    @api.constrains('position_ids_to_merge')
    def _constrain_no_affectation(self):
        """ Ensure positions to be merged (i.e. deleted) have no affectations """
        domain = self.position_ids_to_merge._get_domain_affect(group='record')
        count = self.env['carpentry.group.affectation'].sudo().search_count(domain)

        if count > 0:
            raise exceptions.UserError(_(
                'Please remove all the affectations to phases and launches of'
                ' the positions to merge before merging.'
            ))

    #===== Onchange =====#
    @api.onchange('position_ids_to_merge', 'position_id_target')
    def _clean_fields(self):
        """ Clean the `to merge` list of the `target` position """
        for wizard in self:
            wizard.position_ids_to_merge = [Command.unlink(wizard.position_id_target.id)]
    
    #===== Action =====#
    def button_merge(self):
        """ Merging logics: is to sum-add budgets of the `to merge` to the `target`,
            with `write()` or `create()` in 

            `external_db_id` is cleaned on `position_id_target` so that the merge
            operation is not erase in case of a new import
        """
        # Checks before merge
        self._clean_fields()
        if not self.position_ids_to_merge.ids:
            raise exceptions.UserError(_('No duplicates to merge.'))
        self._constrain_no_affectation()

        # Sumgroup the budgets to merge
        domain = [('position_id', 'in', self.position_ids_to_merge.ids)]
        budget_ids_to_merge = self.env['carpentry.position.budget'].search(domain)
        vals_list_budget = budget_ids_to_merge._to_vals(
            replace_keys={'position_id': self.position_id_target.id}
        )
        self.position_id_target.position_budget_ids._add_budget(vals_list_budget)
        self.position_id_target.external_db_id = False

        # delete duplicates
        self.position_ids_to_merge.unlink()
