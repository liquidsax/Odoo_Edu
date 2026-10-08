"""时间账本（Do1ng 云同步）批次①的 HTTP 验收。

跑的是一次性新库上的独立实例（默认 http://127.0.0.1:8899），**不碰共享业务库**。
覆盖：探活 → 登录（含缺头/错密码）→ 首次全量上传 → 重推幂等 → 改版 → 陈旧 rev 冲突
→ rebase 收敛 → 时区与时长口径 → 墓碑与级联 → 脏行被拒 → 记录规则隔离 → 门户页与资产包。

用法：
    set ZZ_TIME_PW_A=... & set ZZ_TIME_PW_B=... & python dev/zz_time_http.py
"""
import os
import re
import sys

import requests

BASE = os.environ.get('ZZ_TIME_BASE', 'http://127.0.0.1:8899')
LOGIN_A = os.environ.get('ZZ_TIME_LOGIN_A', 'zz_time_a')
LOGIN_B = os.environ.get('ZZ_TIME_LOGIN_B', 'zz_time_b')
PW_A = os.environ['ZZ_TIME_PW_A']
PW_B = os.environ['ZZ_TIME_PW_B']
HEADER = {'X-Do1ng-Sync': '1'}
CLIENT = {'device_key': 'dev-machine-0001', 'device_name': '验收机',
          'platform': 'windows', 'client_version': 'test-1'}

ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS  ' + name)
    else:
        fail += 1
        print('FAIL  ' + name + (('  | ' + str(extra)) if extra != '' else ''))


def body_of(response):
    try:
        return response.json()
    except ValueError:
        return {}


def task(cid, title, status='ACTIVE', created='2026-10-01T09:00:00+08:00',
         rev=0, deleted=False, interrupted=0):
    return {'client_id': cid, 'title': title, 'status': status, 'created': created,
            'interrupted_count': interrupted, 'updated_at': created,
            'rev': rev, 'deleted': deleted}


def sess(cid, task_cid, start, end=None, notes=None, rev=0, deleted=False):
    return {'client_id': cid, 'task_client_id': task_cid, 'start': start, 'end': end,
            'notes': notes or [], 'updated_at': start, 'rev': rev, 'deleted': deleted}


def pool(cid, task_cid, text, created, done_at=None, rev=0, deleted=False):
    return {'client_id': cid, 'task_client_id': task_cid, 'text': text, 'created': created,
            'done_at': done_at, 'updated_at': created, 'rev': rev, 'deleted': deleted}


def push(session, tasks=None, sessions=None, items=None, offset=480):
    response = session.post(BASE + '/tutoring/time/sync', headers=HEADER, timeout=120, json={
        'client': CLIENT,
        'utc_offset_minutes': offset,
        'changes': {'tasks': tasks or [], 'sessions': sessions or [], 'pool': items or []},
    })
    return response, body_of(response)


def call(session, model, method, args=None, kwargs=None):
    """打一次 JSON-RPC。

    注意 `args` 会被服务端 `method(recs, *args)` 展开一层，所以 domain 一律走 kwargs，
    只有**记录方法**（非 @api.model，如 read/write）才把 ids 放在 args[0]。
    """
    response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
        'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
            'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}})
    payload = body_of(response)
    if 'error' in payload:
        return None, payload['error'].get('data', {}).get('message', '')[:200]
    return payload.get('result'), ''


def login(login, password):
    session = requests.Session()
    response = session.post(BASE + '/tutoring/time/login', headers=HEADER, timeout=120,
                            json={'login': login, 'password': password})
    return session, response, body_of(response)


print('=== 一、匿名：探活与鉴权闸门 ===')
anon = requests.Session()
r = anon.get(BASE + '/tutoring/time/ping', timeout=60)
b = body_of(r)
check('ping 200', r.status_code == 200, r.status_code)
check('ping 报 ok 且协议版本=1', b.get('ok') is True and b.get('protocol') == 1, b)
check('ping 里匿名是未登录', b.get('logged_in') is False, b)
check('ping 不泄露库名', 'zz_do1ng_time' not in r.text, r.text[:120])

