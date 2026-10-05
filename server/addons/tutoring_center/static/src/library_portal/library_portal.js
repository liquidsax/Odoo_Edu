import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/* 门户知识库的上传交互。
 *
 * 两条上传路：
 *  - 拖进来的、或选好点「上传」的：JS 逐个发 XHR 到 /tutoring/library/upload，
 *    只有 XHR 拿得到 upload.onprogress 的真实字节进度（后台那块拖拽区同理）；
 *  - 浏览器没跑这段 JS 时：表单还是原生 multipart POST，照样能传。
 * 所以这里接管 submit 时先 preventDefault，再自己发——原生那条路是退路不是主路。
 */

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

export class LibraryUpload extends Interaction {
    static selector = "[data-lib-upload]";

    setup() {
        this.form = this.el.querySelector("[data-lib-form]");
        this.drop = this.el.querySelector("[data-lib-drop]");
        this.input = this.el.querySelector("[data-lib-input]");
        this.queue = this.el.querySelector("[data-lib-queue]");
        // CSRF 取表单里的隐藏域，不依赖 odoo.csrf_token 有没有注入过
        this.csrf = (this.form.querySelector('[name="csrf_token"]') || {}).value || "";
        this.maxFile = Number(this.el.dataset.libMaxFile || 0);
        this.busy = false;

        this.drop.addEventListener("dragover", (ev) => {
            ev.preventDefault();
            this.drop.classList.add("o_lib_dragover");
        });
        this.drop.addEventListener("dragleave", () => {
            this.drop.classList.remove("o_lib_dragover");
        });
        this.drop.addEventListener("drop", (ev) => {
            ev.preventDefault();
            this.drop.classList.remove("o_lib_dragover");
            this.uploadAll(Array.from((ev.dataTransfer && ev.dataTransfer.files) || []));
        });
        this.form.addEventListener("submit", (ev) => {
            const files = Array.from(this.input.files || []);
            if (!this.csrf || !files.length) {
                return; // 交回原生 POST，退路要留着
            }
            ev.preventDefault();
            this.uploadAll(files);
        });
    }

    async uploadAll(files) {
        if (!files.length || this.busy) {
            return;
        }
        this.busy = true;
        this.queue.classList.remove("d-none");
        let done = 0;
        let failed = 0;
        for (const file of files) {
            const row = this.addRow(file.name, file.size);
            if (this.maxFile && file.size > this.maxFile) {
                // 前端先拦一道，明显超限的不必等服务端跑完才知道
                this.markError(row, `超过单文件上限 ${fmtBytes(this.maxFile)}`);
                failed += 1;
                continue;
            }
            try {
                await this.uploadOne(file, row);
                this.markDone(row);
                done += 1;
            } catch (error) {
                this.markError(row, error.message);
                failed += 1;
            }
        }
        this.busy = false;
        this.input.value = "";
        this.setNote(done, failed);
        if (done) {
            // 列表是服务端渲染的，传完只能整页重取才看得见新卡片
            setTimeout(() => window.location.reload(), 900);
        }
    }

    uploadOne(file, row) {
        return new Promise((resolve, reject) => {
            const data = new FormData();
            data.append("file", file);
            data.append("category", this.form.querySelector("[data-lib-category]").value);
            data.append("folder_id", this.form.querySelector("[data-lib-folder]").value);
            data.append("tags", this.form.querySelector("[data-lib-tags]").value);
            data.append("csrf_token", this.csrf);
            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/tutoring/library/upload");
            xhr.upload.addEventListener("progress", (ev) => {
                if (ev.lengthComputable) {
                    row.fill.style.width = `${Math.min(99, Math.round((ev.loaded / ev.total) * 100))}%`;
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
                    const reason = (payload && payload.failed && payload.failed[0] && payload.failed[0].error)
                        || (payload && payload.error)
                        || `上传失败（HTTP ${xhr.status}）`;
                    reject(new Error(reason));
                }
            });
            xhr.addEventListener("error", () => reject(new Error("网络中断，这个文件没传完")));
            xhr.addEventListener("abort", () => reject(new Error("已取消")));
            xhr.send(data);
        });
    }

    // ---- 进度行的 DOM ----
    // 文件名是外来输入，一律走 textContent，不拼 HTML
    addRow(name, size) {
        const row = document.createElement("div");
        row.className = "o_lib_queue_row d-flex align-items-center gap-2";
        const icon = document.createElement("i");
        icon.className = "fa fa-file-o text-muted";
        const label = document.createElement("span");
        label.className = "o_lib_queue_name text-truncate";
        label.title = name;
        label.textContent = name;
        const sizeEl = document.createElement("span");
        sizeEl.className = "text-muted small";
        sizeEl.textContent = fmtBytes(size);
        const bar = document.createElement("div");
        bar.className = "progress o_lib_row_progress";
        const fill = document.createElement("div");
        fill.className = "progress-bar";
        fill.style.width = "0%";
        bar.appendChild(fill);
        const note = document.createElement("span");
        note.className = "small text-muted";
        row.append(icon, label, sizeEl, bar, note);
        this.queue.appendChild(row);
        return { row, icon, bar, fill, note };
    }

    markDone(row) {
        row.icon.className = "fa fa-check text-success";
        row.bar.remove();
        row.note.textContent = "已上传";
    }

    markError(row, message) {
        row.icon.className = "fa fa-times text-danger";
        row.bar.remove();
        row.note.className = "small text-danger";
        row.note.textContent = message;
    }

    setNote(done, failed) {
        const line = document.createElement("div");
        line.className = "small text-muted mt-1";
        const parts = [];
        if (done) {
            parts.push(`已上传 ${done} 个文件，马上刷新列表…`);
        }
        if (failed) {
            parts.push(`${failed} 个没传上去，看上面每一行的原因`);
        }
        line.textContent = parts.join("　");
        this.queue.appendChild(line);
    }
}

registry
    .category("public.interactions")
    .add("tutoring_center.library_upload", LibraryUpload);
