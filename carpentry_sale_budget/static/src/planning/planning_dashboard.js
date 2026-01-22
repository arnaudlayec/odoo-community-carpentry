/** @odoo-module **/

import { registry } from '@web/core/registry';
import { _lt } from "@web/core/l10n/translation";

//===== Tasks items =====
const dashboardItems = [
    {id: "margins", title: _lt("Budget"), sequence: 30, icon: "fa-line-chart"},
];
dashboardItems.forEach(item => {
    registry.category("carpentry_planning.planning_dashboard_item").add(item.id, item);
});
