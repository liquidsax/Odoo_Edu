"""由《53A 数学精讲册》知识点索引 xlsx 生成高中知识点默认数据 XML。

用法（在仓库根目录）：
    "E:/Odoo/python/python.exe" -X utf8 dev/gen_knowledge_data.py <知识点索引.xlsx> [输出.xml]

只取「知识点索引(总表)」表中 层级=考点 的行：同专题号的行归为一个专题节点，考点挂到该
节点下，年级统一 '13'（高中）。其余列（节号/题型/角度/书页码/PDF页）不进知识点库。
输出文件是模块的默认数据，可直接改；重跑会整体覆盖。
"""
import io
import re
import sys
from xml.sax.saxutils import escape

import openpyxl

SHEET = '知识点索引(总表)'
COL_TOPIC_NO, COL_TOPIC, COL_LEVEL, COL_NAME = 0, 1, 5, 6
LEVEL_POINT = '考点'
GRADE = '13'
GRADE_XML_ID = 'g13'
DEFAULT_OUT = 'server/addons/tutoring_center/data/knowledge_data.xml'

CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
    '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
}


def topic_no(value):
    """专题号是中文数字（一、二…），转成序号用于 ID 与排序。"""
    text = (value or '').strip()
    if text in CN_NUM:
        return CN_NUM[text]
    return int(re.sub(r'\D', '', text) or 0)


def read_rows(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    if ws.title != SHEET:
        raise SystemExit(f'第一个工作表应为「{SHEET}」，实际是「{ws.title}」')
    rows = []
    for row in list(ws.iter_rows(values_only=True))[1:]:
        name = (row[COL_NAME] or '').strip()
        if not name:
            continue
        rows.append((topic_no(row[COL_TOPIC_NO]), str(row[COL_TOPIC]).strip(),
                     row[COL_LEVEL], name))
    return rows


def build(rows):
    """返回 [(xml_id, name, parent_xml_id_or_None)]，专题在前、考点随后，保持原表顺序。"""
    topic_ids, topics, points = {}, [], []
    for no, topic, level, name in rows:
        if level != LEVEL_POINT:
            continue
        if topic not in topic_ids:
            topic_ids[topic] = f'kp_{GRADE_XML_ID}_topic_{no:02d}'
            topics.append((no, topic))
        points.append((topic, name))
    records = [(topic_ids[topic], topic, None) for _, topic in sorted(topics)]
    for idx, (topic, name) in enumerate(points, start=1):
        records.append((f'kp_{GRADE_XML_ID}_point_{idx:03d}', name, topic_ids[topic]))
    return records


def render(records, source):
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<odoo>',
        '    <!--',
        f'        高中数学默认知识点库，由 dev/gen_knowledge_data.py 从「{source}」生成。',
        '        树形：年级(高中) -> 专题 -> 考点，考点的 parent_id 指向所属专题。',
        '        noupdate=1：教师在本库上的改动（改名/归档/挂接）不会被模块升级覆盖。',
        '    -->',
        '    <data noupdate="1">',
    ]
    for xml_id, name, parent in records:
        lines.append(
            f'        <record id="{xml_id}" model="tutoring.knowledge.point">')
        lines.append(f'            <field name="name">{escape(name)}</field>')
        lines.append(f'            <field name="grade">{GRADE}</field>')
        if parent:
            lines.append(
                f'            <field name="parent_id" ref="{parent}"/>')
        lines.append('        </record>')
    lines += ['    </data>', '</odoo>', '']
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    source = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    records = build(read_rows(source))
    with io.open(out_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(render(records, source.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]))
    print('写入 %s：专题 %d 个，考点 %d 个' % (
        out_path, sum(1 for r in records if not r[2]),
        sum(1 for r in records if r[2])))


if __name__ == '__main__':
    main()
