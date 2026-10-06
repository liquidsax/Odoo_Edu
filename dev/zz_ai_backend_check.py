"""业务库上补验：后台按钮走通、三张视图能渲染、_abort 不扣额度。

跑法：cd server && PYTHONUTF8=1 ../python/python.exe odoo-bin shell \
        -c odoo.conf -d OdooForDB --no-http < ../dev/zz_ai_backend_check.py
"""
import time

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('PASS  ' if cond else 'FAIL  ') + label + (('  | ' + str(extra)) if extra else ''))


admin = env.ref('base.user_admin')
Mistake = env['tutoring.mistake']
Job = env['tutoring.mistake.ai.job']

print('\n== 三张视图能被后端渲染（get_view 会做字段与 arch 校验） ==')
for xmlid, label in (
        ('view_tutoring_mistake_form_reader', '只读详情弹窗'),
        ('view_tutoring_mistake_form', '修改台'),
        ('view_tutoring_mistake_list', '列表'),
        ('view_tutoring_mistake_kanban', '看板')):
    vid = env.ref('tutoring_center.' + xmlid).id
    try:
        arch = Mistake.with_user(admin).get_view(vid)['arch']
        check('%s 渲染通过' % label, '<form' in arch or '<list' in arch or '<kanban' in arch)
    except Exception as exc:  # noqa: BLE001
        check('%s 渲染通过' % label, False, '%s: %s' % (type(exc).__name__, str(exc)[:150]))

print('\n== 后台「生成摘要」按钮（真调用，用表弟 P12 那道题号 12） ==')
m = Mistake.sudo().search([('id', '=', 31)])
state = m.ai_state
already = m.ai_state in ('done', 'failed')
if already:
    # 重跑时不再花第二次额度：直接沿用上一轮真调用的结果，只验后续断言
    print('  （这条已有结果 %s，跳过发起）' % m.ai_state)
else:
    check('这条错题可生成', m.can_ai_summary, m.ai_state)
    act = m.with_user(admin).action_ai_generate()
    check('按钮返回通知动作', act.get('tag') == 'display_notification'
          and '2 分钟' in act['params']['title'], act)
    check('点完转 pending', m.ai_state == 'pending', m.ai_state)
    check('pending 时按钮消失（后台也防重复点击）', not m.can_ai_summary)
    try:
        Job.with_user(admin).create({'mistake_id': m.id})
        check('第二条形同虚设的点击被 create 拦住', False, '竟然建成了')
    except Exception as exc:  # noqa: BLE001
        check('第二条形同虚设的点击被 create 拦住', 'ValidationError' in type(exc).__name__,
              type(exc).__name__)
    env.cr.commit()              # 先把任务落库，cron 在另一个进程里才取得到
    state = m.ai_state
    for _ in range(40):
        time.sleep(6)
        # 每轮都开新事务并清缓存：同一事务里反复读会一直拿到旧值（第一版就栽在这儿）
        env.cr.commit()
        env.invalidate_all()
        state = Mistake.sudo().browse(31).ai_state
        if state in ('done', 'failed'):
            break
    m = Mistake.sudo().browse(31)
    check('cron 处理完（done/failed）', state in ('done', 'failed'), state)
last = Job.sudo().search([('mistake_id', '=', m.id)], order='id desc', limit=1)
print('  结果：状态=%s 摘要=%r 知识点=%s token=%s/%s error=%r' % (
    state, m.ai_summary, m.point_id.name or '（空）',
    last.prompt_tokens, last.completion_tokens, last.error))
charged = Job.sudo().search_count([('user_id', '=', admin.id), ('state', 'in', Job.CHARGED)])
check('额度 = 5 减掉"已计费"的任务条数', Job.with_user(admin).quota_left() == 5 - charged,
      (charged, Job.with_user(admin).quota_left()))

print('\n== _abort：我们的错不扣额度、这道题能重来 ==')
before = Job.with_user(admin).quota_left()
scratch = Mistake.sudo().create({
    'student_id': m.student_id.id, 'workbook_id': m.workbook_id.id,
    'page': m.page, 'question_no': 'ZZ 临时', 'note': '验收 _abort 用，跑完删'})
job = Job.with_user(admin).create({'mistake_id': scratch.id})
check('刚建好时额度少 1', Job.with_user(admin).quota_left() == before - 1,
      (before, Job.with_user(admin).quota_left()))
job._abort('故意制造的系统出错')
check('任务转 error', job.state == 'error', job.state)
check('错题退回未生成（可以重来）', scratch.ai_state == 'none', scratch.ai_state)
check('系统出错不计额度（回到原值）', Job.with_user(admin).quota_left() == before,
      (before, Job.with_user(admin).quota_left()))
# 清掉这条临时错题与它的任务行
job.sudo().unlink()
scratch.sudo().unlink()
check('临时数据已清', not scratch.exists() and not job.exists())

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
