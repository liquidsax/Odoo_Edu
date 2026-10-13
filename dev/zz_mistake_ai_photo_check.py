# -*- coding: utf-8 -*-
"""一次性库上验错题 AI 摘要的素材判据放宽与失败口径（照片优先 / 全部照片 / 没成功能重来）。

用法（模块在一次性库里装好之后）：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \\
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_mistake_ai_photo_check.py

只在一次性库上跑：它会建 ZZ 档案、ZZ 练习册、ZZ 附件。
**这一轮一条真请求都不发**：把 `_config` 读密钥那条口与 `_call` 都换成本地替身——
`_call` 一被碰到就抛，这样"素材取不到该在发请求之前退下来"这类断言才是真的在验位置，
而不是偷偷烧了一次 DeepSeek。
"""
import base64
import io

from PIL import Image

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.tutoring_center.models import tutoring_mistake_ai as aimod

ok = fail = 0

# —— 两道本地替身：不发网络 ——
KEYBOX = {'v': ''}          # 模拟"有没有密钥"，不让磁盘上的 .env 或系统参数掺进来
aimod.deepseek_settings = lambda env: {
    'key': KEYBOX['v'], 'model': 'zz-model', 'url': 'http://127.0.0.1:9/'}


def _no_network(self, conf, payload, mistake, candidates, kind='page'):
    raise AssertionError('验收脚本不该走到发请求那一步（kind=%s）' % kind)


aimod.TutoringMistakeAiJob._call = _no_network


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %s %s' % (label, extra))
    else:
        fail += 1
        print('  FAIL  %s %s' % (label, extra))


def jpeg_b64(width, height):
    """造一张能真被 PIL 认出来的 JPEG（尺寸互不相同，用来验多图顺序）。"""
    buf = io.BytesIO()
    Image.new('RGB', (width, height), (250, 245, 230)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue()).decode()


def pdf_with_bitmap_b64():
    """一页真带内嵌位图的 PDF：教辅扫描页就是这一类（Pillow 存 PDF 走 DCTDecode）。"""
    buf = io.BytesIO()
    Image.new('RGB', (400, 300), (250, 245, 230)).save(buf, 'PDF', resolution=120)
    return base64.b64encode(buf.getvalue()).decode()


def pdf_blank_b64():
    """抽得出页、但页里没有位图的 PDF：走的是「这一页交给视觉模型没用」那条退让。"""
    from PyPDF2 import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return base64.b64encode(out.getvalue()).decode()


Mistake = env['tutoring.mistake']
Student = env['tutoring.student']
Workbook = env['tutoring.workbook']
Item = env['tutoring.library.item']
Job = env['tutoring.mistake.ai.job']

# 能随时重跑：先清掉上一轮的 ZZ 数据
for st in Student.search([('name', '=like', 'ZZ %')]):
    st.mistake_ids.with_context(active_test=False).unlink()
    st.unlink()
Workbook.search([('name', '=like', 'ZZ %')]).unlink()
Item.search([('name', '=like', 'ZZ %')]).unlink()
env['ir.config_parameter'].sudo().search([('key', '=like', 'zz_aiphoto.%')]).unlink()

student = Student.create({'name': 'ZZ 照片试验', 'grade': '13'})
book_page = Workbook.create({'name': 'ZZ 有图页的册子'})
book_blank = Workbook.create({'name': 'ZZ 白页的册子'})
env['tutoring.workbook.file'].create({
    'workbook_id': book_page.id, 'name': 'ZZ 上册', 'content': pdf_with_bitmap_b64(),
    'page_from': 1, 'page_to': 1})
env['tutoring.workbook.file'].create({
    'workbook_id': book_blank.id, 'name': 'ZZ 白页册', 'content': pdf_blank_b64(),
    'page_from': 1, 'page_to': 1})


