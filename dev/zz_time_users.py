"""给时间账本验收建两个一次性账号（内部用户 A + 门户用户 B）。

用法：
    PYTHONUTF8=1 odoo-bin shell -c odoo.conf -d zz_do1ng_time --no-http < dev/zz_time_users.py

口令走环境变量 ZZ_TIME_PW_A / ZZ_TIME_PW_B，不写进仓库、不打印到日志。
跑完验收就把整个库删掉，账号随库一起没了。
"""
import os

Users = env['res.users']
teacher = env.ref('tutoring_center.group_teacher')
portal = env.ref('base.group_portal')

WANTED = [
    ('zz_time_a', os.environ['ZZ_TIME_PW_A'], [teacher.id], '时间账本验收A'),
    ('zz_time_b', os.environ['ZZ_TIME_PW_B'], [portal.id], '时间账本验收B'),
    # 契约预检专用一个独立账号：两套脚本各写各的数据，谁都别被对方的残留行数带偏
    ('zz_time_c', os.environ['ZZ_TIME_PW_C'], [teacher.id], '时间账本预检C'),
    # Java 客户端端到端再要一个干净的空账号：它第一轮就该是"全新增"，
    # 蹭别人的数据会把幂等与墓碑两组断言全带歪
    ('zz_time_d', os.environ['ZZ_TIME_PW_D'], [teacher.id], '时间账本预检D'),
]

for login, password, groups, name in WANTED:
    user = Users.search([('login', '=', login)], limit=1)
    if user:
        user.write({'password': password})
        print('USER_EXISTS %s id=%s share=%s' % (login, user.id, user.share))
    else:
        user = Users.with_context(no_reset_password=True).create({
            'login': login,
            'password': password,
            'name': name,
            'group_ids': [(6, 0, groups)],
        })
        print('USER_CREATED %s id=%s share=%s' % (login, user.id, user.share))
env.cr.commit()
print('USERS_DONE')
