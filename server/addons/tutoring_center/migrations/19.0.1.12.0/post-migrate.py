import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """把练习册教材的正文搬进知识库条目表（委托继承改造）。

    `tutoring.workbook.file` 改成 `_inherits = {'tutoring.library.item': 'item_id'}`
    之后，正文与文件名都归条目表管。子表那两列 ORM 不会自动删，所以这里
    建好条目、回填 item_id，再把旧列 DROP 掉，避免同一份 PDF 在库里留两份。

    可重复执行：旧列已经不在就说明搬过了，直接返回。
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tutoring_workbook_file' AND column_name = 'content'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT f.id, f.name, f.filename, f.content, f.create_uid, f.create_date, w.name
        FROM tutoring_workbook_file f
        LEFT JOIN tutoring_workbook w ON w.id = f.workbook_id
        ORDER BY f.id
    """)
    rows = cr.fetchall()
    item_model = env['tutoring.library.item'].with_context(library_skip_quota=True)
    moved = 0
    for file_id, part_name, filename, content, create_uid, create_date, book_name in rows:
        title = ' · '.join(part for part in (book_name, part_name) if part) or part_name or '教材'
        # 裸 SQL 读 bytea 出来是 memoryview——直接给 ORM 会被 str() 成
        # "<memory at 0x...>" 存进库（真踩过），必须先转 bytes
        content = bytes(content) if content is not None else False
        item = item_model.create({
            'name': title,
            'user_id': create_uid or SUPERUSER_ID,
            'category': 'workbook',
            'content': content,
            'filename': filename,
            'upload_date': create_date or False,
        })
        cr.execute(
            'UPDATE tutoring_workbook_file SET item_id = %s WHERE id = %s',
            (item.id, file_id))
        moved += 1

    cr.execute("""
        ALTER TABLE tutoring_workbook_file
        DROP COLUMN IF EXISTS content,
        DROP COLUMN IF EXISTS filename
    """)
    _logger.info('知识库：%s 份练习册教材已迁入 tutoring.library.item', moved)