r = anon.post(BASE + '/tutoring/time/sync', timeout=60, json={'changes': {}})
check('同步缺自定义头 → 400', r.status_code == 400, r.status_code)
check('缺头的错误码是 missing_client_header',
      body_of(r).get('error') == 'missing_client_header', body_of(r))

r = anon.post(BASE + '/tutoring/time/sync', headers=HEADER, timeout=60, json={'changes': {}})
check('匿名带头同步 → 401（不是 302 到登录页）', r.status_code == 401, r.status_code)
check('匿名同步错误码 not_logged_in',
      body_of(r).get('error') == 'not_logged_in', body_of(r))

r = anon.post(BASE + '/tutoring/time/login', timeout=60, json={'login': 'x', 'password': 'y'})
check('登录缺自定义头 → 400', r.status_code == 400, r.status_code)

r = anon.post(BASE + '/tutoring/time/login', headers=HEADER, timeout=60,
              data='这不是 JSON', )
check('登录请求体不是 JSON → 400', r.status_code == 400, r.status_code)

r = anon.post(BASE + '/tutoring/time/login', headers=HEADER, timeout=60,
              json={'login': LOGIN_A, 'password': '故意写错的密码'})
check('错密码 → 401', r.status_code == 401, r.status_code)
check('错密码错误码 bad_credentials',
      body_of(r).get('error') == 'bad_credentials', body_of(r))

r = anon.get(BASE + '/my/time', timeout=60, allow_redirects=False)
check('匿名访问 /my/time 被踢去登录', r.status_code in (302, 303)
      and '/web/login' in (r.headers.get('Location') or ''),
      '%s %s' % (r.status_code, r.headers.get('Location')))

print('\n=== 二、用户 A 登录 ===')
a, r, b = login(LOGIN_A, PW_A)
check('A 登录 200', r.status_code == 200, r.status_code)
check('A 登录拿到 uid 与姓名', bool(b.get('uid')) and bool(b.get('name')), b)
check('A 的会话 cookie 已下发', bool(a.cookies.get('session_id')), dict(a.cookies))
r = a.get(BASE + '/tutoring/time/ping', timeout=60)
check('登录后 ping 报 logged_in=true', body_of(r).get('logged_in') is True, body_of(r))

print('\n=== 三、首次全量上传 ===')
first_tasks = [
    task('20261001-090000-aaaa', '写 Odoo 模块', 'ACTIVE', '2026-10-01T09:00:00+08:00',
         interrupted=2),
    task('20261002-200000-bbbb', '刷 LeetCode', 'DONE', '2026-10-02T20:00:00+08:00'),
]
first_sessions = [
    sess('s-1', '20261001-090000-aaaa', '2026-10-01T09:00:00+08:00',
         '2026-10-01T10:30:00+08:00'),
    sess('s-2', '20261001-090000-aaaa', '2026-10-01T14:00:00+08:00',
         '2026-10-01T14:45:00+08:00', notes=['停在视图继承那一步']),
    # 东八区 10-07 早上 7:30 = UTC 10-06 23:30：跨日边界，专门验时区口径
    sess('s-3', '20261002-200000-bbbb', '2026-10-07T07:30:00+08:00'),
]
first_pool = [
    pool('p-1', '20261001-090000-aaaa', '手撕代码', '2026-10-01T21:51:22+08:00'),
    pool('p-2', '20261001-090000-aaaa', '补验收脚本', '2026-10-01T22:10:00+08:00',
         done_at='2026-10-02T09:00:00+08:00'),
]
r, b = push(a, first_tasks, first_sessions, first_pool)
check('首次上传 200', r.status_code == 200, '%s %s' % (r.status_code, b))
check('首次上传 ok', b.get('ok') is True, b)
stats = b.get('stats') or {}
check('首次上传新增 7 行（2 任务 + 3 区间 + 2 想法）', stats.get('created') == 7, stats)
check('首次上传没有被拒/冲突', not stats.get('rejected') and not stats.get('conflict'), stats)
check('回了 7 个 rev', len(b.get('revs') or {}) == 7, b.get('revs'))
check('新行 rev 都是 1', set((b.get('revs') or {}).values()) == {1}, b.get('revs'))
check('设备已登记', b.get('device_key') == CLIENT['device_key'], b)

