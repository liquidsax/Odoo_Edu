from odoo import _, api, fields, models


class TutoringWorkbookFile(models.Model):
    """练习册的一份教材文件（上册 / 下册 / 答案册……可多份）。

    正文与配额统一放在知识库条目里：`_inherits` 之后每条教材文件
    都是 category=workbook 的 `tutoring.library.item`，所以教材同样
    占用户容量、能在知识库里被搜到和打标签，删除也一并释放。

    content 仍是 `attachment=False`（在条目表里存 bytea），pg_dump 即全量备份。
    大文件受 Odoo 的 128MiB 请求体上限约束，所以一本厚书按页切成几份挂进来，
    靠 page_from/page_to 记"全书连续页码"，逻辑上仍是一册。
    """
    _name = 'tutoring.workbook.file'
    _description = '练习册教材文件'
    _inherits = {'tutoring.library.item': 'item_id'}
    _order = 'workbook_id, page_from, id'

    item_id = fields.Many2one(
        'tutoring.library.item', string='知识库条目', required=True,
        ondelete='cascade', index=True)
    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True,
        ondelete='cascade', index=True)
    # 子表自己的 name 是"分册名"（上册 / 答案册），会盖住继承来的条目标题，
    # 所以每次写完都把条目标题同步成"书名 · 分册名"，知识库里才认得出是哪一本
    name = fields.Char('名称', required=True, default='新教材')
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

    @api.model_create_multi
    def create(self, vals_list):
        """教材一律算作练习册分类，归属当前上传者。

        整趟带 `no_workbook_link`：条目那边现在会在"分类＝练习册/教辅"时反过来
        建教材文件，委托继承又是先写父记录，不设这道闸门两边就互相触发。
        """
        for vals in vals_list:
            vals.setdefault('category', 'workbook')
            vals.setdefault('user_id', self.env.user.id)
        files = super(
            TutoringWorkbookFile, self.with_context(no_workbook_link=True)).create(vals_list)
        files._sync_item_title()
        return files

    def write(self, vals):
        """换过正文或改过页码范围，之前抽的单页就都不作数了。"""
        res = super(TutoringWorkbookFile, self.with_context(no_workbook_link=True)).write(vals)
        if {'content', 'page_from', 'page_to'} & set(vals):
            self.env['tutoring.workbook.page']._invalidate_for_files(self)
        if {'name', 'workbook_id'} & set(vals):
            self._sync_item_title()
        return res

    def unlink(self):
        """教材删了，它在知识库里的那条也一起走（连带释放容量）。"""
        items = self.item_id
        res = super().unlink()
        items.unlink()
        return res

    def _sync_item_title(self):
        """让知识库里的标题带上书名，避免列表里只剩"上册"两个字。

        分册名与书名一致时不拼：知识库自动建书走的就是这一路，两边同名，
        拼出来是「一数 · 一数」，用户在自己列表里看到重复的字眼只会以为是坏了。
        """
        for file in self.filtered('item_id'):
            book = (file.workbook_id.name or '').strip()
            part = (file.name or '').strip()
            title = part if book == part else ' · '.join(p for p in (book, part) if p)
            title = title or file.item_id.name
            if file.item_id.name != title:
                file.item_id.write({'name': title, 'category': 'workbook'})

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
