from odoo import api, fields, models


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
    state = fields.Selection([
        ('todo', '待订正'), ('done', '已订正'),
    ], string='状态', default='todo', required=True, index=True)

    # create_date 即"记录时刻"（系统自动、不可改）；此字段按用户时区格式化，供门户展示
    recorded_at_text = fields.Char('记录时刻', compute='_compute_recorded_at_text')

    @api.depends('create_date')
    def _compute_recorded_at_text(self):
        for rec in self:
            rec.recorded_at_text = (
                fields.Datetime.context_timestamp(rec, rec.create_date).strftime('%Y-%m-%d %H:%M')
                if rec.create_date else '')

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
