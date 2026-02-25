# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _

class BaseModel(models.AbstractModel):
    """ To target parent model of child model using analytics
        Example: on PO, detects changes of `project_id` and cascade it
        to `order_line` because it has `analytic_distribution` field
    """
    _inherit = 'base'

    def write(self, vals):
        # before `write`
        if 'project_id' in vals:
            self._cascade_project_to_line_analytic_distrib(vals['project_id'])
        
        return super().write(vals)

    def _get_fields_related_with(self, looked_fields):
        """ Return every relational field of this model having `field`
            in the model in relation

            Exemple: when called from `purchase.order`, it returns `['order_line']`
        """
        fields = []
        for field, description in self.fields_get(attributes=['relation']).items():
            model_child = description.get('relation')
            if model_child and all(hasattr(self.env[model_child], field) for field in looked_fields):
                fields.append(field)
        return fields

    # @api.onchange('project_id') # must be set in child modules
    def _cascade_project_to_line_analytic_distrib(self, new_project_id=None):
        field_lines = self._get_fields_related_with(
            ['analytic_distribution', '_synch_project_analytic_distrib_from_record']
        )

        if not field_lines:
            return
        
        onchange = bool(new_project_id == None)
        if not onchange: # from `write()`
            new_project = self.env['project.project'].browse(new_project_id)

        for parent in self:
            if onchange:
                new_project = parent.project_id
            
            for field_line in field_lines:
                parent[field_line]._synch_project_analytic_distrib_from_record(new_project)

class AnalyticMixin(models.AbstractModel):
    """
        Designed for `line`-type model (like `account_move_line`)
        Update lines's analytic:
        - Cascading record's project (on some events) - only for project plan
        - Forcing analytic to INTERNAL project & budget - both project & budget plan
    """
    _inherit = ['analytic.mixin']

    #====== CRUD ======#
    def write(self, vals):
        """ Simulate `onchange` """
        res = super().write(vals)

        # 1. after `write()`
        if 'analytic_distribution' in vals and not self._context.get('has_enforced_aac_distrib'):
            self._enforce_internal_analytic()
        
        return res
    
    def _compute_analytic_distribution_carpentry(self):
        """ **TO BE CALLED AT THE END** of `_compute_analytic_distribution`
            in inheriting model
            (because `_compute_analytic_distribution` is fully overriden in them,
            without call to super())
        """
        records = self.filtered(lambda self: self._filter_can_analytic())
        for record in records:
            project = record._get_project_from_parent()._origin
            record._synch_project_analytic_distrib_from_record(project)

        # must be called to enforce other analytics than project
        records._enforce_internal_analytic()

    #====== Compute ======#
    def _synch_project_analytic_distrib_from_record(self, new_project):
        """ Cascade `project_id` of the parent record (if changed)
            to the line's analytic distribution 
        """
        records = self.filtered(lambda self: self._filter_can_analytic())
        if not records: # early-quit optim
            return
        
        self = self.with_context(has_enforced_aac_distrib=True)
        mapped_projects_analytics = self._get_mapped_projects_analytics()
        replace_dict_enforce = self._get_enforce_dict_analytic_internal()
        
        for record in records:
            new_aac_id = new_project.analytic_account_id.id
            if record._should_enforce_internal_analytic():
                new_aac_id = replace_dict_enforce.get(new_aac_id) or new_aac_id

            record._cascade_parent_project_to_analytic(new_aac_id, mapped_projects_analytics)

    def _get_mapped_projects_analytics(self):
        """ Get all analytic accounts of projects """
        data = self.env['project.project'].sudo().search_read(
            domain=[('analytic_account_id', '!=', False)],
            fields=['analytic_account_id']
        )
        return {x['analytic_account_id'][0]: x['id'] for x in data}

    def _get_analytics_projects(self, mapped_projects_analytics):
        """ Return the only analytics accounts from `analytic_distribution`
            that are related to projects
        """
        self.ensure_one()
        projects_analytics = set()
        if self.analytic_distribution:
            projects_analytics = (
                set(int(x) for x in self.analytic_distribution.keys())
                & set(mapped_projects_analytics.keys())
            )
        return projects_analytics

    def _cascade_parent_project_to_analytic(self, new_aac_id, mapped_projects_analytics):
        """ Cascade record's project to line:
            1. Remove all project-related analytics on the line
            2. Set up the cascaded project
        """
        self.ensure_one()
            
        distrib = self.analytic_distribution or {}
        for aac_id in mapped_projects_analytics.keys():
            if str(aac_id) in distrib:
                distrib.pop(str(aac_id))

        if new_aac_id:
            distrib |= {new_aac_id: 100}

        self.analytic_distribution = distrib


    #====== Helper methods ======#
    def _get_project_from_parent(self):
        """ Compute `project_id` from the parent model """
        if self: self.ensure_one()
        
        for field in self._get_fields_related_with(['project_id']):
            project_id = self[field].project_id
            if project_id:
                return project_id
        return self.env['project.project']
    
    def _get_replaced_analytic_distribution(self, replace_dict):
        """ Replaces keys in `self.analytic_distribution` as per `replace_dict`
            :arg replace_dict: {old_analytic_id -> new_analytic_id}
        """
        new_dict = {}
        if self.analytic_distribution:
            for account_id, percent in self.analytic_distribution.items():
                new_account_id = replace_dict.get(int(account_id), int(account_id))
                new_dict[new_account_id] = new_dict.get(new_account_id, 0.0) + percent
        return new_dict

    #====== Internal analytics enforcment ======#
    @api.onchange('analytic_distribution')
    def _enforce_internal_analytic(self):
        """ Forces analytic (e.g. to *internal* project for all *storable* lines) """
        # perf early-quits
        if self._context.get("has_enforced_aac_distrib"):
            return
        
        records = self.filtered(lambda self:
            self._filter_can_analytic() and self._should_enforce_internal_analytic()
        )
        if not records:
            return
        records = records.with_context(has_enforced_aac_distrib=True)
        
        replace_dict_enforce = self._get_enforce_dict_analytic_internal()
        for record in records:
            record.analytic_distribution = record._get_replaced_analytic_distribution(
                replace_dict_enforce
            )
    
    def _should_enforce_internal_analytic(self):
        """ **Can be inheritted**
            Under what conditions the analytic should be forced with
            Forces analytic of *internal* project for all *storable* lines
        """
        return False
    
    def _filter_can_analytic(self):
        """ For `account.move.line`:
            - wait for `account_id` to be set to cascade/force analytic
            - don't cascade/force if account's analytic policy is 'never'
              (see OCA module 'account_analytic_required')
        """
        return (
            # if OCA module installed & `account_id` field available
            not hasattr(self.env['account.account'], "analytic_policy")
            or not hasattr(self, "account_id")
            # or self.account_id and self.account_id.analytic_policy != "never"
        )
    
    def _get_enforce_dict_analytic_internal(self):
        """ [For inheritance] Returns a static `replace_dict` to be applied in
             `_enforce_internal_analytic`
            Rule below replaces any projects by *INTERNAL project*
        """
        Project = self.env['project.project'].sudo().with_context(active_test=False)
        sr_result = Project.search_read(
            domain=[('analytic_account_id', '!=', False)],
            fields=['analytic_account_id']
        )
        internal_aac_id = self.company_id.internal_project_id.analytic_account_id.id
        return {
            project_aac_id: internal_aac_id
            for project_aac_id in [x['analytic_account_id'][0] for x in sr_result]
            if project_aac_id != internal_aac_id
        }
