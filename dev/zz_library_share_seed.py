"""一次性库上的共享验收：造数据 + 提交，好让 HTTP 那层能真的登录来看。

    cd E:\\Odoo\\server
    PYTHONUTF8=1 ..\\python\\python.exe odoo-bin shell -c odoo.conf -d <一次性库> \\
        --db-filter='^<一次性库>$' --no-http < ..\\dev\\zz_library_share_seed.py

跑完数据是留下的（这个库验完整库删掉，所以可以 commit）。
"""
import base64

admin = env.ref('base.user_admin')
student = env['tutoring.student'].create({'name': '共享验收学生'})
suser = env['res.users'].create({
    'name': '共享验收学生', 'login': 'zz_stu', 'partner_id': student.partner_id.id,
    'password': 'Zz-stu-2026',
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
other = env['res.users'].create({
    'name': '别的老师', 'login': 'zz_t2', 'password': 'Zz-t2-2026',
    'group_ids': [(6, 0, [env.ref('base.group_user').id])]})

Item = env['tutoring.library.item']
note = Item.create({
    'name': '验收笔记.md', 'category': 'note', 'user_id': admin.id,
    'filename': 'note.md',
    'content': base64.b64encode('# 验收\n\n正文一行。\n'.encode()).decode()})
folder = env['tutoring.library.folder'].create({'name': '私人收纳', 'user_id': admin.id})
note.write({'folder_id': folder.id, 'tag_ids': [(6, 0, [env['tutoring.library.tag']
                                   .create({'name': '别透出去', 'user_id': admin.id}).id])]})

book = env['tutoring.workbook'].create({'name': '验收教材册'})
book_item = Item.create({
    'name': '验收教材 · 第1份', 'category': 'workbook', 'user_id': admin.id,
    'filename': 'ch1.pdf', 'content': base64.b64encode('%PDF-1.4 验收用\n'.encode()).decode()})
book_file = env['tutoring.workbook.file'].create({'workbook_id': book.id, 'name': '第1份',
                                                  'item_id': book_item.id})
student.write({'user_ids': [(6, 0, [suser.id])]}) if 'user_ids' in student._fields else None
note.write({'share_user_ids': [(6, 0, [suser.id])]})
book_item.write({'share_user_ids': [(6, 0, [suser.id])]})
env.cr.commit()
print('SEED note=%s book=%s book_item=%s book_file=%s student_uid=%s admin_pwd_ok=%s' % (
    note.id, book.id, book_item.id, book_file.id, suser.id,
    env['res.users'].authenticate('admin', 'admin', []) == admin.id))
