from odoo import api, models

# 与数学辅导无关、需要停用的他人模块视图（门户首页卡片等）。
# 这些模块并非本模块依赖，新库里可能根本没装，故按 xml id 容错处理。
VIEWS_TO_DISABLE = [
    'project.portal_my_home',
]


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _apply_tutoring_view_cleanup(self):
        for xml_id in VIEWS_TO_DISABLE:
            view = self.env.ref(xml_id, raise_if_not_found=False)
            if view and view.active:
                view.active = False
