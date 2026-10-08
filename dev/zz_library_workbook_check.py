r"""知识库「练习册/教辅」条目 ↔ 练习册那套打通的验收（一次性库专用，别对业务库跑）。

覆盖 19.0.1.20.0 这一轮：
 - 条目建好、或补上正文之后，同名练习册该出现，教材文件行该挂上（且复用同一条条目）
 - 「先记名字、附件后补」：没有正文也要能把这本练习册立起来，错题页当场选得到
 - 学生账号对练习册只有读权限，不该被 sudo 越过这条线
 - 委托继承那条回头路（item.create → file.create → item.write）不递归、不多生成条目
 - 后台建的教材标题照旧是「书名 · 分册名」，也不会多出一本同名书
 - 19.0.1.20.0 的 post-migrate 补存量时，不把条目归属改成超用户

用法（独立进程 + 一次性库，不碰在跑的服务与 OdooForDB）：
    set PYTHONUTF8=1
    cd /d E:\Odoo\server
    python odoo-bin shell -c odoo.conf -d zz_library_link --no-http --logfile= ^
        --db-filter=^zz_library_link$ < ..\dev\zz_library_workbook_check.py

脚本最后整体 rollback，所以可以反复跑。
"""
import base64
import importlib.util
import os

from odoo.modules.module import get_module_path

ok = fail = 0


