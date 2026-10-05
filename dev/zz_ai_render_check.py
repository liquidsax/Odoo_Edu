r"""渲染上线后的核对：门户页面、后台字段、以及 prompt 文件在运行时读得到。

    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d OdooForDB --no-http < ../dev/zz_ai_render_check.py

不发起任何 API 调用，所以不花额度。
"""
import re

import requests

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('PASS  ' if cond else 'FAIL  ') + label + (('  | ' + str(extra))[:160] if not cond else ''))


print('\n== 运行时读得到 prompts/ 下的文案（不发请求） ==')
Job = env['tutoring.mistake.ai.job']
system = Job._prompt('system')
user = Job._prompt('user')
check('system 提示词读到了', '你是学习记录助手' in system and 'found' in system, len(system))
check('system 里没有被改写的措辞', '能用普通符号' not in system)
check('user 模板带全部占位符',
      all(('%%(%s)s' % k) in user for k in ('book', 'page', 'no', 'grade', 'point', 'points')),
      user[:80])
m = env['tutoring.mistake'].sudo().search([('id', '=', 30)])
job = Job.sudo().search([('mistake_id', '=', m.id)], limit=1)
payload = job._payload(m, 'QUJD', {p.full_name: p.id for p in env['tutoring.knowledge.point'].sudo().search(
    [('grade', 'in', m.student_id.knowledge_grades)], limit=5)}, 'deepseek-flash')
check('_payload 组装得出来', payload['messages'][0]['content'] == system
      and '出处：《五年高考三年模拟》' in payload['messages'][1]['content'][0]['text'],
      payload['messages'][1]['content'][0]['text'][:90])
check('思考模式显式关掉', payload.get('thinking') == {'type': 'disabled'})
check('输出上限与温度按约定', payload['max_tokens'] == 700 and payload['temperature'] == 0)

print('\n== 后台字段：渲染值与原始值 ==')
check('原始字段仍留着 LaTeX', '\\begin{cases}' in (m.ai_question_text or ''), m.ai_question_text)
check('渲染字段出了分段写法', '分段：x+6（x<a）' in (m.ai_readable_text or ''), m.ai_readable_text)
check('渲染字段没有 LaTeX 残留',
      not any(t in (m.ai_readable_text or '') for t in ('\\begin', '\\end', '$', '\\geq')),
      m.ai_readable_text)
m29 = env['tutoring.mistake'].sudo().search([('id', '=', 29)])
check('a^x 渲染成 aˣ', 'aˣ' in (m29.ai_readable_text or ''), m29.ai_readable_text)
admin = env.ref('base.user_admin')
arch = env['tutoring.mistake'].with_user(admin).get_view(
    env.ref('tutoring_center.view_tutoring_mistake_form_reader').id)['arch']
check('只读弹窗改用渲染字段', 'ai_readable_text' in arch and 'name="ai_question_text"' not in arch)

print('\n== 门户页面（真发 HTTP） ==')
B = 'http://127.0.0.1:8069'
s = requests.Session()
r = s.post(B + '/web/session/authenticate', json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': 'OdooForDB', 'login': 'biaodi', 'password': 'Biaodi@2026'}}, timeout=60)
check('登录 biaodi', bool((r.json().get('result') or {}).get('uid')))
page = s.get(B + '/my/learning/mistakes/30', timeout=60).text
check('详情页出现渲染后的分段写法', '分段：x+6（x&lt;a）' in page or '分段：x+6（x<a）' in page,
      re.search(r'题目原文.{0,400}', page, re.S).group(0)[:260] if '题目原文' in page else '没有题目原文块')
check('详情页不再出现 LaTeX 残骸', '\\begin' not in page and '\\geq' not in page)
listing = s.get(B + '/my/mistakes', timeout=60).text
check('列表卡片上有两条摘要（29 与 30）',
      '已知指数函数在区间上的最大值求底数a' in listing
      and '已知分段函数值域为R' in listing)
check('列表页没有任何 LaTeX', '\\begin' not in listing and '\\frac' not in listing)

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
