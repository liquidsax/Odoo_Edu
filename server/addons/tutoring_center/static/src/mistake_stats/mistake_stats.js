/** 错题页顶部概览条：统计数字 + 点击即筛选，列表与看板共用（各挂在 js_class 控制器上）。 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

export class MistakeStatsBanner extends Component {
    static template = "tutoring_center.MistakeStatsBanner";
    static props = {
        bus: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ stats: null });
        this._seq = 0;
        onWillStart(() => this.fetch());
        if (this.props.bus) {
            // 换筛选、弹窗里记完错题后的重载都会经过模型的 update 事件
            useBus(this.props.bus, "update", () => this.fetch());
        }
    }

    async fetch() {
        const seq = ++this._seq;
        try {
            const stats = await this.orm.silent.call("tutoring.mistake", "summary_stats", []);
            if (seq === this._seq) {
                this.state.stats = stats;
            }
        } catch {
            if (seq === this._seq) {
                this.state.stats = null;
            }
        }
    }

    get chips() {
        const s = this.state.stats;
        if (!s) {
            return [];
        }
        return [
            { key: "total", icon: "fa-book", value: s.total, label: "条错题", plain: true },
            { key: "month", icon: "fa-calendar", value: s.month, label: "本月新增",
                filter: "filter_date" },
            { key: "hard", icon: "fa-fire", value: s.hard, label: "高难度", filter: "hard" },
            { key: "no_cause", icon: "fa-question-circle", value: s.no_cause, label: "未标错因",
                filter: "no_cause" },
        ];
    }

    _findSearchItem(name) {
        const searchModel = this.env.searchModel;
        if (!searchModel) {
            return null;
        }
        try {
            return (
                searchModel
                    .getSearchItems(
                        (item) => item.name === name && ["filter", "dateFilter"].includes(item.type)
                    )
                    .at(0) || null
            );
        } catch {
            return null;
        }
    }

    isActive(name) {
        const searchModel = this.env.searchModel;
        const item = this._findSearchItem(name);
        if (!searchModel || !item) {
            return false;
        }
        try {
            return searchModel.query.some((queryElem) => queryElem.searchItemId === item.id);
        } catch {
            return false;
        }
    }

    onChipClicked(chip) {
        const searchModel = this.env.searchModel;
        const item = this._findSearchItem(chip.filter);
        if (!searchModel || !item) {
            return;
        }
        try {
            if (item.type === "dateFilter") {
                searchModel.toggleDateFilter(item.id, "month");
            } else {
                searchModel.toggleSearchItem(item.id);
            }
        } catch {
            // 搜索模型不可用时保持纯展示
        }
    }
}

/** 卡片模板上下文原生不给分组信息，这里补一个 groupByField，供"按学生分组时不重复显示学生 chip"。 */
class MistakeKanbanRecord extends KanbanRecord {
    get renderingContext() {
        return { ...super.renderingContext, groupByField: this.props.groupByField || null };
    }
}

class MistakeKanbanRenderer extends KanbanRenderer {
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: MistakeKanbanRecord,
    };
}

class MistakeKanbanController extends KanbanController {}
MistakeKanbanController.template = "tutoring_center.MistakeKanbanController";
MistakeKanbanController.components = {
    ...KanbanController.components,
    MistakeStatsBanner,
};

class MistakeListController extends ListController {}
MistakeListController.template = "tutoring_center.MistakeListController";
MistakeListController.components = {
    ...ListController.components,
    MistakeStatsBanner,
};

registry.category("views").add("tutoring_mistake_kanban", {
    ...kanbanView,
    Controller: MistakeKanbanController,
    Renderer: MistakeKanbanRenderer,
});
registry.category("views").add("tutoring_mistake_list", {
    ...listView,
    Controller: MistakeListController,
});
