from odoo import api, fields, models


class TutoringExam(models.Model):
    _name = 'tutoring.exam'
    _description = '考试/测验'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True, ondelete='cascade', index=True)
    name = fields.Char('名称', required=True)
    date = fields.Date('考试日期', default=fields.Date.context_today, required=True, tracking=True)
    exam_type = fields.Selection([
        ('quiz', '随堂测验'), ('unit', '单元测验'), ('monthly', '月考'),
        ('midterm', '期中考试'), ('final', '期末考试'), ('mock', '模拟考试'), ('other', '其他'),
    ], string='类型', default='unit', required=True, tracking=True, index=True)
    line_ids = fields.One2many('tutoring.exam.line', 'exam_id', string='得分明细', copy=True)
    total_score = fields.Float('总分', compute='_compute_totals', store=True)
    total_full = fields.Float('卷面满分', compute='_compute_totals', store=True)
    percentage = fields.Float('得分率(%)', compute='_compute_totals', store=True, aggregator='avg')
    remark = fields.Html('备注')

    @api.depends('line_ids.score', 'line_ids.full_score')
    def _compute_totals(self):
        for exam in self:
            exam.total_score = sum(exam.line_ids.mapped('score'))
            exam.total_full = sum(exam.line_ids.mapped('full_score'))
            exam.percentage = (
                exam.total_score / exam.total_full * 100.0 if exam.total_full else 0.0)


class TutoringExamLine(models.Model):
    _name = 'tutoring.exam.line'
    _description = '考试得分明细'
    _order = 'id'

    exam_id = fields.Many2one('tutoring.exam', string='考试', required=True, ondelete='cascade', index=True)
    topic_id = fields.Many2one('tutoring.topic', string='教学内容', required=True,
                               ondelete='restrict', index=True)
    score = fields.Float('得分', digits=(10, 1))
    full_score = fields.Float('满分', digits=(10, 1), default=100.0)
    percentage = fields.Float('得分率(%)', compute='_compute_percentage', store=True, aggregator='avg')

    @api.depends('score', 'full_score')
    def _compute_percentage(self):
        for line in self:
            line.percentage = line.score / line.full_score * 100.0 if line.full_score else 0.0
