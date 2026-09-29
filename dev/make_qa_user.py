import os

Users = env['res.users']
Groups = env['res.groups']
teacher = env.ref('tutoring_center.group_teacher')
existing = Users.search([('login', '=', 'qa_check')], limit=1)
if existing:
    print('QA_EXISTS %s' % existing.id)
else:
    u = Users.create({
        'login': 'qa_check',
        'password': os.environ.get('QA_PASSWORD', 'QaTemp_%s' % os.urandom(4).hex()),
        'name': 'QA',
        'group_ids': [(6, 0, [teacher.id])],
    })
    print('QA_CREATED %s groups=%s' % (u.id, u.group_ids.mapped('name')))
env.cr.commit()
print('QA_DONE')
