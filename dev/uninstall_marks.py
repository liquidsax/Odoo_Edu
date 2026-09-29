NAMES = [
    'auth_passkey_portal', 'auth_totp_mail', 'auth_totp_portal',
    'google_gmail', 'microsoft_outlook', 'partner_autocomplete',
    'privacy_lookup', 'snailmail', 'mass_mailing_themes', 'web_unsplash',
    'hr_gamification', 'hr_homeworking', 'hr_org_chart', 'hr_skills_survey',
    'project_todo', 'project_hr_skills', 'project_sms', 'hr_livechat',
    'website_links', 'website_mail', 'website_project', 'website_sms',
    'website_mass_mailing', 'website_livechat', 'theme_bewise', 'api_doc',
]
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
left = M.search([('name', 'in', NAMES), ('state', '=', 'installed')])
print('STILL_INSTALLED=%d' % len(left))
print('SCRIPT_DONE')
