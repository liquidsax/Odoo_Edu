/** 知识库页顶部：容量条 + 拖拽上传区，列表与看板共用（各挂在自己的 js_class 控制器上）。 */
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

const CATEGORIES = [
    ["other", _t("其他")],
    ["workbook", _t("练习册")],
    ["leetcode", _t("LeetCode")],
    ["note", _t("笔记")],
    ["doc", _t("资料文档")],
];

function fmtBytes(num) {
    const size = Number(num || 0);
    if (size < 1024) {
        return `${size} B`;
    }
    const units = ["KB", "MB", "GB"];
    let value = size / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value.toFixed(1)} ${units[unit]}`;
}

export class LibraryBanner extends Component {
    static template = "tutoring_center.LibraryBanner";
    static props = {
        bus: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.session = useService("session");
        this.effect = useService("effect");
        this.state = useState({
            quota: null,
            queue: [],
            category: "other",
            tags: "",
            dragging: false,
            busy: false,
        });
        this._uid = 0;
        this.fileInput = useRef("fileInput");
        onWillStart(() => this.fetch());
        if (this.props.bus) {
            // 别处改动（删条目、改筛选）后 reload 会经过模型的 update 事件
            useBus(this.props.bus, "update", () => this.fetch());
        }
    }

    get categories() {
        return CATEGORIES;
    }

    async fetch() {
        try {
            this.state.quota = await this.orm.silent.call(
                "tutoring.library.item", "quota_state", []);
        } catch {
            this.state.quota = null;
        }
    }

    // ---- 拖放与选择 ----

    onDragOver(ev) {
        ev.preventDefault();
        this.state.dragging = true;
    }

    onDragLeave(ev) {
        ev.preventDefault();
        this.state.dragging = false;
    }

    async onDrop(ev) {
        ev.preventDefault();
        this.state.dragging = false;
        await this.enqueue(Array.from(ev.dataTransfer?.files || []));
    }

    onPickClick() {
        this.fileInput?.click();
    }

    async onPick(ev) {
        const files = Array.from(ev.target.files || []);
        ev.target.value = "";
        await this.enqueue(files);
    }

    async enqueue(files) {
        for (const file of files) {
            const entry = {
                id: ++this._uid,
                name: file.name,
                size: file.size,
                percent: 0,
                status: "wait",
                error: null,
                file,
            };
            // 前端先拦一道：明显超限的文件不必等服务端跑完才知道
            if (this.state.quota && file.size > this.state.quota.max_file) {
                entry.status = "error";
                entry.error = _t("超过单个文件上限 %s",
                    this.state.quota.max_file_text || "");
            }
            this.state.queue.push(entry);
        }
        await this.run();
    }

    async run() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        let done = 0;
        let failed = 0;
        for (const entry of this.state.queue) {
            if (entry.status !== "wait") {
                continue;
            }
            entry.status = "uploading";
            try {
                await this.upload(entry);
                entry.status = "done";
                entry.percent = 100;
                done += 1;
            } catch (error) {
                entry.status = "error";
                entry.error = error?.message || _t("上传失败");
                failed += 1;
            }
        }
        this.state.busy = false;
        await this.refresh();
        if (done) {
            this.effect.add({ type: "rainbow_man",
                message: _t("已上传 %s 个文件", done) });
        }
        if (failed) {
            this.effect.add({ type: "warning",
                message: _t("%s 个文件没传上去，看下面的原因", failed) });
        }
    }

    upload(entry) {
        // 用 XHR 而不是 rpc service：只有它拿得到 upload.onprogress 的真实字节进度
        return new Promise((resolve, reject) => {
            const form = new FormData();
            form.append("file", entry.file);
            form.append("category", this.state.category);
            form.append("tags", this.state.tags);
            form.append("csrf_token", this.session.csrf_token || "");
            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/tutoring/library/upload");
            xhr.upload.addEventListener("progress", (ev) => {
                if (ev.lengthComputable) {
                    entry.percent = Math.min(99, Math.round((ev.loaded / ev.total) * 100));
                }
            });
            xhr.addEventListener("load", () => {
                let payload = null;
                try {
                    payload = JSON.parse(xhr.responseText);
                } catch {
                    payload = null;
                }
                if (xhr.status >= 200 && xhr.status < 300 && payload && payload.ok !== false) {
                    resolve(payload);
                } else {
                    reject(new Error(
                        (payload && payload.error) || _t("上传失败（HTTP %s）", xhr.status)));
                }
            });
            xhr.addEventListener("error", () =>
                reject(new Error(_t("网络中断，这个文件没传完"))));
            xhr.addEventListener("abort", () => reject(new Error(_t("已取消"))));
            xhr.send(form);
        });
    }

    async refresh() {
        await this.fetch();
        try {
            if (this.env.model?.root?.load) {
                await this.env.model.root.load();
            }
        } catch {
            // 视图模型不可用时，下面的事件也足以让统计条更新
        }
        if (this.props.bus) {
            this.props.bus.trigger("update");
        }
    }

    fmtBytes(num) {
        return fmtBytes(num);
    }

    clearQueue() {
        this.state.queue = this.state.queue.filter((entry) => entry.status !== "done");
    }
}

class LibraryKanbanController extends KanbanController {}
LibraryKanbanController.template = "tutoring_center.LibraryKanbanController";
LibraryKanbanController.components = {
    ...KanbanController.components,
    LibraryBanner,
};

class LibraryListController extends ListController {}
LibraryListController.template = "tutoring_center.LibraryListController";
LibraryListController.components = {
    ...ListController.components,
    LibraryBanner,
};

registry.category("views").add("tutoring_library_kanban", {
    ...kanbanView,
    Controller: LibraryKanbanController,
});
registry.category("views").add("tutoring_library_list", {
    ...listView,
    Controller: LibraryListController,
});
