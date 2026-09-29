import { loadBundle } from "@web/core/assets";
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * 门户学习页图表：模板输出 .tutoring_chart（含 data-chart-type / data-chart-data），
 * 这里用 Odoo 自带的 Chart.js 画线图/柱状图。
 */
export class LearningChart extends Interaction {
    static selector = ".tutoring_chart";

    async willStart() {
        await loadBundle("web.chartjs_lib");
    }

    start() {
        let data;
        try {
            data = JSON.parse(this.el.dataset.chartData);
        } catch {
            return;
        }
        if (!data || !data.labels || !data.labels.length) {
            this.el.classList.add("text-muted", "text-center", "p-4");
            this.el.textContent = "暂无数据";
            return;
        }
        if (this.el.dataset.maxHeight) {
            this.el.style.height = this.el.dataset.maxHeight + "px";
        }
        const canvas = this.el.querySelector("canvas");
        const type = this.el.dataset.chartType || "line";
        this.chart = new Chart(canvas, {
            type,
            data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        suggestedMax: 100,
                        ticks: { callback: (value) => value + "%" },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%` } },
                },
            },
        });
        this.registerCleanup(() => this.chart?.destroy());
    }
}

registry.category("public.interactions").add("tutoring_center.learning_chart", LearningChart);