rows, err = call(a, 'tutoring.time.task', 'search_read', [], {
    'fields': ['client_id', 'title', 'status', 'total_seconds', 'session_count',
               'duration_text', 'interrupted_count', 'origin'],
    'order': 'client_id'})
check('A 能 search_read 自己的任务', rows is not None, err)
by_cid = {row['client_id']: row for row in (rows or [])}
t1 = by_cid.get('20261001-090000-aaaa') or {}
check('任务 1 状态映射成 active', t1.get('status') == 'active', t1)
check('任务 1 累计 8100 秒（5400+2700，只算已结束区间）',
      t1.get('total_seconds') == 8100, t1)
check('任务 1 时长文案「2 小时 15 分」', t1.get('duration_text') == '2 小时 15 分', t1)
check('任务 1 区间数=2（s-3 属任务 2）', t1.get('session_count') == 2, t1)
check('任务 1 被打断次数照抄', t1.get('interrupted_count') == 2, t1)
check('来源标成 device', t1.get('origin') == 'device', t1)
t2 = by_cid.get('20261002-200000-bbbb') or {}
check('任务 2 状态映射成 done', t2.get('status') == 'done', t2)
check('任务 2 只有进行中的区间 → 累计 0 秒', t2.get('total_seconds') == 0, t2)

srows, err = call(a, 'tutoring.time.session', 'search_read', [], {
    'fields': ['client_id', 'start_at', 'end_at', 'local_date', 'utc_offset', 'notes'],
    'order': 'client_id'})
check('A 能读到区间', srows is not None, err)
s3 = next((row for row in (srows or []) if row['client_id'] == 's-3'), {})
check('时区：+08:00 的 07:30 存成 UTC 前一天 23:30',
      s3.get('start_at') == '2026-10-06 23:30:00', s3)
check('时区：当地日期仍是 10-07', str(s3.get('local_date')) == '2026-10-07', s3)
check('时差按行存下来（480 分）', s3.get('utc_offset') == 480, s3)
s2 = next((row for row in (srows or []) if row['client_id'] == 's-2'), {})
check('打断备注原样存成数组', s2.get('notes') == ['停在视图继承那一步'], s2)

prows, err = call(a, 'tutoring.time.pool.item', 'search_read', [], {
    'fields': ['client_id', 'text', 'done_at'], 'order': 'client_id'})
check('A 能读到想法', prows is not None, err)
p2 = next((row for row in (prows or []) if row['client_id'] == 'p-2'), {})
check('勾掉过的想法带 done_at', bool(p2.get('done_at')), p2)

print('\n=== 四、重推幂等（响应丢了也不该重复写） ===')
r, b = push(a, first_tasks, first_sessions, first_pool)
stats = b.get('stats') or {}
check('同样内容重推 → 全部 noop', stats.get('noop') == 7, stats)
check('重推没有新增', not stats.get('created'), stats)
check('重推后 rev 仍是 1', set((b.get('revs') or {}).values()) == {1}, b.get('revs'))

print('\n=== 五、改版 / 陈旧 rev 冲突 / rebase 收敛 ===')
r, b = push(a, [task('20261001-090000-aaaa', '写 Odoo 模块（改）', 'INTERRUPTED',
                     '2026-10-01T09:00:00+08:00', rev=1, interrupted=3)])
stats = b.get('stats') or {}
check('带对 rev 的改动 → updated', stats.get('updated') == 1, stats)
check('改动后 rev=2', (b.get('revs') or {}).get('task:20261001-090000-aaaa') == 2, b.get('revs'))

r, b = push(a, [task('20261001-090000-aaaa', '第三次改名', 'INTERRUPTED',
                     '2026-10-01T09:00:00+08:00', rev=1, interrupted=3)])
