import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { loadPDFJSAssets } from "@web/core/utils/pdfjs";

/* 「原页大图」这一版：把每道错题"出处那一页"的单页 PDF 在浏览器里画成封面。
 *
 * 为什么在客户端画：这台机器的 Python 里没有任何 PDF 光栅化能力（只有 PyPDF2 / pdfminer /
 * Pillow），而 Odoo 自带 pdf.js，`web.assets_frontend` 打包了 `web/static/src/core/**`，
 * 所以门户页 import 一句 `loadPDFJSAssets` 就够了——零新依赖、零 token、不用装 poppler。
 *
 * 一张一张排着来，不并发：一次刷十几道，同时拉十几份 PDF 会把这条本地连接挤满，
 * 而且用户看的是从上往下的顺序，先画上面那张更划算。
 * 任何一张失败（没传正文、页码越界、pdf.js 没加载起来）都只让那一张退回文字封面，
 * 并把原因写在卡片上——封面版最怕的是"整屏空白但不知道为什么"。
 */

const TARGET_WIDTH = 560;
const WORKER_SRC = "/web/static/lib/pdfjs/build/pdf.worker.js";

export class MistakeCovers extends Interaction {
    static selector = "[data-mistake-covers]";

    setup() {
        this.queue = Array.from(this.el.querySelectorAll("img[data-cover-pdf]"));
        this.busy = false;
        this.renderAll();
    }

    async renderAll() {
        // 这一版可能一张 PDF 封面都没有（比如"文字大图"那版），那就别为它加载 pdf.js 这一大包
        if (this.busy || !this.queue.length) {
            return;
        }
        this.busy = true;
        try {
            await loadPDFJSAssets();
            globalThis.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_SRC;
        } catch (error) {
            this.queue.forEach((img) => this.fallback(img, "这台设备的浏览器加载不了 pdf.js"));
            this.busy = false;
            return;
        }
        for (const img of this.queue) {
            await this.renderOne(img);
        }
        this.busy = false;
    }

    async renderOne(img) {
        const card = img.closest("[data-mistake-cover]");
        let doc;
        try {
            const response = await fetch(img.dataset.coverPdf, { credentials: "same-origin" });
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
            doc = await globalThis.pdfjsLib.getDocument({
                data: await response.arrayBuffer(),
            }).promise;
            const page = await doc.getPage(1);
            const base = page.getViewport({ scale: 1 });
            const viewport = page.getViewport({ scale: TARGET_WIDTH / base.width });
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(viewport.width);
            canvas.height = Math.round(viewport.height);
            await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
            img.src = canvas.toDataURL("image/jpeg", 0.82);
            img.classList.add("o_cover_ready");
            if (card) {
                card.classList.add("is-photo");
                card.classList.remove("is-loading");
            }
        } catch (error) {
            this.fallback(img, "这一页抽不出来（没传教材正文，或页码超出了）");
        } finally {
            if (doc) {
                await doc.destroy().catch(() => {});
            }
        }
    }

    fallback(img, reason) {
        const card = img.closest("[data-mistake-cover]");
        if (!card || card.classList.contains("is-fallback")) {
            return;
        }
        card.classList.add("is-fallback");
        card.classList.remove("is-loading");
        const note = card.querySelector("[data-cover-note]");
        if (note) {
            note.textContent = reason;
        }
    }
}

registry.category("public.interactions").add("tutoring_center.mistake_covers", MistakeCovers);