def check(name, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS  ' + name)
    else:
        fail += 1
        print('FAIL  %s  %s' % (name, extra))


Item = env['tutoring.library.item']
File = env['tutoring.workbook.file']
Book = env['tutoring.workbook']
Mistake = env['tutoring.mistake']
Teacher = env.ref('base.user_admin')
T = Item.with_user(Teacher.id)
PDF = base64.b64encode(b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<\n%%EOF\n').decode()

mod = env['ir.module.module'].search([('name', '=', 'tutoring_center')])
check('模块版本已抬到 19.0.1.20.0', mod.latest_version == '19.0.1.20.0', mod.latest_version)

# 1) 老师从知识库上传一本教辅（分类＝练习册/教辅 + 正文）
item = T.create({'name': '一数', 'category': 'workbook', 'content': PDF, 'filename': 'yishu.pdf'})
book = Book.search([('name', '=', '一数')])
check('建条目即建同名练习册', len(book) == 1, '命中 %d 本' % len(book))
check('教材文件行已挂上', len(item.workbook_file_ids) == 1)
check('教材行复用同一条条目', item.workbook_file_ids.item_id.id == item.id)
check('标题没被拼成「一数 · 一数」', item.name == '一数', item.name)
check('条目仍归上传者', item.user_id.id == Teacher.id)
check('条目的「练习册」列读得到书名', item.from_workbook == '一数', item.from_workbook)
check('知识库条目总数没被多建一条', Item.search_count([('name', '=', '一数')]) == 1)

# 2) 同名再传一份 → 归同一本书
item2 = T.create({'name': '一数', 'category': 'workbook', 'content': PDF, 'filename': 'p2.pdf'})
check('同名再传仍只有一本书', Book.search_count([('name', '=', '一数')]) == 1)
check('两行教材挂在同一本下',
      item2.workbook_file_ids.workbook_id == item.workbook_file_ids.workbook_id)

# 3) 先记名字、附件后补（「新建资料」那条路：压根没有 content）
used_before = Item.used_bytes(Teacher.id)
later = T.create({'name': '53 精讲册', 'category': 'workbook'})
check('空条目也立起了书', Book.search_count([('name', '=', '53 精讲册')]) == 1)
check('空条目不建教材文件行', not later.workbook_file_ids)
check('空条目不占配额', Item.used_bytes(Teacher.id) == used_before)
later.write({'content': PDF, 'filename': '53.pdf'})
check('补正文后才挂上教材行', len(later.workbook_file_ids) == 1)
check('补附件后仍指向同一本书', later.workbook_file_ids.workbook_id.name == '53 精讲册')
check('补附件后标题仍是书名本身', later.name == '53 精讲册', later.name)

# 4) 端到端：错题页那本下拉选得到，且能对着它记错题、能定位到那一页
student = env['tutoring.student'].search([], limit=1) or env['tutoring.student'].create({'name': '验收学生'})
check('练习册下拉看得见新建的那本', '一数' in Book.with_user(Teacher.id).search([]).mapped('name'))
mistake = Mistake.with_user(Teacher.id).create({
    'student_id': student.id, 'workbook_id': book.id, 'page': '13', 'question_no': '5'})
check('能对着这本书记错题', bool(mistake.id))
found_file, local_page, hint = later.workbook_file_ids.workbook_id._locate_page('13')
check('错题「展示那一页」定位到了知识库传上来的那份',
      bool(found_file) and found_file.item_id.id == later.id and not hint, hint)

# 5) 学生账号：不越权建书，也不能因此报错
stu = env['res.users'].create({
    'name': '验收门户学生', 'login': 'zz_lib_stu',
    'group_ids': [(6, 0, [env.ref('base.group_portal').id])],
})
books_before = Book.search_count([])
sitem = Item.with_user(stu.id).create({
    'name': '学生手里的教辅', 'category': 'workbook', 'content': PDF, 'filename': 's.pdf'})
check('学生建教辅不报错、条目还在', bool(sitem.id))
check('学生没被允许造出公共练习册', Book.search_count([]) == books_before)
check('学生的条目仍归他自己', sitem.user_id.id == stu.id)

# 6) 后台那条路（直接建教材文件）：标题带分册名，且不多造书、不多建条目
b = Book.create({'name': '五年高考三年模拟'})
f1 = File.create({'workbook_id': b.id, 'name': '第1份', 'content': PDF, 'filename': '1.pdf'})
check('后台建的教材标题是「书名 · 分册名」',
      f1.item_id.name == '五年高考三年模拟 · 第1份', f1.item_id.name)
check('后台建教材没多出一本同名书', Book.search_count([('name', '=', '五年高考三年模拟')]) == 1)
check('后台建教材只生成一条知识库条目',
      Item.search_count([('name', '=like', '五年高考三年模拟%')]) == 1)

# 7) 改分类走 write 钩子
plain = T.create({'name': '改成教辅', 'category': 'note', 'content': PDF, 'filename': 'n.pdf'})
check('分类不是教辅时不建书', Book.search_count([('name', '=', '改成教辅')]) == 0)
plain.write({'category': 'workbook'})
check('改分类后挂成了书', Book.search_count([('name', '=', '改成教辅')]) == 1)
check('改分类后有了教材行', len(plain.workbook_file_ids) == 1)
plain.write({'category': 'other'})
check('改回别的分类不炸', plain.category == 'other')
check('已建出来的书不回收（留给后台归档）', Book.search_count([('name', '=', '改成教辅')]) == 1)

# 8) 删条目：教材行跟着走，书留着
plain.write({'category': 'workbook'})
plain.unlink()
env.cr.execute(
    "SELECT count(*) FROM tutoring_workbook_file WHERE item_id = %s", [plain.id])
check('删条目后教材行一起没了', env.cr.fetchone()[0] == 0)
check('删条目不回收书', Book.search_count([('name', '=', '改成教辅')]) == 1)

# 9) 迁移补存量：造一条"19.0.1.20.0 之前的孤儿条目"，再跑 post-migrate
orphan = Item.with_context(no_workbook_link=True).create({
    'name': '存量教辅', 'category': 'workbook', 'content': PDF,
    'filename': 'old.pdf', 'user_id': Teacher.id})
check('模拟出的存量孤儿确实没挂上书',
      not orphan.workbook_file_ids and not Book.search([('name', '=', '存量教辅')]))
path = os.path.join(
    get_module_path('tutoring_center'), 'migrations', '19.0.1.20.0', 'post-migrate.py')
spec = importlib.util.spec_from_file_location('zz_lib_post_migrate', path)
post_migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(post_migrate)
books_before = Book.search_count([])
# 迁移脚本自己开一个超用户环境（只共用 cursor），没 flush 的写它看不见；
# 跑完也要把本环境的缓存作废，否则读到的还是迁移前那份
env.flush_all()
post_migrate.migrate(env.cr, None)
env.invalidate_all()
check('迁移把存量教辅挂成了书', Book.search_count([('name', '=', '存量教辅')]) == 1)
check('迁移后有了教材行', len(orphan.workbook_file_ids) == 1)
check('迁移没把条目判给超用户', orphan.user_id.id == Teacher.id)
check('迁移只补该补的那一本（已挂书的/学生的都不动）',
      Book.search_count([]) - books_before == 1,
      '多了 %d 本' % (Book.search_count([]) - books_before))

print('\n结果：PASS %d / FAIL %d' % (ok, fail))
env.cr.rollback()
if fail:
    print('有失败项，别提交。')
