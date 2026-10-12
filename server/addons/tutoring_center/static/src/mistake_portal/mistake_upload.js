import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/* 错题页的"拖照片记题"：只做一件事——把拖进来的文件塞进原生 file input。
 *
 * 提交不接管：表单还是浏览器自己的 multipart POST，服务端处理完 303 回列表页，
 * 回执（"已记录 N 道"）由页面本身说。比再写一条 XHR 通道少一份重复实现，
 * 也少了"JS 挂了就不能记题"这条新依赖——没跑这段 JS 的浏览器照样能点选文件提交。
 */

const MAX_FILES = 10;

export class MistakeDrop extends Interaction {
    static selector = "form[data-mistake-drop]";

    setup() {
        this.zone = this.el.querySelector("[data-mistake-dropzone]");
        this.input = this.el.querySelector("[data-mistake-input]");
        this.state = this.el.querySelector("[data-mistake-dropstate]");
        if (!this.zone || !this.input) {
            return;
        }
        this.zone.addEventListener("dragover", (ev) => {
            ev.preventDefault();
            this.zone.classList.add("o_mistake_dragover");
        });
        this.zone.addEventListener("dragleave", () => {
            this.zone.classList.remove("o_mistake_dragover");
        });
        this.zone.addEventListener("drop", (ev) => {
            ev.preventDefault();
            this.zone.classList.remove("o_mistake_dragover");
            this.take(ev.dataTransfer ? ev.dataTransfer.files : null);
        });
        // 点整块虚线区就能开文件选择器，不必精确去点下面那个小输入框
        this.zone.addEventListener("click", (ev) => {
            if (ev.target === this.input) {
                return;
            }
            this.input.click();
        });
        this.input.addEventListener("change", () => this.report(this.input.files));
    }

    take(files) {
        const picked = Array.from(files || []).filter((f) => (f.type || "").startsWith("image/"));
        if (!picked.length) {
            this.report(null, '没看到图片，拖 jpg / png / webp 进来');
            return;
        }
        const kept = picked.slice(0, MAX_FILES);
        try {
            // 整份替换 input.files：拖两次不会累加，也不必先手动清空
            const dt = new DataTransfer();
            kept.forEach((f) => dt.items.add(f));
            this.input.files = dt.files;
        } catch (error) {
            // 老浏览器不让改 input.files：交回原生选择器，别把记题这条路堵死
            this.report(null, "这个浏览器不支持拖拽，请点虚线框里那行「选择文件」");
            return;
        }
        this.report(
            this.input.files,
            kept.length < picked.length ? `一次最多 ${MAX_FILES} 张，多出来的没收` : ""
        );
    }

    report(files, note) {
        if (!this.state) {
            return;
        }
        const n = files ? files.length : 0;
        this.state.textContent = n
            ? `已选好 ${n} 张，点「记下这几道」就各记一条` + (note ? `（${note}）` : "")
            : note || "";
    }
}

registry.category("public.interactions").add("tutoring_center.mistake_drop", MistakeDrop);
