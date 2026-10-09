{
    'name': 'R3ynA 学习平台',
    'version': '19.0.1.29.0',
    'category': 'Services',
    'summary': '个人学习数据平台：学生档案、课次、考试、错题与知识点，含学生/家长门户',
    'description': """
R3ynA 学习平台
==============
面向个人学习场景的数据记录与查看平台：

* 教师端：维护学生档案、教学内容、辅导课次、作业与考试成绩、错题与知识点
* 学生/家长端：门户账号登录，查看与自助记录自己的学习数据
* 多学生之间数据严格隔离
""",
    'author': 'Tutoring',
    'license': 'LGPL-3',
    'depends': ['portal', 'website', 'contacts'],
    'data': [
        'data/branding_data.xml',
        'security/tutoring_security.xml',
        'security/ir.model.access.csv',
        'data/mistake_data.xml',
        'data/mistake_cause_data.xml',
        'data/knowledge_data.xml',
        'data/self_profile_data.xml',
        'data/ai_job_data.xml',
        'views/tutoring_views.xml',
        'views/tutoring_library_views.xml',
        'views/partner_views.xml',
        'views/portal_templates.xml',
        'views/website_templates.xml',
        'views/menus_cleanup.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'tutoring_center/static/src/learning_charts.js',
            'tutoring_center/static/src/function_plot.js',
            'tutoring_center/static/src/function_plot.css',
            'tutoring_center/static/src/library_portal/*',
            'tutoring_center/static/src/library_viewer/*',
            'tutoring_center/static/src/library_preview/*',
            'tutoring_center/static/src/time_portal/*',
            # 代码块上色用站点自带的 Prism（web/static/lib/prismjs），不引第三方库。
            # 脚本在门户包里已经有了，缺的是这份主题 CSS
            'web/static/lib/prismjs/themes/default.css',
        ],
        'web.assets_backend': [
            'tutoring_center/static/src/fields/**/*',
            'tutoring_center/static/src/mistake_stats/*',
            'tutoring_center/static/src/mistake_kanban/*',
            'tutoring_center/static/src/library_upload/*',
            'tutoring_center/static/src/library_preview/*',
        ],
    },
    'installable': True,
    'application': True,
}
