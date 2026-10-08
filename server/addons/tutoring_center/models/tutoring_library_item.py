import base64
import logging
import re

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .library_markdown import render_markdown

_logger = logging.getLogger(__name__)

CATEGORY_SELECTION = [
    ('workbook', '练习册 / 教辅'),
    ('mistake', '错题'),
    ('leetcode', 'LeetCode'),
    ('note', '笔记'),
    ('doc', '资料文档'),
    ('other', '其他'),
]

# 允许在网页里直接内嵌预览的类型；其余一律给下载链接
# **svg 故意不放进来**：SVG 是 XML，能内嵌脚本，同源内联回吐等于给自己种一个 XSS
# （控制器那边也兜了一道，两头都拦住）
IMAGE_EXTS = ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp')

# 能在知识库里就地编辑的纯文本后缀。Markdown 单列出来，因为它的预览要渲染。
MARKDOWN_EXTS = ('md', 'markdown', 'mdown')
TEXT_EXTS = (
    'txt', 'text', 'log', 'csv', 'tsv', 'json', 'jsonl', 'xml', 'html', 'htm',
    'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'md', 'markdown', 'mdown',
    'py', 'js', 'mjs', 'cjs', 'ts', 'jsx', 'tsx', 'json5',
    'c', 'h', 'cpp', 'hpp', 'java', 'kt', 'go', 'rs', 'php', 'rb', 'pl', 'swift',
    'sql', 'sh', 'bash', 'ps1', 'bat', 'css', 'scss',
)
# Prism 只带了自己那一份语法表，映射里没有的后缀就纯文本显示（不硬撑高亮）
PRISM_LANGUAGES = {
    'md': 'markdown', 'markdown': 'markdown', 'mdown': 'markdown',
    'py': 'python',
    'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript',
    'jsx': 'javascript',
    'ts': 'typescript', 'tsx': 'typescript',
    'json': 'json', 'jsonl': 'json', 'json5': 'json', 'webmanifest': 'json',
    'xml': 'xml', 'svg': 'svg', 'html': 'markup', 'htm': 'markup',
    'css': 'css', 'scss': 'scss', 'sql': 'sql', 'java': 'java',
    'c': 'c', 'h': 'c', 'cpp': 'c', 'hpp': 'c', 'conf': 'ini', 'ini': 'ini',
    'sh': 'bash', 'bash': 'bash',
}
# 就地编辑的体积闸值：超了就只读。textarea 塞几 MB 进去，浏览器和服务端都难看，
# 而且这类文件本来也不是靠网页改的
MAX_EDIT_BYTES = 512 * 1024
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


