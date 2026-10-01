import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# 一次最多生成多少条，防止把"1-9999"当成批量录入
MAX_LINES = 100


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
    difficulty = fields.Selection([
        ('2', '🌶🌶'), ('3', '🌶🌶🌶'),
        ('4', '🌶🌶🌶🌶'), ('5', '🌶🌶🌶🌶🌶'),
    ], string='难度', default='3')
    note = fields.Text('错因/备注')

    @api.model
    def _last_mistake(self):
        return self.env['tutoring.mistake'].search([], limit=1, order='create_date desc, id desc')

    def _question_numbers(self):
        """把"1-5""1,3,7""1-3,7"这类写法展开成题号列表；留空则只记一道。"""
        tokens = re.split(r'[,，、;；]', self.question_no or '')
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
        if len(numbers) > MAX_LINES:
            raise ValidationError(_('一次最多记录 %s 道题，请缩小题号范围。') % MAX_LINES)
        return numbers or [False]

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
