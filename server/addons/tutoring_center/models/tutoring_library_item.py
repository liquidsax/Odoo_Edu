import base64
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CATEGORY_SELECTION = [
    ('workbook', '练习册 / 教辅'),
    ('leetcode', 'LeetCode'),
    ('note', '笔记'),
    ('doc', '资料文档'),
    ('other', '其他'),
]

# 允许在网页里直接内嵌预览的类型；其余一律给下载链接
IMAGE_EXTS = ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg')
MIMETYPES = {
    'pdf': 'application/pdf',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'txt': 'text/plain',
    'md': 'text/markdown',
    'csv': 'text/csv',
    'zip': 'application/zip',
}


def bytes_from_base64(value):
    """Binary 字段里是 base64 文本，换回原始字节数（不含填充）。

    调用方可能给 str 也可能给 bytes（base64 编码后的字节串），两种都接。
    """
    if not value:
        return 0
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).decode('ascii', errors='ignore')
    else:
        text = str(value)
    text = text.strip()
    padding = text.endswith('==') and 2 or (text.endswith('=') and 1 or 0)
    return max(len(text) * 3 // 4 - padding, 0)


def fmt_bytes(num):
    """1024 进位的易读体积；配额提示都走它，避免各处口径不一。

    分档要留一点余量，否则"1GB 少 30 字节"会被算进 MB 档再四舍五入成
    "1024.0 MB"，看着像超了配额。
    """
    size = float(num or 0)
    if size < 1024:
        return '%d B' % round(size)
    if size < 1024 ** 2 * 0.995:
        value = size / 1024
        return '%.0f KB' % value if value >= 1000 else '%.1f KB' % value
    if size < 1024 ** 3 * 0.995:
        value = size / 1024 ** 2
        return '%.0f MB' % value if value >= 1000 else '%.1f MB' % value
    return '%.2f GB' % (size / 1024 ** 3)


class TutoringLibraryTag(models.Model):
    _name = 'tutoring.library.tag'
    _description = '知识库标签'
    _order = 'name'

    name = fields.Char('标签', required=True, index=True)
    color = fields.Integer('颜色序号', help='0~11，用于卡片上的标签底色')
    item_ids = fields.Many2many(
        'tutoring.library.item', 'tutoring_library_item_tag_rel',
        'tag_id', 'item_id', string='条目')

    _name_uniq = models.Constraint('unique(name)', _('已经有同名的标签了。'))


class TutoringLibraryItem(models.Model):
    """知识库条目：每位用户自己的顶层内容空间，一条记录就是一个文件。

    练习册的教材 PDF 通过委托继承（`tutoring.workbook.file._inherits`）
    落在这张表上，所以"练习册教材"天然是 category=workbook 的条目，
    与 LeetCode 错题、笔记、资料文档共用同一套存储和容量配额。

    正文用 `attachment=False` 存进本表 bytea 列（和教材 PDF 一致），
    pg_dump 即全量备份；代价是库内占用约为原始文件的 4/3（base64）。
    """
    _name = 'tutoring.library.item'
    _description = '知识库条目'
    _order = 'upload_date desc, id desc'

    # 容量参数：默认 1GB 总配额、单文件 64MB。64MB 是留足余量的取值——
    # Odoo 给每个请求体硬设 128MiB 上限，multipart 不膨胀，64MB 远在安全区内
    DEFAULT_QUOTA_BYTES = 1024 ** 3
    DEFAULT_MAX_FILE_BYTES = 64 * 1024 ** 2
    QUOTA_PARAM = 'tutoring_center.library_quota_bytes'
    MAX_FILE_PARAM = 'tutoring_center.library_max_file_bytes'

    # 委托继承时 Odoo 只搬"父有子没有"的字段：教材文件的 name 与这里同名，
    # 它不会跟着过去，所以给个兜底默认值（真实标题由教材文件建好后同步过来）
    name = fields.Char('标题', required=True, default=lambda self: _('未命名文件'))
    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    category = fields.Selection(
        CATEGORY_SELECTION, string='分类', required=True, default='other',
        index=True, help='练习册只是其中一个分类，内容类型本身不受限制')
    tag_ids = fields.Many2many(
        'tutoring.library.tag', 'tutoring_library_item_tag_rel',
        'item_id', 'tag_id', string='标签')

    content = fields.Binary('文件', attachment=False)
    filename = fields.Char('文件名')
    file_size = fields.Integer(
        '大小(字节)', compute='_compute_file_meta', store=True,
        help='原始文件字节数；配额按它统计')
    upload_date = fields.Datetime('上传时间', default=fields.Datetime.now, index=True)

    ext = fields.Char('扩展名', compute='_compute_file_meta', store=True)
    mimetype = fields.Char('类型', compute='_compute_file_meta', store=True)
    kind = fields.Selection(
        [('pdf', 'PDF'), ('image', '图片'), ('other', '文件')],
        string='预览方式', compute='_compute_file_meta', store=True)
    size_text = fields.Char('大小', compute='_compute_size_text')

    workbook_file_ids = fields.One2many(
        'tutoring.workbook.file', 'item_id', string='作为教材')
    from_workbook = fields.Char('练习册', compute='_compute_from_workbook')

    preview_html = fields.Html('预览', compute='_compute_preview_html', sanitize=False)

    @api.depends('content', 'filename')
    def _compute_file_meta(self):
        for item in self:
            item.file_size = bytes_from_base64(item.content)
            ext = (item.filename or '').rpartition('.')[2].lower()
            item.ext = ext
            item.mimetype = MIMETYPES.get(ext, 'application/octet-stream')
            if ext == 'pdf':
                item.kind = 'pdf'
            elif ext in IMAGE_EXTS:
                item.kind = 'image'
            else:
                item.kind = 'other'

    @api.depends('file_size')
    def _compute_size_text(self):
        for item in self:
            item.size_text = fmt_bytes(item.file_size)

    @api.depends('workbook_file_ids.workbook_id')
    def _compute_from_workbook(self):
        for item in self:
            books = item.workbook_file_ids.workbook_id
            item.from_workbook = ' · '.join(books.mapped('name')) if books else ''

    @api.depends('kind', 'filename')
    def _compute_preview_html(self):
        """预览区按类型拼：PDF/图片直接内嵌，其余给一个下载链接。"""
        for item in self:
            if not item.id or not item.content:
                item.preview_html = ''
                continue
            url = '/tutoring/library/%s/raw' % item.id
            label = item.filename or item.name or ''
            if item.kind == 'pdf':
                item.preview_html = (
                    '<iframe class="o_library_preview_pdf" src="%s" title="%s"></iframe>' % (url, label))
            elif item.kind == 'image':
                item.preview_html = (
                    '<div class="o_library_preview_img"><img src="%s" alt="%s"/></div>' % (url, label))
            else:
                item.preview_html = (
                    '<div class="o_library_preview_file">'
                    '<i class="fa fa-file-o fa-3x mb-2"/>'
                    '<div>这种格式在网页里预览不了，点下面按钮下载到本机看。</div>'
                    '<a class="btn btn-primary mt-2" href="%s?download=1">'
                    '<i class="fa fa-download me-1"/>下载</a></div>' % (url,))

    # ------------------------------------------------------------
    # 容量配额
    # ------------------------------------------------------------

    @api.model
    def _param_bytes(self, param, default):
        value = self.env['ir.config_parameter'].sudo().get_param(param, '')
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @api.model
    def quota_bytes(self):
        return self._param_bytes(self.QUOTA_PARAM, self.DEFAULT_QUOTA_BYTES)

    @api.model
    def max_file_bytes(self):
        return self._param_bytes(self.MAX_FILE_PARAM, self.DEFAULT_MAX_FILE_BYTES)

    @api.model
    def used_bytes(self, user_id=None, exclude_ids=None):
        """已用容量：SQL 求和，不把任何正文读进内存（Binary 列忌全量读）。

        必须先 flush：file_size 是存储型计算字段，算出来的值要等 flush 才写进列，
        直接查会读到 NULL（表现为"传了一堆文件，已用还是 0"）。
        """
        user_id = user_id or self.env.user.id
        try:
            self.env.flush_all()
        except Exception:  # noqa: BLE001 - 只读事务里没法写库，那就按已落库的算
            pass
        query = 'SELECT COALESCE(SUM(file_size), 0) FROM %s WHERE user_id = %%s' % self._table
        params = [user_id]
        if exclude_ids:
            query += ' AND id NOT IN %s'
            params.append(tuple(exclude_ids))
        self.env.cr.execute(query, params)
        return int(self.env.cr.fetchone()[0] or 0)

    @api.model
    def quota_state(self, user_id=None):
        """给前端容量条的四个数：总量 / 已用 / 剩余 / 百分比。"""
        user_id = user_id or self.env.user.id
        quota = self.quota_bytes()
        used = self.used_bytes(user_id)
        remaining = max(quota - used, 0)
        return {
            'quota': quota,
            'used': used,
            'remaining': remaining,
            'percent': round(min(used / quota * 100, 100), 1) if quota else 0.0,
            'quota_text': fmt_bytes(quota),
            'used_text': fmt_bytes(used),
            'remaining_text': fmt_bytes(remaining),
            'max_file': self.max_file_bytes(),
            'max_file_text': fmt_bytes(self.max_file_bytes()),
            'count': self.search_count([('user_id', '=', user_id)]),
        }

    @api.model
    def tags_from_names(self, raw):
        """标签即输即建：逗号/顿号/分号分隔，重名的直接复用。"""
        names = [part.strip() for part in re.split(r'[,，、;；]', raw or '') if part.strip()]
        if not names:
            return [(6, 0, [])]
        tag_model = self.env['tutoring.library.tag']
        tags = tag_model.browse()
        for name in names[:10]:
            tags |= tag_model.search([('name', '=', name)], limit=1) or tag_model.create(
                {'name': name})
        return [(6, 0, tags.ids)]

    @api.model
    def _lock_user(self, user_id):
        """并发上传串行化：锁住该用户这一行，配额的"读-判-写"不再被插队。

        只锁同一个用户的写入，不同用户之间互不阻塞；锁随事务结束自动释放。
        """
        self.env.cr.execute('SELECT id FROM res_users WHERE id = %s FOR UPDATE', (user_id,))

    @api.model
    def _assert_can_store(self, user_id, incoming, filename=None, exclude_ids=None):
        """容量校验：单文件上限 + 剩余配额，两件事分开报，别让用户猜。"""
        max_bytes = self.max_file_bytes()
        if incoming > max_bytes:
            raise UserError(_(
                '单个文件不能超过 %(max)s，这个文件是 %(size)s（%(name)s）。\n'
                '大文件请先在本机拆小再传。') % {
                    'max': fmt_bytes(max_bytes),
                    'size': fmt_bytes(incoming),
                    'name': filename or _('未命名'),
                })
        used = self.used_bytes(user_id, exclude_ids=exclude_ids)
        quota = self.quota_bytes()
        if used + incoming > quota:
            raise UserError(_(
                '知识库放不下这个文件了：已用 %(used)s / %(quota)s，还剩 %(left)s，'
                '而这个文件是 %(size)s。\n先删掉一些不再需要的文件再来传。') % {
                    'used': fmt_bytes(used),
                    'quota': fmt_bytes(quota),
                    'left': fmt_bytes(max(quota - used, 0)),
                    'size': fmt_bytes(incoming),
                })

    @api.model_create_multi
    def create(self, vals_list):
        """有正文就先判容量；同一批多文件逐个累加，避免批量一起挤爆配额。

        历史数据迁移时带 `library_skip_quota` 上下文跳过（老教材不能因为
        超了新配额就迁不进来）。
        """
        if self.env.context.get('library_skip_quota'):
            return super().create(vals_list)
        incoming_total = {}
        for vals in vals_list:
            if 'content' not in vals:
                continue
            user_id = vals.get('user_id') or self.env.user.id
            self._lock_user(user_id)
            size = bytes_from_base64(vals.get('content'))
            incoming_total.setdefault(user_id, 0)
            self._assert_can_store(
                user_id, incoming_total[user_id] + size,
                filename=vals.get('filename') or vals.get('name'))
            incoming_total[user_id] += size
        return super().create(vals_list)

    def write(self, vals):
        """换文件时只算增量：旧的那份先让出来，再判新的放不放得下。"""
        if 'content' in vals and not self.env.context.get('library_skip_quota'):
            new_size = bytes_from_base64(vals.get('content'))
            for item in self:
                self._lock_user(item.user_id.id)
                delta = new_size - (item.file_size or 0)
                if delta > 0:
                    self._assert_can_store(
                        item.user_id.id, delta, filename=vals.get('filename') or item.filename,
                        exclude_ids=item.ids)
        return super().write(vals)

    def unlink(self):
        """删掉即释放（正文在本表 bytea 列里，没有 filestore 残留）。"""
        return super().unlink()

    # ------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------

    def action_preview(self):
        """点条目 → 页中页预览；重命名、改标签、改分类都在同一个弹窗里。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('tutoring_center.view_tutoring_library_item_form').id, 'form')],
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/tutoring/library/%s/raw?download=1' % self.id,
            'target': 'self',
        }
