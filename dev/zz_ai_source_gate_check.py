# -*- coding: utf-8 -*-
"""一次性库上验 19.0.1.34.3：照片改认文件头、没后缀也能走完全程、中止必须在题上留原因。

用法（模块在一次性库里装好之后）：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \\
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_ai_source_gate_check.py

只在一次性库上跑：它会建 ZZ 档案、ZZ 练习册、ZZ 附件，收尾回滚。
**这一轮一条真请求都不发**：`_call` 换成本地替身，一被碰到就抛——所以"该在发请求之前
退下来"那几条断言验的是位置，不是偷偷烧了一次 DeepSeek。
"""
import base64
import io

from PIL import Image

from odoo import fields

from odoo.addons.tutoring_center.models import tutoring_mistake_ai as aimod
from odoo.addons.tutoring_center.models.tutoring_library_item import (
    b64_head, sniff_image_mimetype)

ok = fail = 0

KEYBOX = {'v': 'zz-fake-key'}
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


def png_b64(width=320, height=200):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), (240, 240, 250)).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


def head_b64(prefix, pad=64):
    """只保证文件头对、后面塞零：验"认文件头"这一步不需要一张真图。"""
    return base64.b64encode(prefix + b'\x00' * pad).decode()


def pdf_blank_b64():
    """抽得出页、但页里没有位图的 PDF。"""
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

for st in Student.search([('name', '=like', 'ZZ %')]):
    st.mistake_ids.with_context(active_test=False).unlink()
    st.unlink()
Item.search([('name', '=like', 'ZZ %')]).unlink()

student = Student.create({'name': 'ZZ 取料试验', 'grade': '13'})
book_blank = Workbook.create({'name': 'ZZ 白页的册子'})
env['tutoring.workbook.file'].create({
    'workbook_id': book_blank.id, 'name': 'ZZ 白页册', 'content': pdf_blank_b64(),
    'page_from': 1, 'page_to': 1})


def attach(mistake, filename, content):
    return Item.create({
        'name': 'ZZ ' + filename, 'filename': filename, 'content': content,
        'category': 'mistake', 'mistake_id': mistake.id, 'user_id': env.user.id})


print('\n== 文件头嗅探：扩展名说不出话的时候 ==')
cases = [
    ('IMG_1234', b'\x89PNG\r\n\x1a\n', 'image', 'image/png'),
    ('photo', b'\xff\xd8\xff', 'image', 'image/jpeg'),
    ('clip', b'GIF89a', 'image', 'image/gif'),
    ('snap', b'BM\x00\x00', 'image', 'image/bmp'),
    ('still', b'RIFF\x00\x00\x00\x00WEBP', 'image', 'image/webp'),
    ('sound', b'RIFF\x00\x00\x00\x00WAVE', 'other', 'application/octet-stream'),
    ('pack', b'PK\x03\x04', 'other', 'application/octet-stream'),
]
for name, magic, want_kind, want_mime in cases:
    m = Mistake.create({'student_id': student.id, 'difficulty': '2'})
    item = attach(m, name, head_b64(magic))
    check('「%s」判成 %s' % (name, want_kind),
          item.kind == want_kind and item.mimetype == want_mime,
          'kind=%s mimetype=%s' % (item.kind, item.mimetype))
    m.unlink()

m_empty = Mistake.create({'student_id': student.id, 'difficulty': '2'})
item_empty = attach(m_empty, 'no_content', '')
check('空正文不炸、判成 other', item_empty.kind == 'other' and item_empty.file_size == 0)
m_empty.unlink()

m_ext = Mistake.create({'student_id': student.id, 'difficulty': '2'})
item_ext = attach(m_ext, 'a.pdf', head_b64(b'\xff\xd8\xff'))
check('扩展名说得出话时仍以它为准（.pdf 装着 JPEG 头也判 pdf，交不出去由取料那关说）',
      item_ext.kind == 'pdf')
m_ext.unlink()

check('b64_head 只解开头一小截（够认头就行，不整份解码）',
      b64_head(head_b64(b'ABCDE'), num=16).startswith(b'ABCDE')
      and len(b64_head(png_b64(), num=16)) <= 24)
check('b64_head 对短正文给得出多少解多少',
      b64_head(base64.b64encode(b'AB').decode(), num=16) == b'AB'
      and b64_head('', num=16) == b'')