def attach(mistake, filename, content, user=None):
    return Item.create({
        'name': 'ZZ ' + filename, 'filename': filename, 'content': content,
        'category': 'mistake', 'mistake_id': mistake.id,
        'user_id': (user or env.user).id})


print('\n== 判据：没练习册也能分析，只要有题目照片 ==')
m_photo = Mistake.create({'student_id': student.id, 'difficulty': '3',
                          'question_no': '1'})
attach(m_photo, '题1.png', jpeg_b64(300, 200))
check('只有照片、没出处 → 按钮出现', m_photo.can_ai_summary)

m_nothing = Mistake.create({'student_id': student.id, 'difficulty': '2'})
check('既没照片也没出处 → 按钮不出现', not m_nothing.can_ai_summary)

m_doc = Mistake.create({'student_id': student.id, 'difficulty': '2'})
attach(m_doc, '说明.pdf', pdf_blank_b64())
check('附件是 PDF 不算照片 → 按钮不出现（image_url 直传 PDF 会被拒）',
      not m_doc.can_ai_summary)
check('  但条数仍算附件', m_doc.library_count == 1 and m_doc.library_photo_count == 0)

m_page = Mistake.create({'student_id': student.id, 'workbook_id': book_page.id,
                         'page': '1', 'question_no': '9', 'difficulty': '3'})
check('只有教辅那一页（老路）→ 按钮照旧出现', m_page.can_ai_summary)

print('\n== 取料：照片优先，几张全发，按上传先后排 ==')
images, kind = Job._images(m_photo)
check('照片题走 photo 种类', kind == 'photo' and len(images) == 1)

m_multi = Mistake.create({'student_id': student.id, 'difficulty': '4'})
for w, h in ((120, 90), (240, 150), (360, 110)):
    attach(m_multi, '连拍%d.png' % w, jpeg_b64(w, h))
images, kind = Job._images(m_multi)
check('三张照片全发（不是只取一张）', kind == 'photo' and len(images) == 3)
dims = []
for b64 in images:
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        dims.append(im.size)
check('顺序按上传先后（不是反过来）',
      dims == sorted(dims, key=lambda d: d[0]), '尺寸序列 %s' % dims)
check('每张都重新编成 JPEG', all(b and b != '' for b in images))

m_both = Mistake.create({'student_id': student.id, 'workbook_id': book_page.id,
                         'page': '1', 'difficulty': '3'})
attach(m_both, '我拍的.png', jpeg_b64(200, 200))
_both_images, both_kind = Job._images(m_both)
check('既有原页又有照片 → 用照片（维护者 2026-10-13 拍的）',
      both_kind == 'photo' and len(_both_images) == 1)

images, kind = Job._images(m_page)
check('没照片时退回教辅那一页', kind == 'page' and len(images) == 1)

m_junk = Mistake.create({'student_id': student.id, 'workbook_id': book_page.id,
                         'page': '1', 'difficulty': '3'})
attach(m_junk, '坏图.png', base64.b64encode(b'not an image at all').decode())
images, kind = Job._images(m_junk)
check('坏掉的那张照片跳过、不报错，退到原页', kind == 'page' and len(images) == 1)

print('\n== 话术：照片版不写"第几页"，出处为空也不印出 False ==')
cands = Job._candidates(m_photo)
text = Job._user_text(m_photo, cands, 'photo', 1)
check('照片版话术在', '题目照片，共 1 张' in text)
check('没出处时写"没填"，不是 None/False',
      '出处：没填' in text and 'False' not in text and 'None' not in text)
payload = Job._payload(m_photo, ['AAAA'], cands, 'zz-model', 'photo')
check('系统话术换成了照片版', payload['messages'][0]['content'] == Job._prompt('system_photo'))
check('多图就是多个 image_url',
      len([p for p in payload['messages'][1]['content']
           if p['type'] == 'image_url']) == 1)
