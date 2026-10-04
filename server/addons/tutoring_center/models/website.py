import base64

from odoo import api, models, tools

BRAND_NAME = 'R3ynA 学习平台'
BRAND_LOGO = 'tutoring_center/static/img/logo.svg'
BRAND_FAVICON = 'tutoring_center/static/img/favicon.png'

# 本平台没有可用的联系表单（没配 SMTP，提交也发不出信），Odoo 自带的 Contact us 入口全部撤掉
CONTACTUS_MENU_URLS = ['/contactus']
CONTACTUS_PAGE_URLS = ['/contactus', '/contactus_form', '/contactus-thank-you']


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

    @api.model
    def _apply_tutoring_website_cleanup(self):
        """撤掉 Odoo 自带的 Contact us 导航项与页面。

        `website.menu` 没有 active 字段，只能删；页面走 unpublish。两者都是幂等的，
        每次升级重放——website 模块升级会把 menu_contactus 建回来。
        """
        self.env['website.menu'].sudo().search(
            [('url', 'in', CONTACTUS_MENU_URLS)]).unlink()
        pages = self.env['website.page'].sudo().search(
            [('url', 'in', CONTACTUS_PAGE_URLS), ('is_published', '=', True)])
        if pages:
            pages.write({'is_published': False})
