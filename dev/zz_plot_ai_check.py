# -*- coding: utf-8 -*-
"""一次性库上验智能画图（不联网：requests.post 换成桩）。

    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_plot_ai_check.py

脚本结束前回滚，不往库里留账号。密钥只写临时目录里的 .env。
"""
import io
import os
import shutil
import stat
import tempfile

import requests

from odoo.exceptions import AccessError, UserError

from odoo.addons.tutoring_center.models import tutoring_plot_ai as plot_mod
from odoo.addons.tutoring_center.models.tutoring_plot_ai import (
    DAILY_QUOTA, MAX_OUTPUT_TOKENS,
)

FAKE_KEY = 'sk-TESTKEYONLY0001'
ELLIPSE = (
    '{"found": true, "curves": [{"expr": "x^2/9+y^2/4=1", "label": "椭圆"}]}'
)

ok = fail = 0
captured = {}


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print('  %s  %s %s' % ('PASS' if cond else 'FAIL', label, extra if not cond else ''))


class FakeResp:
    def __init__(self, status, content, usage=True):
        self.status_code = status
        self._content = content
        self.text = content
        self._usage = usage

    def json(self):
        body = {'choices': [{'message': {'content': self._content}}]}
        if self._usage:
            body['usage'] = {'prompt_tokens': 120, 'completion_tokens': 40}
        return body


def install(responder):
    def fake_post(url, headers=None, json=None, timeout=None, allow_redirects=None):
        captured['url'] = url
        captured['json'] = json
        captured['timeout'] = timeout
        captured['redirects'] = allow_redirects
        auth = (headers or {}).get('Authorization') or ''
        captured['auth_is_bearer'] = auth.startswith('Bearer ')
        captured['auth_echoes_key'] = FAKE_KEY in auth
        return responder()
    plot_mod.requests.post = fake_post


def raises(fn, kind):
    try:
        fn()
    except kind:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


Call = env['tutoring.plot.ai.call']
icp = env['ir.config_parameter'].sudo()
tmp = tempfile.mkdtemp(prefix='zz_plot_ai_')
env_path = os.path.join(tmp, '.env')
old_key = os.environ.pop('DEEPSEEK_API_KEY', None)
old_file = os.environ.pop('TUTORING_DEEPSEEK_ENV_FILE', None)
icp.set_param('tutoring_center.deepseek_env_file', env_path)
icp.set_param('tutoring_center.deepseek_api_key', '')
icp.set_param('tutoring_center.deepseek_plot_model', '')

g_user = env.ref('base.group_user')
g_portal = env.ref('base.group_portal')
g_system = env.ref('base.group_system')
tag = 'zzplot'


def mk_user(login, groups):
    return env['res.users'].sudo().create({
        'name': login, 'login': login, 'email': '%s@example.invalid' % login,
        'password': login + '-pw',
        'group_ids': [(4, g.id) for g in groups],
    })


pupil = mk_user(tag + '_p', [g_portal])
teacher = mk_user(tag + '_t', [g_user, env.ref('tutoring_center.group_teacher')])
admin = env.ref('base.user_admin')

print('\n== 没钥匙、空输入、超长：不建流水 ==')
before = Call.sudo().search_count([])
check('没钥匙', raises(lambda: Call.with_user(pupil).draw('椭圆'), UserError))
check('空描述', raises(lambda: Call.with_user(pupil).draw('  '), UserError))
check('超长', raises(lambda: Call.with_user(pupil).draw('椭圆' * 201), UserError))
check('这三下都没记账', Call.sudo().search_count([]) == before)
check('匿名直接拒绝', raises(
    lambda: Call.with_user(env.ref('base.public_user')).draw('椭圆'), AccessError))

