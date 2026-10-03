import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# 一次最多生成多少条，防止把"1-9999"当成批量录入（后台速记与门户速记条共用）
MAX_QUESTION_LINES = 100


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
    note = fields.Text('错因/备注')

    # create_date 即"记录时刻"（系统自动、不可改）；此字段按用户时区格式化，供门户展示
    recorded_at_text = fields.Char('记录时刻', compute='_compute_recorded_at_text')

    # 只读详情页里展示"出错的那一页"：服务端只抽出那一页成小 PDF，不拉整本教材
    page_pdf = fields.Binary('这一页', compute='_compute_page_pdf')
    page_pdf_hint = fields.Char('这一页说明', compute='_compute_page_pdf')

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
            'no_note': self.search_count([('note', '=', False)]),
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