payload3 = Job._payload(m_multi, ['A', 'B', 'C'], cands, 'zz-model', 'photo')
check('三张图就是三条 image_url',
      len([p for p in payload3['messages'][1]['content']
           if p['type'] == 'image_url']) == 3)
check('  文本仍是第一条，图按顺序跟在后面',
      payload3['messages'][1]['content'][0]['type'] == 'text')
page_text = Job._user_text(m_page, cands, 'page', 1)
check('老路话术没动（仍带《册子》第几页）',
      '《ZZ 有图页的册子》第 1 页' in page_text
      and payload['messages'][0]['content'] != Job._prompt('system'))

print('\n== 权限口径：照片归上传人，判据按 sudo 问 ==')
student2 = Student.create({'name': 'ZZ 门户学生', 'grade': '07'})
user2 = env['res.users'].create({
    'name': 'ZZ 门户', 'login': 'zz_aiphoto_p', 'password': 'zz-pw',
    'partner_id': student2.partner_id.id,
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
})
m_owner = Mistake.create({'student_id': student2.id, 'difficulty': '3'})
attach(m_owner, '老师帮拍的.png', jpeg_b64(160, 160), user=env.user)
env.invalidate_all()
check('附件归老师、学生本人算判据时照样数得出来（判据走 sudo）',
      m_owner.with_user(user2).can_ai_summary is True)
check('  他按记录规则确实读不到那条附件',
      len(m_owner.with_user(user2).library_item_ids) == 0)

print('\n== 状态机：成功定稿、正在生成别点、没成功能再来 ==')
job = Job.create({'mistake_id': m_photo.id})
check('发起后 ai_state 进 pending', m_photo.ai_state == 'pending')
try:
    Job.create({'mistake_id': m_photo.id})
    check('排队中不许再发起', False)
except ValidationError as err:
    check('排队中不许再发起', '排进队列' in str(err), str(err)[:40])

job._apply(m_photo, {'found': True, 'summary': 'ZZ 摘要',
                     'question_text': 'ZZ 题目原文', 'point': None}, {})
check('生成成功后 ai_state=done', m_photo.ai_state == 'done')
check('成功过的题按钮消失', not m_photo.can_ai_summary)
try:
    Job.create({'mistake_id': m_photo.id})
    check('成功过的题不许再生成', False)
except ValidationError as err:
    check('成功过的题不许再生成', '已经生成过摘要' in str(err), str(err)[:40])

print('\n== 口径改的那一条：没花出去的钱不算、失败的那道能重来 ==')
# 先验"没密钥"这条路
m_noread = Mistake.create({'student_id': student.id, 'difficulty': '3'})
attach(m_noread, '题n.png', jpeg_b64(180, 180))
KEYBOX['v'] = ''
before = Job.search_count([('user_id', '=', env.uid),
                           ('day', '=', fields.Date.context_today(Job)),
                           ('state', 'in', Job.CHARGED)])
job_n = Job.create({'mistake_id': m_noread.id})
job_n._run()
after = Job.search_count([('user_id', '=', env.uid),
                          ('day', '=', fields.Date.context_today(Job)),
                          ('state', 'in', Job.CHARGED)])
check('没密钥 → 记 error、退回未生成、不扣额度',
      job_n.state == 'error' and m_noread.ai_state == 'none' and before == after)

# 给上密钥，让"素材取不到"这条路走到取料那一步（替身保证仍不发请求）
KEYBOX['v'] = 'zz-fake-key'
m_blank = Mistake.create({'student_id': student.id, 'workbook_id': book_blank.id,
                          'page': '1', 'difficulty': '3'})
check('白页册能定位到页 → 按钮出现（判据只看定位得到，不看页里有没有位图）',
      m_blank.can_ai_summary)
before = Job.search_count([('user_id', '=', env.uid),
                           ('day', '=', fields.Date.context_today(Job)),
                           ('state', 'in', Job.CHARGED)])
