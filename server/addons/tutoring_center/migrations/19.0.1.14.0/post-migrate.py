import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.tutoring_center.models.tutoring_library_item import (
    MARKDOWN_EXTS, TEXT_EXTS)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """重算 `kind`：这次新增了 markdown / text 两档，存量行还停在 other。

    存储型计算字段不会因为"计算逻辑多了一个分支"就自己重算，必须点名。
    只挑文本类后缀的行，所以不会顺手把教材 PDF 的正文读进内存
    （业务库里那个 60KB 的 .json 就是这种存量行）。
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Item = env['tutoring.library.item']
    exts = sorted(set(MARKDOWN_EXTS) | set(TEXT_EXTS))
    todo = Item.sudo().search([('kind', '=', 'other'), ('ext', 'in', exts)])
    if not todo:
        return
    env.add_to_compute(Item._fields['kind'], todo)
    env.flush_all()
    _logger.info('知识库：%s 个文本/Markdown 条目重算了预览方式', len(todo))
