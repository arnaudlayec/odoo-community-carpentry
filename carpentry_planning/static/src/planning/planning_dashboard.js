/** @odoo-module **/

import { Component, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

import { registry } from '@web/core/registry';
import { loadJS } from "@web/core/assets";
import { _lt } from "@web/core/l10n/translation";

//===== Cards =====
export class PlanningDashboardCard extends Component { }
PlanningDashboardCard.template = "carpentry_planning.PlanningDashboardCard";
PlanningDashboardCard.props = {
    slots: {
        type: Object,
        shape: {
            default: Object,
            title: { type: Object, optional: true },
        },
    },
    className: {
        type: String,
        optional: true,
    },
};

//===== Dashboard =====
export class PlanningDashboard extends Component {
    setup() {
        super.setup();
        this.actionService = useService('action');

        this.items = registry.category("carpentry_planning.planning_dashboard_item").getAll().sort(
            (a, b) => a.sequence - b.sequence
        );
        onWillStart(() => {
            loadJS(["/web/static/lib/Chart/Chart.js"]);
        });
        
        this.colorPrefix = "o_status_";
        this.colors = {
            blocked: "red",
            done: "green",
        };
    }

    get data () {
        return this.props.model.data.dashboard;
    }
    get projectId() {
        return this.props.model.projectId;
    }

    statusColor(value) {
        return this.colors[value] ? this.colorPrefix + this.colors[value] : "";
    }
    // data : {date_deadline, date_end, kanban_state}
    btnColor(record) {
        const today = new Date()
        const dateDeadline = record.date_deadline && new Date(record.date_deadline)
        const dateDone = record.date_end && new Date(record.date_end);
        const overdue = record.date_end ? dateDone > dateDeadline : today > dateDeadline;
        const done = record.kanban_state == 'done';
        if (done) {
            return (dateDeadline && overdue) ? 'btn-warning' : 'btn-success';
        } else {
            return (dateDeadline && overdue) ? 'btn-danger' : 'btn-secondary';
        }
    }

    openDashboardRecord(res_model, res_id, context={}) {
        this.actionService.doActionButton({
            type: 'object',
            name: 'action_open_planning_dashboard_card',
            resModel: res_model,
            resId: res_id,
            buttonContext: context
        });
    }
    
    openNextProjectUser(user_id) {
        this.actionService.doActionButton({
            type: 'object',
            name: 'action_open_planning_next_user',
            resId: this.projectId,
            resModel: 'project.project',
            args: JSON.stringify([user_id])
        });
    }
}

//===== Dashboard items =====
const dashboardItems = [
    {id: "next_projects", title: _lt("Next projects"), sequence: 90, icon: "fa-arrow-right"},
];
dashboardItems.forEach(item => {
    registry.category("carpentry_planning.planning_dashboard_item").add(item.id, item);
});


PlanningDashboard.template = "carpentry_planning.PlanningDashboard";
PlanningDashboard.components = { PlanningDashboardCard };
PlanningDashboard.props = {
    model: {}
};

