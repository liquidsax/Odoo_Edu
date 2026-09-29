from odoo import fields, models


class TutoringTopic(models.Model):
    _name = 'tutoring.topic'
    _description = '教学内容'
    _order = 'name'

    name = fields.Char('名称', required=True)
    note = fields.Char('说明')
    active = fields.Boolean('有效', default=True)

    def action_view_related_records(self):
        """返回该教学内容下的课次/作业/考试记录。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'教学内容：{self.name}',
            'res_model': 'tutoring.session',
            'view_mode': 'list,form,calendar',
            'domain': [('topic_ids', 'in', self.id)],
            'context': {'default_topic_ids': [(6, 0, [self.id])]},
        }
