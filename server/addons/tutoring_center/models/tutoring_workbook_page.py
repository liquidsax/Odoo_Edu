import base64
import io
import logging

from odoo import _, api, fields, models
from odoo.tools.pdf import PdfReader, PdfWriter

_logger = logging.getLogger(__name__)


class TutoringWorkbookPage(models.Model):
    """从整本教材里抽出来的**一页**，存下来当缓存（同一页的多条错题共用一份）。

    为什么要抽：核心 `pdf_viewer` 组件用 `/web/content?model=&field=&id=` 取文件，
    而 `/web/content` 不支持 Range 请求（Odoo 源码里没有任何 `Accept-Ranges`），
    pdf.js 于是只能把整本 PDF 拉进浏览器——一本书几十 MB，只为看一页。
    服务端用 pypdf 把那一页另存成一份单页 PDF，阅读器就只加载这一页。

    抽出的一页可能比原文件里"看起来"更大（页自带的资源会被复制一份），但和整本
    相比仍是几个数量级的差距。
    """
    _name = 'tutoring.workbook.page'
    _description = '练习册单页'
    _order = 'file_id, pdf_page'

    file_id = fields.Many2one(
        'tutoring.workbook.file', string='教材文件', required=True,
        ondelete='cascade', index=True)
    pdf_page = fields.Integer(
        '页号', required=True, index=True, help='在这份 PDF 内的物理页号，从 1 开始')
    content = fields.Binary('单页 PDF', attachment=True)

    _uniq_file_page = models.Constraint(
        'unique(file_id, pdf_page)',
        _('同一份教材的同一页只能有一份缓存。'))

    @api.model
    def _pdf_for(self, file, pdf_page):
        """取（必要时生成并缓存）某份教材的某一页，返回单页 PDF 的 base64 或 False。

        抽不出页时返回 False 而不是抛异常：本方法在计算字段里跑，
        抛错等于把整个错题弹窗打成 500。
        """
        if not file or pdf_page < 1:
            return False
        cached = self.search([('file_id', '=', file.id), ('pdf_page', '=', pdf_page)], limit=1)
        if cached and cached.content:
            return cached.content
        data = self._extract_single(file.content, pdf_page)
        if data and not cached and not self.env.cr.readonly:
            # /web/content 走只读游标，写不进去；正常顺序是表单读先到（可写）建好缓存，
            # 之后阅读器再取这一页时直接命中缓存。
            self.create({'file_id': file.id, 'pdf_page': pdf_page, 'content': data})
        return data

    @api.model
    def _extract_single(self, source_base64, pdf_page):
        """把整本 PDF 的第 `pdf_page` 页单独存成一份 PDF，返回 base64；失败返回 False。"""
        raw = base64.b64decode(source_base64) if source_base64 else b''
        if not raw:
            return False
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                reader.decrypt('')
            pages = reader.pages
            if not 1 <= pdf_page <= len(pages):
                _logger.info('教材只有 %s 页，取不到第 %s 页', len(pages), pdf_page)
                return False
            writer = PdfWriter()
            writer.add_page(pages[pdf_page - 1])
            buffer = io.BytesIO()
            writer.write(buffer)
            return base64.b64encode(buffer.getvalue())
        except Exception:  # noqa: BLE001 - 教材本身坏了也不该让错题页打不开
            _logger.exception('抽取教材第 %s 页失败', pdf_page)
            return False

    def _invalidate_for_files(self, files):
        """正文或页码范围变了，之前抽的页全作废。"""
        stale = self.search([('file_id', 'in', files.ids)])
        if stale:
            stale.unlink()
