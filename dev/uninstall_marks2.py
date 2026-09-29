NAMES = ['im_livechat', 'mail_bot', 'mail_bot_hr', 'spreadsheet_dashboard_im_livechat']
M = env['ir.module.module'].sudo()
mods = M.search([('name', 'in', NAMES), ('state', '=', 'installed')])
print('MARK_COUNT=%d' % len(mods))
for m in mods:
    try:
        m.button_uninstall()
        print('MARK_OK %s' % m.name)
    except Exception as e:
        print('MARK_FAIL %s: %s' % (m.name, e))
env.cr.commit()
print('SCRIPT_DONE')