def b64_to_bytes(value):
    """Binary 字段 → 原始字节。ORM 交出来的形状有三种，都得接。

    `memoryview` 是裸读 bytea 的结果（直接 str() 会变成 "<memory at 0x...>"
    存回库里，真踩过），str 是 base64 文本本身，bytes 是常规路径。
    """
    if not value:
        return b''
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, str):
        value = value.encode()
    return base64.b64decode(value)


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
    mistake_id = fields.Many2one(
        'tutoring.mistake', string='关联错题', index=True, ondelete='set null',
        help='错题的照片或说明挂在哪一条错题上；删掉错题不会删掉文件，'
             '练习册教材那类文件不用填')
    mistake_label = fields.Char('错题出处', compute='_compute_mistake_label')

    content = fields.Binary('文件', attachment=False)
    filename = fields.Char('文件名')
    file_size = fields.Integer(
        '大小(字节)', compute='_compute_file_meta', store=True,
        help='原始文件字节数；配额按它统计')
    upload_date = fields.Datetime('上传时间', default=fields.Datetime.now, index=True)

    ext = fields.Char('扩展名', compute='_compute_file_meta', store=True)
    mimetype = fields.Char('类型', compute='_compute_file_meta', store=True)
    kind = fields.Selection(
        [('pdf', 'PDF'), ('image', '图片'), ('markdown', 'Markdown'),
         ('text', '文本 / 代码'), ('other', '文件')],
        string='预览方式', compute='_compute_file_meta', store=True)
    size_text = fields.Char('大小', compute='_compute_size_text')

    workbook_file_ids = fields.One2many(
        'tutoring.workbook.file', 'item_id', string='作为教材')
    from_workbook = fields.Char('练习册', compute='_compute_from_workbook')

    preview_html = fields.Html('预览', compute='_compute_preview_html', sanitize=False)

    # 就地编辑那一套：四个字段共用一次解码，别各读一遍正文
    text_body = fields.Text('正文', compute='_compute_readable',
                            inverse='_inverse_readable')
    text_language = fields.Char('高亮语言', compute='_compute_readable')
    editable = fields.Boolean('可直接编辑', compute='_compute_readable')
    read_note = fields.Char('不可编辑原因', compute='_compute_readable')

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
            elif ext in MARKDOWN_EXTS:
                item.kind = 'markdown'
            elif ext in TEXT_EXTS:
                item.kind = 'text'
            else:
                item.kind = 'other'

    @api.depends('file_size')
    def _compute_size_text(self):
        for item in self:
            item.size_text = fmt_bytes(item.file_size)

    @api.depends('kind', 'filename', 'file_size', 'content')
    def _compute_readable(self):
        """纯文本条目：把正文解出来给编辑器与预览，顺便说清能不能编辑、为什么不能。

        三道门，缺一不可：`kind` 是 markdown/text、体积不超过 `MAX_EDIT_BYTES`、
        UTF-8 真能解码。任何一道不过就 `editable=False` 并把原因写进 `read_note`——
        界面上绝不摆一个点了没反应的"编辑"按钮。

        正文只在过了前两道门之后才读，所以几 MB 的 PDF/压缩包不会被这一次计算拉进内存。
        """
        for item in self:
            item.text_body = False
            item.text_language = PRISM_LANGUAGES.get(item.ext or '', '')
            item.editable = False
            item.read_note = ''
            if item.kind not in ('markdown', 'text'):
                continue
            if not item.file_size:
                item.read_note = _('这个文件是空的。')
                continue
            if item.file_size > MAX_EDIT_BYTES:
                item.read_note = _('文件 %s，超过网页内编辑的上限 %s；'
                                  '请下载到本机改完再传上来。') % (
                                      fmt_bytes(item.file_size), fmt_bytes(MAX_EDIT_BYTES))
                continue
            try:
                text = b64_to_bytes(item.content).decode('utf-8')
            except Exception:  # noqa: BLE001 - 非 UTF-8 的文本宁可只读也别改坏它
                item.read_note = _('不是 UTF-8 文本，在网页里编辑会改坏内容。')
                continue
            item.text_body = text
            item.editable = True

    def _inverse_readable(self):
        """改完写回 `content`：走模型自己的 write()，配额按"旧的让开、新的占上"重算。"""
        for item in self:
            if item.kind not in ('markdown', 'text'):
                continue
            body = item.text_body or ''
            try:
                raw = body.encode('utf-8')
            except UnicodeEncodeError as err:
                raise UserError(_('正文里有存不进去的字符：%s') % err) from err
            item.content = base64.b64encode(raw).decode()

    @api.depends('mistake_id')
    def _compute_mistake_label(self):
        """错题条目要能看出是哪道题：书名 + 页码 + 题号。"""
        for item in self:
            mistake = item.mistake_id
            if not mistake:
                item.mistake_label = ''
                continue
            where = ' · '.join(part for part in (
                mistake.page and _('P%s') % mistake.page,
                mistake.question_no and _('第 %s 题') % mistake.question_no) if part)
            item.mistake_label = ' · '.join(part for part in (
                mistake.workbook_id.display_name or mistake.student_id.display_name,
                where) if part) or mistake.display_name

    @api.depends('workbook_file_ids.workbook_id')
    def _compute_from_workbook(self):
        for item in self:
            books = item.workbook_file_ids.workbook_id
            item.from_workbook = ' · '.join(books.mapped('name')) if books else ''

    @api.depends('kind', 'filename', 'file_size', 'text_body', 'text_language')
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
            elif item.kind == 'markdown':
                # 渲染只在服务端做这一份（models/library_markdown.py），
                # 门户与后台弹窗拿到的是同一串 HTML，不存在两套解析器行为不一致
                item.preview_html = (
                    '<div class="o_library_preview_md">%s</div>'
                    % render_markdown(item.text_body or ''))
            elif item.kind == 'text':
                cls = ' class="language-%s"' % item.text_language if item.text_language else ''
                item.preview_html = (
                    '<pre class="o_library_preview_code"><code%s>%s</code></pre>'
                    % (cls, escape(item.text_body or '')))
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
            items = super().create(vals_list)
            return items._sync_workbook_link()
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
        items = super().create(vals_list)
        return items._sync_workbook_link()

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
        res = super().write(vals)
        if {'category', 'content'} & set(vals):
            self._sync_workbook_link()
        return res

    def unlink(self):
        """删掉即释放（正文在本表 bytea 列里，没有 filestore 残留）。"""
        return super().unlink()

    # ------------------------------------------------------------
    # 与练习册那套打通
    # ------------------------------------------------------------

    def _sync_workbook_link(self):
        """分类是「练习册/教辅」的条目，建完/改完都核对一次它挂上了没有。

        `no_workbook_link` 由 `tutoring.workbook.file` 那边带进来：委托继承建条目
        时核心会先写父记录，不拦就是 item.create → file.create → item.write 一路回头。
        """
        if self.env.context.get('no_workbook_link'):
            return self
        books = self.filtered(lambda item: item.category == 'workbook')
        if books:
            books._ensure_workbook_link()
        return self

    def _ensure_workbook_link(self):
        """把这条条目接进练习册那套，书名取条目标题（同名即同一本）。

        错题速记条、教材阅读页、错题「展示那一页」认的全是 `tutoring.workbook`，
        而条目上那个分类只是条目自己的一个标签——不补这一层，从知识库传上来的
        教辅在错题页等于不存在，也就记不了错题。一本多份文件因为同名，自然归到
        同一本书下。

        还没补附件的条目只把书立起来（记错题只要书名，附件是"看那一页"才要）；
        有正文的才建教材文件那一行，并用 `item_id` 复用同一条条目，不产生第二个文件。
        已经在某本书里的（后台建的教材，标题长这样："五年高考三年模拟 · 第3份"）
        一律不动：拿这种标题去找书，会凭空多出一本重复的练习册。
        """
        Workbook = self.env['tutoring.workbook']
        File = self.env['tutoring.workbook.file']
        # 学生账号对这两张表只有读权限（练习册是老师维护的字典），那就只给能建的账号挂。
        # 这里不 sudo 硬闯：越不过去就维持原状——条目照旧在知识库里，只是不冒充成一本练习册。
        # 超用户环境恒为真，所以迁移补存量时是先拿条目归属人自己的环境判过一遍的
        if not Workbook.has_access('create') or not File.has_access('create'):
            return
        for item in self:
            title = (item.name or '').strip()
            if not title or File.search([('item_id', '=', item.id)], limit=1):
                continue
            book = Workbook.search([('name', '=ilike', title)], limit=1)
            if not book:
                book = Workbook.create({'name': title})
            if not item.file_size:
                continue
            File.create({
                'item_id': item.id,
                'workbook_id': book.id,
                'name': title,
                # 委托继承会因为父记录已存在而回写条目的 user_id，
                # 不显式带上本人就会在超用户跑迁移时把条目判给 superuser
                'user_id': item.user_id.id,
            })

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
