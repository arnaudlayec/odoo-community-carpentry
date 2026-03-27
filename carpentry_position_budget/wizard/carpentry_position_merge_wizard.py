# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, exceptions, _

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
            position_ids_to_merge = Position.search(domain_same_name)
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

    #===== Action =====#
    def button_merge(self):
        """ Merge logic:
            * sum-add the position's qty
            * avg-weight the budget (barycentre-like), meaning:
                new unitary budget (of 1 type of budget) = SUM(position qty * position unitary budget) / SUM(position qties)
                INCLUDING the target position in the AVG

            `external_id` is cleaned on `position_id_target` so that the merge
            operation is not erase in case of a new import
        """
        # Checks before merge
        target, sources = self.position_id_target, self.position_ids_to_merge
        if not sources.ids:
            raise exceptions.UserError(_('No duplicates to merge.'))

        # Calculation
        # (!) be careful not to write `target.quantity` before weighted_average
        sum_qty = target.quantity + sum((sources - target).mapped('quantity'))
        vals_list_budget = self._calculate_weighted_average_budget(sources, target, sum_qty)
        # Write
        target.position_budget_ids._erase_budget(vals_list_budget)
        target.quantity = sum_qty
        sources.affectation_ids.unlink() # Unlink affectations (hard to merge)

        # Clean: unlink with external DB and remove merged positions
        target.external_id = False
        (sources - target).unlink()

    def _calculate_weighted_average_budget(self, sources, target, sum_qty):
        """ Calculate weighted average SUM(budget*qty)/sum_qty
            :return: same `vals_list_budget` format
                     than carpentry_position_budget._write_budget()
        """
        # make sure values are up-to-date in database
        sources.flush_recordset(['quantity'])
        sources.position_budget_ids.flush_recordset(['position_id', 'analytic_account_id', 'amount_unitary'])

        self.env.cr.execute("""
            SELECT
                budget.analytic_account_id,
                SUM(budget.amount_unitary * position.quantity)
            FROM carpentry_position_budget AS budget
                INNER JOIN carpentry_position AS position ON position.id = budget.position_id
            WHERE position.id IN %s
            GROUP BY budget.analytic_account_id
        """, (tuple(sources.ids),))

        return [{
            'position_id': target.id,
            'analytic_account_id': row[0],
            'amount_unitary': row[1] / sum_qty
        } for row in self.env.cr.fetchall()]
