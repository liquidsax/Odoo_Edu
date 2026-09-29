from odoo import fields, models


class TutoringMistake(models.Model):
    _name = 'tutoring.mistake'
    _description = '错题记录'
    _order = 'date desc, id desc'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True,
        ondelete='cascade', index=True)
    date = fields.Date('日期', default=fields.Date.context_today, required=True)
    topic_id = fields.Many2one(
        'tutoring.topic', string='相关教学内容', ondelete='restrict')
    source = fields.Selection([
        ('class', '课内练习'), ('exam', '考试'), ('other', '其他'),
    ], string='来源', default='class', required=True)
    description = fields.Html('题目与错误原因')
    state = fields.Selection([
        ('todo', '待订正'), ('done', '已订正'),
    ], string='状态', default='todo', required=True, index=True)
