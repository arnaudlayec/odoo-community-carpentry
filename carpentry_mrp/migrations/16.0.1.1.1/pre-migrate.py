
def migrate(cr, version):
    """Migrate views from 'mrp_carpentry' to 'mrp_2_steps_materials_out_at_prep'.
    They are re-created by this later module with 'transitory' suffix"""
    cr.execute("""
        DELETE FROM ir_ui_view WHERE name IN (
            'stock.quant.inventory.tree.editable.carpentry',
            'stock.quant.tree.carpentry',
            'stock.quant.form.editable.carpentry',
            'stock.quant.pivot.carpentry',
            'stock.quant.graph.carpentry',
            
            'stock.inventory.conflict.form.view.carpentry'
        )
    """)
