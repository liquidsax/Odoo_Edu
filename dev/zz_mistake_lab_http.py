# -*- coding: utf-8 -*-
"""一次性库上的 HTTP 渲染检查：错题页每一版各真渲染一遍，
「每日回顾」那张一天一张的大图走真 POST。

用法（先起一个 8899 的实例挂在一次性库上；**是 --http-port，`--port` 不存在**）：
    cd server && ../python/python.exe odoo-bin -c odoo.conf -d zz_mistake_lab \\
        --http-port=8899 --http-interface=127.0.0.1 --logfile=../dev/zz_mistake_lab_http.log
    ../python/python.exe ../dev/zz_mistake_lab_http.py

账号与数据由 dev/zz_mistake_lab_check.py 建好（zz_lab_a / zz-lab-pw），
它把要用的行 id 与那三个日子写进 dev/zz_mistake_lab_ids.json。
用 requests 自带会话，不碰浏览器那个 cookie jar（8069 与 8899 共用会互相顶登录）。
"""
import base64
import json
import os
import re
import time

import requests

BASE = 'http://127.0.0.1:8899'
DB = 'zz_mistake_lab'
LOGIN, PW = 'zz_lab_a', 'zz-lab-pw'

# 一次性库上的数据由 dev/zz_mistake_lab_check.py 建好并写了这份 id 清单
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'zz_mistake_lab_ids.json'), encoding='utf-8') as fh:
        IDS = json.load(fh)
except OSError:
    IDS = {'own': 1, 'foreign': 22, 'm_pdf': 0, 'm_ai': 0, 'm_none': 0}
FOREIGN_ID = IDS['foreign']        # 别的学生那条（这个账号在任何页面上都看不到它）

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %s %s' % (label, extra))
    else:
        fail += 1
        print('  FAIL  %s %s' % (label, extra))


def render(url):
    resp = session.get(BASE + url, allow_redirects=False, timeout=60)
    body = resp.text
    broken = any(marker in body for marker in (
        'Traceback', 'QWebException', 'xml syntax error', 'is undefined'))
    return resp, body, broken


session = requests.Session()
auth = session.post(BASE + '/web/session/authenticate', timeout=60, json={
    'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': LOGIN, 'password': PW}})
uid = (auth.json().get('result') or {}).get('uid')
print('\n== 登录 ==')
check('门户账号登录成功', bool(uid), 'uid=%s' % uid)
if not uid:
    raise SystemExit('登不进去，后面都不用跑：%s' % auth.text[:300])

