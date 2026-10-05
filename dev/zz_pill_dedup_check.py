"""药丸条去重（19.0.1.15.1）：mine 那颗只出现一次，循环里不再重复画本人那份。"""
import os
import re
import sys

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'OdooForDB'
PW = os.environ['QA_PASSWORD']
fails = []


def check(name, ok, extra=''):
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))
    if not ok:
        fails.append(name)


s = requests.Session()
r = s.post(BASE + '/web/session/authenticate', json={
    'jsonrpc': '2.0', 'method': 'call',
    'params': {'db': DB, 'login': 'qa_check', 'password': PW}}, timeout=60)
uid = r.json()['result']['uid']
check('登录 qa_check', bool(uid), uid)

html = s.get(BASE + '/my/mistakes', timeout=60).text
pills = re.findall(r'<a[^>]*href="/my/mistakes\?scope=([a-z0-9]+)"[^>]*>([^<]*)</a>', html)
check('mine 那颗只出现一次', sum(1 for k, _ in pills if k == 'mine') == 1, pills)
check('循环里没有再画本人那份（无 scope=9）', not any(k == '9' for k, _ in pills), pills)
check('别人的档案仍在药丸条上', any(k == '7' for k, _ in pills) and
      any(k == '2' for k, _ in pills), pills)
names = [n for _, n in pills]
check('页面上"我自己"字样只剩一颗药丸', names.count('我自己') == 1, names)
sel = re.search(r'<select[^>]*name="student_id".*?</select>', html, re.S)
check('速记条下拉仍列全部可读档案（含本人）',
      bool(sel) and 'value="9"' in sel.group(0) and 'value="7"' in sel.group(0),
      re.findall(r'value="(\d+)"', sel.group(0)) if sel else None)
check('默认仍选中本人那份',
      bool(sel) and re.search(r'<option[^>]*value="9"[^>]*selected', sel.group(0)) is not None)

print('RESULT %s' % ('ALL PASS' if not fails else 'FAILED: %s' % fails))
sys.exit(1 if fails else 0)
