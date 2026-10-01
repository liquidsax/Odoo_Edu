import { registry } from "@web/core/registry";
import { standardFieldProps } from "../standard_field_props";

import { Component, useState } from "@odoo/owl";

export class ChiliField extends Component {
    static template = "tutoring_center.ChiliField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({ hover: -1 });
    }

    get fieldString() {
        return this.props.record.fields[this.props.name].string;
    }
    get selection() {
        return Array.from(this.props.record.fields[this.props.name].selection);
    }
    get minLevel() {
        return Math.min(...this.levels);
    }
    get maxLevel() {
        return Math.max(...this.levels);
    }
    get levels() {
        return this.selection.map((o) => parseInt(o[0], 10));
    }
    /** 渲染 1..max 共 max 格，点第 n 格即 n 辣椒；低于最小档的格子归到最小档 */
    get slots() {
        return Array.from({ length: this.maxLevel }, (_, i) => i + 1);
    }
    get level() {
        const current = parseInt(this.props.record.data[this.props.name], 10);
        return Number.isNaN(current) ? 0 : current;
    }
    get shownLevel() {
        return this.state.hover > -1 ? this.state.hover : this.level;
    }
    slotLevel(slot) {
        return Math.max(slot, this.minLevel);
    }
    isFilled(slot) {
        return slot <= this.shownLevel;
    }
    tooltip(slot) {
        return `${this.fieldString}: ${this.slotLevel(slot)} 辣椒`;
    }
    async onChiliClicked(slot) {
        if (this.props.readonly) {
            return;
        }
        await this.updateRecord(this.slotLevel(slot));
    }
    async updateRecord(level) {
        const record = this.props.record;
        if (record.data[this.props.name] === String(level)) {
            return;
        }
        // 未保存的新行/正在编辑的行只改值，交给该行自己的保存流程，
        // 否则会带着必填项为空就提交
        const save = !record.isNew && !record.isInEdition;
        await record.update({ [this.props.name]: String(level) }, { save });
    }
}

export const chiliField = {
    component: ChiliField,
    supportedTypes: ["selection"],
    extractProps: ({}, dynamicInfo) => ({
        // 列表里未进入编辑态时也要可点：只保留 arch 上的 readonly
        readonly: dynamicInfo.readonly,
    }),
};

registry.category("fields").add("chili", chiliField);
