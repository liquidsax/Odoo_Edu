from odoo import fields, models

# 错因归类：按"错在哪一环"分，跨学科通用（数学/编程/阅读都套得进去）。
CAUSE_CATEGORY_SELECTION = [
    ('concept', '概念'),
    ('read', '审题'),
    ('compute', '运算'),
    ('strategy', '策略'),
    ('habit', '习惯'),
    ('other', '其它'),
]


class TutoringMistakeCause(models.Model):
    """错因字典：录错题时从这一套里选，而不是对着空白文本框发呆。

    预置数据在 data/mistake_cause_data.xml，noupdate=1，老师改过的不会被升级还原。
    """
    _name = 'tutoring.mistake.cause'
    _description = '错因'
    # 顺序由 sequence 说了算（预置数据按"概念→审题→运算→策略→习惯→其它"排好）；
    # 不按 category 排——键是英文，按它排会把分组打散成字母序。
    _order = 'sequence, id'

    name = fields.Char('错因', required=True)
    category = fields.Selection(
        CAUSE_CATEGORY_SELECTION, string='归类', required=True, default='other', index=True)
    hint = fields.Char('怎么理解')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('有效', default=True)

    mistake_count = fields.Integer('错题数', compute='_compute_mistake_count')

    _name_uniq = models.Constraint('unique(name)', '这条错因已经有了。')

    def _compute_mistake_count(self):
        counts = self.env['tutoring.mistake']._read_group(
            [('cause_id', 'in', self.ids)], ['cause_id'], ['__count'])
        by_id = {cause.id: count for cause, count in counts}
        for cause in self:
            cause.mistake_count = by_id.get(cause.id, 0)
