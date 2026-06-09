# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _, Command
import io, openpyxl, os, logging
_logger = logging.getLogger(__name__)

EXTERNAL_DB_TYPE = [
    ('orgadata', 'Orgadata')
]
SEPARATOR_COLOR = '-' # example: "174170-RAL7016 Sat 30"

class CarpentryMrpImportWizard(models.TransientModel):
    _name = "carpentry.mrp.import.wizard"
    _description = "Carpentry MRP Import Wizard"
    _inherit = ['utilities.file.mixin', 'utilities.database.mixin']

    REPORT_FILENAME = 'report/report_mrp_component.xlsx'

    #===== Fields methods =====#
    def default_get(self, fields):
        """Set `production_id` or `picking_id` from action's context"""
        vals = super().default_get(fields)

        if any(x in fields for x in ["production_id", "picking_id"]):
            field_name = {
                "mrp.production": "production_id",
                "stock.picking": "picking_id",
            }
            res_model = self._context.get("active_model")
            record = (res_model in field_name) and self.env[res_model].browse(
                self._context.get("active_id")
            )
            if record:
                vals[field_name[res_model]] = record.id

        return vals

    #===== Fields =====#
    production_id = fields.Many2one(
        comodel_name='mrp.production',
        string='Manufacturing Order',
        readonly=True,
    )
    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Picking',
        readonly=True,
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

    # imported data
    product_ids = fields.One2many(comodel_name='product.product', store=False, readonly=True)
    # ALY, 2025-05-15 : don't import price from Orgadata
    # supplierinfo_ids = fields.One2many(comodel_name='product.supplierinfo', store=False, readonly=True)

    # report
    move_raw_ids = fields.One2many(related='production_id.move_raw_ids')
    move_ids = fields.One2many(related="picking_id.move_ids")
    ignored_product_ids = fields.One2many(comodel_name='product.product', store=False, readonly=True)


    #===== Helper methods =====# 
    def _get_order(self):
        return self.production_id or self.picking_id

    def _get_moves(self):
        return self.move_raw_ids or self.move_ids

    #===== Buttons =====#
    def button_truncate(self):
        self._get_moves().unlink()

        # mo moves to cancel when unlinking its components
        # => make it back to draft
        if self.production_id:
            mo = self.production_id
            mo.move_finished_ids.state = 'draft'
            mo.workorder_ids.state = 'draft'
            mo.state = 'draft'
    
    def button_import(self):
        if not self.import_file:
            raise exceptions.UserError(_('Please upload a file.'))
        return self._action_import_component()

        # if self.mode == 'component':
        #     return self._action_import_component()
        # elif self.mode == 'byproduct':
        #     return self._action_import_byproduct()
        
        # return {'type': 'ir.actions.act_window_close'}

    # def _action_import_byproduct(self):
    #     """ Byproduct: file is Excel """
    #     cols = {
    #         'product_code_or_name',
    #         'description_picking',
    #         'product_uom_qty'
    #     }
    #     vals_list = self._excel_to_vals_list(self.import_file, cols, b64decode=True) # from `utilities.file.mixin`
    #     self._run_import_byproduct(vals_list)

    def _action_import_component(self):
        """ Components: file is Orgadata database """
        filename, db_content, mimetype = self._uncompress(self.filename, self.import_file) # from `utilities.file.mixin`

        db_models = ['AllArticles', 'Elevations']
        db_resource = self._open_external_database(filename, db_content, mimetype, self.encoding, db_models=db_models) # from `utilities.file.database`
        self._run_import_component(db_resource)


    #===== Import logics (Byproducts) =====#
    # def _run_import_byproduct(self, vals_list):
    #     # Search the products from `product_code_or_name`
    #     byproducts = self.env['product.product'].search([])
    #     not_found = []
    #     for row, vals in enumerate(vals_list, start=2):
    #         product_data = vals.get('product_code_or_name')
    #         product = self._find_product(byproducts, product_data)
    #         if not product:
    #             not_found.append(f'Row {row}: {product_data}')
    #         else:
    #             vals['product_id'] = product.id
    #             vals.pop('product_code_or_name')
        
    #     if not_found:
    #         raise exceptions.UserError(
    #             _('Unknown products:\n %s') % not_found.join('\n')
    #         )
        
    #     # Create mo's byproducts
    #     _logger.info(f'[_run_import_byproduct] vals_list: {vals_list}')
    #     self.production_id.move_byproduct_ids = [Command.create(vals) for vals in vals_list]
    
    # def _find_product(self, products, product_key):
    #     """ Search product `products` by code, and then name if not found by code """
    #     return (
    #         products.filtered(lambda x: x.default_code == product_key) or
    #         products.filtered(lambda x: x.name == product_key)
    #     )
    
    #===== Import logics (Components/Orgadata) =====#
    def _run_import_component(self, db_resource):
        """ Extract components and byproducts from Orgadata base
            - components are added to MO
            - byproducts are just exported in the Excel as a report
            
            Import logic:
            0. Read
            1. Substitute
            2. Browse product.product
            3. Identify unknown product
            4. Ignore
            5. Import
            6. Report (consumable, unknown, byproducts, ...) & message
        """
        # 0. Read Orgadata base
        components_valslist, byproducts_valslist = self._read_external_db(db_resource)
        self._close_db(db_resource) # close connection with external db
        
        # 1. Substitute
        mapped_components, substituted = self._substitute(components_valslist)

        # 2. Browse product.product
        domain = [('default_code', 'in', list(mapped_components.keys()))]
        self = self.with_context(active_test=False) # for ignored products
        self.product_ids = self.env['product.product'].search(domain)

        # 3. Unknown products
        default_code_list = self.product_ids.mapped('default_code')
        unknown = [v for k, v in mapped_components.items() if k not in default_code_list]

        # 4. Ignore
        self._ignore()

        # 5. Import
        self._import_components(mapped_components)

        # 6. Report & message
        consu = [
            mapped_components.get(x.product_id.default_code)
            for x in self.move_raw_ids.filtered(lambda x: x.product_id.type == 'consu')
        ]
        args = byproducts_valslist, substituted, unknown, consu
        report_binary = self._make_report(mapped_components, *args)

        # chatter message
        mail_values = self._prepare_chatter_msg_vals(*args, report_binary)
        self._get_order().message_post(**mail_values)

    def _read_external_db(self, db_resource):
        """ Can be overriden to add import logic for other external database """

        def _get_fields(column_qty):
            return f"""
                IIF(
                    ColorInfoInternal IS NOT NULL AND ColorInfoInternal != '',
                    ArticleCode_OrderCode || '{SEPARATOR_COLOR}' || ColorInfoInternal,
                    ArticleCode_OrderCode
                ) AS default_code,
                {column_qty} AS product_uom_qty,
                Units_Unit AS uom_name,
                Description AS name,
                PriceGross AS price,
                Discount AS discount
            """

        if self.external_db_type == 'orgadata':
            # if `ColorInfoInternal` is given, suffix it to the `default_code`
            sql = f"""
                SELECT {_get_fields('Units_Output')} FROM AllArticles
                UNION
                SELECT {_get_fields('Amount')} FROM AllProfiles
            """
            components = self._read_db(db_resource, sql)

            # Final products (positions)
            sql = f"""
                SELECT
                    Name AS description_picking,
                    Amount AS product_uom_qty
                FROM Elevations
            """
            byproducts = self._read_db(db_resource, sql)

        return components, byproducts
    
    def _substitute(self, components_valslist):
        """ Apply reference substitution logic updated components dict.
            Especially, it manages the *merge* of several *substituted* (old) references
             that may happen into a single *target* (new) product, applying the logics:
             - `product_uom_qty`: summed
             - `price` and `discount`: weight-averaged

            :arg components_valslist: valslist from external database
            :return: tuple (
                `mapped_components`: final `components` mapped dict
                `substituted`: replaced valslist (old codes), not mapped dict
            )
        """

        def __weighted_avg(previous_vals, vals, key):
            """ When merging 2 references, merge its *price* and *discount* (`key` arg)
                as weighted avg per `product_uom_qty`
            """
            return (
                previous_vals['product_uom_qty'] * previous_vals[key] +
                vals['product_uom_qty'] * vals[key]
            ) / (
                previous_vals['product_uom_qty'] + vals['product_uom_qty']
            )
        
        mapped_components, substituted = {}, []
        vals_default = {
            'product_uom_qty': 0.0,
            'price': 0.0,
            'discount': 0.0
        }
        mapped_substitution_product = {
            x.substituted_code: x.product_id # old -> new
            for x in self.env['product.substitution'].search([])
        }
        if mapped_substitution_product:
            for vals in components_valslist:
                metadata = vals # default_code, name, uom_name
                default_code = vals['default_code']
                substitution_product = mapped_substitution_product.get(default_code)
                
                # if the reference must be substituted
                if substitution_product:
                    # add old ref to `substituted` mapped dict
                    substituted.append(vals)
                    default_code = substitution_product.default_code
                    metadata = {
                        'default_code': default_code,
                        'name': substitution_product.name,
                        'uom_name': substitution_product.uom_name
                    }
                
                # merge new ref in `mapped_components`
                previous_vals = mapped_components.get(default_code, vals_default.copy())
                mapped_components[default_code] = metadata | {
                    'product_uom_qty': vals['product_uom_qty'] + previous_vals['product_uom_qty'],
                    'price': __weighted_avg(previous_vals, vals, 'price'),
                    'discount': __weighted_avg(previous_vals, vals, 'discount'),
                }
        
        return mapped_components, substituted

    def _ignore(self):
        all_products = self.product_ids
        active = self.product_ids.filtered('active')

        self.ignored_product_ids = all_products - active
        self.product_ids = active

    def _import_components(self, mapped_components):
        """ Update products prices (first)
            and add product materials as MO's components
        """
        component_vals_list = []
        # supplierinfo_vals_list, component_vals_list = [], []
        for product in self.product_ids:
            data = mapped_components.get(product.default_code)
            if not data:
                continue
        
            # ALY, 2025-05-15 : don't import price from Orgadata
            # Update product price
            # if data.get('price') or data.get('discount'):
            #     supplierinfo_vals_list.append({
            #         'product_id': product.id,
            #         'product_tmpl_id': product.product_tmpl_id.id,
            #         'partner_id': product.preferred_supplier_id.id,
            #         'price': data.get('price'),
            #         'discount': data.get('discount'),
            #         'sequence': max(product.seller_ids.mapped('sequence') + [0]) + 1,
            #     })

            # Create need (reservation)
            component_vals_list.append(
                self._prepare_component_vals(product, data)
            )
        
        # ALY, 2025-05-15 : don't import price from Orgadata
        # if supplierinfo_vals_list:
        #     _logger.info(f'[_import_components] supplierinfo_vals_list: {supplierinfo_vals_list}')
        #     self.supplierinfo_ids = self.env['product.supplierinfo'].sudo().create(supplierinfo_vals_list)

        if component_vals_list:
            _logger.info(f'[_import_components] component_vals_list: {component_vals_list}')
            self.env["stock.move"].create(component_vals_list)
    
    def _prepare_component_vals(self, product, data):
        if self.production_id:
            return self.production_id._origin._get_move_raw_values(
                product,
                data.get('product_uom_qty'),
                product.uom_id,
            ) | {
                # (!) very important
                # needed so it's not guessed by [Create] operation
                # else these moves will be considered both as components *and* finished products
                'production_id': False
            }
        elif self.picking_id:
            picking = self.picking_id
            return {
                'picking_id': picking.id,
                'name': _('New'),
                'product_id': product.id,
                'product_uom_qty': data.get('product_uom_qty'),
                'product_uom': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'company_id': picking.company_id,
            }
        else:
            raise exceptions.UserError(_("Operation not supported."))

    def _make_report(self, mapped_components, byproducts, substituted, unknown, consu):
        def __write_section(start_row, title, cols, vals_list):
            # Title
            cell = 'A' + str(start_row)
            sheet[cell] = title
            sheet[cell].font = openpyxl.styles.Font(size=14, bold=True)
            
            # Headers
            for col, header in enumerate(cols, start=1):
                cell = sheet.cell(row=start_row+1, column=col)
                cell.value = header
                cell.font = openpyxl.styles.Font(bold=True)
                cell.fill = openpyxl.styles.PatternFill("solid", fgColor="B4C7DC")
            
            # Content
            row_cursor = start_row+2 # title + header
            for vals in vals_list:
                if not vals:
                    continue
                
                for col, key in enumerate(list(cols.values()), start=1):
                    sheet.cell(row=row_cursor, column=col).value = vals.get(key, '')
                row_cursor += 1
            
            return row_cursor

        # Load the Excel template
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../' + self.REPORT_FILENAME)
        workbook = openpyxl.load_workbook(path)
        sheet = workbook.active

        # Titles & translations
        titles = {
            'A1': _('Report for the import of manufacturing Components'),
            'A2': _('Project'),
            'A3': _('Manufacturing Order'),
            'A4': _('Date'),
            'B2': self._get_order().project_id.display_name,
            'B3': self._get_order().display_name,
            'B4': fields.Date.context_today(self),
        }
        for cell, text in titles.items():
            sheet[cell] = text

        # Final products
        row_cursor = 6
        cols = {
            _('Description'): 'description_picking',
            _('Quantity'): 'product_uom_qty',
        }
        row_cursor = __write_section(row_cursor, _('Final products'), cols, byproducts) + 1

        # Components
        self = self.with_context(active_test=False)
        sections = {
            _('Unknown'): unknown,
            _('Consumable'): consu,
            _('Imported components'): [mapped_components.get(x.default_code, {}) for x in self.product_ids],
            _('Substituted components'): substituted,
            _('Ignored components'): [mapped_components.get(x.default_code, {}) for x in self.ignored_product_ids]
        }
        cols = {
            _('Reference'): 'default_code',
            _('Name'): 'name',
            _('Quantity'): 'product_uom_qty',
            _('Unit of Measure'): 'uom_name',
            _('Unit Price'): 'price',
        }
        for section, vals_list in sections.items():
            row_cursor = __write_section(row_cursor, section, cols, vals_list) + 1

        # Save the file to a BytesIO stream
        output_stream = io.BytesIO()
        workbook.save(output_stream)
        workbook.close()

        output_stream.seek(0)
        return output_stream.read() # binary, NOT base64 encoded for `message_post`

    def _prepare_chatter_msg_vals(self, byproducts, substituted, unknown, consu, report_binary):
        return {
            'message_type': 'notification',
            'subtype_xmlid': 'mail.mt_note',
            'is_internal': True,
            'partner_ids': [],
            'body': _(
                "<ul>"
                    "<li><strong>%(components)s</strong> components added</li>"
                    "<li><strong>%(consu)s</strong> consumable (to order separatly)</li>"
                    "<li><strong>%(substituted)s</strong> substituted references</li>"
                    "<li><strong>%(ignored)s</strong> explicitely ignored</li>"
                    "<li><strong>%(unknown)s</strong> unknown products</li>"
                    "<li><strong>%(byproducts)s</strong> final products</li>"
                "</ul>",
                components=len(self.product_ids),
                consu=len(consu),
                substituted=len(substituted),
                ignored=len(self.ignored_product_ids),
                unknown=len(unknown),
                byproducts=len(byproducts),
            ),
            'attachments': [] if not report_binary else [
                (_('Components report'), report_binary)
            ]
        }
