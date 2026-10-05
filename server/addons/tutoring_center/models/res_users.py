from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        """新老师/新管理员一进来就有一份自己的学习档案。

        错题必须挂在某个档案下（`student_id` 必填），没有档案的人就记不了题；
        存量的人由 `migrations/19.0.1.15.0/post-migrate.py` 补齐。
        """
        users = super().create(vals_list)
        students = self.env['tutoring.student']
        for user in users:
            if user.has_group('tutoring_center.group_teacher'):
                students.ensure_self_profile(user)
        return users
