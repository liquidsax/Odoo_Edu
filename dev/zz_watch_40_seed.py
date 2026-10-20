"""zz_watch_40 fixture（只写这个一次性库）。

跑法：
    PYTHONUTF8=1 python\\python.exe server\\odoo-bin shell -c server/odoo.conf -d zz_watch_40 --db-filter '^zz_watch_40$' < dev\\zz_watch_40_seed.py
"""
import datetime
import json
import os

from odoo import fields

OUT = os.path.join(os.getcwd(), '.agent', 'local', 'overnight', 'zz_watch_40_keys.json')


def mk_user(login, name):
    partner = env['res.partner'].create({'name': name})
    user = env['res.users'].with_context(no_reset_password=True).create({
        'name': name,
        'login': login,
        'partner_id': partner.id,
        'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
    })
    return partner, user


pa, ua = mk_user('zz_watch_a', 'Watch 学生A')
pb, ub = mk_user('zz_watch_b', 'Watch 学生B')

sa = env['tutoring.student'].create({'name': 'Watch 测试学生A', 'partner_id': pa.id, 'grade': '07'})
sb = env['tutoring.student'].create({'name': 'Watch 旁观学生B', 'partner_id': pb.id, 'grade': '07'})

t1 = env['tutoring.topic'].create({'name': 'Watch 专题一'})
t2 = env['tutoring.topic'].create({'name': 'Watch 专题二'})

exam = env['tutoring.exam'].create({
    'student_id': sa.id, 'name': 'Watch 测试考试', 'exam_type': 'unit',
    'line_ids': [
        (0, 0, {'topic_id': t1.id, 'score': 80.0, 'full_score': 100.0}),
        (0, 0, {'topic_id': t2.id, 'score': 45.0, 'full_score': 50.0}),
    ],
})
mist = env['tutoring.mistake'].create({
    'student_id': sa.id, 'difficulty': '3', 'note': 'Watch 复习写口验证',
})


def mk_key(user, name):
    exp = fields.Datetime.now() + datetime.timedelta(days=1)
    return env['res.users.apikeys'].with_user(user)._generate(None, name, exp)


out = {
    'exam_id': exam.id,
    'mistake_id': mist.id,
    'student_a': sa.id,
    'student_b': sb.id,
    'keys': {
        'admin': mk_key(env.ref('base.user_admin'), 'zz-watch-admin'),
        'a': mk_key(ua, 'zz-watch-a'),
        'b': mk_key(ub, 'zz-watch-b'),
    },
}
with open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(out, fh, indent=2)
env.cr.commit()
print('SEED_OK exam=%s mistake=%s keys=3' % (exam.id, mist.id))
