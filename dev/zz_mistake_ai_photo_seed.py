# -*- coding: utf-8 -*-
"""一次性库 zz_ai_photo 的 HTTP 验收备料：建门户账号 + 五种素材形态，写 id 清单。

用法：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \\
        -c odoo.conf -d zz_ai_photo --no-http < ../dev/zz_mistake_ai_photo_seed.py

这一份会 **commit**（跟 zz_mistake_ai_photo_check.py 相反：那个只 rollback），
因为 HTTP 那边是另一个进程、另一个游标，看不见没提交的东西。
"""
import base64
import io
import json
import os

from PIL import Image

from odoo import fields

Student = env['tutoring.student']
Workbook = env['tutoring.workbook']
Mistake = env['tutoring.mistake']
Item = env['tutoring.library.item']

for st in Student.search([('name', '=like', 'ZZ %')]):
    st.mistake_ids.with_context(active_test=False).unlink()
    st.unlink()
for u in env['res.users'].search([('login', '=like', 'zz_aiphoto%')]):
    u.unlink()
Workbook.search([('name', '=like', 'ZZ %')]).unlink()
Item.search([('name', '=like', 'ZZ %')]).unlink()


def png_b64(w, h):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (245, 240, 225)).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


def blank_pdf_b64():
    from PyPDF2 import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return base64.b64encode(out.getvalue()).decode()


student = Student.create({'name': 'ZZ 门户学生', 'grade': '07'})
user = env['res.users'].create({
    'name': 'ZZ 门户', 'login': 'zz_aiphoto_p', 'password': 'zz-aiphoto-pw',
    'partner_id': student.partner_id.id,
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
})
book_blank = Workbook.create({'name': 'ZZ 白页的册子'})
env['tutoring.workbook.file'].create({
    'workbook_id': book_blank.id, 'name': 'ZZ 白页册', 'content': blank_pdf_b64(),
    'page_from': 1, 'page_to': 1})

m_own = Mistake.create({'student_id': student.id, 'difficulty': '3', 'question_no': '1'})
Item.create({'name': 'ZZ 我自己拍的', 'filename': 'own.png', 'content': png_b64(900, 600),
             'category': 'mistake', 'mistake_id': m_own.id, 'user_id': user.id})

# 附件归老师：学生在页面上看不到这条附件，但按钮该不该出现是判据的事（走 sudo）
m_teacher = Mistake.create({'student_id': student.id, 'difficulty': '4', 'question_no': '2'})
Item.create({'name': 'ZZ 老师帮拍的', 'filename': 'teacher.png', 'content': png_b64(800, 500),
             'category': 'mistake', 'mistake_id': m_teacher.id})

m_none = Mistake.create({'student_id': student.id, 'difficulty': '2', 'question_no': '3'})
m_blank = Mistake.create({'student_id': student.id, 'workbook_id': book_blank.id,
                          'page': '1', 'difficulty': '5', 'question_no': '4'})
m_failed = Mistake.create({'student_id': student.id, 'difficulty': '3', 'question_no': '5'})
Item.create({'name': 'ZZ 失败重来的那张', 'filename': 'retry.png', 'content': png_b64(700, 400),
             'category': 'mistake', 'mistake_id': m_failed.id, 'user_id': user.id})
# 上一次没成功过的那道：这次口径改完，它应该重新长出按钮
m_failed.sudo().write({'ai_state': 'failed', 'ai_hint': '这次自动生成没成功，可以再点一次（HTTP 备料写的）'})

out = {'own': m_own.id, 'teacher': m_teacher.id, 'none': m_none.id,
       'blank': m_blank.id, 'failed': m_failed.id,
       'login': user.login, 'today': str(fields.Date.context_today(user))}
# shell 里 exec 没有 __file__，按"从 server/ 目录跑"这一条固定路径写
path = os.path.join(os.getcwd(), os.pardir, 'dev', 'zz_ai_photo_ids.json')
with open(path, 'w', encoding='utf-8') as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
env.cr.commit()
print('备料完成 %s' % out)
