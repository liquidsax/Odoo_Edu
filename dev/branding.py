company = env['res.company'].browse(1)
print('COMPANY_BEFORE=%r' % company.name)
company.name = '数学辅导中心'
company.email = ''
website = env['website'].browse(1)
print('WEBSITE_BEFORE=%r' % website.name)
website.name = '数学辅导学习平台'
env.cr.commit()
print('COMPANY_AFTER=%r WEBSITE_AFTER=%r' % (company.name, website.name))
print('BRAND_DONE')
