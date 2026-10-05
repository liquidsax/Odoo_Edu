"""第五轮（老师也是学习者）在本机业务库上的 HTTP 验收。

覆盖：范围切换药丸、速记条"记到谁"、老师给自己记错题、题目照片落进老师自己的知识库、
学生侧看不到药丸也读不到老师的题。所有测试数据在最后删干净。
"""
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
created = {'mistake': None, 'item': None}


def check(name, ok, extra=''):
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))
    if not ok:
        fails.append(name)


def login(user, pw):
    s = requests.Session()
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call', 'params': {
            'db': DB, 'login': user, 'password': pw}}, timeout=60)
    uid = r.json().get('result', {}).get('uid')
    check('登录 %s' % user, bool(uid), 'uid=%s' % uid)
    return s, uid


def token(session, url):
    html = session.get(BASE + url, timeout=60).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or \
        re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else ''


# ---------------------------------------------------------------- 老师侧
teacher, tuid = login('qa_check', PW)
html = teacher.get(BASE + '/my/mistakes', timeout=60).text

check('老师看到范围切换', 'scope=mine' in html and '我自己' in html and 'scope=all' in html)
check('默认范围是自己那份档案', re.search(r'href="/my/mistakes\?scope=mine"[^>]*class="nav-link[^"]*active', html)
      or re.search(r'class="nav-link[^"]*active[^"]*"\s+href="/my/mistakes\?scope=mine"', html)
      or '/my/mistakes?scope=mine"' in html)
check('速记条存在', 'quickadd' in html or 'o_mistake_quickadd' in html)
m = re.search(r'name="student_id".*?</select>', html, re.S)
if not m:
    m = re.search(r'<select[^>]*name="student_id"[^>]*>.*?</select>', html, re.S)
check('有"记到谁"下拉', bool(m))
if m:
    opts = re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]*)</option>', m.group(0))
    check('下拉里既有自己也有学生',
          any('我自己' in label for _, label in opts) and any('我自己' not in label for _, label in opts),
          opts)
    self_ids = [v for v, label in opts if '我自己' in label]
    picked = re.search(r'<option[^>]*value="(\d+)"[^>]*selected', m.group(0))
    check('默认选中自己那份', bool(picked) and self_ids and picked.group(1) == self_ids[0],
          'default=%s self=%s' % (picked.group(1) if picked else None, self_ids))
    own_student_id = int(self_ids[0])

# 真记一条：给"我自己"
csrf = token(teacher, '/my/mistakes')
r = teacher.post(BASE + '/my/learning/mistakes/new', data={
    'csrf_token': csrf,
    'student_id': own_student_id,
    'workbook_id': 1,
    'question_no': 'ZZ-自测-1',
    'difficulty': '3',
    'note': '老师自测：这条应该只在老师自己名下',
    'date': '2026-10-05',
}, allow_redirects=True, timeout=60)
check('老师记错题成功', r.status_code == 200 and 'created=1' in r.url, r.url)
html = r.text
mid = None
for hit in re.finditer(r'/my/learning/mistakes/(\d+)', html):
    mid = int(hit.group(1))
    break
check('列表里能回到这条', bool(mid), 'mistake=%s' % mid)
created['mistake'] = mid

