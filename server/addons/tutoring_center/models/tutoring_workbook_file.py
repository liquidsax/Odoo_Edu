from odoo import _, api, fields, models


class TutoringWorkbookFile(models.Model):
    """练习册的一份教材文件（上册 / 下册 / 答案册……可多份）。

    content 用 attachment=False：PDF 正文直接落在本表 bytea 列里，
    pg_dump 即全量备份，不会散落到磁盘 filestore。

    大文件受 Odoo 的 128MiB 请求体上限约束（JSON-RPC 走不到按参数放宽的那步），
    所以一本厚书按页切成几份挂进来，靠 page_from/page_to 记"全书连续页码"，
    在逻辑上仍是一册。
    """
    _name = 'tutoring.workbook.file'
    _description = '练习册教材文件'
    _order = 'workbook_id, page_from, id'

    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True,
        ondelete='cascade', index=True)
    # 给默认值是为了"只选文件、没题名"也能一次保存成功（required 会拦空值）
    name = fields.Char('名称', required=True, default='新教材')
    content = fields.Binary('教材 PDF', attachment=False)
    filename = fields.Char('文件名')
    page_from = fields.Integer(
        '起始页', help='整本书的连续页号（PDF 物理页，封面算第 1 页）')
    page_to = fields.Integer('结束页')
    page_range = fields.Char('页码范围', compute='_compute_page_range')

    # 核心 pdf_viewer 组件按 `<字段名>_page` 取值拼进 pdf.js 的 #page=N，
    # 所以这个钩子字段必须就叫 content_page，改名它就读不到了
    content_page = fields.Integer('打开页', compute='_compute_content_page')

    @api.depends('page_from', 'page_to')
    def _compute_page_range(self):
        for file in self:
            if file.page_from and file.page_to:
                file.page_range = f'第 {file.page_from}–{file.page_to} 页'
            elif file.page_from:
                file.page_range = f'第 {file.page_from} 页起'
            else:
                file.page_range = ''

    @api.depends('page_from')
    @api.depends_context('target_page')
    def _compute_content_page(self):
        target = self.env.context.get('target_page')
        for file in self:
            local = 1
            if target and file.page_from and target >= file.page_from:
                local = target - file.page_from + 1
            file.content_page = max(local, 1)

    @api.depends('workbook_id', 'name')
    def _compute_display_name(self):
        for file in self:
            file.display_name = ' · '.join(
                part for part in (file.workbook_id.name, file.name) if part
            ) or _('未命名教材')

    def write(self, vals):
        """换过正文或改过页码范围，之前抽的单页就都不作数了。"""
        res = super().write(vals)
        if {'content', 'page_from', 'page_to'} & set(vals):
            self.env['tutoring.workbook.page']._invalidate_for_files(self)
        return res

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
