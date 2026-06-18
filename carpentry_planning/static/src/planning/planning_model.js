/** @odoo-module */

import { KanbanModel } from "@web/views/kanban/kanban_model"
import { KeepLast } from "@web/core/utils/concurrency";

export class PlanningModel extends KanbanModel {
    setup (params) {
        super.setup(...arguments);

        this.data = {};
        this.launchId = null;
        this.launchName = null;
        this._pendingScroll = false;
    }

    // We need to ensure ORM is called only with both `project_id` and `launch_ids` in domain
    async load(searchParams) {
        this.projectId = searchParams.context['default_project_id'];
        if (!this.projectId && false) {
            this.action.doAction('carpentry_planning.action_srv_open_planning');
        } else {
            await this.loadLaunchIds();
            searchParams['domain'] = [['project_id', '=', this.projectId], ['launch_ids', '=', this.launchId]];
            await super.load(searchParams);
            await this.loadColumnHeaders();
            await this.loadDashboard();
            this.notify();
        }
    }

    // Columns headers
    async loadColumnHeaders() {
        const columnIds = this.root.groups.map((group) => group.resId);
        this.headersKeepLast = this.headersKeepLast || new KeepLast();
        this.data.headers = await this.headersKeepLast.add(this.orm.silent.call(
            "carpentry.planning.column",
            "get_headers_data",
            [columnIds, this.launchId]
        ));
    }

    // Dashboard
    async loadDashboard() {
        if (!this.data.dashboard) {
            this.dashboardKeepLast = this.dashboardKeepLast || new KeepLast();
            this.data.dashboard = await this.dashboardKeepLast.add(this.orm.silent.call(
                "project.project", "get_planning_dashboard_data", [this.projectId]
            ));
        }
    }

    // Launches (left side panel)
    async loadLaunchIds() {
        if (this.projectId && !this.data.launchIds) {
            this.launchKeepLast = this.launchKeepLast || new KeepLast();
            this.data.launchIds = await this.launchKeepLast.add(
                this.orm.silent.searchRead(
                    "carpentry.group.launch",
                    [['project_id', '=', this.projectId]],
                    ["name", "is_done", "milestone_shortcut"]
                )
            );
            if (!this.launchId) {
                this.preSelectLaunch();
            }
        }
    }
    preSelectLaunch() {
        if (this.data.launchIds) {
            const openedLaunches = this.data.launchIds.filter((launch) => !launch.is_done);
            if (!openedLaunches.length && this.data.launchIds.length) {
                openedLaunches = this.data.launchIds; // if all launches are closed: select 1st anyway, even if closed
            }
            this.setLaunch(openedLaunches.length && openedLaunches[0]);
        }
    }
    setLaunch(launch) {
        this._pendingScroll = true; // arm scrolling flag for `onPatched`. See Renderer
        this.launchId = launch.id;
        this.launchName = launch.name;

        this.env.searchModel.setDomainParts({
            launch: {
                domain: [["launch_ids", "=", launch.id]],
                facetLabel: launch.name,
            },
        });
    }
}
