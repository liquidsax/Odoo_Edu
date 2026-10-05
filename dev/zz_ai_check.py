# -*- coding: utf-8 -*-
"""一次性库上验 AI 摘要的数据层（不联网：走的是"没密钥"与"页里没位图"两条失败路径）。

    cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d <一次性库> --no-http < ../dev/zz_ai_check.py

只建测试数据，不 commit，进程退出即回滚。
"""
import base64
import io
import os
import time

from odoo.exceptions import ValidationError

# cron 里是"一条任务一提交"（生产上对），所以本脚本建的数据会真留在库里；
# 每次跑用一个新的标记，免得撞登录名。反正这库验完就删。
TAG = os.environ.get('ZZ_TAG') or str(int(time.time()))[-6:]

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print('  %s  %s %s' % ('PASS' if cond else 'FAIL', label, extra if not cond else ''))


Job = env['tutoring.mistake.ai.job']
Mistake = env['tutoring.mistake']
g_user, g_teacher = env.ref('base.group_user'), env.ref('tutoring_center.group_teacher')


def mk_user(login, groups, partner=None):
    return env['res.users'].sudo().create({
        'name': login, 'login': login, 'email': '%s@example.invalid' % login,
        'password': login + '-pw',
        'partner_id': partner.id if partner else False,
        'group_ids': [(4, g.id) for g in groups],
    })


teacher = mk_user('zz_ai_t_%s' % TAG, [g_user, g_teacher])
pupil = mk_user('zz_ai_p_%s' % TAG, [env.ref('base.group_portal')])
stu_own = env['tutoring.student'].sudo().create({'name': 'ZZ 我的学生 %s' % TAG, 'grade': '13'})
stu_other = env['tutoring.student'].sudo().create(
    {'name': 'ZZ 别人的学生 %s' % TAG, 'grade': '13', 'partner_id': pupil.partner_id.id})

# 一页空白 PDF（没有内嵌位图）：够用来验"定位得到页 → 建任务 → 资料侧失败"整条链
from odoo.tools.pdf import PdfWriter
buf = io.BytesIO()
w = PdfWriter()
w.add_blank_page(width=200, height=200)
w.write(buf)
blank_pdf = base64.b64encode(buf.getvalue()).decode()

wb = env['tutoring.workbook'].sudo().create({'name': 'ZZ AI 用练习册 %s' % TAG})
env['tutoring.workbook.file'].sudo().create({
    'name': 'ZZ 空白教材', 'workbook_id': wb.id,
    'content': blank_pdf, 'filename': 'blank.pdf', 'page_from': 1, 'page_to': 1,
    'user_id': teacher.id,
})


def mk_mistake(no, student=None):
    return Mistake.sudo().create({
        'student_id': (student or stu_own).id, 'workbook_id': wb.id,
        'page': '1', 'question_no': no,
    })


print('\n== 装完的样子 ==')
cron = env.ref('tutoring_center.ir_cron_mistake_ai_job', raise_if_not_found=False)
check('cron 记录已建且启用', bool(cron) and cron.active and cron.interval_type == 'minutes',
      cron and (cron.active, cron.interval_type))
check('三个系统参数占位都在', all(env['ir.config_parameter'].sudo().search_count(
    [('key', '=', 'tutoring_center.' + k)]) == 1
    for k in ('deepseek_api_key', 'deepseek_model', 'deepseek_base_url')))
check('新模型可访问', 'tutoring.mistake.ai.job' in env)

print('\n== 按钮可见性 ==')
m = mk_mistake('例1-1')
check('定位得到页且未生成过 → 可生成', m.can_ai_summary)
m_nopage = Mistake.sudo().create({'student_id': stu_own.id, 'workbook_id': wb.id})
check('没填页码 → 不给生成', not m_nopage.can_ai_summary)

print('\n== 一题一次 & 额度 ==')
job = Job.with_user(teacher).create({'mistake_id': m.id})
check('建任务成功', bool(job) and job.user_id.id == teacher.id)
check('建完错题转 pending', m.ai_state == 'pending')
check('pending 时按钮消失（防重复点击）', not m.can_ai_summary)
try:
    Job.with_user(teacher).create({'mistake_id': m.id})
    check('同一道题第二次被拦', False, '竟然建成了')
except ValidationError as e:
    check('同一道题第二次被拦', True, str(e)[:60])
others = [mk_mistake('例%d' % i) for i in range(2, 6)]
Job.with_user(teacher).create([{'mistake_id': x.id} for x in others])
check('额度剩 0', Job.with_user(teacher).quota_left() == 0,
      Job.with_user(teacher).quota_left())
