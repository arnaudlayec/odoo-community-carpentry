/** @odoo-module */

import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { PlanningModel } from "./planning_model";
import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";

import { PlanningDashboard } from "./planning_dashboard";
import { PlanningLeftSidePanel } from "./planning_left_side_panel";

// ===== Renderer =====
export class PlanningRendered extends KanbanRenderer {
    setup() {
        super.setup();
        this.actionService = useService('action');
    }
    openMilestone(milestone) {
        const actionReload = async () => await this.props.list.model.load(this.props.list);
        console.log("openMilestone", actionReload, this.props.list.model, this.props.list);

        this.actionService.doAction({
            'type': 'ir.actions.act_window',
            'res_model': 'carpentry.planning.milestone.wizard',
            'context': {default_milestone_id: milestone.id, default_offset: 1},
            'name': milestone.name,
            'views': [[false, 'form']],
            'target': 'new',
        }, {
            onClose: actionReload
        });
    }
}
PlanningRendered.template = "carpentry_planning.PlanningRendered";

// ===== Controller =====
export class PlanningController extends KanbanController {
    setup() {
        super.setup();
        this.archInfo = {...this.props.archInfo};
        this.archInfo.className += " flex-grow-1"; // for Kanban flex layout with left side panel
        
        // Custom Layout: only display Breadcrumbs
        this.display = this.props.display;
        this.display.controlPanel = {
            ...this.display.controlPanel,
            'top-right': false, // SearchPanel
            'bottom-right': false, // searchMenuTypes
            'bottom-left': false, // buttons
        };
    }

    // Title (planning) - view milestones dates
    async openPlanningMilestones () {
        this.actionService.doActionButton({
            type: 'object',
            name: 'open_planning_milestone_table',
            resModel: 'project.project',
            resId: this.model.projectId,
        }, {
            clearBreadcrumbs: true,
        });
    }

    // Kanban (planning) - overwrites card opening
    async openRecord (record) {
        const actionReload = async () => await this.model.load(this.model.root);
        this.actionService.doActionButton({
            type: 'object',
            name: 'action_open_planning_card',
            resModel: record._values.res_model,
            resId: record._values.res_id,
            context: record.model.root.context,
            onClose: actionReload,
        });
    }
}
PlanningController.template = "carpentry_planning.CarpentryPlanningKanbanView"
PlanningController.components = {
    ...KanbanController.components,
    PlanningRendered,
    PlanningDashboard,
    PlanningLeftSidePanel,
};

// ===== View =====
export const carpentryPlanningKanbanView = {
    ...kanbanView,
    Renderer: PlanningRendered,
    Controller: PlanningController,
    Model: PlanningModel
};

registry.category("views").add("carpentry_planning_kanban", carpentryPlanningKanbanView);