print('\n== 三个版本各渲染一次 ==')
resp, body, broken = render('/my/mistakes?lab=wall')
check('卡片墙 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('卡片墙画出卡片', 'o_mistake_card' in body)
check('版本开关在三版里都出现', '试用版本' in body)

resp, body, broken = render('/my/mistakes?lab=queue')
check('今日队列 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('队列给了"今天有 N 道"', bool(re.search(r'今天有\s*<b>\d+', body)),
      re.search(r'今天有\s*<b>(\d+)', body).group(1) if re.search(r'今天有\s*<b>(\d+)', body) else '没找到')
check('队列把"其余"折起来了', 'queue_rest' in body and 'collapse' in body)
check('队列版把轻重那句话说在明面上', 'o_mistake_heat_note' in body)

resp, body, broken = render('/my/mistakes?lab=grid')
check('表格版 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('表格版有表头和保存按钮', 'o_mistake_grid' in body and '保存这一屏' in body)
check('表格版每格控件都带了行 id 后缀', bool(re.search(r'name="note_\d+"', body)))

print('\n== 非法 lab 与参数保持 ==')
resp, body, broken = render('/my/mistakes?lab=bogus')
check('lab=bogus 回退成卡片墙而不是 500',
      resp.status_code == 200 and 'o_mistake_card' in body and 'o_mistake_grid' not in body)
resp, body, broken = render('/my/mistakes?lab=queue&filterby=hard')
check('筛选链接把 lab 带上了（切版不丢筛选）', 'lab=queue' in body and 'filterby=hard' in body)
resp, body, broken = render('/my/mistakes?lab=grid&limit=30')
check('limit=30 不在白名单里也不炸', resp.status_code == 200 and not broken)

print('\n== 表格真提交：改一格存一次 ==')
resp, body, _ = render('/my/mistakes?lab=grid')
token = re.search(r'name="csrf_token" value="([^"]+)"', body)
row = re.search(r'name="note_(\d+)"', body)
check('表单里有 csrf 令牌', bool(token))
check('表格里有可编辑的行', bool(row))
if token and row:
    # 每次跑都换一个 marker，否则重跑时"没改动"→ saved=0，看着像写入口坏了
    rid, marker = row.group(1), 'HTTP 验收写的 %s-%d' % (row.group(1), int(time.time()))
    size = re.search(r'name="limit" value="(\d+)"', body)
    resp = session.post(BASE + '/my/mistakes/grid', allow_redirects=False, timeout=60, data={
        'csrf_token': token.group(1), 'row_%s' % rid: '1', 'note_%s' % rid: marker,
        'lab': 'grid', 'limit': size.group(1) if size else '20'})
    loc = resp.headers.get('Location', '')
    check('提交后跳回错题页（303）', resp.status_code in (301, 303), loc)
    check('回执说保存了 1 行', 'saved=1' in loc, loc)
    resp, body, _ = render('/my/mistakes?lab=grid')
    check('改动真的落库并回显', marker in body)

    print('\n== 越权与垃圾提交 ==')
    resp = session.post(BASE + '/my/mistakes/grid', allow_redirects=False, timeout=60, data={
        'csrf_token': token.group(1), 'row_%d' % FOREIGN_ID: '1',
        'note_%d' % FOREIGN_ID: 'A 想改别人的那条', 'lab': 'grid'})
    loc = resp.headers.get('Location', '')
    check('伪造别人那条的行号：整行被丢掉，回执 saved=0',
          resp.status_code in (301, 303) and 'saved=0' in loc, loc)
    resp = session.post(BASE + '/my/mistakes/grid', allow_redirects=False, timeout=60, data={
        'csrf_token': token.group(1), 'row_999999': '1', 'note_999999': '不存在的行',
        'lab': 'grid'})
    check('不存在的行号也不炸', resp.status_code in (301, 303)
          and 'saved=0' in resp.headers.get('Location', ''))
    resp = session.post(BASE + '/my/mistakes/grid', allow_redirects=False, timeout=60, data={
        'row_1': '1', 'note_1': '没有令牌'})
    check('缺 csrf 令牌被挡（400/303 回登录，不是直接写库）',
          resp.status_code in (400, 303), resp.status_code)

print('\n== 详情那条老通道没被带坏 ==')
resp, body, broken = render('/my/learning/mistakes/%s' % (row.group(1) if row else FOREIGN_ID))
check('错题详情页仍 200', resp.status_code == 200 and not broken, resp.status_code)

print('\n== 新 CSS 真的进了资产包（不是只躺在磁盘上）==')
resp, body, _ = render('/my/mistakes?lab=wall')
css_urls = re.findall(r'href="(/web/assets/[^"]+\.min\.css)"', body)
check('页面引了前端资产包', bool(css_urls), ' / '.join(css_urls)[:120])
bundled = ''
for url in css_urls:
    css = session.get(BASE + url, timeout=120)
    if css.status_code == 200:
        bundled += css.text
check('资产包里有卡片色条规则', '.o_mistake_card.o_mistake_heat_hot' in bundled)
check('资产包里有表格版规则', '.o_mistake_grid' in bundled)
check('资产包里有队列版规则', '.o_mistake_queue' in bundled)
check('资产包里有配方封面规则', '.o_mistake_cover_recipe' in bundled)
check('资产包里有拖图区规则', '.o_mistake_dropzone' in bundled)
check('资产包里有每日回顾那张大图的规则', '.o_mistake_daily_cover' in bundled)
check('资产包里有每日回顾清单那行的规则', '.o_mistake_daily_row' in bundled)

print('\n== 每日回顾：一天一张大图（旧三版已从 ?lab= 里消失）==')
for old in ('coverpdf', 'covercss', 'coverai'):
    resp, body, broken = render('/my/mistakes?lab=%s' % old)
    check('%s 这一版已不在白名单里：回退成卡片墙而不是 500' % old,
          resp.status_code == 200 and not broken and 'o_mistake_card' in body
          and 'o_mistake_daily_cover' not in body, resp.status_code)
    check('%s 那一版的大图卡模板也不再被引用' % old, 'o_mistake_cover_card' not in body)

resp, body, broken = render('/my/mistakes?lab=daily')
check('每日回顾 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('一天只有一张大图（不是每题一张）', body.count('o_mistake_daily_cover') == 1,
      body.count('o_mistake_daily_cover'))
check('这一天的题在图下面列成一列', 'o_mistake_daily_row' in body)
check('旧"给这批做封面"那个批量口不再出现', '给这批做封面' not in body)
check('回顾版不引 pdf.js 那套（封面是服务端渲染的）', 'data-mistake-covers' not in body)
# 换日子/翻前后一天必须带着当前范围与筛选：只在看板那种有分页的页面上 scope 才会
# 自己冒出来，回顾版没有分页，所以这里必须**从 URL 就给进去**再验链接带没带上
resp, body, broken = render('/my/mistakes?lab=daily&scope=mine&filterby=hard')
day_links = [h for h in re.findall(r'href="([^"]*day=[^"]*)"', body)]
check('切到回顾版并把范围/筛选带着走（换日子不丢）',
      len(day_links) > 1 and all('scope=mine' in h for h in day_links)
      and all('filterby=hard' in h for h in day_links),
      '%d 条日子链接' % len(day_links))

resp, body, broken = render('/my/mistakes?lab=daily&day=%s' % IDS['yday'])
check('指定日子 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('换日子就换一张：图上写的是那一天', IDS['yday'] in body)
check('那一天有 AI 配方 → 角标写"AI 配方"', 'AI 配方' in body)
check('配方渲染走 CSS 变量 + 内联 SVG，页面里没有外链图',
      '--cbg-a:#312e81' in body and 'o_cover_motif' in body and '/cover.png' not in body)
esc = body.count('&lt;script&gt;alert(2)&lt;/script&gt;')
raw = body.count('<script>alert(2)</script>')
check('带尖括号的概括只以文本形式出现，没变成真标签',
      esc == 1 and raw == 0, 'escaped=%d raw=%d' % (esc, raw))

resp, body, broken = render('/my/mistakes?lab=daily&day=不是个日期')
check('day 参数乱写也不炸（回落到最近有题的那天）',
      resp.status_code == 200 and not broken and 'o_mistake_daily_cover' in body)
resp, body, broken = render('/my/mistakes?lab=daily&day=1999-01-01')
check('翻到一个没题的日子也不炸，明说这一天没错题',
      resp.status_code == 200 and not broken and '这一天没有错题' in body)

print('\n== 整屏流照旧（feed 的 auto 模式还在读单题 cover_recipe，那条路没动）==')
resp, feed_body, broken = render('/my/mistakes?lab=feed')
check('整屏流 200 且没炸', resp.status_code == 200 and not broken, resp.status_code)
check('流里有自己的滚动容器', 'o_mistake_feed' in feed_body)
check('每道都带"打开"和"放过"', '放过' in feed_body and '/snooze' in feed_body)
check('流里"原页优先"（auto 模式）', 'o_mistake_cover_shot' in feed_body)
check('流仍然挂着 pdf.js 的容器', 'data-mistake-covers' in feed_body)
check('单题那份 AI 配方照旧被认出来（字段留着没删）',
      'o_mistake_cover_recipe' in feed_body and '--cbg-a:#064e3b' in feed_body)
check('单题配方的概括与角标印在封面上',
      '正弦周期怎么读' in feed_body and 'P13 第7题' in feed_body)
esc1 = feed_body.count('&lt;script&gt;alert(1)&lt;/script&gt;')
raw1 = feed_body.count('<script>alert(1)</script>')
check('单题那层的尖括号也照样只以文本出现',
      esc1 == 1 and raw1 == 0, 'escaped=%d raw=%d' % (esc1, raw1))


def fetch(url):
    return session.get(BASE + url, allow_redirects=False, timeout=90)


r = fetch('/my/learning/mistakes/%d/page.pdf' % IDS['m_pdf'])
check('单页 PDF 200 且是 %PDF 开头', r.status_code == 200 and r.content[:4] == b'%PDF',
      '%s %d 字节' % (r.headers.get('Content-Type'), len(r.content)))
check('PDF 回包也带 nosniff', r.headers.get('X-Content-Type-Options') == 'nosniff')
check('老师没共享给这个学生的教材：原页取不到 → 404，前端退回文字封面',
      fetch('/my/learning/mistakes/%d/page.pdf' % IDS['m_hidden']).status_code == 404)
check('书没正文那道要 404（前端才退回文字封面）',
      fetch('/my/learning/mistakes/%d/page.pdf' % IDS['own']).status_code == 404)
check('别人的题：原页 PDF 404',
      fetch('/my/learning/mistakes/%d/page.pdf' % FOREIGN_ID).status_code == 404)
check('旧那个逐题批量口真的删了（404，不是半截死代码）',
      session.post(BASE + '/my/mistakes/covers', allow_redirects=False, timeout=60,
                   data={'lab': 'daily'}).status_code == 404)

print('\n== 没配密钥时点"做这一天的回顾"：要说清楚，还要退出一张能看的封面 ==')
resp, body, _ = render('/my/mistakes?lab=daily&day=%s' % IDS['day2'])
check('这天有题、一次回顾都没做过 → 退让原因写在图上',
      '文字回顾' in body and '还没做过回顾' in body, '')
check('没配方那天只给"做这一天的回顾"，不给重做那颗', 'name="redo"' not in body)
check('退让那张仍然是一张封面：有底色、有概括、有角标',
      '--cbg-a:' in body and 'o_mistake_daily_headline' in body
      and IDS['day2'] in body)
tok2 = re.search(r'name="csrf_token" value="([^"]+)"', body)
check('回顾那张表单带 csrf 与 day（做完回到同一天）',
      bool(tok2) and ('name="day" value="%s"' % IDS['day2']) in body)
if tok2:
    resp = session.post(BASE + '/my/mistakes/digest', allow_redirects=False, timeout=90,
                        data=dict(csrf_token=tok2.group(1), lab='daily', scope='mine',
                                  day=IDS['day2']))
    loc = resp.headers.get('Location', '')
    check('点了按钮不炸（303 回错题页）', resp.status_code in (301, 303), resp.status_code)
    check('回到的是每日回顾那版、同一天（回执沿用 ?error= 那套机制）',
          'lab=daily' in loc and 'day=%s' % IDS['day2'] in loc.replace('+', '%20'), loc[:120])
    check('没密钥时把原因带回页面，而不是假装成功',
          'error=' in loc and 'flash=digest' not in loc, loc[:120])
    resp, body2, broken = render(resp.headers.get('Location', '/my/mistakes'))
    check('那句原因真的显示在页面上', '密钥' in body2 and not broken)
    check('退让封面没变成空白：图上写着为什么退让',
          'o_mistake_daily_cover' in body2 and '密钥' in body2)
    check('退让那一张的配方没被写坏（ready 仍是 False，图仍是文字那张）',
          '文字回顾' in body2)

    print('\n== 重做已有的一张：不毁图，也只有一张 ==')
    resp, body, _ = render('/my/mistakes?lab=daily&day=%s' % IDS['today'])
    check('已有配方那天显示的是"重做这一天的回顾"', '重做这一天的回顾' in body)
    check('已有配方那天给的是重做那颗（redo 这个键只在已有配方时才出现在表单里）',
          'name="redo"' in body)
    tok3 = re.search(r'name="csrf_token" value="([^"]+)"', body)
    if tok3:
        resp = session.post(BASE + '/my/mistakes/digest', allow_redirects=False, timeout=90,
                            data=dict(csrf_token=tok3.group(1), lab='daily', scope='mine',
                                      day=IDS['today'], redo='1'))
        loc = resp.headers.get('Location', '')
        check('重做时接口没成也不 500（303 带 error）',
              resp.status_code in (301, 303) and 'error=' in loc, loc[:120])
        resp, after, _ = render('/my/mistakes?lab=daily&day=%s' % IDS['today'])
        check('重做失败没把已有那张好图毁掉（AI 配方还在）',
              'AI 配方' in after and '集合运算一起过' in after)
        check('一天还是只有一张大图', after.count('o_mistake_daily_cover') == 1)
    else:
        check('重做表单里有 csrf 令牌', False)

    print('\n== 回顾的越权与垃圾提交 ==')
    resp = session.post(BASE + '/my/mistakes/digest', allow_redirects=False, timeout=90,
                        data=dict(csrf_token=tok2.group(1), lab='daily', day=IDS['today']))
    check('缺 csrf 令牌的生成被挡（400/303 回登录，不是静默写库）',
          resp.status_code in (400, 303), resp.status_code)
    # 把 scope 伪造成别人的档案 id：记录规则应该让它落到"自己那份"上，而不是别人的
    resp = session.post(BASE + '/my/mistakes/digest', allow_redirects=False, timeout=90,
                        data=dict(csrf_token=tok2.group(1), lab='daily', scope='999999',
                                  day=IDS['day2']))
    check('scope 写一个不存在的档案也不炸（回落到本人那份）',
          resp.status_code in (301, 303), resp.status_code)
    resp, mine, _ = render('/my/mistakes?lab=daily&day=%s' % IDS['today'])
    check('伪造 scope 也写不到别人名下：页面上仍是我自己那一张',
          '别人的回顾' not in mine and '集合运算一起过' in mine)

resp, feed_body2, _ = render('/my/mistakes?lab=feed')
tok = re.search(r'name="csrf_token" value="([^"]+)"', feed_body2)
tgt = re.search(r'action="/my/learning/mistakes/(\d+)/snooze"', feed_body)
check('流里的"放过"带令牌与目标', bool(tok) and bool(tgt))
if tok and tgt:
    resp = session.post(BASE + '/my/learning/mistakes/%s/snooze' % tgt.group(1),
                        allow_redirects=False, timeout=60,
                        data=dict(csrf_token=tok.group(1), lab='feed', scope='mine'))
    check('放过之后跳回同一版（lab=feed 还在）',
          resp.status_code in (301, 303) and 'lab=feed' in resp.headers.get('Location', ''),
          resp.headers.get('Location', ''))
    resp = session.post(BASE + '/my/learning/mistakes/%d/snooze' % FOREIGN_ID,
                        allow_redirects=False, timeout=60,
                        data=dict(csrf_token=tok.group(1), lab='feed'))
    check('对别人的题按"放过"→ 404，不写别人的排期', resp.status_code == 404, resp.status_code)

print('\n== 批次③：拖图记题、归档、删除（含"连照片一起删"）==')
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
resp, body, _ = render('/my/mistakes?lab=wall')
tok3 = re.search(r'name="csrf_token" value="([^"]+)"', body)
check('页面上有"传照片记题"入口', '传照片记题' in body)
check('拖图表单是 multipart 且指向新口',
      'enctype="multipart/form-data"' in body and 'action="/my/mistakes/photos"' in body)
check('筛选药丸里有"已归档"', '已归档' in body)

if tok3:
    r = session.post(BASE + '/my/mistakes/photos', allow_redirects=False, timeout=90,
                     data=dict(csrf_token=tok3.group(1), lab='wall', scope='mine'),
                     files=[('file', ('zz 拖图验收.png', PNG, 'image/png'))])
    loc = r.headers.get('Location', '')
    check('拖一张图就记下一道题（303 回列表、created=1）',
          r.status_code in (301, 303) and 'created=1' in loc, loc[:80])
    resp, body, _ = render('/my/mistakes?lab=wall&limit=50')
    check('没练习册的这道照样出现在列表里，并标着"没填出处"', '没填出处' in body)

    own = IDS['own']
    r = session.post(BASE + '/my/learning/mistakes/%d/archive' % own, allow_redirects=False,
                     timeout=60, data=dict(csrf_token=tok3.group(1), lab='wall', scope='mine'))
    check('归档自己那条 → 303 带 flash=archived',
          'flash=archived' in r.headers.get('Location', ''), r.headers.get('Location', '')[:60])
    resp, wall, _ = render('/my/mistakes?lab=wall&limit=50')
    resp, arch, _ = render('/my/mistakes?lab=wall&filterby=archived&limit=50')
    check('归档后默认视野不再出现它，"已归档"里能看到',
          ('/my/learning/mistakes/%d"' % own) not in wall
          and ('/my/learning/mistakes/%d"' % own) in arch)
    resp, arch, _ = render('/my/learning/mistakes/%d' % own)
    check('归档那条的详情页还打得开，并写明是归档状态',
          resp.status_code == 200 and '已经' in arch and '归档' in arch)
    r = session.post(BASE + '/my/learning/mistakes/%d/unarchive' % own, allow_redirects=False,
                     timeout=60, data=dict(csrf_token=tok3.group(1), lab='wall', scope='mine'))
    check('放回 → 303 带 flash=restored', 'flash=restored' in r.headers.get('Location', ''))
    # 用 limit=50 而不是默认每页 10：这一路里我们**打开过这条的详情页**，
    # 而"打开一次＝往后挪一格"正是排期的设计（review_count 已经 +1、到期日被推后），
    # 于是它按 next_review_at 升序掉到第一页之外了。这里要验的是"放回视野"，不是"排在第几"。
    resp, wall, _ = render('/my/mistakes?lab=wall&limit=50')
    want = '/my/learning/mistakes/%d"' % own
    check('放回后默认视野里又有了', want in wall,
          'status=%s 页内 %d 条链接 找 %s' % (
              resp.status_code, len(set(re.findall(r'/my/learning/mistakes/(\d+)', wall))), want))

    nb = IDS['m_nobook']
    r = session.post(BASE + '/my/learning/mistakes/%d/attach' % nb, allow_redirects=False,
                     timeout=90, data=dict(csrf_token=tok3.group(1)),
                     files=[('file', ('zz 验收照片.png', PNG, 'image/png'))])
    check('给这条挂一张题目照片', 'attached=1' in r.headers.get('Location', ''),
          r.headers.get('Location', '')[:60])
    resp, lib, _ = render('/my/library')
    check('照片出现在知识库里', 'zz 验收照片' in lib)
    r = session.post(BASE + '/my/learning/mistakes/%d/delete' % nb, allow_redirects=False,
                     timeout=60, data=dict(csrf_token=tok3.group(1), also_files='1',
                                           lab='wall', scope='mine'))
    check('删除 → 303 带 flash=deleted', 'flash=deleted' in r.headers.get('Location', ''))
    resp, wall, _ = render('/my/mistakes?lab=wall')
    resp, lib, _ = render('/my/library')
    check('那条错题从视野里消失', '/my/learning/mistakes/%d"' % nb not in wall)
    check('勾了"连照片一起删"，知识库里也没有那张了', 'zz 验收照片' not in lib)
    r = session.post(BASE + '/my/learning/mistakes/%d/delete' % FOREIGN_ID,
                     allow_redirects=False, timeout=60,
                     data=dict(csrf_token=tok3.group(1), lab='wall'))
    check('删别人的那条 → 404，不是静默成功', r.status_code == 404, r.status_code)
    r = session.post(BASE + '/my/learning/mistakes/%d/delete' % IDS['m_pdf'],
                     allow_redirects=False, timeout=60, data=dict(lab='wall'))
    check('没令牌的删除被挡（400）', r.status_code == 400, r.status_code)
else:
    check('列表页里有 csrf 令牌', False)


print('\n== 结果：%d 过 / %d 不过 ==' % (ok, fail))
if fail:
    print('!!! 有 %d 条不过，别部署' % fail)
