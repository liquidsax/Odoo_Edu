from odoo import _, api, fields, models

from .tutoring_knowledge import GRADE_SELECTION, SENIOR_HIGH


class TutoringStudent(models.Model):
    _name = 'tutoring.student'
    _description = '学生档案'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char('姓名', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='门户联系人', tracking=True,
        help='学生（或代学生查看的家长）用该联系人的门户账号登录，查看本学生的学习数据。')
    grade = fields.Selection(GRADE_SELECTION, string='年级', default='07', required=True, tracking=True)
    knowledge_grades = fields.Json('可选知识点年级', compute='_compute_knowledge_grades')
    school = fields.Char('学校')
    status = fields.Selection([
        ('active', '在读'), ('paused', '暂停'), ('done', '结课'),
    ], string='状态', default='active', required=True, tracking=True)
    remark = fields.Html('备注')
    is_self_profile = fields.Boolean(
        '本人档案', copy=False,
        help='老师本人那条学习档案（「我自己」）。它只属于他一个人：同事那边的学生列表、'
             '错题范围与「记到谁」下拉都不该出现它，见记录规则。')

    session_ids = fields.One2many('tutoring.session', 'student_id', string='辅导课次')
    homework_ids = fields.One2many('tutoring.homework', 'student_id', string='作业')
    exam_ids = fields.One2many('tutoring.exam', 'student_id', string='考试成绩')
    point_ids = fields.One2many('tutoring.student.point', 'student_id', string='知识点掌握')
    mistake_ids = fields.One2many('tutoring.mistake', 'student_id', string='错题记录')

    point_count = fields.Integer('需掌握知识点数', compute='_compute_point_stats')
    point_mastered_count = fields.Integer('已熟练掌握知识点数', compute='_compute_point_stats')
    mistake_count = fields.Integer('错题数', compute='_compute_stats')

    session_planned_count = fields.Integer(
        '总课次', tracking=True,
        help='本学期计划给该学生上的总节数。')
    session_count = fields.Integer('已上课次', compute='_compute_stats')
    homework_count = fields.Integer('作业数', compute='_compute_stats')
    homework_open_count = fields.Integer('待完成作业', compute='_compute_stats')
    homework_avg = fields.Float('作业平均正确率(%)', compute='_compute_stats', aggregator='avg')
    exam_count = fields.Integer('考试数', compute='_compute_stats')
    exam_avg = fields.Float('考试平均得分率(%)', compute='_compute_stats', aggregator='avg')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('partner_id'):
                vals['partner_id'] = self.env['res.partner'].create({
                    'name': vals.get('name') or _('新学生'),
                }).id
        return super().create(vals_list)

    # 老师本人也是学习者：他刷过的题、做错的题也要能进这套系统，而错题必须挂在
    # 某个学习档案下（student_id 必填）。与其为"老师记的题"再发明一套归属，
    # 不如给他一条自己的档案——这张表的中文描述本来就是"学习档案"。
    SELF_PROFILE_NAME = '我自己'
    SELF_PROFILE_GRADE = '13'   # 高中那层（跨高一~高三），成年人自学最贴近；后台可改

    @api.model
    def ensure_self_profile(self, user):
        """取（没有就建）某个用户本人的学习档案，联系人指向他自己的联系人。

        门户那边 `_tutoring_student()` 是按 `partner_id` 查的，所以建好之后
        他打开 /my/mistakes 就能直接"记到自己名下"，不用先去找后台。
        """
        if not user or not user.partner_id:
            return self.browse()
        existing = self.sudo().search(
            [('partner_id', '=', user.partner_id.id)], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'name': self.SELF_PROFILE_NAME,
            'partner_id': user.partner_id.id,
            'grade': self.SELF_PROFILE_GRADE,
            'is_self_profile': True,
            'remark': _('老师本人的学习档案：自己刷过的题、做错的题记在这里。'),
        })

    @api.model
    def mark_self_profiles(self):
        """给升级之前就存在的本人档案补上标记（数据文件里的 <function> 调它）。

        判据只认「名字是『我自己』+ 联系人身上挂着教师组账号 + 这条还没标记」，
        所以手工建的学生就算也叫这个名，不会被误标成私人档案。
        """
        teacher = self.env.ref('tutoring_center.group_teacher', raise_if_not_found=False)
        if not teacher:
            return 0
        rows = self.sudo().search([
            ('name', '=', self.SELF_PROFILE_NAME),
            ('is_self_profile', '=', False),
            ('partner_id.user_ids', 'in', teacher.user_ids.ids),
        ])
        rows.write({'is_self_profile': True})
        return len(rows)

    @api.model
    def ensure_teacher_profiles(self):
        """给每一位在册的老师补一条本人档案（数据文件里的 <function> 调它）。

        放在数据阶段而不是迁移脚本里，是因为**全新安装也会跑数据**：
        装好模块的第一分钟老师就能记自己的错题，不用等一次升级。
        """
        teacher = self.env.ref('tutoring_center.group_teacher', raise_if_not_found=False)
        if not teacher:
            return 0
        made = 0
        for user in teacher.user_ids.filtered(lambda u: u.active and u.partner_id):
            before = self.sudo().search_count([('partner_id', '=', user.partner_id.id)])
            self.ensure_self_profile(user)
            made += 1 if not before else 0
        return made

    def _compute_stats(self):
        for student in self:
            homework = student.homework_ids
            reviewed = homework.filtered(lambda h: h.state == 'reviewed' and h.question_count)
            student.session_count = len(student.session_ids)
            student.homework_count = len(homework)
            student.homework_open_count = len(homework.filtered(lambda h: h.state == 'draft'))
            student.homework_avg = (
                sum(h.accuracy for h in reviewed) / len(reviewed) if reviewed else 0.0)
            student.exam_count = len(student.exam_ids)
            scored = student.exam_ids.filtered(lambda e: e.total_full)
            student.exam_avg = (
                sum(e.percentage for e in scored) / len(scored) if scored else 0.0)
            student.mistake_count = len(student.mistake_ids)

    def _compute_point_stats(self):
        for student in self:
            student.point_count = len(student.point_ids)
            student.point_mastered_count = len(
                student.point_ids.filtered(lambda p: p.mastery == 'mastered'))

    def _compute_knowledge_grades(self):
        # 供学生表单挑知识点的域使用：高一~高三额外放开整个高中知识点库。
        for student in self:
            grades = [student.grade]
            if student.grade in ('10', '11', '12'):
                grades.append(SENIOR_HIGH)
            student.knowledge_grades = grades

    def action_view_partner(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('门户联系人'),
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
