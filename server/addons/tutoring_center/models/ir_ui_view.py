from odoo import api, models

# 与本平台无关、需要停用的他人模块视图（门户首页卡片等）。
# 这些模块并非本模块依赖，新库里可能根本没装，故按 xml id 容错处理。
VIEWS_TO_DISABLE = [
    'project.portal_my_home',
]

# 页脚文案是改造时用 dev/branding2.py 直接写进 website.footer_custom 的库内容，
# 模块里没有它的 XML 副本，改名只能按旧串就地替换。
FOOTER_BRAND_REPLACEMENTS = [
    ('数学辅导中心 · 学习数据平台', 'R3ynA 学习平台'),
    ('记录每一次课、每一份作业、每一场考试，让学习进步看得见。',
     '记下做错的题、刷过的好题、翻过的书，让学习留痕。'),
]


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _apply_tutoring_view_cleanup(self):
        for xml_id in VIEWS_TO_DISABLE:
            view = self.env.ref(xml_id, raise_if_not_found=False)
            if view and view.active:
                view.active = False

    @api.model
    def _apply_tutoring_footer_branding(self):
        """把页脚里残留的旧品牌串换成当前口径；没跑过 branding2.py 的库是空操作。"""
        view = self.env.ref('website.footer_custom', raise_if_not_found=False)
        if not view:
            return
        for lang, _name in self.env['res.lang'].get_installed():
            arch = view.with_context(lang=lang).arch_db or ''
            new_arch = arch
            for old, new in FOOTER_BRAND_REPLACEMENTS:
                new_arch = new_arch.replace(old, new)
            if new_arch != arch:
                view.with_context(lang=lang).arch_db = new_arch
