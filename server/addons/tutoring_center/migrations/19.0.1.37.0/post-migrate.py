"""把「分类＝错题」却还没绑上错题的知识库条目补立成真错题。

19.0.1.37.0 之前这个分类只是条目上的一个标签：从知识库（网页、小程序、接口都一样）
传上来的题图永远不会变成 `tutoring.mistake`，而错题页、复习队列、AI 摘要认的全是那张表
——于是"我传了一张题，错题页里没有"。运行时那条链已经补上
（`models/tutoring_library_item.py` 的 `_ensure_mistake_link`），这里补存量。

一道一条：一张图立一道错题，出处留空（照片本身就是题面），归属人取条目自己的 `user_id`
对应的那份学生档案。**立之前先拿条目主人自己的环境问一遍权限**——`has_access` 在超用户下
恒为真，直接用迁移环境建，就等于替一个本来没建题权限的人造了一道他自己管不了的题，
跟运行时那条界线正好相反（练习册那次补挂是同一个做法）。
"""

import logging

from odoo import api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    Item = env['tutoring.library.item']
    orphans = Item.search([('category', '=', 'mistake'), ('mistake_id', '=', False)])

    linked, kept = 0, []
    for item in orphans:
        owner = item.user_id
        if not owner or not owner.active:
            kept.append('%s（归属人已停用）' % item.display_name)
            continue
        mine = item.with_user(owner.id)
        if not mine.env['tutoring.mistake'].has_access('create'):
            kept.append('%s（%s 无建错题权限）' % (item.display_name, owner.login))
            continue
        mine._ensure_mistake_link()
        # 认结果不认动作：立不立得成取决于"这个人名下有没有学生档案"，
        # 按调用过就算一条的话，日志会说谎（第一版就是这么写错的）
        if mine.mistake_id:
            linked += 1
        else:
            kept.append('%s（%s 名下没有学习档案）' % (item.display_name, owner.login))

    _logger.warning(
        '知识库错题条目补立错题：%d 条已立起并绑回；%d 条保持原状（%s）',
        linked, len(kept), '、'.join(kept) or '无',
    )
