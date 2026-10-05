import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """把已有标签归到"用它的人"名下（标签从共享字典改为按用户隔离）。

    新加的 `user_id` 列在存量行上一定是 NULL，而 ORM 层的 required 拦不住裸行，
    所以这里必须回填。规则是"标签跟着用它的人走"：

    * 没人用的孤儿标签直接删——它已经不在任何文件上，留着只会占别人的补全列表；
    * 只被一个人用过就归他；
    * 被多人用过要**拆**：一个标签一行，多个用户共用同一行时，后一个用户改名
      会把前一个人的标签也改掉，所以给每个额外用户复制一行并把自己那些条目挪过去。

    可重复执行：user_id 已全部有值时第二次跑什么都不做。
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Tag = env['tutoring.library.tag'].sudo()
    cr.execute('SELECT id FROM tutoring_library_tag WHERE user_id IS NULL ORDER BY id')
    tag_ids = [row[0] for row in cr.fetchall()]
    if not tag_ids:
        return

    split, dropped = 0, 0
    for tag in Tag.browse(tag_ids):
        users = tag.item_ids.user_id
        if not users:
            tag.unlink()
            dropped += 1
            continue
        tag.user_id = users[0].id
        for user in users[1:]:
            copy = Tag.create({
                'name': tag.name,
                'color': tag.color,
                'user_id': user.id,
            })
            for item in tag.item_ids.filtered(lambda r: r.user_id == user):
                item.sudo().write({'tag_ids': [(3, tag.id), (4, copy.id)]})
            split += 1

    _logger.info(
        '知识库：标签归属本人（回填 %s 个、拆出 %s 份、清掉 %s 个没人用的）',
        len(tag_ids) - dropped, split, dropped)