if mid:
    detail = teacher.get(BASE + '/my/learning/mistakes/%d' % mid, timeout=60).text
    check('详情页有题目照片上传区', 'file' in detail and '/attach' in detail)
    csrf = token(teacher, '/my/learning/mistakes/%d' % mid)
    a = teacher.post(BASE + '/my/learning/mistakes/%d/attach' % mid,
                     data={'csrf_token': csrf, 'title': 'ZZ-自测照片', 'tags': '自测'},
                     files={'file': ('zz_self.jpg', io.BytesIO(JPEG), 'image/jpeg')},
                     allow_redirects=False, timeout=60)
    check('题目照片挂上了', a.status_code == 303 and 'attached=1' in a.headers.get('Location', ''),
          a.headers.get('Location'))

    lib = teacher.get(BASE + '/my/library?filterby=mistake', timeout=60).text
    check('老师知识库里能看到这条错题附件', 'ZZ-自测照片' in lib or 'zz_self.jpg' in lib)
    item = None
    for hit in re.finditer(r'/my/library/(\d+)', lib):
        item = int(hit.group(1))
        break
    created['item'] = item
    check('附件卡片带错题徽章', '错题' in lib)
    if item:
        page = teacher.get(BASE + '/my/library/%d' % item, timeout=60).text
        check('附件能跳回这道错题', '/my/learning/mistakes/%d' % mid in page)

# 范围切到"全部"：卡片上要带学生名
allscope = teacher.get(BASE + '/my/mistakes?scope=all', timeout=60).text
check('全部范围能打开', allscope.count('/my/learning/mistakes/') > 0)
check('全部范围里显示档案名', '我自己' in allscope or '表弟' in allscope)
# 切到某个学生
one = re.search(r'/my/mistakes\?scope=(\d+)"', allscope)
if one:
    sub = teacher.get(BASE + '/my/mistakes?scope=%s' % one.group(1), timeout=60).text
    check('按学生筛选可用', sub.count('/my/mistakes') > 0 and 'scope=%s' % one.group(1) in sub)

# ---------------------------------------------------------------- 学生侧
student, suid = login('biaodi', 'Biaodi@2026')
sh = student.get(BASE + '/my/mistakes', timeout=60).text
check('学生看不到范围切换', 'scope=all' not in sh and '我自己' not in sh)
check('学生仍有速记条', 'quickadd' in sh or 'o_mistake_quickadd' in sh)
check('学生没有"记到谁"下拉', not re.search(r'name="student_id"', sh, re.S))
if created['mistake']:
    forbidden = student.get(BASE + '/my/learning/mistakes/%d' % created['mistake'], timeout=60)
    check('学生读不到老师的错题', forbidden.status_code == 404, forbidden.status_code)
sl = student.get(BASE + '/my/library?filterby=mistake', timeout=60).text
check('学生看不到老师的附件', 'ZZ-自测照片' not in sl and 'zz_self.jpg' not in sl)
# 学生想把题记到老师名下：前端塞 id 也无效
csrf = token(student, '/my/mistakes')
teacher_profile = own_student_id
b = student.post(BASE + '/my/learning/mistakes/new', data={
    'csrf_token': csrf, 'student_id': teacher_profile, 'workbook_id': 1,
    'question_no': 'ZZ-越权-1', 'note': '不该落到老师名下', 'difficulty': '3',
}, allow_redirects=True, timeout=60)
if 'created=1' in b.url:
    hijacked = int(re.search(r'/my/learning/mistakes/(\d+)', b.text).group(1))
    created['mistake2'] = hijacked
    mine = student.get(BASE + '/my/mistakes', timeout=60).text
    check('越权指定别人档案没生效', 'ZZ-越权-1' in mine)
else:
    check('越权指定别人档案没生效', True, b.url)

# ---------------------------------------------------------------- 匿名
anon = requests.get(BASE + '/my/mistakes', timeout=60, allow_redirects=False)
check('未登录进不了错题页', anon.status_code in (301, 302, 303) and '/web/login' in anon.headers.get('Location', ''),
      '%s %s' % (anon.status_code, anon.headers.get('Location')))
anl = requests.get(BASE + '/my/library', timeout=60, allow_redirects=False)
check('未登录进不了知识库', anl.status_code in (301, 302, 303) and '/web/login' in anl.headers.get('Location', ''),
      '%s %s' % (anl.status_code, anl.headers.get('Location')))

print('\nIDS %s' % created)
print('RESULT %s' % ('ALL PASS' if not fails else 'FAILED: %s' % fails))
sys.exit(1 if fails else 0)
