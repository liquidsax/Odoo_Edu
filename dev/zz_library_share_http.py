"""共享功能的 HTTP 层验收：打 8899 上那个一次性实例，走真实门户路由。

    cd E:\\Odoo && PYTHONUTF8=1 ./python/python.exe dev/zz_library_share_http.py

需要一次性实例已在 8899 上跑着（--db-filter 钉在那个库）。脚本自己登录、自己判。
"""
import re
import sys

import requests

B = 'http://127.0.0.1:8069' if '--live' in sys.argv else 'http://127.0.0.1:8899'
DB = 'OdooForDB' if '--live' in sys.argv else 'zz_library_share'
NOTE_ID = 3
FILE_ID = 4

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
    print('%-4s %s%s' % ('PASS' if cond else 'FAIL', label, ('  <- %s' % extra) if extra and not cond else ''))


def login(login_name, password):
    s = requests.Session()
    for _ in range(30):
        try:
            r = s.post(B + '/web/session/authenticate', json={'jsonrpc': '2.0', 'method': 'call', 'params': {
                'db': DB, 'login': login_name, 'password': password}}, timeout=10)
            if r.status_code == 200 and r.headers.get('content-type', '').startswith('application/json'):
                uid = r.json()['result']['uid']
                if uid:
                    return s
                break
        except requests.exceptions.RequestException:
            pass
        import time
        time.sleep(2)
    raise SystemExit('登录失败：%s' % login_name)


def csrf(session, path):
    html = session.get(B + path, timeout=30).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or \
        re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else ''


stu = login('zz_stu', 'Zz-stu-2026')
adm = login('admin', 'admin')

# --- 学生侧 ---
r = stu.get(B + '/my/library?filterby=shared', timeout=60)
check('学生打开「共享给我」是 200', r.status_code == 200, str(r.status_code))
check('列表里能看到主人那条', '验收笔记' in r.text)
check('卡片标了「来自」', '来自' in r.text)
check('别人的标签名没有透出去', '别透出去' not in r.text)
check('别人的文件夹名没有透出去', '私人收纳' not in r.text)

r = stu.get(B + '/my/library', timeout=60)
check('学生自己的知识库仍然正常', r.status_code == 200 and '共享给我' in r.text)

r = stu.get(B + '/my/library/%d' % NOTE_ID, timeout=60)
check('学生能打开共享条目详情', r.status_code == 200, str(r.status_code))
check('详情页写明不占他的容量', '不占你的容量' in r.text)
check('详情页没有「保存修改」', '保存修改' not in r.text)
check('详情页没有删除按钮', '>删除<' not in r.text)
check('详情页没有「谁可以看」入口', '谁可以看' not in r.text)
check('详情页不渲染主人的文件夹与标签', '私人收纳' not in r.text and '别透出去' not in r.text)

r = stu.get(B + '/tutoring/library/%d/raw' % NOTE_ID, timeout=60)
check('学生能取到正文（200）', r.status_code == 200, str(r.status_code))

r = stu.get(B + '/my/learning/workbook-files/%d' % FILE_ID, timeout=60)
check('共享后学生能打开教材文件页（原来这里 404）', r.status_code == 200, str(r.status_code))

# --- 主人侧 ---
r = adm.get(B + '/my/library/%d' % NOTE_ID, timeout=60)
check('主人详情页有「谁可以看」', r.status_code == 200 and '谁可以看' in r.text)
check('主人看得到已共享人数', '已共享 1 人' in r.text, r.text[r.text.find('已共享'):r.text.find('已共享') + 20] if '已共享' in r.text else '没有这段')
check('主人侧仍渲染自己的文件夹', '私人收纳' in r.text)

token = csrf(adm, '/my/library/%d' % NOTE_ID)
r = adm.post(B + '/my/library/%d/share' % NOTE_ID,
             data={'csrf_token': token, 'share_uid': ['7', '8', '2']},
             timeout=60, allow_redirects=False)
check('主人提交共享名单是 303 回详情页', r.status_code == 303, str(r.status_code))
r = adm.get(B + '/my/library/%d' % NOTE_ID, timeout=60)
check('内部用户与主人自己被剔掉，名单还是 1 人', '已共享 1 人' in r.text)

# 没带 CSRF 的越权 POST
r = adm.post(B + '/my/library/%d/share' % NOTE_ID, data={'share_uid': ['7']}, timeout=60)
check('缺 CSRF 的共享 POST 被拒', r.status_code in (400, 403, 303) and '403' in r.text or r.status_code == 400,
      str(r.status_code))

# 学生试图改别人的条目：非本人那一侧根本没有这张表单，凑一个 POST 上去
token = csrf(stu, '/my/library/%d' % NOTE_ID)
r = stu.post(B + '/my/library/%d/edit' % NOTE_ID,
             data={'csrf_token': token, 'name': '学生乱改', 'category': 'note', 'folder': '', 'tags': ''},
             timeout=60, allow_redirects=False)
# 400 = 页面上没表单所以连 CSRF 都取不到；403/404 = 服务端按归属拦下。三种都算拦住了
check('学生 POST 改名进不去', r.status_code in (400, 403, 404), str(r.status_code))
r = adm.get(B + '/my/library/%d' % NOTE_ID, timeout=60)
check('改名确实没落库', '学生乱改' not in r.text)

print('\n合计 %d 项：通过 %d，失败 %d' % (ok + fail, ok, fail))
sys.exit(1 if fail else 0)
