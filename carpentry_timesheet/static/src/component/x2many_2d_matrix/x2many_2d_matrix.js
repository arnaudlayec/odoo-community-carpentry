/** @odoo-module **/

import { registry } from "@web/core/registry";
import { X2Many2DMatrixField } from "@web_widget_x2many_2d_matrix/components/x2many_2d_matrix_field/x2many_2d_matrix_field.esm";
import { X2Many2DMatrixCarpentryTimesheetRenderer } from "../x2many_2d_matrix_renderer/x2many_2d_matrix_renderer.esm";

export class X2Many2DMatrixCarpentryTimesheetField extends X2Many2DMatrixField {
    setup() {
        super.setup();
    }
}

X2Many2DMatrixCarpentryTimesheetField.template = "carpentry_timesheet.X2Many2DMatrixCarpentryTimesheetField";
X2Many2DMatrixCarpentryTimesheetField.components = { X2Many2DMatrixCarpentryTimesheetRenderer };
registry.category("fields").add(
    "x2many_2d_matrix_carpentry_timesheet",
    X2Many2DMatrixCarpentryTimesheetField
);
