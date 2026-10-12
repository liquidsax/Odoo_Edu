# -*- coding: utf-8 -*-
"""探针：门户错题的排期到底是几点，写进去和读出来差在哪。

用法：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_mistake_probe.py
"""
from datetime import timedelta

from odoo import fields

Mistake = env['tutoring.mistake']
Student = env['tutoring.student']
Workbook = env['tutoring.workbook']

student = Student.create({'name': 'ZZ 探针', 'grade': '07'})
book = Workbook.create({'name': 'ZZ 探针册'})
rec = Mistake.create({'student_id': student.id, 'workbook_id': book.id, 'difficulty': '3'})

script_now = fields.Datetime.now()
target = script_now + timedelta(days=5)
print('env.context.get(tz)      =', repr(env.context.get('tz')))
print('env.user.tz              =', repr(env.user.tz))
print('script_now (UTC)         =', script_now.isoformat(sep=' ', timespec='seconds'))
print('要写入的目标             =', target.isoformat(sep=' ', timespec='seconds'))

rec.write({'next_review_at': target})
env.flush_all()

env.cr.execute('SELECT next_review_at FROM tutoring_mistake WHERE id=%s', (rec.id,))
raw = env.cr.fetchone()[0]
read_back = rec.next_review_at
rec.invalidate_recordset(['next_review_at'])
read_fresh = rec.next_review_at

print('库里原始列值             =', raw)
print('write 后缓存读回         =', read_back)
print('失效后重读               =', read_fresh)
print('原始 − 目标 (小时)       = %.3f' % ((raw - target).total_seconds() / 3600.0))

compute_now = fields.Datetime.now()
delta_seconds = (read_fresh - compute_now).total_seconds()
print('计算用的 now             =', compute_now.isoformat(sep=' ', timespec='seconds'))
print('剩余秒数                 = %.3f  （5 天整 = 432000）' % delta_seconds)
print('//86400 得 %s → 我给的 N = %d'
      % (delta_seconds // 86400, int(delta_seconds // 86400) + 1))
print('portal_heat_note         =', rec.portal_heat_note)
print('按日历天算               =', (read_fresh.date() - compute_now.date()).days)

print('\n== 带用户时区的那一路（生产里门户请求都带 tz）==')
sh = rec.with_context(tz='Asia/Shanghai')
target2 = fields.Datetime.now() + timedelta(days=5)
sh.write({'next_review_at': target2})
env.flush_all()
env.cr.execute('SELECT next_review_at FROM tutoring_mistake WHERE id=%s', (rec.id,))
raw2 = env.cr.fetchone()[0]
rec.invalidate_recordset(['next_review_at'])
print('带 tz 写入的目标 (UTC 语义) =', target2)
print('库里原始列值               =', raw2)
print('库里 − 目标 (小时)         = %.3f' % ((raw2 - target2).total_seconds() / 3600.0))
print('带 tz 读回                 =', sh.next_review_at)
print('不带 tz 读回               =', rec.next_review_at)