try:
    Job.with_user(teacher).create({'mistake_id': mk_mistake('例6').id})
    check('第 6 条被额度拦', False, '竟然建成了')
except ValidationError:
    check('第 6 条被额度拦', True)
check('另一个账号不受这个额度影响', Job.with_user(pupil).quota_left() == 5,
      Job.with_user(pupil).quota_left())

print('\n== 越权引用别人的错题 ==')
try:
    Job.with_user(pupil).create({'mistake_id': m.id})
    check('门户学生引用别人错题被拦', False, '竟然建成了')
except ValidationError:
    check('门户学生引用别人错题被拦', True)
check('任务只看得到自己发起的', Job.with_user(pupil).search_count([]) == 0)
check('老师看得到 5 条（自己发起的）', Job.with_user(teacher).search_count([]) == 5,
      Job.with_user(teacher).search_count([]))
# 下面还要再建几条任务，先把这位账号今天的额度腾出来（测试便利，不改生产逻辑）
Job.sudo().search([('user_id', '=', teacher.id)]).unlink()
check('腾出额度后回到 5', Job.with_user(teacher).quota_left() == 5,
      Job.with_user(teacher).quota_left())

print('\n== 响应解析 ==')
P = Job._parse
check('正常 JSON', P('{"found": true, "summary": "x"}') == {'found': True, 'summary': 'x'})
check('带代码块围栏', P('```json\n{"found": false}\n```') == {'found': False})
check('前后有废话', P('好的：{"found": true} 以上') is not None)
check('不是 JSON → None', P('我找不到这页') is None)
check('缺 found → None', P('{"summary": "只有摘要"}') is None)
check('空串 → None', P('') is None)

print('\n== 知识点只在为空时填、且必须逐字命中 ==')
cand = Job._candidates(m)
check('候选知识点非空（高中库随模块自带）', len(cand) > 0, len(cand))
first_point_name = next(iter(cand))
m2 = mk_mistake('例7-1')
job2 = Job.with_user(teacher).create({'mistake_id': m2.id})
job2._apply(m2, {'found': True, 'question_text': '题目', 'summary': '摘要',
                 'point': first_point_name}, cand)
check('为空时按候选逐字填上', m2.point_id.id == cand[first_point_name], m2.point_id.name)
check('状态转 done 且有摘要', m2.ai_state == 'done' and m2.ai_summary == '摘要')
m2.point_id = False
job2._apply(m2, {'found': True, 'question_text': 't', 'summary': 's2',
                 'point': '候选里根本没有的名字'}, cand)
check('AI 造出来的名字不被采纳', not m2.point_id)
m3 = mk_mistake('例7-2')
m3.point_id = env['tutoring.knowledge.point'].sudo().search(
    [('grade', 'in', m3.student_id.knowledge_grades)], limit=1)
before = m3.point_id.id
job3 = Job.with_user(teacher).create({'mistake_id': m3.id})
job3._apply(m3, {'found': True, 'question_text': 't', 'summary': 's',
                 'point': first_point_name}, cand)
check('已有人工知识点不被覆盖', m3.point_id.id == before)

print('\n== 失败路径（不联网） ==')
m4 = mk_mistake('例8')
job4 = Job.with_user(teacher).create({'mistake_id': m4.id})
Job._cron_process_pending()
check('没配密钥时 cron 不崩', True)
check('没密钥 → 任务 failed', job4.state == 'failed', job4.state)
check('没密钥 → 错题 failed 且带提示', m4.ai_state == 'failed' and bool(m4.ai_hint),
      (m4.ai_state, m4.ai_hint))
check('提示里说了要手工填', '手工' in (m4.ai_hint or ''), m4.ai_hint)
env['ir.config_parameter'].sudo().set_param('tutoring_center.deepseek_api_key', 'sk-fake')
m5 = mk_mistake('例9')
job5 = Job.with_user(teacher).create({'mistake_id': m5.id})
Job._cron_process_pending()
check('有"密钥"但页里没位图 → 资料侧失败，不发请求',
      job5.state == 'failed' and '位图' in (job5.error or ''), (job5.state, job5.error))
check('失败后这道题不再给按钮', not m5.can_ai_summary)
check('失败也算一次额度', Job.with_user(teacher).quota_left() == 1,
      Job.with_user(teacher).quota_left())
check('今天已记 4 次尝试（含失败的）', Job.sudo().search_count(
    [('user_id', '=', teacher.id)]) == 4,
    Job.sudo().search_count([('user_id', '=', teacher.id)]))

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
