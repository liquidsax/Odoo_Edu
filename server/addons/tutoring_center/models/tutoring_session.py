from odoo import fields, models


class TutoringSession(models.Model):
    _name = 'tutoring.session'
    _description = '辅导课次'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _rec_name = 'date'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True, ondelete='cascade', index=True)
    date = fields.Date('上课日期', default=fields.Date.context_today, required=True, tracking=True)
    duration = fields.Float('时长(小时)', default=1.5, tracking=True)
    topic_ids = fields.Many2many('tutoring.topic', string='教学内容')
    performance = fields.Html('课堂内容与表现')
    plan = fields.Html('下一步计划')
