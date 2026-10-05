# -*- coding: utf-8 -*-
"""一次性库上验「别人的本人档案 + 其名下错题」收口。

用法（模块已装好后）：
    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_selfprofile_check.py

只在一次性库上跑，别打业务库——它会建两个老师账号。
"""
from odoo import SUPERUSER_ID, _
from odoo.exceptions import AccessError

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %s %s' % (label, extra))
    else:
        fail += 1
        print('  FAIL  %s %s' % (label, extra))


Teacher = env['res.users']
Student = env['tutoring.student']
Mistake = env['tutoring.mistake']
g_user = env.ref('base.group_user')
g_teacher = env.ref('tutoring_center.group_teacher')


def mk_teacher(login):
    return Teacher.sudo().create({
        'name': login, 'login': login, 'email': '%s@example.invalid' % login,
        'password': login + '-pw',
        'group_ids': [(4, g_user.id), (4, g_teacher.id)],
    })


a = mk_teacher('zz_teacher_a')
b = mk_teacher('zz_teacher_b')
real = Student.sudo().create({'name': 'ZZ 真实学生', 'grade': '07'})
print('\n== 建档 ==')
pa = Student.sudo().search([('partner_id', '=', a.partner_id.id)], limit=1)
pb = Student.sudo().search([('partner_id', '=', b.partner_id.id)], limit=1)
check('A/B 各有一条本人档案', bool(pa and pb))
check('新建时就带 is_self_profile 标记', pa.is_self_profile and pb.is_self_profile)
check('真实学生不带标记', not real.is_self_profile)

print('\n== 学生可见性（以 A 的身份）==')
seen_a = Student.with_user(a).search([])
check('A 看得到自己的本人档案', pa in seen_a)
check('A 看不到 B 的本人档案', pb not in seen_a)
check('A 看得到真实学生', real in seen_a)
check('A 的学生列表里没有成对的「我自己」',
      len(seen_a.filtered(lambda s: s.name == '我自己')) == 1,
      '-> %s' % seen_a.mapped('name'))

print('\n== 错题可见性 ==')
wb = env['tutoring.workbook'].sudo().create({'name': 'ZZ 练习册'})
mb = Mistake.sudo().create({'student_id': pb.id, 'workbook_id': wb.id})
ma = Mistake.sudo().create({'student_id': real.id, 'workbook_id': wb.id})
check('B 本人档案下的错题，A 读不到',
      Mistake.with_user(a).search_count([('id', '=', mb.id)]) == 0)
check('B 自己读得到', Mistake.with_user(b).search_count([('id', '=', mb.id)]) == 1)
check('真实学生的错题全体教师可见',
      Mistake.with_user(a).search_count([('id', '=', ma.id)]) == 1
      and Mistake.with_user(b).search_count([('id', '=', ma.id)]) == 1)
try:
    Mistake.with_user(a).create({'student_id': pb.id, 'workbook_id': wb.id})
    check('A 不能往 B 的私人档案里记题', False, '竟然建成了')
except AccessError:
    check('A 不能往 B 的私人档案里记题（AccessError）', True)
except Exception as e:  # noqa: BLE001
    check('A 不能往 B 的私人档案里记题', False, '异常类型 %s' % type(e).__name__)
check('A 能给真实学生记题', bool(Mistake.with_user(a).create({'student_id': real.id, 'workbook_id': wb.id})))
grouped = Mistake.with_user(a).read_group([], ['student_id'], groupby=['student_id'])
check('错题看板按学生分组时不含 B 的档案',
      pb.id not in [r['student_id'][0] for r in grouped if r['student_id']])

print('\n== 门户学生不受影响 ==')
portal_student_user = Teacher.sudo().create({
    'name': 'zz_pupil', 'login': 'zz_pupil', 'email': 'zz_pupil@example.invalid',
    'password': 'zz-pupil-pw',
    'group_ids': [(4, env.ref('base.group_portal').id)],
})
pupil = Student.sudo().create({'name': 'ZZ 学生', 'grade': '08',
                               'partner_id': portal_student_user.partner_id.id})
mp = Mistake.sudo().create({'student_id': pupil.id, 'workbook_id': wb.id})
check('门户学生只看到自己那份档案',
      Student.with_user(portal_student_user).search([]) == pupil)
check('门户学生只看到自己的错题',
      Mistake.with_user(portal_student_user).search_count([('id', '=', mp.id)]) == 1)
check('老师仍看得到门户学生的错题',
      Mistake.with_user(a).search_count([('id', '=', mp.id)]) == 1)

print('\n== 补标函数判据 ==')
lookalike = Student.sudo().create({'name': Student.SELF_PROFILE_NAME, 'grade': '07'})
made = Student.sudo().mark_self_profiles()
check('手工建的同名学生没被误标', not lookalike.is_self_profile)
check('补标函数幂等（再跑一次补 0 条）', made == 0, '本次补了 %d 条' % made)
check('A/B 的档案仍是已标状态', pa.is_self_profile and pb.is_self_profile)

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
