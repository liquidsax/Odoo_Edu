from odoo import _, api, fields, models


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

    def action_open_quickadd(self):
        """列表控制栏「快速记录」：打开速记弹窗（学生/练习册沿用上一条记录）。

        刻意不加 @api.model：call_kw 只对带该标记的方法跳过 ids，
        而列表按钮 RPC 恒以 [ids] 作为第一个位置参数（空选区时是 [[]]）。
        """
        return self.env['tutoring.mistake.quickadd']._action_window()

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
