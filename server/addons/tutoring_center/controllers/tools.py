from odoo import http
from odoo.http import request


class TutoringTools(http.Controller):

    @http.route('/tools/function-plot', type='http', auth='public', website=True)
    def function_plot(self, **kwargs):
        """函数图像绘制器：纯前端计算与绘制，服务端只负责出页面。"""
        return request.render('tutoring_center.function_plot_page', {})
