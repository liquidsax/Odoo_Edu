{
    'name': '数学辅导数据中台',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': '一对一个性化数学辅导：学生档案、课次、作业、考试记录与学生/家长门户',
    'description': """
数学辅导数据中台
================
面向个人数学辅导场景的学习数据记录与查看平台：

* 教师端：维护学生档案、教学内容、辅导课次、作业与考试成绩
* 学生/家长端：门户账号登录，只读查看自己的学习数据（课次、作业、考试、趋势图）
* 多学生之间数据严格隔离
""",
    'author': 'Tutoring',
    'license': 'LGPL-3',
    'depends': ['portal', 'website'],
    'data': [
        'security/tutoring_security.xml',
        'security/ir.model.access.csv',
        'views/tutoring_views.xml',
        'views/partner_views.xml',
        'views/portal_templates.xml',
        'views/website_templates.xml',
        'views/menus_cleanup.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'tutoring_center/static/src/learning_charts.js',
        ],
    },
    'installable': True,
    'application': True,
}
