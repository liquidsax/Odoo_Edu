from odoo import api, models

# 隐藏的后台应用根菜单：应用/讨论/项目/邮件营销/调查/员工/仪表板
MENUS_TO_HIDE = [
    'base.menu_management',
    'mail.menu_root_discuss',
    'project.menu_main_pm',
    'mass_mailing.mass_mailing_menu_root',
    'survey.menu_surveys',
    'hr.menu_hr_root',
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',
]


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _apply_tutoring_menu_cleanup(self):
        """把与数学辅导无关的应用根菜单限制到"显示全部应用菜单"组，
        组内无人即隐藏；把用户加入该组即可恢复显示。"""
        group = self.env.ref('tutoring_center.group_show_hidden_apps')
        for xmlid in MENUS_TO_HIDE:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu.group_ids = [(6, 0, group.ids)]
