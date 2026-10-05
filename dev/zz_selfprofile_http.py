"""业务库上的真机对照：第二位老师进来之后，别人的「我自己」不该再露出来。

用 qa_teacher2 走真实 HTTP：范围药丸、速记条「记到谁」、后台学生列表的 search_read；
再用门户学生 biaodi 对照一遍，确认学生侧没被这两条规则碰着。
跑完即弃，测试账号随后删除。
"""
import os
import re
import sys

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'OdooForDB'
PW = os.environ['QA_PASSWORD']
ADMIN_PROFILE = 7      # admin 的「我自己」
SELF_PROFILE = 11      # qa_teacher2 的「我自己」

ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('PASS  ' if cond else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))


def login(user, pw):
    s = requests.Session()
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call', 'params': {
            'db': DB, 'login': user, 'password': pw}}, timeout=60)
    uid = (r.json().get('result') or {}).get('uid')
    check('登录 %s' % user, bool(uid), 'uid=%s' % uid)
    return s


def call(session, model, method, args=None, kwargs=None):
    r = session.post(BASE + '/web/dataset/call_kw', json={
        'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
            'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}},
        timeout=60)
    body = r.json()
    if 'error' in body:
        return None, body['error'].get('data', {}).get('message', '')[:180]
    return body['result'], ''


qa = login('qa_teacher2', PW)

# ---- 后台学生列表（前端列表就是这条 RPC）----
res, err = call(qa, 'tutoring.student', 'search_read', [], {
    'fields': ['name'], 'order': 'id', 'limit': 100})
ids = sorted(r['id'] for r in res) if res is not None else []
check('qa2 的学生列表 search_read 成功', res is not None, err)
check('列表里没有 admin 的本人档案 #%d' % ADMIN_PROFILE, ADMIN_PROFILE not in ids, ids)
check('列表里有 qa2 自己的本人档案 #%d' % SELF_PROFILE, SELF_PROFILE in ids, ids)
check('真实学生仍在列表里（表弟#2 / 示例学生B#3 / 小明#4）',
      {2, 3, 4} <= set(ids), ids)

# ---- 门户错题页：药丸与「记到谁」 ----
r = qa.get(BASE + '/my/mistakes', timeout=60, allow_redirects=True)
check('qa2 打开 /my/mistakes', r.status_code == 200, r.status_code)
page = r.text
pills = re.findall(r'href="/my/mistakes\?scope=(\d+)"[^>]*>([^<]+)<', page)
check('范围药丸里没有别人的「我自己」',
      not [1 for sid, label in pills if sid != str(SELF_PROFILE) and label.strip() == '我自己'],
      pills)
# 只截「记到谁」那一个 select（整页还有练习册/错因/知识点三个下拉，别把它们算进来）
block = re.search(r'id="q_student".*?</select>', page, re.S)
opts = re.findall(r'<option value="(\d+)"[^>]*>\s*([^<]+?)\s*<', block.group(0)) if block else []
check('抓到「记到谁」下拉', bool(block))
check('「记到谁」下拉不含 admin 的档案', ADMIN_PROFILE not in [int(v) for v, _ in opts], opts)
check('「记到谁」下拉有且只有一颗「我自己」',
      len([1 for v, label in opts if label == '我自己']) == 1, opts)

# ---- 错题侧：qa2 看不到别人的、看得到真实学生的 ----
res, err = call(qa, 'tutoring.mistake', 'search_read', [], {'fields': ['student_id'], 'limit': 200})
check('qa2 读错题成功', res is not None, err)
check('读到的错题全部挂在可见档案下',
      all(m['student_id'][0] != ADMIN_PROFILE for m in (res or [])),
      sorted({m['student_id'][0] for m in (res or []) if m['student_id']}))

# ---- 门户学生对照：biaodi 一切照旧 ----
pu = login('biaodi', 'Biaodi@2026')
r = pu.get(BASE + '/my/mistakes', timeout=60, allow_redirects=True)
check('门户学生 biaodi 打开 /my/mistakes', r.status_code == 200, r.status_code)
check('门户学生看不到范围切换条', '看谁的' not in r.text)
res, err = call(pu, 'tutoring.student', 'search_read', [], {'fields': ['name'], 'limit': 50})
check('门户学生只看到自己那一份档案',
      res is not None and len(res) == 1 and res[0]['name'] == '表弟',
      [(x['id'], x['name']) for x in (res or [])])
res, err = call(pu, 'tutoring.mistake', 'search_count', [[]])
check('门户学生的错题数仍为 7', res == 7, res)

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
sys.exit(1 if fail else 0)
