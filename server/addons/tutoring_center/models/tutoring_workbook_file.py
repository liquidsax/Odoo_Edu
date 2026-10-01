from odoo import _, api, fields, models


class TutoringWorkbookFile(models.Model):
    """练习册的一份教材文件（上册 / 下册 / 答案册……可多份）。

    content 用 attachment=False：PDF 正文直接落在本表 bytea 列里，
    pg_dump 即全量备份，不会散落到磁盘 filestore。
    """
    _name = 'tutoring.workbook.file'
    _description = '练习册教材文件'
    _order = 'workbook_id, id'

    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True,
        ondelete='cascade', index=True)
    # 给默认值是为了"只选文件、没题名"也能一次保存成功（required 会拦空值）
    name = fields.Char('名称', required=True, default='新教材')
    content = fields.Binary('教材 PDF', attachment=False)
    filename = fields.Char('文件名')

    @api.depends('workbook_id', 'name')
    def _compute_display_name(self):
        for file in self:
            file.display_name = ' · '.join(
                part for part in (file.workbook_id.name, file.name) if part
            ) or _('未命名教材')

    @api.model
    def _viewer_action(self, res_id=False, context=None):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': res_id,
            'view_mode': 'form',
            'views': [(self.env.ref('tutoring_center.view_tutoring_workbook_file_form').id, 'form')],
            'target': 'new',
            'context': dict({'dialog_size': 'extra-large'}, **(context or {})),
        }

    def action_open_viewer(self):
        """单击文件行：页中页里滚动阅读；传错就在同一处重新选择文件后保存。

        刻意不加 @api.model：列表按钮 RPC 恒以 [ids] 作为第一个位置参数。
        """
        self.ensure_one()
        action = self._viewer_action(res_id=self.id)
        action['name'] = self.display_name
        return action
