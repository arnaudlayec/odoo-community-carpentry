# -*- coding: utf-8 -*-

from odoo import exceptions, fields, Command
from odoo.tests import common, Form
from odoo.tools import file_open

import base64

class TestCarpentryMrpImport(common.SingleTransactionCase):

    COMPONENT_DB_FILE = 'orgadata_test.sqlite3'
    BYPRODUCTS_XLSX_FILE = 'byproducts_import_test.xlsx'
    SUM_QUANTITY_SUBSTITUTED = 96*2 # from `orgadata_test.sqlite3`
    SUBSTITUTED_CODE_1 = '218156'
    SUBSTITUTED_CODE_2 = '218157'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.project = cls.env['project.project'].create({'name': 'Project Test 001'})

        # Products
        cls.Product = cls.env['product.product']
        cls.final_product, cls.storable, cls.replacement, cls.ignored, cls.consu = cls.Product.create([{
            'name': 'Position Final Product Test 001',
            'default_code': False,
        }, {
            'name': 'Vis TF cruciforme ø 4,8x30',
            'default_code': '205082',
            'type': 'product',
        }, {
            'name': 'Replacement',
            'default_code': 'replacement',
            'type': 'product',
            'substitution_ids': [
                Command.create({'substituted_code': cls.SUBSTITUTED_CODE_1}),
                Command.create({'substituted_code': cls.SUBSTITUTED_CODE_2})
            ]
        }, {
            'name': 'Ignored',
            'default_code': '236253',
            'type': 'product',
            'active': False,
        }, {
            'name': 'Consummable',
            'default_code': '269510',
            'type': 'consu',
        }])

        # Manufacturing Order
        cls.mo = cls.env['mrp.production'].create([{
            'project_id': cls.project.id,
            'product_id': cls.final_product.id
        }])

        cls.wizard = cls._load_wizard()
    
    @classmethod
    def _load_wizard(cls, mode='component'):
        # Open Wizard & upload file
        file = cls.COMPONENT_DB_FILE if mode == 'component' else cls.BYPRODUCTS_XLSX_FILE
        file_res = file_open('carpentry_mrp_import/tests/' + file, 'rb')
        file_content = file_res.read()

        Wizard = cls.env['carpentry.mrp.import.wizard'].with_context(
            active_id=cls.mo.id,
            active_model="mrp.production",
        )
        wizard = Wizard.create([{
            # 'mode': mode,
            'external_db_type': 'orgadata',
            'import_file': base64.b64encode(file_content),
            'filename': cls.COMPONENT_DB_FILE
        }])
        file_res.close()

        return wizard

    def test_01_load_file(self):
        """ Tests load of external database (code execution) """
        self.wizard.button_import()
        self.assertTrue(self.wizard.product_ids)
    
    def test_02_filter(self):
        self.assertTrue(self.storable in self.wizard.product_ids)
        self.assertEqual(self.ignored, self.wizard.with_context(active_test=False).ignored_product_ids)

    def test_03_import_component(self):
        """ Tests components import in the Manufacturing Order """
        # self.assertTrue(self.wizard.supplierinfo_ids)
        self.assertTrue(self.storable in self.mo.move_raw_ids.product_id)
    
    def test_04_substitution(self):
        """ Tests substitution logics """
        # `replacement` in the components though not in .sqlite
        self.assertTrue(self.replacement in self.wizard.product_ids)

        # good quantity (summed)
        move_raw_id = self.mo.move_raw_ids.filtered(lambda x: x.product_id == self.replacement)
        self.assertEqual(move_raw_id.product_uom_qty, self.SUM_QUANTITY_SUBSTITUTED)
    
    def test_05_substitution_raise_chain(self):
        """ Tests constrain preventing a product to be both a
            substitution one (target) a substituted reference (source)
        """
        # one can declare as real *product.product* a substituted reference...
        product_substituted = self.Product.create([{
            'name': 'Product both target and substituted',
            'default_code': self.SUBSTITUTED_CODE_1,
        }])
        # ...but cannot create chained substitution
        with self.assertRaises(exceptions.ValidationError):
            product_substituted.substitution_ids = [Command.create({'substituted_code': 'anything'})]
    
    def test_06_report_chatter(self):
        self.assertTrue(self.mo.message_ids)
        self.assertEqual(self.mo.message_attachment_count, 1)

    # def test_07_byproducts_import(self):
    #     wizard = self._load_wizard('byproduct')
    #     wizard.button_import()
    #     self.assertTrue(self.mo.move_byproduct_ids)
