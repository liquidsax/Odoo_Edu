"""Do1ng → 时间账本的同步契约预检：拿**本机真实的 tasks.json** 打一遍云端。

这一步在写 Java 之前把协议钉死：Do1ng 那边将要实现的映射（补 id、墙上时间换 ISO 带时差、
totalMillis 交给云端按区间重算）在这里先用 Python 走一遍，跑通再往 Java 里搬，
省得两边同时改、同时错。

会话/想法在 Do1ng 里没有 id，这里用「任务 id + 该行的时间戳」派生一个**确定性** id，
这样两次运行才会命中同一行——真正落地时 Java 端是首次运行时生成 UUID 并写回文件持久化。

用法：
    set ZZ_TIME_PW_C=... & python dev/zz_do1ng_sync_check.py
    DO1NG_TASKS=别的路径 python dev/zz_do1ng_sync_check.py   # 换数据源
"""
import json
import os
import sys
from datetime import datetime

import requests

SRC = os.environ.get('DO1NG_TASKS', r'D:\WorkSpaceD\CodeMountains\Do1ng\data\tasks.json')
BASE = os.environ.get('ZZ_TIME_BASE', 'http://127.0.0.1:8899')
LOGIN = os.environ.get('ZZ_TIME_LOGIN_C', 'zz_time_c')
PASSWORD = os.environ['ZZ_TIME_PW_C']
HEADER = {'X-Do1ng-Sync': '1'}
CLIENT = {'device_key': 'precheck-machine', 'device_name': '契约预检',
          'platform': 'python', 'client_version': 'precheck-1'}
LOCAL_TZ = datetime.now().astimezone().tzinfo

ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS  ' + name)
    else:
        fail += 1
        print('FAIL  ' + name + (('  | ' + str(extra))[:200] if extra != '' else ''))


def iso(text):
    """Do1ng 的无时区墙上时间 → 带时差的 ISO（客户端上报形式）。"""
    if not text:
        return False
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(
        tzinfo=LOCAL_TZ).isoformat()


def offset_minutes():
    now = datetime.now(LOCAL_TZ)
    return int(now.utcoffset().total_seconds() // 60)


with open(SRC, encoding='utf-8') as handle:
    local_tasks = json.load(handle)
print('读到 %s：%d 个任务' % (SRC, len(local_tasks)))

tasks, sessions, items = [], [], []
for task in local_tasks:
    tasks.append({
        'client_id': task['id'],
        'title': task.get('title') or '未命名',
        'status': task.get('status') or 'ACTIVE',
        'created': iso(task.get('created')),
        'interrupted_count': task.get('interruptedCount') or 0,
        'updated_at': iso(task.get('created')),
        'rev': 0,
        'deleted': False,
    })
    for ses in task.get('sessions') or []:
        sessions.append({
            'client_id': '%s-s-%s' % (task['id'], (ses.get('start') or '').replace(
                ' ', 'T').replace(':', '').replace('-', '')),
            'task_client_id': task['id'],
            'start': iso(ses.get('start')),
            'end': iso(ses.get('end')),
            'notes': ses.get('notes') or [],
            'updated_at': iso(ses.get('end') or ses.get('created') or task.get('created')),
            'rev': 0,
            'deleted': False,
        })
    for note in task.get('pool') or []:
        items.append({
            'client_id': '%s-p-%s' % (task['id'], (note.get('created') or '').replace(
                ' ', 'T').replace(':', '').replace('-', '')),
            'task_client_id': task['id'],
            'text': note.get('text') or '（空）',
            'created': iso(note.get('created')),
            'done_at': iso(note.get('doneAt')),
            'updated_at': iso(note.get('doneAt') or note.get('created')),
            'rev': 0,
            'deleted': False,
        })

payload = {'client': CLIENT, 'utc_offset_minutes': offset_minutes(),
           'changes': {'tasks': tasks, 'sessions': sessions, 'pool': items}}
print('载荷：任务 %d / 区间 %d / 想法 %d，时差 %d 分'
      % (len(tasks), len(sessions), len(items), offset_minutes()))

session = requests.Session()
r = session.post(BASE + '/tutoring/time/login', headers=HEADER, timeout=120,
                 json={'login': LOGIN, 'password': PASSWORD})
check('登录成功', r.status_code == 200 and r.json().get('ok'), r.text[:200])

r = session.post(BASE + '/tutoring/time/sync', headers=HEADER, timeout=300, json=payload)
b = r.json()
check('首轮全量推送 200', r.status_code == 200 and b.get('ok'), '%s %s' % (r.status_code, b))
stats = b.get('stats') or {}
revs = b.get('revs') or {}
expect = len(tasks) + len(sessions) + len(items)
check('新增行数 = 本地行数（%d）' % expect, stats.get('created') == expect, stats)
check('没有被拒的行', not stats.get('rejected'), b.get('rejected'))

# 关键一致性：云端按区间重算的累计时长，必须等于 Do1ng 自己攒的 totalMillis
rows, err = [], ''
response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
    'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
        'model': 'tutoring.time.task', 'method': 'search_read', 'args': [],
        'kwargs': {'domain': [], 'fields': ['client_id', 'title', 'status', 'total_seconds',
                                            'session_count', 'interrupted_count',
                                            'client_created', 'duration_text'],
                   'limit': 200}}})
