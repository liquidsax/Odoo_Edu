import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# 一次最多生成多少条，防止把"1-9999"当成批量录入（后台速记与门户速记条共用）
MAX_QUESTION_LINES = 100

# 打开一次详情＝复习过一次，下次到期按第几次复习往后推。
# 封顶 60 天：个人自用，间隔再长就等于不再会翻到这道题了。
REVIEW_INTERVALS_DAYS = (1, 3, 7, 15, 30, 60)


def split_question_numbers(value):
    """把"1-5""1,3,7""1-3,7"这类写法展开成题号列表；留空则只记一道。"""
    tokens = re.split(r'[,，、;；]', value or '')
    numbers = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        span = re.fullmatch(r'(\d+)\s*[-~至]\s*(\d+)', token)
        if span:
            start, end = sorted((int(span[1]), int(span[2])))
            numbers += [str(n) for n in range(start, end + 1)]
        else:
            numbers.append(token)
    numbers = list(dict.fromkeys(numbers))
    if len(numbers) > MAX_QUESTION_LINES:
        raise ValidationError(_('一次最多记录 %s 道题，请缩小题号范围。') % MAX_QUESTION_LINES)
    return numbers or [False]


class TutoringMistake(models.Model):
    _name = 'tutoring.mistake'
    _description = '错题记录'
    _order = 'date desc, create_date desc, id desc'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True,
        ondelete='cascade', index=True)
    date = fields.Date('发生日期', default=fields.Date.context_today, required=True)
    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True,
        ondelete='restrict', index=True)
    page = fields.Char('页码')
    question_no = fields.Char('题号')
    topic_id = fields.Many2one(
        'tutoring.topic', string='相关教学内容', ondelete='restrict')
    difficulty = fields.Selection([
        ('2', '🌶🌶'), ('3', '🌶🌶🌶'),
        ('4', '🌶🌶🌶🌶'), ('5', '🌶🌶🌶🌶🌶'),
    ], string='难度', default='3')
    note = fields.Text('补充说明')
    cause_id = fields.Many2one(
        'tutoring.mistake.cause', string='错因', ondelete='restrict', index=True)
    # 存下来才能按"归类"分组（read_group 不接受非存储的 related）
    cause_category = fields.Selection(
        related='cause_id.category', string='错因归类', store=True)
    point_id = fields.Many2one(
        'tutoring.knowledge.point', string='知识点', ondelete='set null', index=True)
    # 挑知识点的域按学生年级放开（初一只有 '07'，高一~高三额外给整层高中库 '13'）；
    # student_grade 只用来给"就地新建知识点"的弹窗带上默认年级
    knowledge_grades = fields.Json('可选知识点年级', related='student_id.knowledge_grades')
    student_grade = fields.Selection(
        related='student_id.grade', string='学生年级')

    # 复习排期：纯服务端机制，不进任何视图、也不展示给学生——
    # 学生只是"今天打开错题页，看到的顺序和昨天不一样"。
    last_review_at = fields.Datetime('上次复习')
    review_count = fields.Integer('复习次数', default=0)
    next_review_at = fields.Datetime(
        '下次可复习', default=fields.Datetime.now, index=True)

    # create_date 即"记录时刻"（系统自动、不可改）；此字段按用户时区格式化，供门户展示
    recorded_at_text = fields.Char('记录时刻', compute='_compute_recorded_at_text')

    # 只读详情页里展示"出错的那一页"：服务端只抽出那一页成小 PDF，不拉整本教材
    page_pdf = fields.Binary('这一页', compute='_compute_page_pdf')
    page_pdf_hint = fields.Char('这一页说明', compute='_compute_page_pdf')

    # 错题是知识库的一个固有类型：题目照片/说明作为条目挂进来，两边都能跳。
    # 删错题不动文件（条目上 ondelete='set null'），删文件也不影响错题记录。
    library_item_ids = fields.One2many(
        'tutoring.library.item', 'mistake_id', string='题目文件')
    library_count = fields.Integer('题目文件数', compute='_compute_library_count')

    @api.depends('page', 'workbook_id.page_mode', 'workbook_id.page_offset',
                 'workbook_id.file_ids.content')
    def _compute_page_pdf(self):
        for mistake in self:
            mistake.page_pdf = False
            mistake.page_pdf_hint = ''
            file, local, hint = mistake.workbook_id._locate_page(mistake.page)
            if not file:
                mistake.page_pdf_hint = hint
                continue
            data = self.env['tutoring.workbook.page']._pdf_for(file, local)
            if not data:
                mistake.page_pdf_hint = _(
                    '《%(book)s》里抽不出这一页：第 %(page)s 页大概超出了这份教材的页数。') % {
                    'book': mistake.workbook_id.name, 'page': mistake.page}
                continue
            mistake.page_pdf = data

    @api.depends('library_item_ids')
    def _compute_library_count(self):
        # 一次 read_group 拿完整份计数：错题列表页每行都算一次就是 N+1
        counts = {
            mistake.id: count
            for mistake, count in self.env['tutoring.library.item']._read_group(
                [('mistake_id', 'in', self.ids)], ['mistake_id'], ['__count'])
        }
        for mistake in self:
            mistake.library_count = counts.get(mistake.id, 0)

    @api.model
    def default_get(self, fields_list=None):
        """新建行沿用上一条记录的学生与练习册：连续记同一本练习册时不必反复选。"""
        defaults = super().default_get(fields_list)
        student_id = self.env.context.get('default_student_id')
        last = self.search(
            [('student_id', '=', student_id)] if student_id else [],
            limit=1, order='create_date desc, id desc')
        if last:
            for fname in ('student_id', 'workbook_id'):
                if fields_list is None or fname in fields_list:
                    defaults.setdefault(fname, last[fname].id)
        return defaults

    @api.depends('student_id', 'workbook_id', 'page', 'question_no')
    def _compute_display_name(self):
        for rec in self:
            where = ' '.join(part for part in (
                f'P{rec.page}' if rec.page else '',
                f'第{rec.question_no}题' if rec.question_no else '') if part)
            name = ' · '.join(part for part in (
                rec.student_id.name, rec.workbook_id.name, where) if part)
            rec.display_name = name or _('未命名错题')

    @api.depends('create_date')
    def _compute_recorded_at_text(self):
        for rec in self:
            rec.recorded_at_text = (
                fields.Datetime.context_timestamp(rec, rec.create_date).strftime('%Y-%m-%d %H:%M')
                if rec.create_date else '')

    @api.model
    def summary_stats(self):
        """错题页顶部概览条的四个数字（全局统计，不随当前筛选变）。"""
        today = fields.Date.context_today(self)
        return {
            'total': self.search_count([]),
            'month': self.search_count([('date', '>=', today.replace(day=1))]),
            'hard': self.search_count([('difficulty', 'in', ['4', '5'])]),
            'no_cause': self.search_count([('cause_id', '=', False)]),
        }

    def action_open_quickadd(self):
        """列表控制栏「快速记录」：打开速记弹窗（学生/练习册沿用上一条记录）。

        刻意不加 @api.model：call_kw 只对带该标记的方法跳过 ids，
        而列表按钮 RPC 恒以 [ids] 作为第一个位置参数（空选区时是 [[]]）。
        """
        return self.env['tutoring.mistake.quickadd']._action_window()

    def _form_dialog(self, view_xmlid, name, res_id, size='large'):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': self._name,
            'res_id': res_id,
            'view_mode': 'form',
            'views': [(self.env.ref('tutoring_center.%s' % view_xmlid).id, 'form')],
            'target': 'new',
            'context': {'dialog_size': size},
        }

    def action_open_reader(self):
        """列表里单击整行 → 只读详情页：出处 + 出错那一页的教材原页。

        跟练习册页同一套路：行点击不落到单元格编辑，所以不会"一碰就改库"；
        要改这条记录得点「修改」。
        """
        self.ensure_one()
        return self._form_dialog(
            'view_tutoring_mistake_form_reader', self.display_name, self.id,
            size='extra-large')

    def action_open_edit(self):
        """「修改」→ 同一弹窗位置换成可编辑表单（arch 里没有 <footer>，核心自动补保存/放弃）。"""
        self.ensure_one()
        return self._form_dialog('view_tutoring_mistake_form', _('修改错题记录'), self.id)

    def action_new_mistake(self):
        """控制栏「新建错题」：加记录走明确按钮，不在只读表格里就地加行。

        刻意不加 @api.model：列表按钮 RPC 恒以 [ids] 作为第一个位置参数（空选区是 [[]]）。
        """
        return self._form_dialog('view_tutoring_mistake_form', _('新建错题记录'), False)

    @api.model
    def _migration_backfill_workbook(self):
        """把没有练习册的存量错题归入按需创建的默认练习册。

        workbook_id 现为必填；升级时给已有行的表加 NOT NULL 会被延迟到数据加载之后，
        这里先回填，收尾阶段约束才能干净生效。全新库没有存量错题，此函数是空操作。
        """
        orphan = self.search([('workbook_id', '=', False)])
        if not orphan:
            return
        default = self.env['tutoring.workbook'].search([('name', '=', '课内/其他')], limit=1)
        if not default:
            default = self.env['tutoring.workbook'].create({'name': '课内/其他'})
        orphan.write({'workbook_id': default.id})

    def touch_review(self):
        """打开一次详情＝复习过一次：记时刻、次数 +1，下次到期按次数往后推。

        刻意不做成"点一下标记已复习"的按钮——那要求学生理解并维护一个状态，
        而"翻这道题"这个动作本身就是复习。
        """
        now = fields.Datetime.now()
        for rec in self:
            step = min(rec.review_count, len(REVIEW_INTERVALS_DAYS) - 1)
            rec.write({
                'last_review_at': now,
                'review_count': rec.review_count + 1,
                'next_review_at': now + timedelta(days=REVIEW_INTERVALS_DAYS[step]),
            })

    @api.model
    def _migration_backfill_review(self):
        """存量行补排期：新字段对老数据是 NULL，而门户错题页按它升序排，
        PostgreSQL 默认把 NULL 排在最后——不补的话老错题会永久沉底。"""
        now = fields.Datetime.now()
        for rec in self.search([('next_review_at', '=', False)]):
            rec.next_review_at = rec.create_date or now
