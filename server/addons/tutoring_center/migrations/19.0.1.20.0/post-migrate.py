"""把「分类＝练习册/教辅」的知识库条目补挂成真正的练习册。

19.0.1.20.0 之前这个分类只是条目上的一个标签：从知识库传上来的教辅永远不会变成
`tutoring.workbook`，而错题速记条、教材阅读页、错题「展示那一页」认的全是
`tutoring.workbook`——于是"我在知识库传了练习册，错题页那本下拉里却没有"。
运行时那条链已经补上（`models/tutoring_library_item.py` 的 `_ensure_workbook_link`），
这里补存量。

书名取条目标题（同名即同一本）；只有正文的条目才建 `tutoring.workbook.file` 那一行，
没附件的只把书立起来——记错题只要书名。已经挂在某本书下的（后台建的教材）不动。
"""

import logging

from odoo import api

_logger = logging.getLogger(__name__)


def _file_rows(cr):
    cr.execute("SELECT count(*) FROM tutoring_workbook_file")
    return cr.fetchone()[0]


def migrate(cr, version):
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    Item = env['tutoring.library.item']

    def can_own_books(user_id):
        """这条目的归属人本来能不能建练习册——用他本人的环境问，不用超用户问。

        `has_access` 在 `env.su` 下恒为真，拿迁移这个超用户环境直接问，就等于替
        学生把私有条目升成了公共的一本，跟运行时那条界线正好相反。
        """
        return env(user=user_id, su=False)['tutoring.workbook'].has_access('create')

    allowed = {api.SUPERUSER_ID: True}
    denied = {}
    before = _file_rows(cr)
    linked = skipped = 0
    for item in Item.search([('category', '=', 'workbook')]):
        owner_id = item.user_id.id
        if owner_id not in allowed:
            allowed[owner_id] = can_own_books(owner_id)
        if not allowed[owner_id]:
            denied[owner_id] = denied.get(owner_id, 0) + 1
            skipped += 1
            continue
        item._ensure_workbook_link()
        linked += 1
    _logger.warning(
        '知识库教辅条目补挂练习册：%d 条已核对（新增教材文件行 %d 条）；'
        '%d 条的归属人无权建练习册，保持原状（%s）',
        linked, _file_rows(cr) - before, skipped,
        '、'.join('用户 %s 名下 %d 条' % pair for pair in denied.items()) or '无',
    )
