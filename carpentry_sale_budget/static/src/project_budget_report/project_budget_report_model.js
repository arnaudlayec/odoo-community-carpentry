/** @odoo-module */

import { PivotModel } from "@web/views/pivot/pivot_model"
import { KeepLast } from "@web/core/utils/concurrency";

export class ProjectBudgetReportModel extends PivotModel {
    setup (params) {
        super.setup(...arguments);
    }

    async load(searchParams) {
        this.projectId = searchParams.context['default_project_id'];
        await super.load(searchParams);
        await this.loadCarpentryData();
        this.notify();
    }
    async loadCarpentryData() {
        if (!this.data.margins) {
            this.marginsKeepLast = this.marginsKeepLast || new KeepLast();
            this.data.margins = await this.marginsKeepLast.add(this.orm.silent.call(
                "project.project", "get_budget_margins_data", [this.projectId]
            ));
        }
        console.log("this.projectId", this.projectId)
        console.log("this.data.margins", this.data.margins)
    }
}
