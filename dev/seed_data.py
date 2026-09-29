import datetime
import os

# 演示账号密码：优先取环境变量，避免真实口令进入代码仓库
DEMO_PW_A = os.environ.get('TUTOR_DEMO_PW_A', 'DemoPwd_A_2026')
DEMO_PW_B = os.environ.get('TUTOR_DEMO_PW_B', 'DemoPwd_B_2026')

Topic = env['tutoring.topic']
Student = env['tutoring.student']
Session = env['tutoring.session']
Homework = env['tutoring.homework']
Exam = env['tutoring.exam']
Users = env['res.users']

def make_user(login, password, name, partner):
    existing = Users.search([('login', '=', login)], limit=1)
    if existing:
        return existing
    return Users.create({
        'login': login,
        'password': password,
        'name': name,
        'partner_id': partner.id,
        'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
    })

TOPIC_NAMES = ['有理数及其运算', '整式的加减', '一元一次方程', '几何图形初步',
               '相交线与平行线', '实数', '二元一次方程组', '不等式与不等式组']
topics = {}
for n in TOPIC_NAMES:
    topics[n] = Topic.search([('name', '=', n)], limit=1) or Topic.create({'name': n})

# 学生 A（演示数据，名称可改）
student_a = Student.create({'name': '学生A', 'grade': '7', 'school': '示例中学', 'status': 'active'})
user_a = make_user('biaodi', DEMO_PW_A, '学生A', student_a.partner_id)

# 学生 B（隔离验证用，验收后可删）
student_b = Student.create({'name': '示例学生B', 'grade': '8', 'school': '示例中学', 'status': 'active'})
user_b = make_user('student02', DEMO_PW_B, '示例学生B', student_b.partner_id)

D = datetime.date
# 学生 A 的课次
for d, tlist in [
    (D(2026, 9, 7), ['有理数及其运算']),
    (D(2026, 9, 10), ['有理数及其运算', '整式的加减']),
    (D(2026, 9, 14), ['整式的加减']),
    (D(2026, 9, 17), ['一元一次方程']),
    (D(2026, 9, 21), ['一元一次方程', '几何图形初步']),
]:
    Session.create({
        'student_id': student_a.id,
        'date': d,
        'duration': 1.5,
        'topic_ids': [(6, 0, [topics[t].id for t in tlist])],
        'performance': '<p>本课完成 planned 内容，课堂练习正确率良好，注意计算细心。</p>',
        'plan': '<p>下次课：错题巩固 + 新内容预习。</p>',
    })

# 学生 A 的作业
for d, title, qc, cc, state in [
    (D(2026, 9, 7), '有理数混合运算练习', 20, 17, 'reviewed'),
    (D(2026, 9, 10), '整式加减基础题', 15, 13, 'reviewed'),
    (D(2026, 9, 14), '一元一次方程应用题', 12, 9, 'reviewed'),
    (D(2026, 9, 21), '几何图形初步练习', 15, 12, 'reviewed'),
    (D(2026, 9, 28), '本周错题订正', 8, 0, 'draft'),
]:
    Homework.create({
        'student_id': student_a.id,
        'title': title,
        'assigned_date': d,
        'due_date': d + datetime.timedelta(days=3),
        'question_count': qc,
        'correct_count': cc,
        'state': state,
        'feedback': '<p>整体完成认真，计算类错误需多练。</p>' if state == 'reviewed' else False,
    })

# 学生 A 的考试
e1 = Exam.create({
    'student_id': student_a.id,
    'name': '开学摸底测验',
    'date': D(2026, 9, 9),
    'exam_type': 'unit',
    'line_ids': [(0, 0, {'topic_id': topics['有理数及其运算'].id, 'score': 38, 'full_score': 50}),
                 (0, 0, {'topic_id': topics['整式的加减'].id, 'score': 40, 'full_score': 50})],
})
e2 = Exam.create({
    'student_id': student_a.id,
    'name': '九月月考',
    'date': D(2026, 9, 25),
    'exam_type': 'monthly',
    'line_ids': [(0, 0, {'topic_id': topics['一元一次方程'].id, 'score': 44, 'full_score': 50}),
                 (0, 0, {'topic_id': topics['几何图形初步'].id, 'score': 41, 'full_score': 50})],
})

# 学生 B 少量数据（验证互相不可见）
Session.create({'student_id': student_b.id, 'date': D(2026, 9, 20), 'duration': 2.0,
                'topic_ids': [(6, 0, [topics['实数'].id])],
                'performance': '<p>学生B的课次记录。</p>'})
Exam.create({'student_id': student_b.id, 'name': '学生B单元测', 'date': D(2026, 9, 22),
             'exam_type': 'unit',
             'line_ids': [(0, 0, {'topic_id': topics['实数'].id, 'score': 45, 'full_score': 50})]})

env.cr.commit()
print('STUDENT_A=%s PARTNER_A=%s USER_A=%s' % (student_a.id, student_a.partner_id.id, user_a.login))
print('STUDENT_B=%s USER_B=%s' % (student_b.id, user_b.login))
print('SESSIONS_A=%d HOMEWORK_A=%d EXAMS_A=%d' % (
    len(student_a.session_ids), len(student_a.homework_ids), len(student_a.exam_ids)))
print('SEED_DONE')
