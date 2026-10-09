"""知识库「谁可以看」的模型层断言。在 odoo-bin shell 里跑，结束整体回滚：

    cd E:\\Odoo\\server
    PYTHONUTF8=1 ..\\python\\python.exe odoo-bin shell -c odoo.conf -d <一次性库> \\
        < ..\\dev\\zz_library_share_check.py

只测 ORM 与权限，HTTP 那层另跑。
"""
from odoo.exceptions import AccessError

import base64

Item = env['tutoring.library.item']

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
    print('%-4s %s%s' % ('PASS' if cond else 'FAIL', label, ('  <- %s' % extra) if extra and not cond else ''))


admin = env.ref('base.user_admin')
student = env['tutoring.student'].create({'name': '共享验收学生'})
spart = student.partner_id
suser = env['res.users'].create({
    'name': '共享验收学生', 'login': 'zz_share_stu', 'partner_id': spart.id,
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
senv = env(user=suser.id)
# 另一位老师：内部用户，绝不该出现在可共享名单里
teacher2 = env['res.users'].create({
    'name': '同事老师', 'login': 'zz_share_t2',
    'group_ids': [(6, 0, [env.ref('base.group_user').id])]})

item = Item.create({
    'name': '验收笔记', 'category': 'doc', 'user_id': admin.id,
    'filename': 'note.md', 'content': base64.b64encode(b'# hi\n').decode()})

# --- 默认仅本人 ---
check('学生默认看不到别人的条目', Item.with_user(suser).search_count([('id', '=', item.id)]) == 0)
check('可共享名单里有这个学生', suser.id in item.share_candidate_ids.ids)
check('可共享名单里没有内部用户', teacher2.id not in item.share_candidate_ids.ids)
check('可共享名单里没有条目主人自己', admin.id not in item.share_candidate_ids.ids)

# --- 共享之后 ---
item.write({'share_user_ids': [(6, 0, [suser.id])]})
check('共享后学生能搜到', Item.with_user(suser).search_count([('id', '=', item.id)]) == 1)
check('共享后学生能读正文', bool(Item.with_user(suser).browse(item.id).content))
check('条目仍然挂在主人名下', item.user_id.id == admin.id)
check('学生配额一格没涨', Item.with_user(suser).used_bytes(suser.id) == 0,
      'used_bytes=%s' % Item.with_user(suser).used_bytes(suser.id))
check('主人配额照旧计入', Item.used_bytes(admin.id) > 0)

try:
    Item.with_user(suser).browse(item.id).write({'name': '改一下'})
    check('学生改不动共享条目', False)
except AccessError:
    check('学生改不动共享条目', True)
try:
    Item.with_user(suser).browse(item.id).unlink()
    check('学生删不掉共享条目', False)
except AccessError:
    check('学生删不掉共享条目', True)
check('学生读不到别人的文件夹名', not Item.with_user(suser).browse(item.id).folder_id)

# --- 名单收敛：越权 id 一律剔掉 ---
item.write({'share_user_ids': [(6, 0, [suser.id, teacher2.id, admin.id, 999999])]})
check('越权与不存在的 id 被剔掉，只留下学生', item.share_user_ids.ids == [suser.id],
      'got=%s' % item.share_user_ids.ids)
item.write({'share_user_ids': [suser.id]})
check('裸 id 列表这种写法也收敛', item.share_user_ids.ids == [suser.id])
item.write({'share_user_ids': [(6, 0, [teacher2.id])]})
check('全是非法 id 时名单清空', not item.share_user_ids)
check('清空后学生又看不到了', Item.with_user(suser).search_count([('id', '=', item.id)]) == 0)

# --- 教材那条真实链路：委托继承的正文有没有跟着放开 ---
book = env['tutoring.workbook'].create({'name': '验收教材册'})
book_item = Item.create({
    'name': '验收教材 · 第1份', 'category': 'workbook', 'user_id': admin.id,
    'filename': 'ch1.pdf', 'content': base64.b64encode(b'%PDF-1.4 fake\n').decode()})
book_file = env['tutoring.workbook.file'].create({
    'workbook_id': book.id, 'name': '第1份', 'item_id': book_item.id})
check('没共享时学生数不到教材文件',
      env['tutoring.workbook.file'].with_user(suser).search_count([('workbook_id', '=', book.id)]) == 0)
book_item.write({'share_user_ids': [(6, 0, [suser.id])]})
seen = env['tutoring.workbook.file'].with_user(suser).search([('workbook_id', '=', book.id)])
check('共享后学生数得到教材文件', seen.ids == [book_file.id], 'got=%s' % seen.ids)
try:
    check('学生能读教材正文（这一条就是原来那个 404）', bool(seen.content))
except AccessError as exc:
    check('学生能读教材正文（这一条就是原来那个 404）', False, str(exc)[:80])

print('\n合计 %d 项：通过 %d，失败 %d' % (ok + fail, ok, fail))
