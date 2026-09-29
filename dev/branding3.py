import base64

LOGO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="48" viewBox="0 0 200 48">'
            '<rect width="200" height="48" rx="8" fill="#714B67"/>'
            '<text x="16" y="31" font-family="Microsoft YaHei, sans-serif" font-size="19" '
            'font-weight="bold" fill="#ffffff">数学辅导中心</text></svg>')

v = env.ref('website.header_text_element')
v.active = False
print('HEADER_TEXT_DEACTIVATED')

env['res.company'].browse(1).phone = False
website = env['website'].browse(1)
website.logo = base64.b64encode(LOGO_SVG.encode('utf-8'))
env.cr.commit()
print('BRAND3_DONE logo=%d bytes' % len(website.logo))
