import json

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


def _json(payload, status=200):
    """自己编码，Content-Length 按字节算，中文错误信息不会被截断。"""
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return request.make_response(body, headers=[
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(body))),
        ('Cache-Control', 'no-store'),
    ], status=status)


class TutoringTools(http.Controller):

    @http.route('/tools/function-plot', type='http', auth='public', website=True)
    def function_plot(self, **kwargs):
        """函数图像绘制器。计算与绘制在浏览器里；智能画图才回服务器。"""
        user = request.env.user
        public = not user or user._is_public()
        Call = request.env['tutoring.plot.ai.call']
        admin = (not public) and user.has_group('base.group_system')
        masked, source = '', 'none'
        if admin:
            status = Call.key_status()
            masked, source = status['masked'], status['source']
        return request.render('tutoring_center.function_plot_page', {
            'plot_ai_user': not public,
            'plot_ai_left': 0 if public else Call.quota_left(),
            'plot_ai_max': Call.DAILY_QUOTA,
            'plot_ai_admin': admin,
            'plot_ai_key_masked': masked,
            'plot_ai_key_source': source,
        })

    @http.route(
        '/tools/function-plot/ai', type='http', auth='user', methods=['POST'],
        website=True, csrf=True, readonly=False,
    )
    def function_plot_ai(self, description='', **kwargs):
        Call = request.env['tutoring.plot.ai.call']
        try:
            result = Call.draw(description)
        except AccessError:
            return _json({'ok': False, 'error': '请先登录后再使用智能画图。'}, status=403)
        except UserError as exc:
            return _json({
                'ok': False,
                'error': str(exc),
                'quota_left': Call.quota_left(),
                'quota_max': Call.DAILY_QUOTA,
            })
        return _json({
            'ok': True,
            'curves': result['curves'],
            'note': result.get('note') or '',
            'quota_left': result['quota_left'],
            'quota_max': result['quota_max'],
        })

    @http.route(
        '/tools/function-plot/ai-key', type='http', auth='user', methods=['POST'],
        website=True, csrf=True, readonly=False,
    )
    def function_plot_ai_key(self, api_key='', **kwargs):
        Call = request.env['tutoring.plot.ai.call']
        try:
            status = Call.save_api_key(api_key)
        except AccessError:
            return _json({'ok': False, 'error': '只有系统管理员可以保存密钥。'}, status=403)
        except UserError as exc:
            return _json({'ok': False, 'error': str(exc)})
        # 只回掩码。status 里本来也没有原文，这里再点一次名，避免以后加字段时漏出去。
        return _json({
            'ok': True,
            'configured': status['configured'],
            'masked': status['masked'],
            'source': status['source'],
        })
