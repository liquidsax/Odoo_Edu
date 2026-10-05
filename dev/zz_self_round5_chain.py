"""老师给自己记错题这条主链：不传 student_id，看默认落在谁名下，再挂题目照片。"""
import base64
import io
import os
import re
import sys

import requests

BASE = 'http://127.0.0.1:8069'
DB = 'OdooForDB'
PW = os.environ['QA_PASSWORD']
JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a'
    'HBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPDs0NDT/wAALCAABAAEBAREA/8QAFAABAQAAAAAA'
    'AAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/a'
    'AAwDAQACEQMRAD8AlgAB/9k=')

fails = []
item = None


def check(name, ok, extra=''):
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))
    if not ok:
        fails.append(name)


s = requests.Session()
r = s.post(BASE + '/web/session/authenticate', json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {'db': DB, 'login': 'qa_check', 'password': PW}},
    timeout=60)
uid = r.json()['result']['uid']
check('登录 qa_check', bool(uid), uid)

html = s.get(BASE + '/my/mistakes', timeout=60).text
sel = re.search(r'<select[^>]*name="student_id".*?</select>', html, re.S).group(0)
default = re.search(r'<option[^>]*value="(\d+)"[^>]*selected', sel)
own = int(default.group(1))
labels = dict(re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]*)</option>', sel))
check('默认选中自己那份（且只有一份叫我自己是默认的）', labels[str(own)] == '我自己', 'default=%s' % own)
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)

# 关键：故意不传 student_id，模拟"老师点开就填、不动下拉"
r = s.post(BASE + '/my/learning/mistakes/new', data={
    'csrf_token': csrf, 'workbook_id': 1, 'question_no': 'ZZ-默认-1',
    'difficulty': '4', 'note': '不选记到谁，应该落在自己名下', 'date': '2026-10-05',
}, allow_redirects=True, timeout=60)
check('默认落到自己名下', 'created=1' in r.url, r.url)
page = r.text
mid = None
for hit in re.finditer(r'/my/learning/mistakes/(\d+)', page):
    mid = int(hit.group(1))
    break
check('自己范围的列表里看得到这条', bool(mid), 'mistake=%s' % mid)
check('卡片上带出了这条的内容', 'ZZ-默认-1' in page or '不选记到谁' in page)

if mid:
    detail = s.get(BASE + '/my/learning/mistakes/%d' % mid, timeout=60).text
    check('详情页显示归属是自己那份', '我自己' in detail)
    csrf2 = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', detail).group(1)
    a = s.post(BASE + '/my/learning/mistakes/%d/attach' % mid,
               data={'csrf_token': csrf2, 'title': 'ZZ-默认照片', 'tags': '自测,默认'},
               files={'file': ('zz_default.jpg', io.BytesIO(JPEG), 'image/jpeg')},
               allow_redirects=False, timeout=60)
    loc = a.headers.get('Location', '')
    check('题目照片挂上并回到详情页', a.status_code == 303 and 'attached=1' in loc, loc)

    lib = s.get(BASE + '/my/library?filterby=mistake', timeout=60).text
    check('知识库错题筛选里有这张照片', 'zz_default.jpg' in lib or 'ZZ-默认照片' in lib)
    item = None
    for hit in re.finditer(r'/my/library/(\d+)', lib):
        item = int(hit.group(1))
        break
    check('能进附件详情页', bool(item), 'item=%s' % item)
    if item:
        ipage = s.get(BASE + '/my/library/%d' % item, timeout=60).text
        check('附件详情页能跳回这道错题', '/my/learning/mistakes/%d' % mid in ipage)
        check('图片类型走内联预览', 'library_preview' in ipage or 'o_library_preview' in ipage)
        raw = s.get(BASE + '/tutoring/library/%d/raw' % item, timeout=60)
        check('原图可取且带 nosniff', raw.status_code == 200 and
              raw.headers.get('X-Content-Type-Options') == 'nosniff',
              '%s %s' % (raw.status_code, raw.headers.get('Content-Type')))

# 速记条校验失败要回填，不让人重打
r = s.post(BASE + '/my/learning/mistakes/new', data={
    'csrf_token': csrf, 'question_no': 'ZZ-缺练习册', 'note': '这条不该建起来',
}, allow_redirects=True, timeout=60)
check('没选练习册时回填原值并提示', '请先选择练习册' in r.text and 'ZZ-缺练习册' in r.text, r.url)

print('IDS mistake=%s item=%s' % (mid, item))
print('RESULT %s' % ('ALL PASS' if not fails else 'FAILED: %s' % fails))
sys.exit(1 if fails else 0)