check('sniff 认不出来的开头给 False', sniff_image_mimetype(b'hello worl') is False)

print('\n== 没后缀的照片现在能走完全程（34.2 之前这条是断的）==')
m_nosuffix = Mistake.create({'student_id': student.id, 'difficulty': '3'})
attach(m_nosuffix, 'IMG_0001', png_b64())
check('无后缀照片的条目 kind=image', m_nosuffix.library_item_ids.kind == 'image')
check('  计进题目照片数', m_nosuffix.library_photo_count == 1)
check('  没填练习册、没填页码、没填题号 → 按钮出现', m_nosuffix.can_ai_summary)
images, kind = Job._images(m_nosuffix)
check('取料取到 1 张、种类走 photo', kind == 'photo' and len(images) == 1,
      'n=%d kind=%s' % (len(images), kind))
user_text = Job._user_text(m_nosuffix, Job._candidates(m_nosuffix), kind, len(images))
check('话术里没出处就写「没填」，不印 False', 'False' not in user_text and '没填' in user_text)
check('候选知识点为空时话术照样成形（不抛）',
      '%(points)s' not in Job._user_text(m_nosuffix, {}, 'photo', 1))

print('\n== 中止必须在题上留原因（抹成空就等于"没响应"）==')
KEYBOX['v'] = ''
job = Job.create({'mistake_id': m_nosuffix.id})
job._run()
check('没密钥 → job 记 error、题退回未生成',
      job.state == 'error' and m_nosuffix.ai_state == 'none')
check('  题上写着原因，且说的是密钥',
      bool(m_nosuffix.ai_hint) and '密钥' in m_nosuffix.ai_hint,
      (m_nosuffix.ai_hint or '')[:70])
check('  句话说清没扣额度', '没扣额度' in (m_nosuffix.ai_hint or ''))
check('  旧的那句"不再重复生成"不许回来',
      '不再重复生成' not in (m_nosuffix.ai_hint or ''))
KEYBOX['v'] = 'zz-fake-key'
Job.search([('mistake_id', '=', m_nosuffix.id), ('state', '=', 'error')]).unlink()

m_blank = Mistake.create({'student_id': student.id, 'workbook_id': book_blank.id,
                          'page': '1', 'difficulty': '3'})
charged_before = Job.search_count([
    ('user_id', '=', env.uid), ('day', '=', fields.Date.context_today(Job)),
    ('state', 'in', Job.CHARGED)])
job_b = Job.create({'mistake_id': m_blank.id})
job_b._run()
charged_after = Job.search_count([
    ('user_id', '=', env.uid), ('day', '=', fields.Date.context_today(Job)),
    ('state', 'in', Job.CHARGED)])
check('白页册：定位得到页但页里没位图 → 中止、不扣额度',
      job_b.state == 'error' and m_blank.ai_state == 'none' and charged_before == charged_after)
check('  原因里写着是哪一本哪一页',
      'ZZ 白页的册子' in (m_blank.ai_hint or '') and '1' in (m_blank.ai_hint or ''),
      (m_blank.ai_hint or '')[:90])
check('  并且给出去路：传一张题目照片',
      '传一张题目照片' in (m_blank.ai_hint or ''))
check('  按钮还在，能再来一次', m_blank.can_ai_summary)

m_junk = Mistake.create({'student_id': student.id, 'difficulty': '3'})
attach(m_junk, '唯一那张坏.png', base64.b64encode(b'broken').decode())
job_j = Job.create({'mistake_id': m_junk.id})
job_j._run()
check('照片坏到读不出来、又没出处 → 也留原因',
      job_j.state == 'error' and bool(m_junk.ai_hint), (m_junk.ai_hint or '')[:70])

print('\n== 门户那条分支与整表重算 ==')
arch = env.ref('tutoring_center.portal_my_learning_mistake_detail').arch
check('详情页有「未生成但写着原因」这一档',
      "ai_state == 'none' and mistake.ai_hint" in arch)
check('整表重算 can_ai_summary 不报错',
      all(isinstance(m.can_ai_summary, bool) for m in Mistake.search([])))

print('\n== 汇总：%d 条断言，%d 条没过 ==' % (ok, fail))
env.cr.rollback()