print('\n== 桩出来的椭圆 ==')
os.environ['DEEPSEEK_API_KEY'] = FAKE_KEY
install(lambda: FakeResp(200, ELLIPSE))
result = Call.with_user(pupil).draw('焦点在x轴、离心率√5/3、长轴长6的椭圆')
check('画出椭圆', result['curves'][0]['expr'] == 'x^2/9+y^2/4=1' and result['curves'][0]['label'] == '椭圆')
check('额度剩 9', result['quota_left'] == DAILY_QUOTA - 1, result['quota_left'])
payload = captured['json']
check('显式 max_tokens', payload['max_tokens'] == MAX_OUTPUT_TOKENS, payload['max_tokens'])
check('关掉思考', payload['thinking'] == {'type': 'disabled'})
check('不锁死单个 JSON', 'response_format' not in payload)
check('超时写明了', captured['timeout'] == plot_mod.API_TIMEOUT)
check('不跟随重定向', captured['redirects'] is False)
check('描述进了用户提示词', '焦点在x轴' in payload['messages'][1]['content'])
check('默认模型是 deepseek-flash', payload['model'] == 'deepseek-flash', payload['model'])
check('请求带了 Bearer', captured['auth_is_bearer'])
icp.set_param('tutoring_center.deepseek_plot_model', 'deepseek-v4-pro')
Call.with_user(pupil).draw('再画一条直线 y=x')
check('画图模型参数盖过共用默认', captured['json']['model'] == 'deepseek-v4-pro')
icp.set_param('tutoring_center.deepseek_plot_model', '')

print('\n== 整道题里的椭圆：模型拒绝也要画出来 ==')
ELLIPSE_PROBLEM = (
    '3.椭圆 C: frac{x^{2}}{16}+frac{y^{2}}{7}=1 的两个焦点分别为 F_{1}, F_{2}, '
    '椭圆 C 上有一点 P, 则 triangle P F_{1} F_{2} 的周长为'
)
before_used = DAILY_QUOTA - Call.with_user(pupil).quota_left()
install(lambda: FakeResp(200, '{"found": false, "error": "不是函数图像"}'))
recovered = Call.with_user(pupil).draw(ELLIPSE_PROBLEM)
expr = recovered['curves'][0]['expr']
check('拒绝之后仍画出椭圆', '16' in expr and '7' in expr and recovered['curves'][0].get('label') == '椭圆', expr)
check('这次仍扣额度', DAILY_QUOTA - Call.with_user(pupil).quota_left() == before_used + 1)
check('说明是从题目方程来的', '已经有方程' in (recovered.get('note') or ''), recovered.get('note'))

print('\n== 图片：识图桩 ==')
from PIL import Image
buf = io.BytesIO()
Image.new('RGB', (80, 40), (20, 40, 180)).save(buf, 'PNG')
png = buf.getvalue()
before = Call.sudo().search_count([])
check('不是图片不记账', raises(lambda: Call.with_user(pupil).draw('椭圆', image=b'<svg></svg>'), UserError))
check('太大不记账', raises(
    lambda: Call.with_user(pupil).draw('', image=b'\xff\xd8\xff' + b'0' * (8 * 1024 * 1024)), UserError))
check('这两下都没记账', Call.sudo().search_count([]) == before)
install(lambda: FakeResp(200, ELLIPSE))
seen = Call.with_user(pupil).draw('', image=png)
check('只上传图片也能画出', seen['curves'][0]['expr'] == 'x^2/9+y^2/4=1')
content = captured['json']['messages'][1]['content']
check('识图走 image_url', isinstance(content, list) and content[1]['type'] == 'image_url')
url = content[1]['image_url']['url']
check('发出去的是 jpeg', url.startswith('data:image/jpeg;base64,') and 'png' not in url[:40])
check('识图超时更长', captured['timeout'] == plot_mod.API_TIMEOUT_IMAGE, captured['timeout'])
check('识图也关思考', captured['json']['thinking'] == {'type': 'disabled'})
check('图片原文不在流水说明里', '（图片）' in Call.sudo().search([], limit=1, order='id desc').description)

