"""业务库上的端到端真调用：门户学生给自己那道题生成 AI 摘要。

走的是真实用户路径（取 CSRF → POST → 等 ir.cron 跑 → 回读页面），
所以顺带验到：路由与 csrf、额度、cron 取任务、写回、详情页与卡片渲染、二次点击被拦。
"""
import re
import sys
import time

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'OdooForDB'
LOGIN, PW = 'biaodi', 'Biaodi@2026'
MID = 30          # 表弟 · 五三 P12 · 变式训练3-3

ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('PASS  ' if cond else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))


s = requests.Session()
r = s.post(BASE + '/web/session/authenticate', json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': LOGIN, 'password': PW}}, timeout=60)
uid = (r.json().get('result') or {}).get('uid')
check('登录 %s' % LOGIN, bool(uid), uid)


def call(model, method, args=None, kwargs=None):
    body = s.post(BASE + '/web/dataset/call_kw', json={
        'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
            'model': model, 'method': method, 'args': args or [],
            'kwargs': kwargs or {}}}, timeout=60).json()
    if 'error' in body:
        return None, body['error'].get('data', {}).get('message', '')[:200]
    return body['result'], ''


res, err = call('tutoring.mistake', 'read', [[MID]], {'fields': ['ai_state', 'can_ai_summary']})
before = res[0] if res else {}
check('发起前：这一页定位得到且没生成过', before.get('can_ai_summary') is True, before)
res, err = call('tutoring.mistake.ai.job', 'search_count', [[]])
check('发起前这个账号还没有任何任务（额度是满的）', res == 0, res)

# 取详情页上的 csrf 令牌，真发一次 POST
page = s.get(BASE + '/my/learning/mistakes/%d' % MID, timeout=60).text
token = re.search(r'name="csrf_token" value="([^"]+)"', page)
check('详情页取到 csrf 令牌', bool(token))
check('详情页上有「生成摘要」按钮', '生成摘要' in page)

r = s.post(BASE + '/my/learning/mistakes/%d/ai_summary' % MID,
           data={'csrf_token': token.group(1)},
           headers={'Referer': BASE + '/my/learning/mistakes/%d' % MID},
           timeout=60, allow_redirects=True)
check('POST 排队成功（回到详情页并带 ai_queued）',
      r.status_code == 200 and 'ai_queued' in r.url, r.url)
check('页面提示正在生成中', '正在生成中' in r.text and '2 分钟' in r.text)

res, err = call('tutoring.mistake', 'read', [[MID]], {'fields': ['ai_state']})
check('错题已转 pending', res and res[0]['ai_state'] == 'pending', res)
res, err = call('tutoring.mistake.ai.job', 'search_read', [[]], {
    'fields': ['state', 'user_id', 'day'], 'limit': 5})
check('任务表里有 1 条排队的', res and len(res) == 1 and res[0]['state'] == 'pending', res)

# 等 cron（每 1 分钟一次，一条一提交）
state = 'pending'
for _ in range(40):
    time.sleep(6)
    res, _e = call('tutoring.mistake', 'read', [[MID]], {'fields': ['ai_state']})
    state = res[0]['ai_state'] if res else '?'
    if state in ('done', 'failed'):
        break
check('cron 跑完了（done/failed）', state in ('done', 'failed'), state)

res, err = call('tutoring.mistake', 'read', [[MID]], {
    'fields': ['ai_state', 'ai_summary', 'ai_question_text', 'ai_hint', 'point_id',
               'ai_done_at']})
row = res[0] if res else {}
print('\n  实际结果：', {k: (str(v)[:70] if v else v) for k, v in row.items()})
check('状态是 done', row.get('ai_state') == 'done', row.get('ai_state'))
check('摘要非空且 ≤40 字', bool(row.get('ai_summary')) and len(row.get('ai_summary') or '') <= 40,
      row.get('ai_summary'))
check('题目原文抄回来了', len(row.get('ai_question_text') or '') > 10,
      (row.get('ai_question_text') or '')[:60])
check('知识点没被硬填（候选里没有就留空）',
      row.get('point_id') is False, row.get('point_id'))
check('写了生成时间', bool(row.get('ai_done_at')))

res, err = call('tutoring.mistake.ai.job', 'search_read', [[]], {
    'fields': ['state', 'prompt_tokens', 'completion_tokens', 'error'], 'limit': 5})
job = res[0] if res else {}
check('任务记了 token 用量', job.get('state') == 'done'
      and job.get('prompt_tokens', 0) > 500 and job.get('completion_tokens', 0) > 10, job)

# 页面渲染：详情有摘要与题目原文，按钮不再出现；卡片上也该有摘要
page = s.get(BASE + '/my/learning/mistakes/%d' % MID, timeout=60).text
check('详情页显示题目摘要行', '题目摘要' in page)
check('详情页显示题目原文块', '题目原文' in page)
check('详情页不再给「生成摘要」按钮', '生成摘要' not in page)
listing = s.get(BASE + '/my/mistakes', timeout=60).text
check('错题卡片上直接能看到摘要',
      (row.get('ai_summary') or '@@')[:12] in listing)

# 二次发起：服务端必须拦（虽然按钮已经没了）
token = re.search(r'name="csrf_token" value="([^"]+)"', listing)
r = s.post(BASE + '/my/learning/mistakes/%d/ai_summary' % MID,
           data={'csrf_token': token.group(1)},
           headers={'Referer': BASE + '/my/mistakes'},
           timeout=60, allow_redirects=True)
check('第二次发起被拦并带回中文提示',
      'error=' in r.url and ('只能生成一次' in r.text or '已经' in r.text), r.url[:120])

res, _e = call('tutoring.mistake.ai.job', 'search_count', [[]])
check('任务表仍然只有 1 条', res == 1, res)

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
sys.exit(1 if fail else 0)
