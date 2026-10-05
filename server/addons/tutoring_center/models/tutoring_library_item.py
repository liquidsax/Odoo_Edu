import base64
import logging
import re

from markupsafe import escape

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
# **svg 故意不放进来**：SVG 是 XML，能内嵌脚本，同源内联回吐等于给自己种一个 XSS
# （控制器那边也兜了一道，两头都拦住）
IMAGE_EXTS = ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp')
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


class TutoringLibraryFolder(models.Model):
    """知识库文件夹：每个人自己建的一层收纳格。

    和 `category` 是两回事——分类回答"这是什么内容"（练习册教材由委托继承写死成
    workbook），文件夹回答"这个人把它放哪儿"，所以只对本人生效、可以自建。
    删除文件夹不动文件：条目上的 `ondelete='set null'` 让它们退回未分类。
    """
    _name = 'tutoring.library.folder'
    _description = '知识库文件夹'
    _order = 'name, id'

    name = fields.Char('文件夹', required=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    item_ids = fields.One2many('tutoring.library.item', 'folder_id', string='条目')
    item_count = fields.Integer('文件数', compute='_compute_item_count')
    size_text = fields.Char('占用', compute='_compute_size_text')

    _name_uniq = models.Constraint(
        'unique(name, user_id)', _('这个文件夹已经存在了，换个名字。'))

    @api.depends('item_ids')
    def _compute_item_count(self):
        # 一次 read_group 拿完整份计数，别按记录 search_count（一列文件夹就是一条 SQL）
        counts = {
            folder.id: count
            for folder, count in self.env['tutoring.library.item']._read_group(
                [('folder_id', 'in', self.ids)], ['folder_id'], ['__count'])
        }
        for folder in self:
            folder.item_count = counts.get(folder.id, 0)

    @api.depends('item_ids.file_size')
    def _compute_size_text(self):
        sizes = {
            folder.id: total or 0
            for folder, _count, total in self.env['tutoring.library.item']._read_group(
                [('folder_id', 'in', self.ids)],
                ['folder_id'],
                ['__count', 'file_size:sum'])
        }
        for folder in self:
            folder.size_text = fmt_bytes(sizes.get(folder.id, 0))


class TutoringLibraryTag(models.Model):
    """标签也是各人的：`rule_library_tag_all` 的域已经是"仅本人"。

    标签名本身就是"这个人在学什么"的信息，共享字典会让别人在补全列表里看到，
    所以和条目一样按用户隔离；`tags_from_names()` 的 search 天然只命中本人。
    （xmlid 留着 tag_all 这个名字是有原因的，见 tutoring_security.xml 里那条注释）
    """
    _name = 'tutoring.library.tag'
    _description = '知识库标签'
    _order = 'name'

    name = fields.Char('标签', required=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    color = fields.Integer('颜色序号', help='0~11，用于卡片上的标签底色')
    item_ids = fields.Many2many(
        'tutoring.library.item', 'tutoring_library_item_tag_rel',
        'tag_id', 'item_id', string='条目')

    _name_uniq = models.Constraint(
        'unique(name, user_id)', _('你已经有一个同名标签了。'))

    @api.model
    def _assign_owner_from_items(self):
        """把每个标签归到"用它的人"名下，被多人用过的拆成每人一份。

        升级迁移（19.0.1.13.0）和一次性修数都走这里。**判据不能是
        `user_id IS NULL`**：Odoo 给存量表加 required 列时会把现有一行填成
        "升级那一刻的当前用户"，等业务库里查就全是非空了——只能拿条目重新核对。

        以 sudo 调用（要跨用户看全部标签）；可重复执行。
        返回 (归位数, 拆出副本数, 删掉的孤儿数)。
        """
        moved = split = dropped = 0
        for tag in self.search([]):
            users = tag.item_ids.user_id
            if not users:
                # 没人用的孤儿：留着既不会出现在任何人手里，又占着这条 unique(name, user_id)
                tag.unlink()
                dropped += 1
                continue
            if len(users) == 1 and tag.user_id == users[0]:
                continue
            tag.user_id = users[0].id
            moved += 1
            for user in users[1:]:
                copy = self.create({
                    'name': tag.name, 'color': tag.color, 'user_id': user.id})
                for item in tag.item_ids.filtered(lambda r: r.user_id == user):
                    item.write({'tag_ids': [(3, tag.id), (4, copy.id)]})
                split += 1
        return moved, split, dropped


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
    folder_id = fields.Many2one(
        'tutoring.library.folder', string='文件夹', index=True, ondelete='set null',
        help='自己建的收纳格；留空就是未分类，删掉文件夹只会把文件退回未分类。'
             '下拉里只会出现本人的文件夹——那条记录规则管着，不用在这里写域')
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

    @api.depends('kind', 'filename', 'file_size')
    def _compute_preview_html(self):
        """预览区按类型拼：PDF/图片直接内嵌，其余给一个下载链接。

        判"有没有正文"要看 file_size（已存库的算字段），不能读 content——
        读一次就把整本 PDF 的字节拉进内存，而预览本来就是靠那条 raw 路由串流的。

        这是 `sanitize=False` 的裸 HTML，而文件名/标题是外来输入：进属性位之前
        必须转义。`_clean_name` 只护住走控制器那条路，后台用 JSON-RPC 直接 write
        filename 是不经过它的。
        """
        for item in self:
            if not item.id or not item.file_size:
                item.preview_html = ''
                continue
            url = '/tutoring/library/%s/raw' % item.id
            label = escape(item.filename or item.name or '')
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