print('\n== 花了 token 才扣；没花不扣 ==')
used = lambda: DAILY_QUOTA - Call.with_user(pupil).quota_left()
before_used = used()
install(lambda: FakeResp(200, '{"found": false, "error": "不是函数图像"}'))
check('画不了是 UserError', raises(lambda: Call.with_user(pupil).draw('今天天气怎么样'), UserError))
check('画不了扣一次', used() == before_used + 1, used())
before_used = used()
install(lambda: FakeResp(200, '我不会按 JSON 说'))
check('解析失败扣一次', raises(lambda: Call.with_user(pupil).draw('椭圆'), UserError) and used() == before_used + 1, used())
before_used = used()
install(lambda: FakeResp(200, '{"found": true, "curves": [{"expr": "__import__(\'os\')"}]}'))
check('代码式子扣一次但不返回式子', raises(lambda: Call.with_user(pupil).draw('椭圆'), UserError) and used() == before_used + 1, used())
def _timeout():
    raise requests.Timeout('slow')


install(_timeout)
before_used = used()
check('超时是 UserError', raises(lambda: Call.with_user(pupil).draw('椭圆'), UserError))
check('超时不扣', used() == before_used, used())
install(lambda: FakeResp(401, 'no', usage=False))
check('401 不扣', raises(lambda: Call.with_user(pupil).draw('椭圆'), UserError) and used() == before_used)

print('\n== 一天 10 次，人与人分开 ==')
# 上面已经用掉若干次，补到顶
left = Call.with_user(pupil).quota_left()
install(lambda: FakeResp(200, '{"found": true, "curves": [{"expr": "y=x"}]}'))
for _i in range(left):
    Call.with_user(pupil).draw('直线')
check('额度到 0', Call.with_user(pupil).quota_left() == 0)
check('第 11 次被拦', raises(lambda: Call.with_user(pupil).draw('直线'), UserError))
check('老师自己还有 10 次', Call.with_user(teacher).quota_left() == DAILY_QUOTA)
check('门户只能看见自己扣过次数的流水', Call.with_user(pupil).search_count(
    [('state', 'in', ('pending', 'done', 'failed'))]) == DAILY_QUOTA)
check('老师看不见学生的流水', Call.with_user(teacher).search_count([]) == 0)

print('\n== 密钥：管理员能存，别人 403，页面上看不到全文 ==')
os.environ.pop('DEEPSEEK_API_KEY', None)
check('老师不能存', raises(lambda: Call.with_user(teacher).save_api_key(FAKE_KEY), AccessError))
check('老师不能看状态', raises(lambda: Call.with_user(teacher).key_status(), AccessError))
check('失败时文件还没出现', not os.path.exists(env_path))
status = Call.with_user(admin).save_api_key(FAKE_KEY)
masked = status['masked']
check('掩码是末四位', masked == '****' + FAKE_KEY[-4:] and FAKE_KEY not in masked, masked)
check('状态里没有 key 这个字段', 'key' not in status)
check('文件 0600', stat.S_IMODE(os.stat(env_path).st_mode) == 0o600)
check('进程环境变量已更新', os.environ.get('DEEPSEEK_API_KEY') == FAKE_KEY)
os.environ.pop('DEEPSEEK_API_KEY', None)
check('重启前之外：文件能被读回来', Call.with_user(admin).key_status()['source'] == 'file')
check('非管理员仍然不能读', raises(lambda: Call.with_user(pupil).key_status(), AccessError))

print('\n%d PASS / %d FAIL' % (ok, fail))
shutil.rmtree(tmp, ignore_errors=True)
if old_key is None:
    os.environ.pop('DEEPSEEK_API_KEY', None)
else:
    os.environ['DEEPSEEK_API_KEY'] = old_key
if old_file is not None:
    os.environ['TUTORING_DEEPSEEK_ENV_FILE'] = old_file
env.cr.rollback()
if fail:
    raise SystemExit(1)
