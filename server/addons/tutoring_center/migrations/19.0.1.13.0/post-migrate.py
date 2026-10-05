import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """把已有标签归到"用它的人"名下（标签从共享字典改为按用户隔离）。

    共享字典是条隐私漏口：标签名本身就是"这个人在学什么"，别人在 m2one 补全
    列表里就能看见。现在三张表（条目/文件夹/标签）都挂"仅本人"的组规则。

    实际的活儿全在 `tutoring.library.tag._assign_owner_from_items()` 里，
    那边写清了为什么不能按 `user_id IS NULL` 找存量行。
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    moved, split, dropped = env['tutoring.library.tag'].sudo()._assign_owner_from_items()
    _logger.info(
        '知识库：标签归属本人（归位 %s 个、拆出 %s 份、清掉 %s 个没人用的）',
        moved, split, dropped)
