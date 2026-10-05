import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/* 知识库里的文本/Markdown 查看与编辑。
 *
 * 三件事：预览/编辑两个页签的切换、textarea 的 Tab 缩进与 Ctrl+S 保存、
 * 以及把代码块交给 Prism 上色。刻意不做 IDE：没有自动补全、没有行号槽、
 * 没有分栏实时渲染——"预览草稿"点一下才走一次服务端渲染。
 *
 * 渲染只有一份实现（models/library_markdown.py）：草稿预览 POST 给
 * /tutoring/library/render_md，返回的就是存盘后你会看到的同一段 HTML。
 * 前端再写一个解析器迟早和后端对不上，那种双实现的分歧最难查。
 */

const INDENT = "  ";

export class LibraryViewer extends Interaction {
    static selector = "[data-lib-viewer]";

    setup() {
        this.panes = {};
        this.el.querySelectorAll("[data-lib-pane]").forEach((node) => {
            this.panes[node.dataset.libPaneName || node.getAttribute("data-lib-pane")] = node;
        });
        this.tabs = Array.from(this.el.querySelectorAll("[data-lib-tab]"));
        this.source = this.el.querySelector("[data-lib-source]");
        this.draft = this.el.querySelector("[data-lib-draft]");
        this.renderUrl = this.el.dataset.libRender || "";
        this.form = this.source ? this.source.closest("form") : null;
        this.csrf = this.form
            ? (this.form.querySelector('[name="csrf_token"]') || {}).value || ""
            : "";

        this.tabs.forEach((tab) => {
            tab.addEventListener("click", () => this.showTab(tab.dataset.libPaneName));
        });
        if (this.tabs.length) {
            // 默认停在预览；没跑这段 JS 时两个页签都在，功能不丢
            this.showTab("preview");
        }
        if (this.source) {
            this.source.addEventListener("keydown", (ev) => this.onKeydown(ev));
        }
        const renderBtn = this.el.querySelector("[data-lib-render]");
        if (renderBtn) {
            renderBtn.addEventListener("click", () => this.renderDraft());
        }
        this.highlight(this.el);
    }

    showTab(name) {
        Object.entries(this.panes).forEach(([key, node]) => {
            node.classList.toggle("d-none", key !== name);
        });
        this.tabs.forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.libPaneName === name);
        });
        if (name === "preview") {
            this.highlight(this.panes.preview);
        }
    }

    onKeydown(ev) {
        if (ev.key === "Tab") {
            ev.preventDefault();
            this.indent(ev.shiftKey);
        } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
            ev.preventDefault();
            if (this.form) {
                this.form.requestSubmit ? this.form.requestSubmit() : this.form.submit();
            }
        }
    }

    indent(backward) {
        const el = this.source;
        const start = el.selectionStart;
        const end = el.selectionEnd;
        const value = el.value;
        // 单光标：插两个空格。有选区：整块加/退缩进，一层最多吃掉 1 个制表符或 2 个空格
        if (!backward && start === end) {
            el.value = value.slice(0, start) + INDENT + value.slice(end);
            el.selectionStart = el.selectionEnd = start + INDENT.length;
            return;
        }
        const lineStart = value.lastIndexOf("\n", start - 1) + 1;
        const lines = value.slice(lineStart, end).split("\n");
        const next = (backward
            ? lines.map((line) => line.replace(/^(\t| {1,2})/, ""))
            : lines.map((line) => INDENT + line)
        ).join("\n");
        el.value = value.slice(0, lineStart) + next + value.slice(end);
        el.selectionStart = lineStart;
        el.selectionEnd = lineStart + next.length;
    }

    async renderDraft() {
        if (!this.renderUrl || !this.csrf) {
            return;
        }
        this.draft.textContent = "正在渲染…";
        const body = new URLSearchParams({
            body: this.source.value,
            csrf_token: this.csrf,
        });
        try {
            const resp = await fetch(this.renderUrl, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body,
                credentials: "same-origin",
            });
            const data = await resp.json();
            if (data && data.ok) {
                // 这段 HTML 是服务端渲染 + html_sanitize 过的，来源是我们自己的接口
                this.draft.innerHTML = data.html;
                this.highlight(this.draft);
            } else {
                this.draft.textContent = (data && data.error) || "渲染失败";
            }
        } catch {
            this.draft.textContent = "网络中断，草稿没渲染出来（文件内容没丢）";
        }
    }

    highlight(root) {
        // Prism 是站点资产包里带的（web/static/lib/prismjs），不额外引库
        if (window.Prism && root) {
            window.Prism.highlightAllUnder(root);
        }
    }
}

registry
    .category("public.interactions")
    .add("tutoring_center.library_viewer", LibraryViewer);
