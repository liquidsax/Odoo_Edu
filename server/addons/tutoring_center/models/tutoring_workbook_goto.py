from odoo import _, fields, models
from odoo.exceptions import UserError


class TutoringWorkbookGoto(models.TransientModel):
    """「按页码定位」：输整本书的页号，自动挑出含这一页的分册并跳到那一页。

    一本厚书受上传体积上限约束会按页切成几份，但使用者心里只有"这本书的第 80 页"，
    这个向导就是把全局页号翻译成分册 + 分册内局部页号的唯一入口。
    """
    _name = 'tutoring.workbook.goto'
    _description = '练习册按页码定位'

    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True, readonly=True)
    page = fields.Integer('页码', required=True)

    def action_goto(self):
        self.ensure_one()
        book = self.workbook_id
        parts = book.file_ids.filtered(
            lambda f: f.page_from and f.page_to and f.page_from <= self.page <= f.page_to)
        if not parts:
            ranges = '、'.join(
                f'{f.page_from}–{f.page_to}' for f in book.file_ids if f.page_from and f.page_to)
            raise UserError(_(
                '第 %(page)s 页不在已上传的分册里。现有页码范围：%(ranges)s。',
                page=self.page, ranges=ranges or _('（分册未填页码范围）'),
            ))
        action = parts[0]._viewer_action(res_id=parts[0].id)
        action['context']['target_page'] = self.page
        action['name'] = _('%(book)s · 第 %(page)s 页') % {'book': book.name, 'page': self.page}
        return action
