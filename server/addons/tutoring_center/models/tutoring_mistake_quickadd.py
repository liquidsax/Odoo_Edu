from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .tutoring_mistake import split_question_numbers


class TutoringMistakeQuickadd(models.TransientModel):
    _name = 'tutoring.mistake.quickadd'
    _description = '错题速记'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True,
        default=lambda s: s._last_mistake().student_id.id)
    date = fields.Date('发生日期', required=True, default=fields.Date.context_today)
    workbook_id = fields.Many2one(
        'tutoring.workbook', string='练习册', required=True,
        default=lambda s: s._last_mistake().workbook_id.id)
    page = fields.Char('页码')
    question_no = fields.Char('题号')
    topic_id = fields.Many2one('tutoring.topic', string='相关教学内容')
    cause_id = fields.Many2one('tutoring.mistake.cause', string='错因')
    point_id = fields.Many2one('tutoring.knowledge.point', string='知识点')
    # 挑知识点的域按学生年级放开，字段得在表单里（不可见）加载出来
    knowledge_grades = fields.Json('可选知识点年级', related='student_id.knowledge_grades')
    student_grade = fields.Selection(related='student_id.grade', string='学生年级')
    difficulty = fields.Selection([
        ('2', '🌶🌶'), ('3', '🌶🌶🌶'),
        ('4', '🌶🌶🌶🌶'), ('5', '🌶🌶🌶🌶🌶'),
    ], string='难度', default='3')
    note = fields.Text('补充说明')

    @api.model
    def _last_mistake(self):
        return self.env['tutoring.mistake'].search([], limit=1, order='create_date desc, id desc')

    def _question_numbers(self):
        """题号写法展开，解析规则统一在 tutoring_mistake.split_question_numbers。"""
        return split_question_numbers(self.question_no)

    def _action_window(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('快速记录错题'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _create_mistakes(self):
        self.ensure_one()
        if not self.student_id or not self.workbook_id:
            raise ValidationError(_('请先选择学生和练习册。'))
        base = {
            'student_id': self.student_id.id,
            'date': self.date,
            'workbook_id': self.workbook_id.id,
            'page': (self.page or '').strip() or False,
            'topic_id': self.topic_id.id or False,
            'cause_id': self.cause_id.id or False,
            'point_id': self.point_id.id or False,
            'difficulty': self.difficulty or '3',
            'note': (self.note or '').strip() or False,
        }
        return self.env['tutoring.mistake'].create([
            dict(base, question_no=no) for no in self._question_numbers()
        ])

    def action_save_and_more(self):
        """入库后清空出处、保留学生/练习册/难度，继续记下一批。"""
        self._create_mistakes()
        self.write({'page': False, 'question_no': False, 'note': False})
        return self._action_window()

    def action_save_and_close(self):
        self._create_mistakes()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
