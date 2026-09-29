Users = env['res.users']
u = Users.search([('login', '=', 'qa_check')], limit=1)
if u:
    u.active = False
    env.cr.commit()
    u.unlink()
    print('QA_UNLINKED')
else:
    print('QA_NOT_FOUND')
p = env['res.partner'].search([('name', '=', 'QA')], limit=1)
if p:
    p.active = False
    print('QA_PARTNER_ARCHIVED %s' % p.id)
env.cr.commit()
print('QA_CLEAN_DONE')
