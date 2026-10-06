"""去掉错题上的「相关教学内容」(tutoring.mistake.topic_id)。

它和「知识点」(point_id) 是同一个意思的两份字典：topic 是扁平的 8 条初一章节名，
知识点是 103 条的树（年级→专题→考点）。错题上这个字段只有 1/14 条在用，而门户的
分组/筛选/搜索、年级校验、AI 摘要挑考点全都只认 point_id，所以把这一列去掉。

tutoring.topic 模型本身保留：课次的 topic_ids、考试明细行 required 的 topic_id 还在用。
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 先把"只填了教学内容、没填知识点"的错题按同名归到知识点上，避免静默丢信息。
    # 只在同名唯一匹配时才动，匹配到多条就留着空，宁缺勿错。
    cr.execute("""
        UPDATE tutoring_mistake m
           SET point_id = kp.id
          FROM tutoring_topic t
          JOIN tutoring_knowledge_point kp ON btrim(kp.name) = btrim(t.name)
         WHERE m.topic_id = t.id
           AND m.point_id IS NULL
           AND (SELECT count(*)
                  FROM tutoring_knowledge_point k2
                 WHERE btrim(k2.name) = btrim(t.name)) = 1
    """)
    moved = cr.rowcount

    # 剩下没映射上的（同名不唯一，或字典里根本没有这条知识点）数一下，别让它们无声消失
    cr.execute(
        "SELECT count(*) FROM tutoring_mistake "
        "WHERE topic_id IS NOT NULL AND point_id IS NULL"
    )
    left = cr.fetchone()[0]

    cr.execute("ALTER TABLE tutoring_mistake DROP COLUMN IF EXISTS topic_id")
    _logger.warning(
        '错题去掉「相关教学内容」：%d 条已按同名并入知识点，%d 条没能并入（留空）',
        moved, left,
    )