stats = b.get('stats') or {}
check('陈旧 rev → conflict（不写库）', stats.get('conflict') == 1, stats)
check('冲突时把服务器当前 rev=2 回给客户端',
      (b.get('revs') or {}).get('task:20261001-090000-aaaa') == 2, b.get('revs'))
rows, err = call(a, 'tutoring.time.task', 'search_read', None, {
    'domain': [['client_id', '=', '20261001-090000-aaaa']], 'fields': ['title', 'rev']})
check('冲突没有覆盖库里的值', rows and rows[0]['title'] == '写 Odoo 模块（改）', rows)
check('冲突没有涨 rev', rows and rows[0]['rev'] == 2, rows)

r, b = push(a, [task('20261001-090000-aaaa', '第三次改名', 'INTERRUPTED',
                     '2026-10-01T09:00:00+08:00', rev=2, interrupted=3)])
stats = b.get('stats') or {}
check('rebase 后重推 → updated（收敛）', stats.get('updated') == 1, stats)
check('rebase 后 rev=3', (b.get('revs') or {}).get('task:20261001-090000-aaaa') == 3,
      b.get('revs'))

print('\n=== 六、脏行被拒 ===')
r, b = push(a, tasks=[
    task('bad-status', '状态不认识', 'WEIRD'),
    {'title': '没有 client_id', 'status': 'ACTIVE'},
], sessions=[
    sess('orphan', '不存在的任务', '2026-10-03T09:00:00+08:00'),
    sess('backwards', '20261001-090000-aaaa', '2026-10-03T12:00:00+08:00',
         '2026-10-03T11:00:00+08:00'),
])
stats = b.get('stats') or {}
check('脏行让整体仍是 200', r.status_code == 200, r.status_code)
check('四行全被拒', stats.get('rejected') == 4, stats)
rejected = b.get('rejected') or []
check('每条被拒的都给了原因', len(rejected) == 4 and all(x.get('reason') for x in rejected),
      rejected)
count, err = call(a, 'tutoring.time.task', 'search_count', None,
                  {'domain': [['client_id', '=', 'bad-status']]})
check('被拒的行没有落库', count == 0, '%s %s' % (count, err))
logs, err = call(a, 'tutoring.time.sync', 'search_read', [], {
    'fields': ['status', 'rejected_count', 'created_count', 'duration_ms', 'device_id',
               'remote_addr'], 'limit': 1})
check('同步流水记成 rejected', logs and logs[0]['status'] == 'rejected', logs)
check('流水里有被拒计数', logs and logs[0]['rejected_count'] == 4, logs)
check('流水记了设备', bool(logs and logs[0]['device_id']), logs)

print('\n=== 七、墓碑与级联 ===')
r, b = push(a, tasks=[task('20261002-200000-bbbb', '刷 LeetCode', 'DONE',
                           '2026-10-02T20:00:00+08:00', rev=1, deleted=True)])
stats = b.get('stats') or {}
check('删除 → deleted 计数 1', stats.get('deleted') == 1, stats)
check('删除后 rev 涨到 2', (b.get('revs') or {}).get('task:20261002-200000-bbbb') == 2,
      b.get('revs'))
rows, err = call(a, 'tutoring.time.task', 'search_read', [], {'fields': ['client_id']})
check('归档的任务不再出现在默认搜索里',
      [row['client_id'] for row in (rows or [])] == ['20261001-090000-aaaa'], rows)
alive, err = call(a, 'tutoring.time.session', 'search_read', [], {'fields': ['client_id']})
check('任务归档时它名下的区间跟着归档（不留孤儿时长）',
      sorted(row['client_id'] for row in (alive or [])) == ['s-1', 's-2'], alive)
r, b = push(a, tasks=[task('20261002-200000-bbbb', '刷 LeetCode', 'DONE',
                           '2026-10-02T20:00:00+08:00', rev=2, deleted=True)])
check('重复的墓碑 → noop', (b.get('stats') or {}).get('noop') == 1, b.get('stats'))

