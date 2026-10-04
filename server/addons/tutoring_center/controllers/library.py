import base64
import logging
import re
from urllib.parse import quote

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

SAFE_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]')


class TutoringLibraryController(http.Controller):

    # ------------------------------------------------------------
    # 上传：走 multipart 而不是 JSON-RPC
    # ------------------------------------------------------------
    # 原因有两条：一是 base64 会让请求体膨胀 1/3，128MiB 的请求体上限下
    # 实际只能传 ~96MB；二是 XHR 发 FormData 才有 upload.onprogress，
    # 前端能拿到真实的字节进度，不用假装在转圈。
    @http.route('/tutoring/library/upload', type='http', auth='user', methods=['POST'], csrf=True)
    def library_upload(self, **kw):
        files = request.httprequest.files.getlist('file')
        if not files:
            return request.make_json_response(
                {'ok': False, 'error': _('没有收到文件，重新选一个试试。')})

        model = request.env['tutoring.library.item']
        category = kw.get('category') or 'other'
        if category not in dict(model._fields['category'].selection):
            category = 'other'

        uploaded, failed = [], []
        for upload in files:
            raw = upload.read()
            filename = self._clean_name(upload.filename or '')
            try:
                item = model.create({
                    'name': self._title_of(filename, kw.get('title')),
                    'filename': filename,
                    'content': base64.b64encode(raw).decode(),
                    'category': category,
                    'tag_ids': model.tags_from_names(kw.get('tags')),
                })
                # 逐个提交：下一个文件失败要回滚时，不能把已成功的也带走
                request.env.cr.commit()
                uploaded.append({
                    'id': item.id,
                    'name': item.name,
                    'size': item.file_size,
                    'size_text': item.size_text,
                })
            except UserError as err:
                request.env.cr.rollback()
                failed.append({'name': filename, 'error': str(err)})
            except Exception:  # noqa: BLE001 - 单个文件写坏不该让整批上传失败
                request.env.cr.rollback()
                _logger.exception('知识库上传失败：%s', filename)
                failed.append({'name': filename, 'error': _('写入失败，请重试。')})

        return request.make_json_response({
            'ok': not failed,
            'uploaded': uploaded,
            'failed': failed,
            'quota': model.quota_state(),
        })

    # ------------------------------------------------------------
    # 读取：预览与下载走同一条路由，download=1 才是附件下载
    # ------------------------------------------------------------
    @http.route('/tutoring/library/<int:item_id>/raw', type='http', auth='user')
    def library_raw(self, item_id, download=False, **kw):
        item = request.env['tutoring.library.item'].browse(item_id).exists()
        if not item:
            return request.not_found()
        try:
            item.check_access('read')
        except AccessError:
            return request.not_found()
        data = base64.b64decode(item.content or b'')
        filename = self._clean_name(item.filename or item.name or 'file')
        disposition = 'attachment' if download else 'inline'
        headers = [
            ('Content-Type', item.mimetype or 'application/octet-stream'),
            ('Content-Length', str(len(data))),
            ('Content-Disposition',
             "%s; filename*=UTF-8''%s" % (disposition, quote(filename))),
        ]
        return request.make_response(data, headers)

    # ------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------

    def _clean_name(self, filename):
        return SAFE_FILENAME.sub('_', (filename or '').strip()) or '未命名文件'

    def _title_of(self, filename, title):
        """没填标题就用文件名去掉扩展名。"""
        title = (title or '').strip()
        if title:
            return title
        return filename.rpartition('.')[0] or filename or _('未命名文件')

