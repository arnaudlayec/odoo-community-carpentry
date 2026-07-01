/** @odoo-module **/

import { Component, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { X2Many2DMatrixRenderer } from "@web_widget_x2many_2d_matrix/components/x2many_2d_matrix_renderer/x2many_2d_matrix_renderer.esm";

export class X2Many2DMatrixCarpentryTimesheetRenderer extends X2Many2DMatrixRenderer {
    setup() {
        super.setup();
    }

    _getRows(records = this.list.records) {
        const rows = [];
        records.forEach((record) => {
            const row = {
                value: record.data[this.matrixFields.y],
                text: record.data[this.matrixFields.y],
                totalExpense: record.data.effective_hours,
                reservedBudget: record.data.reserved_budget,
            };
            if (record.fields[this.matrixFields.y].type === "many2one") {
                row.text = row.value[1];
                row.value = row.value[0];
            }
            if (rows.findIndex((r) => r.value === row.value) !== -1) return;
            rows.push(row);
        });
        return rows;
    }

    // Getters
    getRowExpense(row) {
        return Math.round(
            (row.totalExpense + this._aggregateRow(row.value)) * 100
        ) / 100;
    }
    getRowBudget(row) {
        return row.reservedBudget;
    }
    getRowProcess(row) {
        if (!this.getRowBudget(row)) {
            return 0.0;
        }
        return Math.round(this.getRowExpense(row) / this.getRowBudget(row) * 100);
    }
}

X2Many2DMatrixCarpentryTimesheetRenderer.template = "carpentry_timesheet.X2Many2DMatrixCarpentryTimesheetRenderer";