print('\n=== 八、记录规则：B 看不见 A 的数据 ===')
bb, r, b = login(LOGIN_B, PW_B)
check('B（门户）登录 200', r.status_code == 200, r.status_code)
check('B 是门户账号（share）', b.get('uid') != None, b)
r, b = push(bb, [task('b-task-1', 'B 自己的任务', 'ACTIVE', '2026-10-05T09:00:00+08:00')],
            [sess('b-s-1', 'b-task-1', '2026-10-05T09:00:00+08:00',
                  '2026-10-05T09:30:00+08:00')])
check('门户用户能同步自己的数据', b.get('ok') is True and (b.get('stats') or {}).get('created') == 2, b)
rows, err = call(bb, 'tutoring.time.task', 'search_read', None, {'fields': ['client_id', 'title']})
check('B 只搜到自己的那一条',
      [row['client_id'] for row in (rows or [])] == ['b-task-1'], rows)
found, err = call(a, 'tutoring.time.task', 'search', None,
                  {'domain': [['client_id', '=', '20261001-090000-aaaa']]})
check('A 能定位到自己那条任务的 id', bool(found), err)
a_task_id = (found or [0])[0]
rows, err = call(bb, 'tutoring.time.task', 'read', [[a_task_id], ['title']])
check('B 直接 read A 的任务被记录规则挡掉', rows is None or rows == [], '%s %s' % (rows, err))
count_b, err = call(bb, 'tutoring.time.task', 'search_count', None, {'domain': []})
check('B 的计数里不含 A 的数据', count_b == 1, '%s %s' % (count_b, err))
count_a, err = call(a, 'tutoring.time.task', 'search_count', None, {'domain': []})
check('A 的计数里不含 B 的数据', count_a == 1, '%s %s' % (count_a, err))

print('\n=== 九、门户页与资产包 ===')
r = a.get(BASE + '/my/time', timeout=120)
html = r.text
check('/my/time 200', r.status_code == 200, r.status_code)
check('页面标题是时间账本', '时间账本' in html)
check('页面渲染了任务卡（o_time_card）', 'o_time_card' in html)
check('页面渲染了概览大数字（o_time_stat_value）', 'o_time_stat_value' in html)
check('页面里有 A 的任务标题', '第三次改名' in html)
check('归档的任务不出现在页面上', '刷 LeetCode' not in html)
check('页面里有累计时长文案', '2 小时 15 分' in html)
check('页面里有同步流水区块', 'o_time_synclog' in html)
check('分页器用的是 t-call（没把字典打到页面上）', "{'page_count'" not in html)

css_href = [m for m in re.findall(r'href="([^"]+\.css[^"]*)"', html)]
found_css = False
for href in css_href:
    url = href if href.startswith('http') else BASE + href
    css = a.get(url, timeout=120).text
    if 'o_time_stat_value' in css and 'o_time_pulse' in css:
        found_css = True
        break
check('时间账本的 CSS 真的进了资产包（%d 个 css 里找到）' % len(css_href), found_css,
      css_href[:4])

r = a.get(BASE + '/my', timeout=120)
check('/my 首页有「时间账本」入口卡', '/my/time' in r.text and '时间账本' in r.text)

menus, err = call(a, 'website.menu', 'search_read', None, {
    'domain': [['url', '=', '/my/time']],
    'fields': ['name', 'group_ids', 'sequence']})
check('顶栏菜单已建（/my/time）', bool(menus), err)
check('菜单挂了内部+门户两个组（匿名看不见）',
      menus and len(menus[0]['group_ids']) == 2, menus)
check('菜单排在知识库之后（seq 40）', menus and menus[0]['sequence'] == 40, menus)

r = a.get(BASE + '/my/time?filterby=done&search=不存在的东西', timeout=120)
check('筛选+搜索组合不炸', r.status_code == 200, r.status_code)
check('空结果给的是提示而不是 500', '没有任务' in r.text or 'alert-info' in r.text)

