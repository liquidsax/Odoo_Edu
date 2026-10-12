import json
import re
from datetime import timedelta
from math import ceil

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .math_text import to_plain_math
from . import mistake_cover

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
    # 归档（软删）与真删并存："复习到位了、不再重要"是降级，不是销毁；
    # 加了 active 之后 search() 默认就只看在用的，归档的要显式带 active_test=False 才捞得回
    active = fields.Boolean('在用', default=True)

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True,
        ondelete='cascade', index=True)
    date = fields.Date('发生日期', default=fields.Date.context_today, required=True)
    # 练习册不再是必填：拖一张题目照片进来就该能记下一道错题，
    # 出处是"有则更好"（能定位到那一页才有原页封面与 AI 摘要），不是门槛。
    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', ondelete='restrict', index=True)
    page = fields.Char('页码')
    question_no = fields.Char('题号')
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

    # 门户错题页的分主次依据：不建新字段、不引新状态，就从现在有的两样东西里算——
    # 到期多久 × 难度高低。刻意不进后台视图，也只用于上色与一句话说明，
    # 不构成"这道题订正了没有"那种需要人维护的状态。
    portal_heat = fields.Char('轻重', compute='_compute_portal_heat')
    portal_heat_note = fields.Char('为什么排在这儿', compute='_compute_portal_heat')

    # 试用封面版要知道"这道题的封面能从哪儿来"。判据刻意只问"落不落得到那一页"，
    # 不读 page_pdf——那个 compute 会真去抽页，列表页每行算一次就是灾难（同 can_ai_summary）。
    cover_pdf_ready = fields.Boolean('有原页封面', compute='_compute_cover')
    cover_ai_ready = fields.Boolean('有 AI 封面', compute='_compute_cover')
    cover_kind = fields.Char('封面走哪条', compute='_compute_cover')
    # AI 给的封面配方：只存我们白名单过的结构化选择（色板 id + 图案 id + 三句短话），
    # 图与颜色都由我们按 id 查表画，模型碰不到样式。
    # 「每日回顾」收拢之后这道口没有了（一天一张不再逐题出，见 tutoring.mistake.digest），
    # 字段与下面那套渲染留着给整屏流的 auto 模式继续认——它按 cover_kind 挑能用的那张。
    cover_recipe = fields.Text('封面配方', copy=False)
    cover_style = fields.Char('封面底色', compute='_compute_cover_plan')
    cover_motifs = fields.Html('封面图案', compute='_compute_cover_plan', sanitize=False)
    cover_headline = fields.Char('封面概括', compute='_compute_cover_plan')
    cover_sub = fields.Char('封面小字', compute='_compute_cover_plan')
    cover_badge = fields.Char('封面角标', compute='_compute_cover_plan')

    def _cover_plan(self):
        """配方原文 → 白名单过的 dict。坏 JSON、整串废 id 都当"没有配方"，两处共用一份判据。

        不管进来什么都返回 `clean()` 的结果：那样保证五个键都在，
        调用方才可以直接 `plan['headline']` 而不是满地的 .get()。
        """
        self.ensure_one()
        try:
            plan = json.loads(self.cover_recipe or '{}')
        except ValueError:
            plan = {}
        return mistake_cover.clean(plan if isinstance(plan, dict) else {})

    @api.depends('cover_recipe')
    def _compute_cover_plan(self):
        for rec in self:
            plan = rec._cover_plan()
            rec.cover_style = mistake_cover.style_for(plan)
            rec.cover_motifs = mistake_cover.motifs_svg(plan)
            rec.cover_headline = plan['headline']
            rec.cover_sub = plan['sub']
            rec.cover_badge = plan['badge']

    # 只读详情页里展示"出错的那一页"：服务端只抽出那一页成小 PDF，不拉整本教材
    page_pdf = fields.Binary('这一页', compute='_compute_page_pdf')
    page_pdf_hint = fields.Char('这一页说明', compute='_compute_page_pdf')

    # 错题是知识库的一个固有类型：题目照片/说明作为条目挂进来，两边都能跳。
    # 删错题不动文件（条目上 ondelete='set null'），删文件也不影响错题记录。
    library_item_ids = fields.One2many(
        'tutoring.library.item', 'mistake_id', string='题目文件')
    library_count = fields.Integer('题目文件数', compute='_compute_library_count')

    # AI 摘要（见 tutoring.mistake.ai.job）：一题只许发起一次，成败都扣发起人的当日额度。
    # 之所以长在错题上而不是知识库条目上——"能被 AI 分析"正是错题区别于其它资料的地方。
    ai_state = fields.Selection([
        ('none', '未生成'), ('pending', '生成中'), ('done', '已生成'), ('failed', '没成功'),
    ], string='AI 摘要', default='none', required=True, copy=False, index=True)
    ai_summary = fields.Char('题目摘要', copy=False)
    ai_question_text = fields.Text('题目原文（AI 抄录）', copy=False)
    # 给人看的那一份：AI 抄回来的题目带 LaTeX，直接印出来是 \begin{cases} 这种。
    # 渲染只在服务端做这一份（models/math_text.py），门户与后台拿的是同一个字符串——
    # 后台的 Char/Text 字段不渲染 HTML，所以这里产纯文本而不是 <sup> 那类标签。
    ai_readable_summary = fields.Char('题目摘要', compute='_compute_ai_readable')
    ai_readable_text = fields.Text('题目原文', compute='_compute_ai_readable')
    ai_hint = fields.Char('AI 提示', copy=False)
    ai_done_at = fields.Datetime('AI 生成时间', copy=False)
    # 只给表单用：定位不到那一页的题没有资料可分析，按钮就不出现。
    # 刻意不依赖 page_pdf——那个 compute 会真去抽页，列表页每行算一次就是灾难。
    can_ai_summary = fields.Boolean('可生成摘要', compute='_compute_can_ai_summary')

    @api.depends('ai_summary', 'ai_question_text')
    def _compute_ai_readable(self):
        for mistake in self:
            mistake.ai_readable_summary = to_plain_math(mistake.ai_summary) or False
            mistake.ai_readable_text = to_plain_math(mistake.ai_question_text) or False

    @api.depends('page', 'workbook_id', 'ai_state')
    def _compute_can_ai_summary(self):
        for mistake in self:
            # sudo 只用来问"这本练习册里有没有这一页"：教材正文挂在上传者自己的知识库
            # 条目上，学生按记录规则读不到那些行，但按钮对他该不该出现是另一回事。
            file, _local, _hint = mistake.sudo().workbook_id._locate_page(mistake.page)
            mistake.can_ai_summary = bool(file) and mistake.ai_state == 'none'

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
            # 单页缓存表 tutoring.workbook.page 只有教师组读得动（它是内部件），
            # 而"这个人能不能看这本教材的这一页"已经由上一行的 _locate_page 说完了：
            # 那里是按当前用户的权限找文件，找不到就不会走到这一步。
            data = self.env['tutoring.workbook.page'].sudo()._pdf_for(file, local)
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

    @api.depends('page', 'workbook_id.page_mode', 'workbook_id.page_offset',
                 'workbook_id.file_ids.page_from', 'workbook_id.file_ids.page_to',
                 'cover_recipe')
    def _compute_cover(self):
        for rec in self:
            # sudo 只用来问"这本练习册里到底有没有这一页"，理由同 can_ai_summary：
            # 教材正文挂在上传者自己的行上，学生按记录规则读不到那些行，
            # 但"封面该不该出现"是另一回事。
            file, _local, _hint = rec.sudo().workbook_id._locate_page(rec.page)
            plan = rec._cover_plan()
            rec.cover_pdf_ready = bool(file)
            rec.cover_ai_ready = bool(plan['headline'] or plan['motifs'])
            rec.cover_kind = ('pdf' if rec.cover_pdf_ready
                              else 'ai' if rec.cover_ai_ready else 'css')

    def _cover_facts(self):
        """喂给模型的那一行事实：只给它已经有的文字，一句都不替它编。

        逐题那套封面版（`coverpdf`/`covercss`/`coverai`）已经收拢成「每日回顾」，
        但这一行事实留着——一天一张的那张大图正是把当天每条的这个字符串收进去的
        （见 `tutoring.mistake.digest._day_facts`）。
        """
        self.ensure_one()
        parts = [
            '知识点：%s' % (self.point_id.name or '未标'),
            '错因：%s' % (self.cause_id.name or '未标'),
            '难度：%s/5' % (self.difficulty or '3'),
            '出处：%s' % ('《%s》P%s 第%s题' % (
                self.workbook_id.name, self.page or '—', self.question_no or '—')
                if self.workbook_id else '没填'),
        ]
        body = self.ai_readable_summary or self.ai_readable_text
        if body:
            parts.append('摘要：%s' % body.replace('\n', ' ')[:180])
        if self.note:
            parts.append('补充说明：%s' % self.note.replace('\n', ' ')[:120])
        return '｜'.join(parts)

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
    def _due_domain(self, at=None):
        """"该翻出来了"的判定，门户队列首屏与卡片配色共用同一份口径。

        `next_review_at` 为空要按"该看"处理：SQL 里 NULL 参与比较恒为 unknown，
        不显式写这一条，空排期的题会永远不进队列。
        """
        now = at or fields.Datetime.now()
        return ['|', ('next_review_at', '=', False), ('next_review_at', '<=', now)]

    @api.depends('difficulty', 'next_review_at', 'last_review_at')
    def _compute_portal_heat(self):
        now = fields.Datetime.now()
        for rec in self:
            hard = rec.difficulty in ('4', '5')
            due_at = rec.next_review_at or now
            if rec.next_review_at and rec.next_review_at > now:
                # 不满一天按一天说，但落在整天那一刻不能再加一格：
                # 库里和缓存都把微秒截成整秒，用「floor+1」会在整 5 天时写成 6 天
                days_left = max(ceil(
                    (rec.next_review_at - now).total_seconds() / 86400.0), 1)
                rec.portal_heat = 'hard' if hard else 'cool'
                rec.portal_heat_note = _(
                    '难度高，%d 天后再看') % days_left if hard else _('%d 天后再看') % days_left
                continue
            overdue = max((now - due_at).days, 0)
            if overdue >= 7 and hard:
                rec.portal_heat = 'hot'
                rec.portal_heat_note = _('搁了 %d 天没翻，难度也高') % overdue
            elif not rec.last_review_at:
                rec.portal_heat = 'due'
                rec.portal_heat_note = _('记下了，一次都没翻开过')
            else:
                rec.portal_heat = 'due'
                rec.portal_heat_note = (
                    _('到期了') if overdue <= 0 else _('上次翻是 %d 天前') % overdue)

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

    def action_ai_generate(self):
        """只读详情里的「生成摘要」：只建一条任务，真正调用交给 ir.cron。

        刻意不同步等：一个请求占住 worker 几秒到几十秒不值得，而且关掉页面就前功尽弃。
        刻意不加 @api.model：表单按钮 RPC 也恒以 [ids] 作为第一个位置参数。
        """
        self.ensure_one()
        self.env['tutoring.mistake.ai.job'].create({'mistake_id': self.id})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'title': _('正在生成中，大约需要 2 分钟'),
                'message': _('生成完成后，摘要会出现在这道题上；一道题只能生成一次。'),
                'sticky': False,
            },
        }

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
