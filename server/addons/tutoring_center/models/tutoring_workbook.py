from odoo import _, fields, models


class TutoringWorkbook(models.Model):
    _name = 'tutoring.workbook'
    _description = '练习册'
    _order = 'name'

    name = fields.Char('名称', required=True)
    note = fields.Char('备注')
    active = fields.Boolean('启用', default=True)

    mistake_ids = fields.One2many('tutoring.mistake', 'workbook_id', string='错题')
    mistake_count = fields.Integer('错题数', compute='_compute_mistake_count')

    file_ids = fields.One2many('tutoring.workbook.file', 'workbook_id', string='教材文件')
    file_count = fields.Integer('教材数', compute='_compute_file_count')

    def _compute_mistake_count(self):
        for workbook in self:
            workbook.mistake_count = len(workbook.mistake_ids)

    def _compute_file_count(self):
        for workbook in self:
            workbook.file_count = len(workbook.file_ids)

    def _form_dialog(self, view_xmlid, name, res_id, context=None):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': self._name,
            'res_id': res_id,
            'view_mode': 'form',
            'views': [(self.env.ref('tutoring_center.%s' % view_xmlid).id, 'form')],
            'target': 'new',
            'context': dict({'dialog_size': 'large'}, **(context or {})),
        }

    def action_open_reader(self):
        """列表里单击整行 → 只读页中页：看这本书有哪些教材、点进去滚动阅读。

        行点击不再落到单元格编辑，所以不会"一碰就改库"。
        footer 关掉：只读页不该出现保存/放弃按钮。
        """
        self.ensure_one()
        return self._form_dialog(
            'view_tutoring_workbook_form_reader', self.display_name, self.id,
            context={'footer': False})

    def action_open_edit(self):
        """「修改」→ 同一弹窗位置换成可编辑表单（改书名/备注、增删教材文件）。"""
        self.ensure_one()
        return self._form_dialog('view_tutoring_workbook_form_edit', _('修改练习册'), self.id)

    def action_new_workbook(self):
        """控制栏「新建练习册」：添加元素也要走明确按钮，不在表格里就地加行。

        刻意不加 @api.model：列表按钮 RPC 恒以 [ids] 作为第一个位置参数
        （空选区是 [[]]），带该标记反而会 TypeError。
        """
        return self._form_dialog('view_tutoring_workbook_form_edit', _('新建练习册'), False)

    def action_new_file(self):
        """「上传教材」→ 新建一条教材文件，本书作为默认归属。"""
        self.ensure_one()
        action = self.env['tutoring.workbook.file']._viewer_action(
            context={'default_workbook_id': self.id})
        action['name'] = _('上传教材')
        return action
