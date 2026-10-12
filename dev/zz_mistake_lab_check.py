# -*- coding: utf-8 -*-
"""一次性库上验错题页那几个试用版本的取数与写入口径（含「每日回顾」一天一张大图）。

用法（模块在一次性库里装好之后）：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_mistake_lab_check.py

只在一次性库上跑：它会建一个 ZZ 档案和几条错题。
**执行顺序**：破坏性的那段（归档/真删）排在最后——更早的渲染与读类断言要用到那几条题，
顺序错了就是自己把自己要看的数据删掉（陷阱 85）。
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError

from odoo.addons.tutoring_center.controllers.portal import TutoringPortal

ok = fail = 0

def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %s %s' % (label, extra))
    else:
        fail += 1
        print('  FAIL  %s %s' % (label, extra))


Mistake = env['tutoring.mistake']
Student = env['tutoring.student']
Workbook = env['tutoring.workbook']
Cause = env['tutoring.mistake.cause']
Point = env['tutoring.knowledge.point']
Digest = env['tutoring.mistake.digest']

# 先清掉上一轮留下的 ZZ 数据：这个脚本要能随时重跑（上一次跑就在 commit 之后才崩的）
for _st in Student.search([('name', '=like', 'ZZ %')]):
    _st.mistake_ids.unlink()
    _st.unlink()
for _u in env['res.users'].search([('login', '=like', 'zz_lab%')]):
    _u.unlink()
Workbook.search([('name', '=like', 'ZZ %')]).unlink()
env['ir.config_parameter'].sudo().search(
    [('key', '=like', 'zz_lab.%')]).unlink()

now = fields.Datetime.now()
student = Student.create({'name': 'ZZ 版本试验', 'grade': '07'})
user_a = env['res.users'].create({
    'name': 'ZZ 门户A', 'login': 'zz_lab_a', 'password': 'zz-lab-pw',
    'partner_id': student.partner_id.id,
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
})
book = Workbook.create({'name': 'ZZ 试验册'})
cause = Cause.search([], limit=1)
point = Point.search([('grade', 'in', student.knowledge_grades or [student.grade])], limit=1)
print('\n== 备料 ==  档案 %s / 练习册 %s / 错因 %s / 知识点 %s'
      % (student.name, book.name, cause.name or '（库里没有错因）', point.name or '（没有知识点）'))


def mk(days, difficulty, opened=True, reviewed=None):
    """造一条错题并按需要把排期挪到过去/未来；reviewed=None 时留空排期。"""
    rec = Mistake.create({
        'student_id': student.id, 'workbook_id': book.id, 'difficulty': difficulty,
        'page': '13', 'question_no': str(900 + len(Mistake.search([('student_id', '=', student.id)]))),
    })
    rec.write({
        'last_review_at': now if opened else False,
        'next_review_at': now + timedelta(days=days) if reviewed is None else reviewed,
    })
    return rec


hot = mk(-10, '5')
due_new = mk(-1, '3', opened=False)
due_now = mk(0, '3')
hard = mk(5, '4')
cool = mk(5, '2')
never_scheduled = mk(5, '3', reviewed=False)
batch = hot | due_new | due_now | hard | cool | never_scheduled

print('\n== 轻重四档（到期多久 × 难度）==')
for rec, want in ((hot, 'hot'), (due_new, 'due'), (due_now, 'due'),
                  (hard, 'hard'), (cool, 'cool')):
    check('%s→%s' % (rec.display_name[-6:], want), rec.portal_heat == want,
          '[实际 %s / %s]' % (rec.portal_heat, rec.portal_heat_note))
check('搁了 10 天且高难度写进说明', '10 天' in (hot.portal_heat_note or ''), hot.portal_heat_note)
check('没翻开过的题说"一次都没翻开过"',
      '一次都没翻开过' in (due_new.portal_heat_note or ''), due_new.portal_heat_note)
check('到期当天的题说"到期了"',
      '到期了' in (due_now.portal_heat_note or ''), due_now.portal_heat_note)
check('未到期但难度高的说"N 天后再看"',
      '5 天后再看' in (hard.portal_heat_note or ''), hard.portal_heat_note)
check('每档都有一句话说明（界面上不能出现空白理由）',
      all(rec.portal_heat_note for rec in batch))

print('\n== 队列分区：到期条件与卡片配色必须同一口径 ==')
due_domain = Mistake._due_domain(now)
due_set = Mistake.search(due_domain + [('id', 'in', batch.ids)])
check('到期集合 = hot+两条due+空排期', set(due_set.ids) == {hot.id, due_new.id, due_now.id, never_scheduled.id},
      '实际 %s' % sorted(due_set.ids))
check('未到期的两条与"空排期"不落在 rest 里',
      set(Mistake.search([('next_review_at', '>', now)] + [('id', 'in', batch.ids)]).ids)
      == {hard.id, cool.id})
check('两半相加不重不漏（分区而不是筛选）',
      len(due_set) + len(Mistake.search([('next_review_at', '>', now)] +
                                        [('id', 'in', batch.ids)])) == len(batch))
check('空排期按"该看"处理（SQL 里 NULL 比不出真假）',
      never_scheduled.id in due_set.ids)
check('空排期那卡片也判成 due', never_scheduled.portal_heat == 'due',
      never_scheduled.portal_heat_note)

print('\n== 表格写入口：认不出的值跳过那一格，不是清空 ==')
ctrl = TutoringPortal()
rid = hard.id
vals = ctrl._mistake_grid_vals(hard, {'page_%d' % rid: '  27  ', 'question_no_%d' % rid: '',
                                      'note_%d' % rid: '   ', 'difficulty_%d' % rid: '9'}, rid)
check('页码去空格后写入', vals.get('page') == '27', repr(vals.get('page')))
check('题号空串写成 False（清空是明确动作）', vals.get('question_no') is False)
check('说明全空白不写（必填之外的字段不抹成 False 之外）',
      'note' not in vals or vals['note'] is False, repr(vals.get('note')))
check('难度 9 不在选项里：整格跳过而不是落库', 'difficulty' not in vals, repr(vals))
same = ctrl._mistake_grid_vals(hard, {'page_%d' % rid: hard.page or '',
                                      'difficulty_%d' % rid: hard.difficulty}, rid)
check('没改动的格不产生写入（保存只写动过的那几行）', same == {}, repr(same))
bad = ctrl._mistake_grid_vals(hard, {'date_%d' % rid: '2026-13-45'}, rid)
check('坏日期不动这一格', 'date' not in bad, repr(bad))
good = ctrl._mistake_grid_vals(hard, {'date_%d' % rid: '2026-10-02'}, rid)
check('好日期写入', good.get('date') == fields.Date.from_string('2026-10-02'), repr(good))
missing = ctrl._mistake_grid_vals(hard, {}, rid)
check('模板没给下拉的行（现值不在可选项里）整行不动', missing == {}, repr(missing))

print('\n== 版本白名单与分组互斥 ==')
# `_()` 要靠 request/env 找语言，shell 里两者都没有（Controller.env 是只读 property），
# 而这里要测的是"有哪几把键、标签中不中性"，跟翻译无关，所以把 `_` 临时换成恒等函数
portal_mod = __import__('odoo.addons.tutoring_center.controllers.portal', fromlist=['_'])
real_gettext = portal_mod._
portal_mod._ = lambda source: source
try:
    labs = ctrl._mistake_labs()
finally:
    portal_mod._ = real_gettext
check('五个版本都在（三个"一题一张"的封面版已收拢成 daily）',
      set(labs) == {'wall', 'queue', 'grid', 'daily', 'feed'},
      repr(sorted(labs)))
check('旧三版从 ?lab= 白名单里消失了',
      not ({'coverpdf', 'covercss', 'coverai'} & set(labs)), repr(sorted(labs)))
check('每版都有标签和一句说明',
      all(v.get('label') and v.get('hint') for v in labs.values()))
check('标签中性：不出现"推荐/新版/更好"',
      not any(w in ''.join(v['label'] + v['hint'] for v in labs.values())
              for w in ('推荐', '新版', '更好')))
check('daily 的说明说的是"一天一张"',
      '一天一张' in labs['daily']['hint'], labs['daily']['hint'])
check('默认每页 10，表格版默认 20',
      TutoringPortal.MISTAKE_PAGE_SIZES[0] == 10
      and TutoringPortal.MISTAKE_GRID_DEFAULT_SIZE == 20
      and 20 in TutoringPortal.MISTAKE_PAGE_SIZES)

print('\n== 卡片配色不靠颜色当唯一通道 ==')
check('每档都有 portal_heat_note 供悬停/长按读',
      all(rec.portal_heat_note for rec in batch))

print('\n== 封面配方：模型只许报 id，其余全部查我们的表 ==')
import base64
import io as _io
import json as _json

from PyPDF2 import PdfWriter

from odoo.addons.tutoring_center.models import mistake_cover as mc
from odoo.addons.tutoring_center.models import tutoring_mistake_digest as dmod
from odoo.addons.tutoring_center.models.tutoring_mistake_ai import DAILY_QUOTA

_w = PdfWriter()
_w.add_blank_page(width=595, height=842)
_w.add_blank_page(width=595, height=842)
_out = _io.BytesIO()
_w.write(_out)
PDF_B64 = base64.b64encode(_out.getvalue()).decode()

book_pdf = Workbook.create({'name': 'ZZ 有正文的册子'})
env['tutoring.workbook.file'].create({
    'workbook_id': book_pdf.id, 'name': 'ZZ 上册', 'content': PDF_B64,
    'page_from': 1, 'page_to': 2, 'user_id': user_a.id})
# 另一本：正文是老师传的、没共享给这个学生。判据用 sudo 问"有没有这一页"，
# 所以它仍会说"有原页可画"；真去取那一页时按本人权限来，取不到就退回文字封面。
book_hidden = Workbook.create({'name': 'ZZ 老师没共享的册子'})
env['tutoring.workbook.file'].create({
    'workbook_id': book_hidden.id, 'name': 'ZZ 老师上册', 'content': PDF_B64,
    'page_from': 1, 'page_to': 2})
m_pdf = Mistake.create({'student_id': student.id, 'workbook_id': book_pdf.id,
                        'page': '1', 'question_no': '1', 'difficulty': '3'})
m_hidden = Mistake.create({'student_id': student.id, 'workbook_id': book_hidden.id,
                           'page': '1', 'question_no': '2', 'difficulty': '3'})
m_ai = Mistake.create({'student_id': student.id, 'workbook_id': book.id,
                       'page': '13', 'question_no': '7', 'difficulty': '5'})
m_junk = Mistake.create({'student_id': student.id, 'workbook_id': book.id, 'difficulty': '2'})
# 练习册不再是必填：一张照片就该能记下一道题。
# 注意 default_get 会沿用上一条的练习册，所以"不填"必须显式给 False（拖图那条口就是这么传的）
m_nobook = Mistake.create({'student_id': student.id, 'difficulty': '3', 'workbook_id': False})
check('显式不填练习册也建得起来（拖照片记题的前提）',
      bool(m_nobook.id) and not m_nobook.workbook_id)
check('没练习册时喂给模型的事实行写"没填"', '出处：没填' in m_nobook._cover_facts())
check('有正文又有页码 → 走教材原页', m_pdf.cover_kind == 'pdf' and m_pdf.cover_pdf_ready)
check('单页 PDF 真抽得出来（page.pdf 那口有料）', bool(m_pdf.page_pdf))
check('老师没共享的教材：判据仍说"有原页"（判据走 sudo，取图按本人权限）',
      m_hidden.cover_kind == 'pdf' and m_hidden.cover_pdf_ready)
check('什么都没有 → 文字封面', m_nobook.cover_kind == 'css')

good = ('先是一句解释 {"bg":"ink","motifs":["ellipse","axes","bars","venn"],'
        '"headline":"离心率今天一起过","sub":"a=4 b=3","badge":"6 道·2 难"} 后面还想多说两句')
plan = mc.parse_single(good)
check('前后裹着解释文字也能把那个 JSON 抠出来',
      plan['bg'] == 'ink' and plan['headline'] == '离心率今天一起过', repr(plan))
check('图案最多收 3 个（给了 4 个）', len(plan['motifs']) == 3)
check('认不出的色板丢掉而不是照用', mc.parse_single('{"bg":"neon"}')['bg'] is None)
check('认不出的图案丢掉、认得出的留下',
      mc.parse_single('{"motifs":["unicorn","axes"]}')['motifs'] == ['axes'])
check('超长概括被截住',
      len(mc.parse_single('{"headline":"%s"}' % ('长' * 80))['headline']) <= 40)
check('模型沿用老格式回 {"covers":[{…}]} 也认（取第一条，不是报错）',
      mc.parse_single('{"covers":[{"bg":"pine","headline":"椭圆"}]}')['bg'] == 'pine')
check('模型直接回数组也认',
      mc.parse_single('[{"bg":"sea","headline":"双曲线"}]')['headline'] == '双曲线')
check('回的是空 covers 也只当"没配方"，不炸',
      mc.parse_single('{"covers":[]}')['bg'] is None)
try:
    mc.parse_single('模型今天不想回 JSON')
    check('抠不到 JSON 要抛错，不能静默当空', False)
except ValueError:
    check('抠不到 JSON 要抛错，不能静默当空', True)
style = mc.style_for(mc.clean({'bg': 'red;background:url(http://x)'}))
check('样式串只可能来自色板表，模型给的东西进不去',
      'http' not in style and '#1f2937' in style, style)
svg = str(mc.motifs_svg(mc.clean({'motifs': ['axes', 'evil', 'venn']})))
check('SVG 只画表里的形状，认不出的连字都不出现',
      'evil' not in svg and svg.count('<svg') == 2 and 'http' not in svg)
check('回顾一次最多喂 20 道（再多模型开始复读）', dmod.DAY_ITEM_LIMIT == 20,
      dmod.DAY_ITEM_LIMIT)
# 陷阱 87：模块级函数里那个参数原本叫 `user`，`_()` 顺栈找翻译上下文时会拿它去 int()，
# 于是"没配密钥"这句该好好说的话变成 ValueError。没有请求上下文（shell/cron）时必炸。
try:
    mc.chat(env, 'system', 'prompt')
    check('没密钥时 chat() 该抛异常而不是装着成功', False)
except UserError as err:
    check('没密钥时 chat() 抛的是说人话的 UserError（不是被 _() 找 uid 炸成的 ValueError）',
          '密钥' in str(err), str(err)[:60])
except Exception as err:
    check('没密钥时 chat() 抛的是说人话的 UserError（不是被 _() 找 uid 炸成的 ValueError）',
          False, repr(err)[:120])
check('摘要额度仍是每天 25 条', DAILY_QUOTA == 25)

m_ai.write({'cover_recipe': _json.dumps(mc.clean({
    'bg': 'pine', 'motifs': ['sine'], 'headline': '正弦周期怎么读',
    'sub': 'ω=2 φ=π/3', 'badge': 'P13 第7题'}), ensure_ascii=False)})
check('有能用的配方 → cover_kind=ai', m_ai.cover_kind == 'ai' and m_ai.cover_ai_ready)
check('底色取自色板（pine 的深端）', m_ai.cover_style.startswith('--cbg-a:#064e3b'),
      m_ai.cover_style)
check('概括/小字/角标各归各位',
      m_ai.cover_headline == '正弦周期怎么读' and m_ai.cover_sub == 'ω=2 φ=π/3'
      and m_ai.cover_badge == 'P13 第7题')
check('图案是内联 SVG 不是外链', 'o_cover_motif' in m_ai.cover_motifs and 'http' not in m_ai.cover_motifs)
m_junk.write({'cover_recipe': '{"bg":"ink","motifs":["axes"'})
check('配方本身是坏 JSON → 当没有，不炸也不上色',
      m_junk.cover_kind == 'css' and not m_junk.cover_headline)
m_junk.write({'cover_recipe': _json.dumps({'bg': 'nope', 'motifs': ['nope']})})
check('配方里全是废 id → 同样算"没有封面"', m_junk.cover_kind == 'css')
check('空配方也只会给出合法渐变串',
      m_junk.cover_style.startswith('--cbg-a:') and 'nope' not in m_junk.cover_style)
# 把一条"带标签的概括"原样写进去，转义要在页面上验（HTTP 那半边负责）
m_nobook.write({'cover_recipe': '{"bg":"ink","motifs":["axes"],'
                                '"headline":"<script>alert(1)</script>","sub":"","badge":"角标"}'})
check('带尖括号的概括仍算"有封面"（clean 只管 id 与长度，不吞文本）',
      m_nobook.cover_kind == 'ai' and '<script>' in m_nobook.cover_headline)

print('\n== 门户隔离：表格那条新通道靠的就是 search() 这一手 ==')
student_b = Student.create({'name': 'ZZ 别的学生', 'grade': '07'})
mistake_b = Mistake.create({'student_id': student_b.id, 'workbook_id': book.id,
                            'difficulty': '3', 'page': '9'})
try:
    own = Mistake.with_user(user_a).search([('id', '=', hot.id)], limit=1)
    other = Mistake.with_user(user_a).search([('id', '=', mistake_b.id)], limit=1)
except Exception as err:  # 路由里没有 try：这里炸了就是线上 500
    check('门户账号读错题不该抛异常', False, repr(err))
    own, other = None, None
check('A 搜得到自己那条（表格给下拉、能写）', bool(own) and own.id == hot.id)
check('A 搜不到别人那条（越权行在 route 里就是这么丢掉的）', not other)
check('A 对自己那条有写权限', hot.with_user(user_a).has_access('write'))
check('A 对别人那条连读都过不了', mistake_b.with_user(user_a).has_access('read') is False)

print('\n== 每日回顾：一天一张大图，配方属于"某一天"而不属于某条错题 ==')
today_d = fields.Date.context_today(env.user)
yday = today_d - timedelta(days=1)
day_set = Mistake.search([('student_id', '=', student.id), ('date', '=', today_d)])
check('今天这一份档案下确实有题可回顾（后面全靠它）', bool(day_set), len(day_set))

empty = Digest.browse()
check('空记录集也回一份"形状齐"的配方（陷阱 82 的口径）',
      set(empty._plan()) == {'bg', 'motifs', 'headline', 'sub', 'badge'})
check('空记录集的退让原因也是一句话，不是 False', bool(empty._fallback_reason()))
check('空记录集判"没有 AI 那一张"而不是抛异常', empty._is_ready() is False)

fb = Digest.fallback_plan(student, today_d, day_set)
check('文字回顾那张也是同一形状（模板只有一条渲染路径）',
      set(fb) == {'bg', 'motifs', 'headline', 'sub', 'badge'})
check('文字回顾有底色、且底色是表内的 id', fb['bg'] in mc.PALETTE_BY_ID, fb['bg'])
check('文字回顾有概括（不许是空白的封面）', bool(fb['headline']), fb['headline'])
check('文字回顾的概括只由这一天的事实拼出来（知识点带道数）',
      str(len(day_set)) in (fb['sub'] or '') or '×' in (fb['headline'] or ''),
      '%s / %s' % (fb['headline'], fb['sub']))
check('AI 不在场时不替它猜图案（文字那张一个图案都不放）', fb['motifs'] == [])
check('没题的一天也能算退让配方（空集不炸）',
      set(Digest.fallback_plan(student, today_d, Mistake.browse())) == set(fb))
check('文字回顾渲染出来的样式串里没有模型能碰的位置',
      'http' not in mc.style_for(fb) and mc.style_for(fb).startswith('--cbg-a:#'))

far = today_d + timedelta(days=400)
_d, state, message = Digest.generate(student, far)
check('那一天没题 → 说"没错题就不用做"，而不是抛异常',
      state == 'empty' and '没有错题' in message, '%s / %s' % (state, message))
check('没题的那天不会留下一张空回顾', not Digest.search(
    [('student_id', '=', student.id), ('date', '=', far)]))

# 一次性库三层都没密钥（env / .env / 系统参数），这一趟正是"AI 不通畅"那条退路
_d, state, message = Digest.generate(student, today_d)
digest = Digest.for_day(student, today_d)
check('没密钥时点生成不抛异常（不 500）', state == 'failed', '%s / %s' % (state, message))
check('退让原因里写着"没配密钥"这件事', bool(digest.note) and '密钥' in digest.note,
      digest.note)
check('退让那张照样有配方形状可读', digest.ready is False and bool(digest.reason),
      digest.reason)
check('退让时不留下半成品配方（recipe 仍是空的）', not digest.recipe)
check('那一天只留一张回顾（生成两次也只有一行）',
    Digest.search_count([('student_id', '=', student.id), ('date', '=', today_d)]) == 1)
check('回顾行上"这一天几道题"读得出来、也对得上（read_group 的日期粒度与归一都算验过）',
      digest.mistake_count == len(day_set),
      '%s vs %s' % (digest.mistake_count, len(day_set)))

seeded = mc.clean({'bg': 'plum', 'motifs': ['venn'], 'headline': '集合运算一起过',
                  'sub': '补集最常错', 'badge': '6 道·2 难'})
digest.write({'recipe': _json.dumps(seeded, ensure_ascii=False), 'note': False})
check('写好配方 → 判成"有 AI 那一张"', digest.ready and digest.reason is False)
check('底色查的是色板表（plum 的深端）', digest.style.startswith('--cbg-a:#4a044e'),
      digest.style)
check('概括/小字/角标各归各位',
      digest.headline == '集合运算一起过' and digest.sub == '补集最常错'
      and digest.badge == '6 道·2 难')
check('图案是内联 SVG 不是外链', 'o_cover_motif' in digest.motifs and 'http' not in digest.motifs)
_d, state, _message = Digest.generate(student, today_d)
check('已有配方的默认不重做', state == 'kept' and digest.ready, state)
_d, state, _message = Digest.generate(student, today_d, force=True)
check('重做时接口没成，也不把已有那张好图毁掉（recipe 原样留着）',
      state == 'failed' and digest.ready and digest.recipe, digest.recipe)
check('重做失败那次的原因仍然记下来（页面上说得出为什么还是 AI 那张/或退让）',
      bool(digest.note), digest.note)
digest.write({'note': False})

bad = Digest.create({'student_id': student.id, 'date': yday,
                     'recipe': '{"bg":"neon","motifs":["unicorn"]}'})
check('配方全是废 id → 判成"没有 AI 那一张"', bad.ready is False and bool(bad.reason),
      bad.reason)
bad.write({'recipe': '{"bg":"ink","motifs":["axes"'})
check('配方本身是坏 JSON → 同样当没有，不炸', bad.ready is False and not bad.headline)
bad.write({'recipe': _json.dumps(mc.clean({
    'bg': 'indigo', 'motifs': ['axes'], 'headline': '<script>alert(2)</script>',
    'sub': '', 'badge': '昨天'}), ensure_ascii=False)})
check('带尖括号的概括仍算"有 AI 那一张"（转义要在页面上验，HTTP 那半边负责）',
      bad.ready and '<script>' in bad.headline)
# 那一天得有题可列，HTTP 那半边才验得出"一张图 + 一列题"的排版
m_yday = Mistake.create({'student_id': student.id, 'workbook_id': book.id, 'date': yday,
                         'difficulty': '4', 'page': '31', 'question_no': '8'})
# 再留一个"有题、但一次回顾都没做过"的日子：HTTP 那半边要验退让封面 + 点生成不 500
day2 = yday - timedelta(days=1)
Mistake.create({'student_id': student.id, 'workbook_id': book.id, 'date': day2,
                'difficulty': '5', 'page': '7', 'question_no': '2'})

try:
    with env.cr.savepoint():
        Digest.create({'student_id': student.id, 'date': today_d})
    check('同一天再建一张会被 SQL 判重拦下（一天一张是这版的全部意义）', False)
except Exception:
    check('同一天再建一张会被 SQL 判重拦下（一天一张是这版的全部意义）', True)

facts = Digest._day_facts(student, today_d, day_set)
check('喂给模型的是"一天的账目"而不是一题一段',
      '这一天一共' in facts and '日期：%s' % today_d in facts, facts[:60])
check('逐条事实里带着每道题已有的文字', ('出处：' in facts or '出处：没填' in facts))
_old_limit = dmod.DAY_ITEM_LIMIT
dmod.DAY_ITEM_LIMIT = 2
try:
    cut = Digest._day_facts(student, today_d, day_set)
finally:
    dmod.DAY_ITEM_LIMIT = _old_limit
check('超过上限的条数只算进分布、不逐条展开（说在明面上）',
      '没展开' in cut and cut.count('知识点：') == 2 and len(day_set) > 2,
      '展开 %d 条 / 共 %d 条' % (cut.count('知识点：'), len(day_set)))

digest_b = Digest.create({'student_id': student_b.id, 'date': today_d,
                          'recipe': _json.dumps(mc.clean({'bg': 'ink', 'headline': '别人的回顾'}))})
check('别人的那份回顾：A 按记录规则搜不到',
      not Digest.with_user(user_a).search([('id', '=', digest_b.id)]))
check('别人的那份回顾：A 连读都过不了',
      digest_b.with_user(user_a).has_access('read') is False)
check('自己那份回顾：A 读得到', bool(digest.with_user(user_a).search([('id', '=', digest.id)])))
check('自己那份回顾：A 写得了（做回顾就是写这一行）',
      digest.with_user(user_a).has_access('write'))
check('门户对回顾只读/改，不给删（unlink 不在 ACL 里）',
      Digest.with_user(user_a).has_access('unlink') is False)
check('教师能读写删回顾', Digest.has_access('unlink') and Digest.has_access('write'))
check('A 用 for_day 也捞不到别人那张（判据走 search 而不是 browse）',
      not Digest.with_user(user_a).for_day(student_b, today_d))

print('\n== 归档（软删）与真删的边界 ==')
hot.write({'active': False})
check('归档后默认 search 捞不到', not Mistake.search([('id', '=', hot.id)]))
check('域里显式写 active 就能捞到（ORM 便不再补隐含过滤）',
      bool(Mistake.search([('id', '=', hot.id), ('active', '=', False)])))
check('带 active_test=False 也捞得到（详情页那条路靠这个）',
      bool(Mistake.with_context(active_test=False).search([('id', '=', hot.id)])))
check('归档的行仍读得到——它是降级不是销毁',
      bool(hot.with_context(active_test=False).exists()))
check('归档那道不计入"在用"的计数',
      Mistake.search_count([('id', 'in', batch.ids), ('active', '=', True)]) == len(batch) - 1)
hot.write({'active': True})
check('放回后默认视野里又有了', bool(Mistake.search([('id', '=', hot.id)])))
check('门户账号能删自己那条', hot.with_user(user_a).has_access('unlink'))
check('门户账号删不动别人那条',
      not mistake_b.with_user(user_a).search([('id', '=', mistake_b.id)]))

# 提交给下一段 HTTP 渲染检查用（同一个一次性库、同一批数据）
env.cr.commit()
import json
import os

import odoo.addons.tutoring_center as _pkg
# shell 里 odoo.__file__ 是 None；模块包路径就是 <仓库根>/server/addons/tutoring_center
_root = os.path.dirname(os.path.dirname(os.path.dirname(_pkg.__path__[0])))
_ids = {'own': hot.id, 'foreign': mistake_b.id, 'm_pdf': m_pdf.id,
        'm_ai': m_ai.id, 'm_junk': m_junk.id, 'm_nobook': m_nobook.id,
        'm_hidden': m_hidden.id,
        # 每日回顾：today_d 已有一张好配方（重做要能证明"没成也不毁图"）、
        # yday 带尖括号配方（转义）、day2 有题但从没做过回顾（退让封面 + 点生成）
        'today': str(today_d), 'yday': str(yday), 'day2': str(day2),
        'digest': digest.id, 'digest_foreign': digest_b.id,
        'day_count': len(day_set)}
_path = os.path.join(_root, 'dev', 'zz_mistake_lab_ids.json')
with open(_path, 'w', encoding='utf-8') as fh:
    json.dump(_ids, fh)
print('  已提交：门户账号 zz_lab_a / 口令 zz-lab-pw，错题 %s 条，id 写到 %s：%s'
      % (len(Mistake.search([])), _path, _ids))

cr_pass, cr_fail = ok, fail
print('\n== 结果：%d 过 / %d 不过 ==' % (cr_pass, cr_fail))
if cr_fail:
    print('!!! 有 %d 条不过，别部署' % cr_fail)
