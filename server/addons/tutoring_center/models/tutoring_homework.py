from odoo import api, fields, models


class TutoringHomework(models.Model):
    _name = 'tutoring.homework'
    _description = '作业'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'assigned_date desc, id desc'
    _rec_name = 'title'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True, ondelete='cascade', index=True)
    session_id = fields.Many2one(
        'tutoring.session', string='关联课次', ondelete='set null',
        domain="[('student_id', '=', student_id)]")
    title = fields.Char('标题', required=True)
    assigned_date = fields.Date(
        '布置日期', default=fields.Date.context_today, required=True, tracking=True)
    due_date = fields.Date('截止日期', tracking=True)
    question_count = fields.Integer('总题数', default=0, tracking=True)
    correct_count = fields.Integer('正确题数')
    accuracy = fields.Float('正确率(%)', compute='_compute_accuracy', store=True, aggregator='avg')
    state = fields.Selection([
        ('draft', '已布置'), ('done', '已完成'), ('reviewed', '已批改'),
    ], string='状态', default='draft', required=True, tracking=True, index=True)
    feedback = fields.Html('教师反馈')

    @api.depends('question_count', 'correct_count')
    def _compute_accuracy(self):
        for homework in self:
            homework.accuracy = (
                homework.correct_count / homework.question_count * 100.0
                if homework.question_count else 0.0)
