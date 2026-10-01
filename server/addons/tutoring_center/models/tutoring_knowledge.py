from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# 初中 7~9 年级按国内习惯叫初一/初二/初三，另备高中 10~12（高一/高二/高三）。
# 键值补零为两位（'07' 而非 '7'）：Selection 在库里存字符串，知识点列表的
# _order 与「按年级分组」都按字符串比较，不补零会让高一/高二/高三排在初一之前。
# '13'（高中）不指某个学年，而是跨高一~高三的整层知识点（53A 精讲册的专题都挂它），
# 所以高一/高二/高三的学生挑选时连 '13' 一起给，见 tutoring.student.knowledge_grades。
GRADE_SELECTION = [
    ('07', '初一'), ('08', '初二'), ('09', '初三'),
    ('10', '高一'), ('11', '高二'), ('12', '高三'),
    ('13', '高中'),
]
GRADE_LABEL = dict(GRADE_SELECTION)
SENIOR_HIGH = '13'


class TutoringKnowledgePoint(models.Model):
    _name = 'tutoring.knowledge.point'
    _description = '知识点'
    # 树形平铺：枝干（parent_id 为空）排在它的叶子之前，同级按录入先后。
    # 不按 name 排——中文名是按 Unicode 码位比的，「计数原理」会插到「集合」前面，
    # 自带的高中库就乱了原书专题顺序；按 id 排恰好是导数据的顺序，手填的排在末尾。
    _order = 'grade, parent_id nulls first, id'

    name = fields.Char('知识点', required=True)
    grade = fields.Selection(GRADE_SELECTION, string='年级', required=True, index=True)
    parent_id = fields.Many2one(
        'tutoring.knowledge.point', string='上级', ondelete='cascade', index=True)
    full_name = fields.Char('完整路径', compute='_compute_full_name')
    note = fields.Char('说明')
    active = fields.Boolean('有效', default=True)

    # 属性名不改（改成 _name_grade_parent_uniq 只会让旧约束在库里无人认领地留着）：
    # Odoo 19 比对定义后会 drop 再 add，同名换定义即可生效。
    _name_grade_uniq = models.Constraint(
        'unique(name, grade, parent_id)', '同一上级下知识点名称不能重复。')

    @api.onchange('parent_id')
    def _onchange_parent_id(self):
        # 年级不一致会让子节点从父节点的分组与排序里掉出去。
        if self.parent_id:
            self.grade = self.parent_id.grade

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('知识点不能把自己或自己的下级设为上级。'))

    @api.depends('name', 'grade', 'parent_id.full_name')
    def _compute_full_name(self):
        for point in self:
            names = [point.name]
            parent = point.parent_id
            while parent:
                names.append(parent.name)
                parent = parent.parent_id
            grade_label = GRADE_LABEL.get(point.grade)
            if grade_label:
                names.append(grade_label)
            point.full_name = ' / '.join(reversed(names))


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
