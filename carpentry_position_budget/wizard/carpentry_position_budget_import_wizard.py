# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
from odoo.tools import float_is_zero, float_compare

from odoo.addons.carpentry_position_budget.models.carpentry_position_budget_interface import EXTERNAL_DB_TYPE

from collections import defaultdict

class CarpentryPositionBudgetImportWizard(models.TransientModel):
    _name = "carpentry.position.budget.import.wizard"
    _description = "Carpentry Position Budget Import Wizard"
    _inherit = ['utilities.file.mixin', 'utilities.database.mixin']

    #===== Fields =====#
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        readonly=True,
        default=lambda self: self.env['project.default.mixin']._get_project_id()
    )
    import_file = fields.Binary(
        string='External DB file'
    )
    filename = fields.Char(
        string='Filename'
    )

    external_db_type = fields.Selection(
        selection=EXTERNAL_DB_TYPE,
        string='Type of external database',
        default=EXTERNAL_DB_TYPE[0][0],
        required=True,
    )
    encoding = fields.Selection(
        selection=[
            ('utf-8', 'UTF-8'),
            ('utf-16', 'UTF-16'),
            ('iso-8859-1', 'ISO-8859-1'),
        ],
        string='Encoding',
        default='utf-8',
        required=True,
    )

    # -- settings fields --
    budget_coef = fields.Integer(
        # integer for easy
        string='Budget coefficient (%)',
        default=100,
    )
    column_mode = fields.Selection(
        selection=[
            ('all', 'All columns'),
            ('ignore', 'All columns, but some listed'),
            ('only', 'Only listed columns, ignore all others')
        ],
        string='Import mode',
        default='all',
        required=True
    )
    column_ids = fields.Many2many(
        comodel_name='carpentry.position.budget.interface',
        relation='carpentry_position_budget_import_wizard_rel',
        string='External columns',
        domain="""[
            ('external_db_type', '=', external_db_type),
            ('active', '=', True),
        ]"""
    )


    #===== Button =====#
    def button_truncate_budget(self):
        self.project_id.position_budget_ids.unlink()

    def button_import(self):
        """ File management (unarchive if needed), database opening and call import router """
        if not self.import_file:
            raise exceptions.UserError(_('Please upload a file.'))
        
        db_models = ['Phases', 'ElevationGroups', 'a_elevations']
        filename, db_content, mimetype = self._uncompress(self.filename, self.import_file) # from `utilities.file.mixin`
        db_resource = self._open_external_database(filename, db_content, mimetype, self.encoding, db_models=db_models) # from `utilities.file.database`
        # dbsource is a record of `base.external.dbsource` (see module `server-env/base_external_dbsource`)
        
        self._run_import(db_resource)
        # self.with_context(import_budget_no_compute=True)._run_import(db_content, filename, mimetype)
        # self.with_context(import_budget_no_compute=False).project_id._budget_full_refresh()


    #===== Import logics =====#
    def _run_import(self, db_resource):
        """ Can be overriden to add import logic for other external database """

        if self.external_db_type == 'orgadata':
            self._run_orgadata_import(db_resource)


    def _get_interface(self, cols_external):
        """ Add any discovered cols of `cols_external` in active=False in
            `carpentry.position.budget.interface` and notify the users
            
            :arg cols_external:
                Cols of external database, which must corresponds
                 to `name` field of `carpentry.position.budget` records
            
            :return:
                Dict to pivot from external db col to `analytic_account_id`,
                 like: {col_name (str): analytic_account_id}
        """
        # Get known cols
        domain = [('external_db_type', '=', self.external_db_type)]
        Interface = self.env['carpentry.position.budget.interface'].with_context(active_test=False).sudo()
        interface_ids = Interface.search(domain)

        # Add new Orgadata cols if any
        cols_discovered = set(cols_external) - set(interface_ids.mapped('external_db_col'))
        vals_list = [{
            'external_db_col': col,
            'external_db_type': self.external_db_type,
        } for col in cols_discovered]
        if vals_list:
            Interface._create_default_and_ignore(vals_list)

        mapped_interface = {x.external_db_col: x.analytic_account_id.id for x in interface_ids.filtered('active')}
        return self._filter_interface_columns(mapped_interface)

    def _filter_interface_columns(self, mapped_interface):
        """ Apply `column_mode` by filtering `mapped_interface`:
            ignore or keep only columns listed in `column_ids`
        """
        if self.column_mode == 'all':
            return mapped_interface

        cols = set(self.column_ids.mapped('external_db_col')) & set(mapped_interface.keys())
        
        if self.column_mode == 'only':
            return {col: mapped_interface.get(col) for col in cols}
        elif self.column_mode == 'ignore':
            return {col: analytic for col, analytic in mapped_interface.items() if col not in cols}


    #===== Specific import logics =====#
    def _run_orgadata_import(self, db_resource):
        read_result = self._read_orgadata(db_resource)
        self._write_orgadata(*read_result)
    
    def _read_orgadata(self, db_resource):
        # Get `carpentry.position`
        # ALY (2024-06-26) :
        # a. removed 'SystemName': 'range' which is in 'Elevations' but missing in 'a_elevations'
        # b. ElevationID and ElevationGroupId in 'Elevations' -> elevationId and elevationGroupId in 'a_elevations'
        sql = """
            SELECT
                a_elevations.elevationId,
                a_elevations.Name,
                a_elevations.Amount,
                a_elevations.Area,
                a_elevations.SystemName,
                a_elevations.AutoDescription,
                Phases.PhaseID,
                Phases.Name AS PhaseName
            FROM a_elevations
            INNER JOIN ElevationGroups
                ON ElevationGroups.ElevationGroupID = a_elevations.elevationGroupId
            INNER JOIN Phases
                ON Phases.PhaseID = ElevationGroups.PhaseId
        """
        cols_mapping = {
            'elevationId': 'external_id',
            'Name': 'name',
            'Amount': 'quantity',
            'Area': 'surface',
            'SystemName': 'range',
            'AutoDescription': 'description',
            # Lots fields, will be removed from Elevations
            'PhaseID': 'external_id_lot',
            'PhaseName': 'name_lot',
        }
        Elevations = self._read_db(db_resource, sql, cols_mapping)

        # 3. Get `carpentry.position.budget`
        # cols of `a_elevations` are rows of carpentry Interface `carpentry.position.budget.interface`
        # don't pass any `cols_mapping`: one might discover new Orgadata columns
        Budgets = self._read_db(db_resource, "SELECT * FROM a_elevations")
        self._close_db(db_resource) # close connection with Orgadata mssql db

        return Elevations, Budgets

    def _write_orgadata(self, Elevations, Budgets):
        # 1. Get Odoo's budget column, linked to external DB one
        cols_orgadata = [x for x in Budgets[0]] if Budgets else []
        mapped_interface = self._get_interface(cols_orgadata)

        # 2. Create `carpentry.group.lot` and set Elevation's `lot_id`
        domain = [('project_id', '=', self.project_id.id)]
        Lot = self.env["carpentry.group.lot"]
        mapped_lots = {x.name: x for x in Lot.search(domain)}
        for elevation in Elevations:
            lot = mapped_lots.get(elevation["name_lot"])
            if not lot:
                lot = Lot.create({
                    "project_id": self.project_id.id,
                    "name": elevation["name_lot"],
                    "external_id": elevation["external_id_lot"],
                })
                mapped_lots[lot.name] = lot
            elevation.update({
                "project_id": self.project_id.id,
                "lot_id": lot.id,
            })
            elevation.pop("name_lot")
            elevation.pop("external_id_lot")
        
        # 3. Import carpentry.position
        positions = self.env['carpentry.position'].search(domain)
        primary_keys = ["name"]
        position_ids = self._import_data(Elevations, positions, primary_keys)
        mapped_positions = {x.external_id: x.id for x in position_ids}

        # 4. Import carpentry.position.budget
        precision = self.env['decimal.precision'].precision_get('Product Price')
        # Sum-group budget of active columns, in the format for `carpentry_position_budget._erase_budget()`
        mapped_budget = defaultdict(float)
        for elevation in Budgets:
            position_id_ = mapped_positions.get(str(elevation.get('elevationId')))
            assert position_id_
            for col, analytic_account_id_ in mapped_interface.items():
                amount_unitary = elevation.get(col, 0.0)
                if not float_is_zero(float(amount_unitary), precision_digits=precision):
                    mapped_budget[(position_id_, analytic_account_id_)] += amount_unitary
        
        # 5. Create if new, write/erase if existing, delete if not touched
        # and apply `budget_coef` to amount
        vals_list_budget = [{
            'project_id': self.project_id.id,
            'position_id': key[0],
            'analytic_account_id': key[1],
            'amount_unitary': amount_unitary * self.budget_coef/100
        } for key, amount_unitary in mapped_budget.items()]
        position_ids.position_budget_ids._erase_budget(vals_list_budget)
