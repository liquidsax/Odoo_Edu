from odoo import fields, models

# 初中 7~9 年级按国内习惯叫初一/初二/初三，另备高中 10~12（高一/高二/高三）。
# 键值补零为两位（'07' 而非 '7'）：Selection 在库里存字符串，知识点列表的
# _order 与「按年级分组」都按字符串比较，不补零会让高一/高二/高三排在初一之前。
GRADE_SELECTION = [
    ('07', '初一'), ('08', '初二'), ('09', '初三'),
    ('10', '高一'), ('11', '高二'), ('12', '高三'),
]


class TutoringKnowledgePoint(models.Model):
    _name = 'tutoring.knowledge.point'
    _description = '知识点'
    _order = 'grade, name'

    name = fields.Char('知识点', required=True)
    grade = fields.Selection(GRADE_SELECTION, string='年级', required=True, index=True)
    note = fields.Char('说明')
    active = fields.Boolean('有效', default=True)

    _name_grade_uniq = models.Constraint(
        'unique(name, grade)', '同一年级下知识点名称不能重复。')


class TutoringStudentPoint(models.Model):
    _name = 'tutoring.student.point'
    _description = '学生知识点掌握'
    _order = 'point_id'
    _rec_name = 'point_id'

    student_id = fields.Many2one(
        'tutoring.student', string='学生', required=True,
        ondelete='cascade', index=True)
    point_id = fields.Many2one(
        'tutoring.knowledge.point', string='知识点', required=True,
        ondelete='cascade', index=True)
    mastery = fields.Selection([
        ('none', '未掌握'), ('learning', '学习中'),
        ('basic', '基本掌握'), ('mastered', '熟练掌握'),
    ], string='掌握程度', default='none', required=True, index=True)
    note = fields.Char('备注')

    _student_point_uniq = models.Constraint(
        'unique(student_id, point_id)', '该知识点已在此学生的掌握列表中。')
