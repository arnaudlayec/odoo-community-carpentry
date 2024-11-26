# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.addons.carpentry_planning_task_need.models.project_task import XML_ID_NEED

class CarpentryNeedFamily(models.Model):
    _name = 'carpentry.need.family'
    _inherit = ['project.default.mixin']
    _description = 'Need family'

    name = fields.Char(
        string='Need family',
        required=True
    )
    need_ids = fields.Many2many(
        comodel_name='carpentry.need',
        relation='carpentry_need_family_rel',
        column1='family_id',
        column2='need_id',
        string='Needs templates',
        domain="[('project_id', '=', project_id)]",
        required=True
    )
    launch_ids = fields.Many2many(
        comodel_name='carpentry.group.launch',
        relation='carpentry_need_rel_launch',
        column1='need_id',
        column2='launch_id',
        string='Launches'
    )
    parent_type_id = fields.Many2one(
        # defined by 1st need added in the family
        # cf. constrain to prevent mixing different `parent_type_id` in same family
        # eg. "Need (Method)"
        comodel_name='project.type',
        string='Need Type',
        related='need_ids.type_id.parent_id',
        store=True
    )
    role_id = fields.Many2one(
        comodel_name='project.role',
        related='parent_type_id.role_id',
    )
    # my_role = fields.Boolean(
    #     # (!) actually doesn't work but keep it, in case of magic idea
    #     # only for search filter
    #     compute=True, # required else `search` is ignored
    #     search='_search_my_role'
    # )

    _sql_constraints = [(
        'name_unique',
        'UNIQUE (name, project_id)',
        'A Need Family with this name already exists in the project.'
    )]
    
    #===== Constrains =====#
    @api.constrains('need_ids')
    def _constrains_need_ids(self):
        """ Unique `type_id.parent_type_id` in same Need Family """
        for family in self:
            if len(family.need_ids.type_id.parent_id.ids) > 1:
                raise exceptions.ValidationError(
                    _('A Need Family cannot mix Needs of different type.')
                )

    #====== CRUD =====#
    @api.model_create_multi
    def create(self, vals_list):
        result = super().create(vals_list)
        self._reconcile_with_tasks(self.project_id.ids) # after .create()
        return result

    def unlink(self):
        need_ids, project_ids = self.need_ids, self.project_id.ids
        result = super().unlink()
        self._reconcile_with_tasks(project_ids) # reconcile
    
    def write(self, vals):
        result = super().write(vals)
        self._reconcile_with_tasks(self.project_id.ids) # after .write()
        return result

    #===== Compute =====#
    # @api.model
    # def _search_my_role(self, operator, value):
    #     """ Filter 'My Role':
    #          1. On Need Families linked to the current user, via role assignation (e.g. project manager, field manager)
    #          2. Or all Need Families, if user is not linked to any Need Family (e.g. Administrator)
    #         (!) A user affected to role A on project 1 and role B on project 2 will see Need Families of
    #             project 1's Role B and project 2's Role A
    #     """
    #     return [
    #         ('project_id.assignment_ids.user_id', '=', self.env.uid), # user affected on this project
    #         ('role_id.assignment_ids.user_id', '=', self.env.uid) # user affected to this role (on any project)
    #     ]

    #===== Logics =====#
    def _reconcile_with_tasks(self, project_ids_):
        """ Assess differences between existing tasks of type 'need' *and* needs in launches (via needs family),
            and create any missing tasks or delete any tasks from removed needs
            (!) Converted needs (i.e. fix deadline) are out of any reconcialition
            
            Copy logic:
             * 1 need translate into 1 task per launch
             * Need Families carry the affectation of needs to launches...
             * 1 need can be affected through several Need Families to same or different
                launches : create only 1 task per launch per need
            => computation must always be done at project level
        """
        # Computation considers archived tasks,
        # (e.g. a generated need we actually don't want on 1 launch)
        self = self.with_context(active_test=False)

        # 1. Define existing & target
        # existing
        domain_task = [
            ('root_type_id', '=', self.env.ref(XML_ID_NEED).id),
            ('project_id', 'in', project_ids_)
        ]
        task_ids = self.env['project.task'].search(domain_task)
        existing_tuples = set([
            (task.launch_ids[0], task.need_id) # [0] because tasks of type need have only 1 launch
            for task in task_ids
        ])

        # target
        domain_family = [('project_id', 'in', project_ids_)]
        family_ids = self.env['carpentry.need.family'].search(domain_family)
        target_tuples = set([
            (launch, need)
            for family in family_ids
            for launch in family.launch_ids
            for need in family.need_ids
        ])

        # 2. Delete tasks if a need were removed (only non-converted need)
        to_delete = task_ids.filtered(lambda task: (
            (task.launch_ids[0], task.need_id) in (existing_tuples - target_tuples)
        ))
        to_delete.with_context(force_delete=True).unlink()

        # 3. Create tasks from added need or launch to (a) family(ies)
        model_id_ = self.env['ir.model'].sudo().search([('model', '=', 'project.type')]).id
        stage_id_ = self.env['project.task.type'].sudo().search([('fold', '=', False)], limit=1).id
        self.env['project.task'].create([
            need._convert_to_task_vals(launch.id, model_id_, stage_id_)
            for launch, need in (target_tuples - existing_tuples)
        ])
