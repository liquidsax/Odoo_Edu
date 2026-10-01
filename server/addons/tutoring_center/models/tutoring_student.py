from odoo import _, api, fields, models

from .tutoring_knowledge import GRADE_SELECTION


class TutoringStudent(models.Model):
    _name = 'tutoring.student'
    _description = '学生档案'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char('姓名', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='门户联系人', tracking=True,
        help='学生（或代学生查看的家长）用该联系人的门户账号登录，查看本学生的学习数据。')
    grade = fields.Selection(GRADE_SELECTION, string='年级', default='07', required=True, tracking=True)
    school = fields.Char('学校')
    status = fields.Selection([
        ('active', '在读'), ('paused', '暂停'), ('done', '结课'),
    ], string='状态', default='active', required=True, tracking=True)
    remark = fields.Html('备注')

    session_ids = fields.One2many('tutoring.session', 'student_id', string='辅导课次')
    homework_ids = fields.One2many('tutoring.homework', 'student_id', string='作业')
    exam_ids = fields.One2many('tutoring.exam', 'student_id', string='考试成绩')
    point_ids = fields.One2many('tutoring.student.point', 'student_id', string='知识点掌握')
    mistake_ids = fields.One2many('tutoring.mistake', 'student_id', string='错题记录')

    point_count = fields.Integer('需掌握知识点数', compute='_compute_point_stats')
    point_mastered_count = fields.Integer('已熟练掌握知识点数', compute='_compute_point_stats')
    mistake_count = fields.Integer('错题数', compute='_compute_stats')

    session_planned_count = fields.Integer(
        '总课次', tracking=True,
        help='本学期计划给该学生上的总节数。')
    session_count = fields.Integer('已上课次', compute='_compute_stats')
    homework_count = fields.Integer('作业数', compute='_compute_stats')
    homework_open_count = fields.Integer('待完成作业', compute='_compute_stats')
    homework_avg = fields.Float('作业平均正确率(%)', compute='_compute_stats', aggregator='avg')
    exam_count = fields.Integer('考试数', compute='_compute_stats')
    exam_avg = fields.Float('考试平均得分率(%)', compute='_compute_stats', aggregator='avg')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('partner_id'):
                vals['partner_id'] = self.env['res.partner'].create({
                    'name': vals.get('name') or _('新学生'),
                }).id
        return super().create(vals_list)

    def _compute_stats(self):
        for student in self:
            homework = student.homework_ids
            reviewed = homework.filtered(lambda h: h.state == 'reviewed' and h.question_count)
            student.session_count = len(student.session_ids)
            student.homework_count = len(homework)
            student.homework_open_count = len(homework.filtered(lambda h: h.state == 'draft'))
            student.homework_avg = (
                sum(h.accuracy for h in reviewed) / len(reviewed) if reviewed else 0.0)
            student.exam_count = len(student.exam_ids)
            scored = student.exam_ids.filtered(lambda e: e.total_full)
            student.exam_avg = (
                sum(e.percentage for e in scored) / len(scored) if scored else 0.0)
            student.mistake_count = len(student.mistake_ids)

    def _compute_point_stats(self):
        for student in self:
            student.point_count = len(student.point_ids)
            student.point_mastered_count = len(
                student.point_ids.filtered(lambda p: p.mastery == 'mastered'))

    def action_view_partner(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('门户联系人'),
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
