/** @odoo-module **/

const { Component, useState, onWillStart } = owl;
import { useService } from "@web/core/utils/hooks";

// Launch item (<li> element)
export class PlanningLeftSidePanel_LaunchItem extends Component {
    setup() {
        super.setup();

        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            is_done: this.props.launch.is_done,
            milestone_shortcut: this.props.launch.milestone_shortcut ? this.props.launch.milestone_shortcut.data : []
        });
    }

    toggleMilestone(milestone) {
        // Milestone color
        const done_new = !milestone.is_done;
        const state_milestone = this.state.milestone_shortcut.find(
            (vals) => { return vals.id == milestone.id }
        )
        if (state_milestone) {
            state_milestone.is_done = done_new;
        }

        // Launch `is_done` (substriked)
        if (milestone.is_last) {
            this.state.is_done = done_new;
            this.props.launch.is_done = done_new;
        }

        // ORM save
        this.orm.write(
            "carpentry.planning.milestone",
            [milestone.id],
            { is_done: done_new },
        );
    }
    openLaunch() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'carpentry.group.launch',
            res_id: this.props.launch.id,
            views: [[false, 'form']],
            name: this.props.launch.name,
            target: 'new',
            context: { 'carpentry_planning': true }
        });
    }
}
PlanningLeftSidePanel_LaunchItem.template = "carpentry_planning.PlanningLeftSidePanel_LaunchItem";
PlanningLeftSidePanel_LaunchItem.props = {
    launch: Object,
    isSelected: Boolean,
    selectLaunch: Function
};


// List (left side pannel)
export class PlanningLeftSidePanel extends Component {
    setup() {
        this.state = useState({
            selectedLaunchId: this.props.model.launchId,
            lazyDisplay: true,
            launchCount: 0
        });
    }

    get launchIds() {
        let launchs = this.props.model.data.launchIds || {};
        if (launchs && Array.isArray(launchs) && this.state.lazyDisplay) {
            launchs = launchs.filter(
                (launch) => { return !launch.is_done; }
            );
        }
        return launchs;
    }

    selectLaunch(launch) {
        if (launch) {
            this.props.model.setLaunch(launch); // model
            this.state.selectedLaunchId = launch.id; // reload left side panel
        }
    }

    toggleLazyDisplay() {
        this.state.lazyDisplay = !this.state.lazyDisplay;
    }

    // Simili-pager (prev, next)
    get goLeft() {
        return this.launchIds.length > 1 && this.state.selectedLaunchId != this.launchIds[0].id
    }
    get goRight() {
        const lastIndex = this.launchIds.length - 1
        return this.launchIds.length > 1 && this.state.selectedLaunchId != this.launchIds[lastIndex].id
    }
    move(direction) {
        const currentIndex = this.launchIds.findIndex((launch) => launch.id == this.state.selectedLaunchId);
        if (currentIndex + direction >= 0 && currentIndex + direction < this.launchIds.length) {
            this.selectLaunch(this.launchIds[currentIndex + direction]);
        }
    }
}
PlanningLeftSidePanel.template = "carpentry_planning.PlanningLeftSidePanel";
PlanningLeftSidePanel.components = { PlanningLeftSidePanel_LaunchItem };
PlanningLeftSidePanel.props = {
    model: {}
};
