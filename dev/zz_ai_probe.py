# -*- coding: utf-8 -*-
"""DeepSeek 视觉输入可行性探针：单页 PDF 能不能直接当 image_url 塞进去。

    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d OdooForDB --no-http < ../dev/zz_ai_probe.py

只打印响应与用量，绝不打印密钥。跑完不会往库里写任何东西（全程 sudo 之外只读）。
"""
import base64
import json
import os
import time

import requests

MISTAKE_ID = int(os.environ.get('AI_PROBE_MISTAKE', '30'))
MODEL = 'deepseek-flash'
BASE_URL = 'https://api.deepseek.com/v1/chat/completions'


def read_key():
    p = os.environ.get('DEEPSEEK_ENV') or 'E:/Odoo/.env'
    if not os.path.exists(p):
        raise SystemExit('找不到 .env：%s' % p)
    for line in open(p, encoding='utf-8'):
        k, _, v = line.partition('=')
        if k.strip().lower() in ('deepseek-api', 'deepseek_api_key', 'deepseek_api'):
            return v.strip().strip('"').strip("'")
    raise SystemExit('.env 里没找到 deepseek-api')


KEY = read_key()
m = env['tutoring.mistake'].sudo().browse(MISTAKE_ID)
file, local, hint = m.workbook_id._locate_page(m.page)
print('目标错题 id=%d 学生=%s 册=%s page=%r 题号=%r' % (
    m.id, m.student_id.name, m.workbook_id.name, m.page, m.question_no))
if not file:
    raise SystemExit('定位不到那一页：%s' % hint)
b64 = env['tutoring.workbook.page']._pdf_for(file, local)
if not b64:
    raise SystemExit('抽页失败')
if isinstance(b64, bytes):      # 命中缓存与现抽的返回形态不一致（一个 str 一个 bytes）
    b64 = b64.decode('ascii')
pdf_bytes = base64.b64decode(b64)
print('单页 PDF：%d 字节（base64 后 %d 字符）' % (len(pdf_bytes), len(b64)))

# 扫描页 = 一页一张内嵌位图，直接取出来用，不必光栅化（零新依赖）
import io
from odoo.tools.pdf import PdfReader
from PIL import Image

pages = PdfReader(io.BytesIO(pdf_bytes)).pages
imgs = list(pages[0].images)
if not imgs:
    raise SystemExit('这一页里没有内嵌位图（可能是矢量页）')
raw_img = imgs[0].data
img = Image.open(io.BytesIO(raw_img))
LONG_SIDE = int(os.environ.get('AI_PROBE_LONG_SIDE', '1600'))
SCALE = os.environ.get('AI_PROBE_SCALE', '1') == '1'
QUALITY = int(os.environ.get('AI_PROBE_QUALITY', '82'))
if SCALE:
    ratio = min(1.0, LONG_SIDE / float(max(img.size)))
    if ratio < 1.0:
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
buf = io.BytesIO()
img.convert('RGB').save(buf, 'JPEG', quality=QUALITY, optimize=True)
img_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
print('内嵌图 %s → 送出去 %s JPEG %d 字节（base64 %d 字符）' % (
    Image.open(io.BytesIO(raw_img)).size, img.size, buf.tell(), len(img_b64)))

# 候选知识点：按这条错题学生的年级取（与门户挑选域同源）
grades = m.student_id.knowledge_grades or [m.student_id.grade]
points = env['tutoring.knowledge.point'].sudo().search(
    [('grade', 'in', [g for g in grades if g])], order='grade, name')
names = [p.full_name for p in points][:200]
print('候选知识点 %d 条（年级 %s）' % (len(names), grades))

SYSTEM = (
    '你是学习记录助手。给你的是教辅书的**其中一页**，以及要在这页里找的一道题的出处。\n'
    '只做三件事：1) 找到这道题并把题目原文抄出来；2) 用不超过 40 个字概括它在问什么；'
    '3) 从候选知识点里挑出这道题真正考的那一个。\n'
    '规则：\n'
    '- 只依据给你的这一页。这一页里没有这道题时，**立刻**只回 {"found": false}，'
    '不要解释、不要猜测、不要输出别的字。\n'
    '- 不要解题、不要讲思路、不要给答案。\n'
    '- 知识点必须从候选列表里逐字选一个，列表里没有就填 null，不要自己造名字。\n'
    '- 只输出一个 JSON 对象，不要 markdown 代码块，不要多余文字。\n'
    '输出字段：{"found": true, "question_text": "题目原文", '
    '"summary": "≤40字摘要", "point": "候选中的知识点原名或 null"}'
)
USER = (
    '出处：《%s》第 %s 页（分册：%s，该分册内第 %d 页），题号：%s。\n'
    '学生年级：%s。当前已填知识点：%s。\n'
    '候选知识点（只能从中选，逐字）：\n%s\n' % (
        m.workbook_id.name, m.page, file.name, local, m.question_no,
        m.student_id.grade, m.point_id.name or '（无）',
        '\n'.join('- ' + n for n in names))
)

payload = {
    'model': MODEL,
    'messages': [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': [
            {'type': 'text', 'text': USER},
            {'type': 'image_url',
             'image_url': {'url': 'data:image/jpeg;base64,' + img_b64,
                           'detail': os.environ.get('AI_PROBE_DETAIL', 'high')}},
        ]},
    ],
    'temperature': 0,
    'max_tokens': 700,
}
THINK = os.environ.get('AI_PROBE_THINKING', 'default')
if THINK != 'default':
    payload['thinking'] = {'type': THINK}      # OpenAI 兼容接口里 extra_body 就是顶层字段
if os.environ.get('AI_PROBE_QUESTION'):        # 故意指一个不存在的题号，验快速回绝
    payload['messages'][1]['content'][0]['text'] = USER.replace(
        m.question_no, os.environ['AI_PROBE_QUESTION'])
print('\n== 探针：detail=%s 长边=%s thinking=%s 题号覆盖=%s ==' % (
    payload['messages'][1]['content'][1]['image_url']['detail'],
    '原图' if not SCALE else LONG_SIDE, THINK, os.environ.get('AI_PROBE_QUESTION') or '—'))
t0 = time.time()
r = requests.post(BASE_URL, headers={'Authorization': 'Bearer ' + KEY}, json=payload, timeout=180)
print('HTTP %s  用时 %.1fs' % (r.status_code, time.time() - t0))
try:
    body = r.json()
except Exception:
    print('非 JSON 响应:', r.text[:400])
    raise SystemExit(1)
if 'error' in body:
    print('API 报错:', json.dumps(body['error'], ensure_ascii=False)[:500])
else:
    ch = body['choices'][0]
    print('finish_reason:', ch.get('finish_reason'))
    print('内容:', (ch['message'].get('content') or '')[:900])
    print('用量:', json.dumps(body.get('usage', {}), ensure_ascii=False))