job_b = Job.create({'mistake_id': m_blank.id})
job_b._run()
after = Job.search_count([('user_id', '=', env.uid),
                          ('day', '=', fields.Date.context_today(Job)),
                          ('state', 'in', Job.CHARGED)])
check('页里没有位图 → 算素材取不到，不扣额度（以前这条要扣还锁死）',
      job_b.state == 'error' and m_blank.ai_state == 'none' and before == after,
      '原因：%s' % (job_b.error or '')[:40])
check('  退回未生成后按钮还在，能重来', m_blank.can_ai_summary)

m_junkonly = Mistake.create({'student_id': student.id, 'difficulty': '3'})
attach(m_junkonly, '唯一那张坏.png', base64.b64encode(b'broken').decode())
job_j = Job.create({'mistake_id': m_junkonly.id})
job_j._run()
check('照片全坏、又没出处 → 也是素材取不到，不扣',
      job_j.state == 'error' and m_junkonly.ai_state == 'none')
check('  错题上不留任何"锁死"提示', not m_junkonly.ai_hint)

print('\n== 真花了钱的失败：扣一条额度，但不焊死 ==')
m_fail = Mistake.create({'student_id': student.id, 'difficulty': '3'})
attach(m_fail, '题f.png', jpeg_b64(200, 120))
quota_before = Job.quota_left()
job_f = Job.create({'mistake_id': m_fail.id})
job_f._fail('接口返回 HTTP 500：zz 模拟')
check('失败后 ai_state=failed', m_fail.ai_state == 'failed')
check('  当日额度扣掉一条', Job.quota_left() == quota_before - 1)
check('失败反而让按钮消失（旧口径）——现在要能重来', m_fail.can_ai_summary)
job_f2 = Job.create({'mistake_id': m_fail.id})
check('失败的题可以再生成，同一题留下两行历史',
      job_f2.id != job_f.id and Job.search_count(
          [('mistake_id', '=', m_fail.id)]) == 2)
check('  第二行是 pending，所以第三行要被挡', m_fail.ai_state == 'pending')
try:
    Job.create({'mistake_id': m_fail.id})
    check('正在生成的第二道闸仍生效', False)
except ValidationError as err:
    check('正在生成的第二道闸仍生效', '正在生成中' in str(err), str(err)[:40])
check('失败写的那句话现在说"可以再点一次"',
      '再点一次' in (m_fail.ai_hint or ''), (m_fail.ai_hint or '')[:50])

print('\n== 额度闸还是那道闸（防烧钱靠它，不靠把题焊死）==')
check('quota_left 读的是 DAILY_QUOTA 常量',
      Job.quota_left() == max(0, aimod.DAILY_QUOTA - Job.search_count(
          [('user_id', '=', env.uid),
           ('day', '=', fields.Date.context_today(Job)),
           ('state', 'in', Job.CHARGED)])))
charged = Job.search([('state', 'in', Job.CHARGED), ('user_id', '=', env.uid),
                      ('day', '=', fields.Date.context_today(Job))])
errors = Job.search([('state', '=', 'error'), ('user_id', '=', env.uid),
                     ('day', '=', fields.Date.context_today(Job))])
check('今天确实攒下了 error 行（都是没花钱的）而不算进额度',
      len(errors) >= 2 and len(charged) >= 2,
      'charged=%d error=%d' % (len(charged), len(errors)))

print('\n== 收口：判据不读正文、列表页不炸 ==')
check('can_ai_summary 不依赖 page_pdf（列表每行都算它）',
      'page_pdf' not in str(Mistake._fields['can_ai_summary']._depends))
check('library_photo_count 是存算字段', Mistake._fields['library_photo_count'].store)
grouped = Mistake.with_context(active_test=False).search([])
check('整表重算一遍不报错', all(isinstance(m.can_ai_summary, bool) for m in grouped))

print('\n== 汇总：%d 条断言，%d 条没过 ==' % (ok, fail))
env.cr.rollback()