body = response.json()
if 'error' in body:
    check('云端读回任务', False, body['error'].get('data', {}).get('message', ''))
else:
    rows = body.get('result') or []
    check('云端读回任务', True)
by_cid = {row['client_id']: row for row in rows}
check('云端任务数 = 本地任务数', len(rows) == len(local_tasks),
      '%s vs %s' % (len(rows), len(local_tasks)))

mismatch = []
for task in local_tasks:
    cloud = by_cid.get(task['id'])
    if not cloud:
        mismatch.append((task['id'], '云端没有这条'))
        continue
    # Do1ng 落盘的 start/end 只到秒，而 totalMillis 是内存里按毫秒累加的，
    # 所以云端按区间重算必然和本地累计值差「每段区间最多 1 秒」。
    # 差在这个界限内就算一致；超出界限才是真的算错了。
    local_ms = task.get('totalMillis') or 0
    closed = [s for s in (task.get('sessions') or []) if s.get('end')]
    cloud_ms = (cloud['total_seconds'] or 0) * 1000
    tolerance = 1000 * max(len(closed), 1)
    if abs(local_ms - cloud_ms) > tolerance:
        mismatch.append((task['id'], 'totalMillis %s 与云端重算 %s 差得超过 %s ms'
                         % (local_ms, cloud_ms, tolerance)))
    if (task.get('status') or '').lower() != cloud['status']:
        mismatch.append((task['id'], '状态 %s ≠ %s' % (task.get('status'), cloud['status'])))
    if (task.get('interruptedCount') or 0) != cloud['interrupted_count']:
        mismatch.append((task['id'], '打断次数对不上'))
check('每个任务的累计时长（秒级精度内）/状态/打断次数都和 Do1ng 一致',
      not mismatch, mismatch[:6])

local_sessions = sum(len(t.get('sessions') or []) for t in local_tasks)
local_items = sum(len(t.get('pool') or []) for t in local_tasks)
response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
    'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
        'model': 'tutoring.time.session', 'method': 'search_count', 'args': [],
        'kwargs': {'domain': []}}})
count = response.json().get('result')
check('云端区间数 = 本地区间数（%d）' % local_sessions, count == local_sessions, count)
response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
    'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
        'model': 'tutoring.time.pool.item', 'method': 'search_count', 'args': [],
        'kwargs': {'domain': []}}})
count = response.json().get('result')
check('云端想法数 = 本地想法数（%d）' % local_items, count == local_items, count)

r = session.post(BASE + '/tutoring/time/sync', headers=HEADER, timeout=300, json=payload)
stats = r.json().get('stats') or {}
check('同一份数据重推 → 全部无变化（幂等）',
      stats.get('noop') == expect and not any(
          stats.get(key) for key in ('created', 'updated', 'deleted', 'conflict')),
      stats)

victim = local_tasks[-1]['id']
tombstone = dict(payload)
tombstone['changes'] = {
    'tasks': [dict(task, rev=revs.get('task:%s' % victim, 1), deleted=True)
              for task in tasks if task['client_id'] == victim],
    'sessions': [],
    'pool': [],
}
r = session.post(BASE + '/tutoring/time/sync', headers=HEADER, timeout=300, json=tombstone)
stats = r.json().get('stats') or {}
check('删掉最后一个任务 → 云端标成墓碑', stats.get('deleted') == 1, stats)
response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
    'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
        'model': 'tutoring.time.task', 'method': 'search_count', 'args': [],
        'kwargs': {'domain': [['client_id', '=', victim]]}}})
check('墓碑任务不再被默认搜到', response.json().get('result') == 0, response.json())
response = session.post(BASE + '/web/dataset/call_kw', timeout=120, json={
    'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
        'model': 'tutoring.time.task', 'method': 'search_count', 'args': [],
        'kwargs': {'domain': [], 'context': {'active_test': False}}}})
check('带 active_test=False 仍能搜到它（墓碑没被真删）',
      response.json().get('result') == len(local_tasks), response.json())

r = session.get(BASE + '/my/time', timeout=120)
check('真实数据渲染 /my/time 不报错', r.status_code == 200, r.status_code)
check('页面上有真实任务标题',
      bool(local_tasks) and any((t.get('title') or '\0') in r.text for t in local_tasks[:-1]))

print('\n%d 项通过，%d 项失败' % (ok, fail))
sys.exit(1 if fail else 0)