print('\n=== 十、概览口径 ===')
overview, err = call(a, 'tutoring.time.task', 'overview', [], {})
check('overview 能调通（@api.model 用模型调用）', isinstance(overview, dict), err)
if isinstance(overview, dict):
    check('overview 报任务数=1', overview.get('task_count') == 1, overview)
    check('overview 报今日时长（含进行中的区间）', overview.get('today_seconds', -1) >= 0,
          overview)
    check('overview 报最后同步时间文案', bool(overview.get('last_sync_text')), overview)

print('\n=== 十一、逐行动作与极简墓碑（同步协议的另一半） ===')
r, b = push(a, tasks=[task('tomb-lab', '墓碑试验田', 'ACTIVE', '2026-10-08T09:00:00+08:00')],
            sessions=[sess('tomb-lab-s1', 'tomb-lab', '2026-10-08T09:00:00+08:00',
                           '2026-10-08T09:30:00+08:00')])
stats = b.get('stats') or {}
actions = b.get('actions') or {}
check('新增行在 actions 里标成 created', stats.get('created') == 2
      and actions.get('task:tomb-lab') == 'created'
      and actions.get('session:tomb-lab-s1') == 'created', actions)

r, b = push(a, tasks=[task('tomb-lab', '墓碑试验田', 'ACTIVE', '2026-10-08T09:00:00+08:00',
                           rev=1)],
            sessions=[sess('tomb-lab-s1', 'tomb-lab', '2026-10-08T09:00:00+08:00',
                           '2026-10-08T09:30:00+08:00', rev=1)])
actions = b.get('actions') or {}
check('重推在 actions 里标成 noop',
      actions.get('task:tomb-lab') == 'noop'
      and actions.get('session:tomb-lab-s1') == 'noop', actions)

# 只送子行的墓碑，且**父任务不在这一批里**：服务端必须回查数据库才认得它
r, b = push(a, sessions=[{'client_id': 'tomb-lab-s1', 'task_client_id': 'tomb-lab',
                          'rev': 1, 'deleted': True}])
stats = b.get('stats') or {}
actions = b.get('actions') or {}
check('只带 id 的子行墓碑不会被拒（父任务靠回查）',
      stats.get('deleted') == 1 and not stats.get('rejected'),
      '%s %s' % (stats, b.get('rejected')))
check('子行墓碑的 action 是 deleted',
      actions.get('session:tomb-lab-s1') == 'deleted', actions)

# 任务的墓碑：同样只带 id，没有标题也没有状态
r, b = push(a, tasks=[{'client_id': 'tomb-lab', 'rev': 1, 'deleted': True}])
stats = b.get('stats') or {}
actions = b.get('actions') or {}
check('只带 id 的任务墓碑被接受（不要求标题/状态）',
      stats.get('deleted') == 1 and not stats.get('rejected'),
      '%s %s' % (stats, b.get('rejected')))
check('任务墓碑之后默认搜索里查不到它',
      call(a, 'tutoring.time.task', 'search_count', None,
           {'domain': [['client_id', '=', 'tomb-lab']]})[0] == 0)
count, err = call(a, 'tutoring.time.task', 'search_count', None,
                  {'domain': [['client_id', '=', 'tomb-lab']],
                   'context': {'active_test': False}})
check('带 active_test=False 仍查得到（是墓碑不是真删）', count == 1, '%s %s' % (count, err))

# 约束消息必须写成 callable（models.Constraint 的 message 会在抛错时求值）：
# 类体里直接 _('…') 会在导入期就翻译，全新库安装刷一片 "no translation language
# detected" 警告，而且消息永远不会按访问者语言翻译。这条断言保证它仍然出得来。
result, err = call(a, 'tutoring.time.task', 'create',
                   [{'client_id': 'tomb-lab', 'title': '撞唯一约束'}])
check('重复 client_id 直接建会被唯一约束挡住', result is None, result)
check('挡下时说的是人话而不是 SQL 报错', '已经同步过' in (err or ''), (err or '')[:160])

print('\n%d 项通过，%d 项失败' % (ok, fail))
sys.exit(1 if fail else 0)
