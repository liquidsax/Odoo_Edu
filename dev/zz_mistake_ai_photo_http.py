# -*- coding: utf-8 -*-
"""一次性库 zz_ai_photo 上的真渲染验收：错题详情页那颗 AI 按钮与它的四条退路。

用法（先起一个只读队列、不跑 cron 的第二实例；**是 --http-port，`--port` 不存在**）：
    cd server && ../python/python.exe odoo-bin -c odoo.conf -d zz_ai_photo \\
        --http-port=8899 --http-interface=127.0.0.1 --max-cron-threads=0 \\
        --logfile=../dev/zz_ai_photo_http.log
    ../python/python.exe ../dev/zz_mistake_ai_photo_http.py

数据与账号由 dev/zz_mistake_ai_photo_seed.py 建好并写进 dev/zz_ai_photo_ids.json。
`--max-cron-threads=0` 是刻意的：排队之后不让它真去发请求（一次性库里三层都没密钥，
本来也只会长一条不扣额度的 error，但把 cron 关掉更干净——这一轮验的是页面与发起，
取料与状态机由 zz_mistake_ai_photo_check.py 那 44 条断言管）。
用 requests 自带会话，不碰浏览器那个 cookie jar（8069 与 8899 共用会互相顶登录）。
"""
import json
import os
import re

import requests

BASE = 'http://127.0.0.1:8899'
DB = 'zz_ai_photo'

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'zz_ai_photo_ids.json'), encoding='utf-8') as fh:
    IDS = json.load(fh)
LOGIN, PW = IDS['login'], 'zz-aiphoto-pw'

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %s %s' % (label, extra))
    else:
        fail += 1
        print('  FAIL  %s %s' % (label, extra))


def render(url, session_obj=None):
    resp = (session_obj or session).get(BASE + url, allow_redirects=False, timeout=60)
    body = resp.text
    broken = any(marker in body for marker in (
        'Traceback', 'QWebException', 'xml syntax error', 'is undefined', 'missed'))
    return resp, body, broken


def token_of(body):
    found = re.search(r'name="csrf_token" value="([^"]+)"', body)
    return found.group(1) if found else ''


def queue(mistake_id, body):
    return session.post(BASE + '/my/learning/mistakes/%s/ai_summary' % mistake_id,
                        allow_redirects=False, timeout=60,
                        data={'csrf_token': token_of(body)})


session = requests.Session()
auth = session.post(BASE + '/web/session/authenticate', timeout=60, json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': LOGIN, 'password': PW}})
uid = (auth.json().get('result') or {}).get('uid')
print('\n== 登录 ==')
check('门户账号登录成功', bool(uid), 'uid=%s' % uid)
if not uid:
    raise SystemExit('登不进去，后面都不用跑：%s' % auth.text[:300])

print('\n== 判据放宽在真页面上：没练习册、只有照片的那道 ==')
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['own'])
check('只有照片的题：页面 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('  「生成摘要」按钮真的渲染出来了', '生成摘要' in body)
check('  额度那句提示也在', bool(re.search(r'今天还能生成\s*<b>\d+', body)))

resp, body, broken = render('/my/learning/mistakes/%s' % IDS['teacher'])
check('附件是老师传的、学生看不到那条附件，按钮照样出现（判据走 sudo）',
      resp.status_code == 200 and not broken and '生成摘要' in body)
check('  而他这一页确实没把老师的附件列出来', 'ZZ 老师帮拍的' not in body)

print('\n== 没素材的那道：按钮收起，但要说清为什么 ==')
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['none'])
check('没照片又没出处的题：不给按钮', resp.status_code == 200 and not broken
      and '生成摘要' not in body)
check('  改说一句为什么（而不是让人对着空按钮区猜）', '还没有能交给 AI 的素材' in body)

resp, body, broken = render('/my/learning/mistakes/%s' % IDS['blank'])
check('能定位到页、页里没位图的：按钮照给（取不到料是不扣额度的退让，不是锁死）',
      '生成摘要' in body)

print('\n== 口径改的那一条：上一次没成功的，这一页要能再点 ==')
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['failed'])
check('failed 的那道重新长出按钮', resp.status_code == 200 and not broken
      and '生成摘要' in body)
check('  话从"不再自动生成"改成了"可以再点一次"', '上一次没生成出来，可以再点一次' in body)
resp2 = queue(IDS['failed'], body)
check('  真 POST 一次：排进队列而不是被拒', resp2.status_code in (301, 303)
      and 'ai_queued=1' in resp2.headers.get('Location', ''),
      resp2.headers.get('Location', ''))

print('\n== 排队与再点 ==')
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['own'])
resp2 = queue(IDS['own'], body)
check('有素材的一道：POST 后 303 回详情页并带 ai_queued', resp2.status_code in (301, 303)
      and 'ai_queued=1' in resp2.headers.get('Location', ''),
      resp2.headers.get('Location', ''))
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['own'])
check('生成中的那一版：按钮收起、写明大约两分钟',
      '正在生成中' in body and '生成摘要' not in body)
resp2 = queue(IDS['own'], body)
loc = resp2.headers.get('Location', '')
check('正在生成时再点一次：被挡下来并把话带回页面上',
      resp2.status_code in (301, 303) and 'error=' in loc, loc[:120])
check('  挡下来的那句说的是"排进队列"而不是"只能一次"',
      'error=%E8%BF%99%E9%81%93%E9%A2%98%E5%B7%B2%E7%BB%8F%E6%8E%92%E8%BF%9B%E9%98%9F%E5%88%97' in loc
      or '排进队列' in requests.utils.unquote(loc), loc[:160])

print('\n== 手工 POST 一道没素材的题：能排上，但那条任务花不到钱（模型层已验 state=error）==')
resp, body, broken = render('/my/learning/mistakes/%s' % IDS['none'])
resp2 = queue(IDS['none'], body)
check('不被 500 也不被 400 挡（闸在取料那一步，不在发起）',
      resp2.status_code in (301, 303) and 'ai_queued=1' in resp2.headers.get('Location', ''),
      resp2.headers.get('Location', ''))

print('\n== 匿名访问不炸 ==')
anon = requests.Session()
for url in ('/my/learning/mistakes/%s' % IDS['own'], '/my/mistakes'):
    resp = anon.get(BASE + url, allow_redirects=False, timeout=60)
    check('匿名 %s → 303 跳登录' % url, resp.status_code in (301, 303), resp.status_code)

print('\n== 汇总：%d 条断言，%d 条没过 ==' % (ok, fail))
