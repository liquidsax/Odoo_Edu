import base64

from odoo import api, models, tools

BRAND_NAME = 'R3ynA 学习平台'
BRAND_LOGO = 'tutoring_center/static/img/logo.svg'
BRAND_FAVICON = 'tutoring_center/static/img/favicon.png'


class Website(models.Model):
    _inherit = 'website'

    @api.model
    def _apply_tutoring_branding(self):
        """把网站名 / 顶栏 logo / 浏览器图标统一成模块里声明的那一份。

        写成函数而不是 <record id="website.default_website">：那个 xmlid 自身带
        noupdate=1，升级时 Odoo 会直接跳过这类外部记录，名字永远换不掉。
        代价同上——网站设置里手填的这几项会在每次升级被盖回去。
        """
        def _b64(path):
            with tools.file_open(path, 'rb') as f:
                return base64.b64encode(f.read())

        self.env['res.company'].search([]).write({'name': BRAND_NAME})
        self.search([]).write({
            'name': BRAND_NAME,
            'logo': _b64(BRAND_LOGO),
            'favicon': _b64(BRAND_FAVICON),
        })
