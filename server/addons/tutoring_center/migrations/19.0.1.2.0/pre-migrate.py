def migrate(cr, version):
    """年级键值补零：'7'/'8'/'9' -> '07'/'08'/'09'。

    只改显示名不够——年级在库里是字符串，知识点列表的 _order 和「按年级分组」
    都按字符串比较，新增的 '10'~'12'（高一~高三）会排在初中之前。补零后
    '07'<'08'<'09'<'10'<'11'<'12'，顺序自然正确。可重复执行。
    """
    for table in ('tutoring_student', 'tutoring_knowledge_point'):
        cr.execute(
            "UPDATE %s SET grade = lpad(grade, 2, '0') WHERE grade IN ('7', '8', '9')"
            % table
        )
