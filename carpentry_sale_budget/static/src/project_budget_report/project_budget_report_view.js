/** @odoo-module */

import { PivotController } from "@web/views/pivot/pivot_controller";
import { ProjectBudgetReportModel } from "./project_budget_report_model";
import { registry } from '@web/core/registry';
import { pivotView } from '@web/views/pivot/pivot_view';

export class ProjectBudgetReportController extends PivotController {
    setup() {
        super.setup();
    }
}

// ===== View =====
export const carpentryProjectBudgetReport = {
    ...pivotView,
    Controller: ProjectBudgetReportController,
    Model: ProjectBudgetReportModel,
    buttonTemplate: "carpentry_project_budget_report.PivotAmounts",
}
registry.category("views").add("project_budget_report_pivot", carpentryProjectBudgetReport);
