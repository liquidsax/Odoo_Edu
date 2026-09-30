from odoo import fields, models


class TutoringWorkbook(models.Model):
    _name = 'tutoring.workbook'
    _description = '练习册'
    _order = 'name'

    name = fields.Char('名称', required=True)
    note = fields.Char('备注')
    active = fields.Boolean('启用', default=True)

    mistake_ids = fields.One2many('tutoring.mistake', 'workbook_id', string='错题')
    mistake_count = fields.Integer('错题数', compute='_compute_mistake_count')

    def _compute_mistake_count(self):
        for workbook in self:
            workbook.mistake_count = len(workbook.mistake_ids)
