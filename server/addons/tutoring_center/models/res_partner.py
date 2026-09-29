from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    tutoring_student_ids = fields.One2many(
        'tutoring.student', 'partner_id', string='关联学生')
    tutoring_school = fields.Char(
        '学校', compute='_compute_tutoring_school', store=True, readonly=False,
        inverse='_inverse_tutoring_school',
        help='与该联系人关联的学生所在学校；在此修改会同步写回学生档案。')

    @api.depends('tutoring_student_ids.school')
    def _compute_tutoring_school(self):
        for partner in self:
            partner.tutoring_school = partner.tutoring_student_ids[:1].school

    def _inverse_tutoring_school(self):
        for partner in self:
            if partner.tutoring_student_ids:
                partner.tutoring_student_ids.write({'school': partner.tutoring_school})
