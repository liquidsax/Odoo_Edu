r"""知识库「新建资料 / 补附件 / 自动成练习册」的 HTTP 验收（一次性库 + 独立端口）。

前提：一次性库 `zz_library_link` 已 `-i tutoring_center` 装好，并且有一个独立进程在跑：

    cd /d E:\Odoo\server
    python odoo-bin -c odoo.conf -d zz_library_link --http-interface=127.0.0.1 ^
        --http-port=8899 --db-filter=^zz_library_link$ --max-cron-threads=0 --logfile=
    set ZZ_LIB_PW=admin
    python ..\dev\zz_library_workbook_http.py

这条脚本盯的是报上来的那两件事，全程真发 HTTP、真解析页面，不看模型内部：
 - 没有电子版也能先把一本资料建起来（/my/library 搜索框旁「新建资料」），之后补附件；
 - 建完/传完，/my/mistakes 的「哪本练习册」下拉立刻选得到，并且当场记得上一条错题。
"""
import os
import re
import sys

import requests

BASE = os.environ.get('ZZ_LIB_BASE', 'http://127.0.0.1:8899')
DB = os.environ.get('ZZ_LIB_DB', 'zz_library_link')
LOGIN = os.environ.get('ZZ_LIB_LOGIN', 'admin')
PW = os.environ.get('ZZ_LIB_PW', 'admin')

# 一段最小可辨认的 PDF（不是空文件，扩展名决定条目的 kind）
PDF = (b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
       b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
       b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n'
       b'trailer<</Root 1 0 R>>\n%%EOF\n')

fails = []
total = 0


def check(name, ok, extra=''):
    global total
    total += 1
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  | ' + str(extra)) if extra else ''))
    if not ok:
        fails.append(name)


def session():
    s = requests.Session()
    s.trust_env = False  # 本机端口，别让环境里的代理插一脚
    return s


def token(s, url):
    html = s.get(BASE + url, timeout=120).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else ''


def workbook_options(html):
    """速记条里「哪本练习册」这个 select 的选项文本。"""
    block = re.search(r'<select[^>]*name="workbook_id"[^>]*>(.*?)</select>', html, re.S)
    if not block:
        return None
    return [t.strip() for _, t in re.findall(
        r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]*?)\s*</option>', block.group(1))]


def redirected(r):
    """POST 之后 Odoo 回 303（不是 302），两种都算"跳走了"。"""
    return r.status_code in (302, 303), r.headers.get('Location', '')


s = session()
r = s.post(BASE + '/web/session/authenticate', json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': LOGIN, 'password': PW}}, timeout=120)
uid = (r.json() or {}).get('result', {}).get('uid')
check('登录 %s' % LOGIN, bool(uid), 'uid=%s' % uid)
if not uid:
    sys.exit('登不上，后面都没法跑')

# ---------------------------------------------------------------- 新建资料
r = s.get(BASE + '/my/library', timeout=120)
check('/my/library 打开正常', r.status_code == 200, r.status_code)
check('搜索框旁有「新建资料」', '新建资料' in r.text and 'o_lib_new_item' in r.text)
check('没 JS 时这块常驻展开', '#o_lib_new_item.collapse' in r.text)

r = s.post(BASE + '/my/library/new', data={
    'csrf_token': token(s, '/my/library'), 'name': 'HTTP 验收册',
    'category': 'workbook', 'folder': '', 'tags': '验收, 一数'},
    allow_redirects=False, timeout=120)
moved, location = redirected(r)
check('新建资料提交后跳详情页', moved and 'created=1' in location, location)
item_url = location.split('?')[0]
m = re.search(r'/my/library/(\d+)', item_url)
item_id = m.group(1) if m else None
check('拿到了条目 id', bool(item_id), item_id)

if item_id:
    page = s.get(BASE + item_url, timeout=120).text
    check('详情页说这条还没有附件', '还没有附件' in page)
    check('详情页给了「补附件」表单', '/my/library/%s/add_file' % item_id in page)
    check('没附件时不给下载按钮', 'raw?download=1' not in page)
    card = s.get(BASE + '/my/library', timeout=120).text
    check('卡片上标了「还没补附件」', '还没补附件' in card and 'HTTP 验收册' in card)

# ------------------------------------------------ 报错回路：名字没填 / 越权
r = s.post(BASE + '/my/library/new', data={
    'csrf_token': token(s, '/my/library'), 'name': '   ', 'category': 'workbook'},
    allow_redirects=False, timeout=120)
moved, location = redirected(r)
check('名字空着会被退回并展开表单', moved and 'new=1' in location, location)

# ---------------------------------------------------------------- 错题页
html = s.get(BASE + '/my/mistakes', timeout=120).text
opts = workbook_options(html)
check('错题页速记条有「哪本练习册」下拉', opts is not None)
check('刚建的资料出现在练习册下拉里', bool(opts) and 'HTTP 验收册' in opts, opts)

picked = re.search(r'<option[^>]*value="(\d+)"[^>]*>\s*HTTP 验收册', html)
if picked:
    r = s.post(BASE + '/my/learning/mistakes/new', data={
        'csrf_token': token(s, '/my/mistakes'), 'workbook_id': picked.group(1),
        'page': '13', 'question_no': '1,3'}, allow_redirects=True, timeout=120)
    check('对着这本新练习册记得上错题（题号 1,3 拆两条）',
          'created=2' in r.url, r.url)
else:
    check('对着这本新练习册记得上错题（题号 1,3 拆两条）', False, '没抓到练习册 id')

# ---------------------------------------------------------------- 上传那条路
r = s.post(BASE + '/tutoring/library/upload', data={
    'csrf_token': token(s, '/my/library'), 'category': 'workbook',
    'title': '传上来的教辅'}, files=[('file', ('教辅.pdf', PDF, 'application/pdf'))],
    timeout=120)
check('知识库上传成功', r.status_code == 200 and r.json().get('ok'), r.text[:200])
opts = workbook_options(s.get(BASE + '/my/mistakes', timeout=120).text)
check('传上来的教辅也出现在下拉里', bool(opts) and '传上来的教辅' in opts, opts)

# ---------------------------------------------------------------- 补附件
if item_id:
    r = s.post(BASE + '/my/library/%s/add_file' % item_id,
               data={'csrf_token': token(s, item_url)},
               files=[('file', ('HTTP 验收册.pdf', PDF, 'application/pdf'))],
               allow_redirects=False, timeout=120)
    moved, location = redirected(r)
    check('补附件提交成功', moved and 'attached=1' in location, location)
    page = s.get(BASE + item_url, timeout=120).text
    check('补完之后不再提示"还没有附件"', '还没有附件' not in page)
    check('补完之后有下载了', 'raw?download=1' in page)
    opts = workbook_options(s.get(BASE + '/my/mistakes', timeout=120).text)
    check('补附件后下拉里仍只有一本同名', bool(opts) and opts.count('HTTP 验收册') == 1, opts)

print('\n结果：%d 项通过，%d 项失败' % (total - len(fails), len(fails)))
if fails:
    print('失败项：' + '、'.join(fails))
    sys.exit(1)
