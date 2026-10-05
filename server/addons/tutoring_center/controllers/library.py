import base64
import logging
import re
from urllib.parse import quote

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.tutoring_library_item import MAX_EDIT_BYTES, b64_to_bytes
from ..models.library_markdown import render_markdown

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
        folder = self._own_folder(kw.get('folder_id'))
        mistake = self._own_mistake(kw.get('mistake_id'))
        if mistake and not kw.get('category'):
            category = 'mistake'

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
                    'folder_id': folder.id if folder else False,
                    'mistake_id': mistake.id if mistake else False,
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
        # Binary 字段读出来是 base64 编码后的 bytes（Odoo 不自动解码），
# 这里负责解码回原始字节再写响应；数据异常时返回明确的 404 而不是 500。
        try:
            data = b64_to_bytes(item.content)
        except Exception:  # noqa: BLE001 - 内容损坏不该炸成 500
            _logger.warning('知识库条目 %s 的正文不是合法 base64，可能已损坏', item_id)
            return request.not_found()
        filename = self._clean_name(item.filename or item.name or 'file')
        # SVG 里能带脚本：同源内联回吐等于给存储型 XSS 开门（虽然只有本人读得到，
        # 但同一浏览器里还登着后台）。所以 SVG 一律按附件下载，另外再上一道 nosniff。
        if item.mimetype == 'image/svg+xml':
            disposition = 'attachment'
        else:
            disposition = 'attachment' if download else 'inline'
        headers = [
            ('Content-Type', item.mimetype or 'application/octet-stream'),
            ('Content-Length', str(len(data))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Content-Disposition',
             "%s; filename*=UTF-8''%s" % (disposition, quote(filename))),
        ]
        return request.make_response(data, headers)

    # ------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------

    def _clean_name(self, filename):
        return SAFE_FILENAME.sub('_', (filename or '').strip()) or '未命名文件'

    def _own_folder(self, folder_id):
        """把上传时带的 folder_id 收敛成"本人的那一个"。

        必须走 search 而不是 browse().exists()：只有 search 会拼上记录规则，
        别人文件夹的 id 到这儿就是搜不到，等价于没填。
        """
        try:
            fid = int(folder_id)
        except (TypeError, ValueError):
            return None
        return request.env['tutoring.library.folder'].search(
            [('id', '=', fid)], limit=1)

    def _own_mistake(self, mistake_id):
        """同上：错题的 id 也只有"当前账号读得到"才算数。

        学生只能挂自己学生的错题，老师能挂任何一条——这条界线由 tutoring.mistake
        自己的记录规则画，不在这里重复一遍。
        """
        try:
            mid = int(mistake_id)
        except (TypeError, ValueError):
            return None
        return request.env['tutoring.mistake'].search([('id', '=', mid)], limit=1)

    # ------------------------------------------------------------
    # 实时预览：编辑态把草稿交给同一份服务端渲染器
    # ------------------------------------------------------------
    @http.route('/tutoring/library/render_md', type='http', auth='user',
                methods=['POST'], csrf=True)
    def library_render_md(self, **kw):
        """Markdown 草稿 → 渲染后的 HTML 片段（不写库）。

        只留这一个渲染器：所见即所存靠的就是"编辑预览和落库后显示走同一段代码"，
        前端再写一个解析器迟早和后端对不上。体积按编辑上限收，防一个人贴几十 MB
        文本把 worker 卡在渲染上。
        """
        body = kw.get('body') or ''
        if len(body.encode('utf-8', errors='ignore')) > MAX_EDIT_BYTES:
            return request.make_json_response(
                {'ok': False, 'error': _('草稿太长，先保存再看渲染效果。')})
        return request.make_json_response({'ok': True, 'html': render_markdown(body)})

    def _title_of(self, filename, title):
        """没填标题就用文件名去掉扩展名。"""
        title = (title or '').strip()
        if title:
            return title
        return filename.rpartition('.')[0] or filename or _('未命名文件')

