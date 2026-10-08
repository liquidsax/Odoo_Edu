import base64
import json
from urllib.parse import quote, urlencode

from odoo import _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Date
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager

from ..models.tutoring_knowledge import GRADE_LABEL
from ..models.tutoring_mistake import split_question_numbers
from .library import SAFE_FILENAME


class TutoringPortal(CustomerPortal):

    def _tutoring_student(self):
        """当前门户用户绑定的学生档案（记录规则已按门户联系人过滤）。"""
        return request.env['tutoring.student'].search(
            [('partner_id', '=', request.env.user.partner_id.id)], limit=1)

    def home(self, **kw):
        """已绑定学习档案的**门户用户**，访问 /my 直接进入学习页。

        内部用户（老师）现在也有一条"我自己"的档案，但他不该因此被丢到自己的
        空看板上去——他要的是那张卡片页（错题 / 教材 / 知识库都在里面）。
        """
        if self._tutoring_student() and not request.env.user._is_internal():
            return request.redirect('/my/learning')
        return super().home(**kw)

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        student = self._tutoring_student()
        if 'tutoring_session_count' in counters:
            values['tutoring_session_count'] = (
                request.env['tutoring.session'].search_count([('student_id', '=', student.id)])
                if student and request.env['tutoring.session'].has_access('read') else 0)
        if 'tutoring_mistake_count' in counters:
            # 不按"当前账号绑定的学生"算：老师/维护者自己没有学生档案，那样永远是 0，
            # 而核心的 portal_docs_entry 见计数 0 就把卡片 d-none 掉——错题入口会整体消失。
            # search_count([]) 配合记录规则正好等于"我能读到多少条错题"。
            values['tutoring_mistake_count'] = (
                request.env['tutoring.mistake'].search_count([])
                if request.env['tutoring.mistake'].has_access('read') else 0)
        if 'tutoring_workbook_count' in counters:
            values['tutoring_workbook_count'] = (
                len(self._tutoring_workbooks(student))
                if student and request.env['tutoring.workbook'].has_access('read') else 0)
        if 'tutoring_library_count' in counters:
            values['tutoring_library_count'] = (
                request.env['tutoring.library.item'].search_count(
                    [('user_id', '=', request.env.user.id)])
                if request.env['tutoring.library.item'].has_access('read') else 0)
        if 'tutoring_time_count' in counters:
            # 同样不按学生档案算：时间账本挂的是登录用户，老师本人也有自己的一份
            values['tutoring_time_count'] = (
                request.env['tutoring.time.task'].search_count([])
                if request.env['tutoring.time.task'].has_access('read') else 0)
        return values

    # ------------------------------------------------------------
    # 我的学习总览
    # ------------------------------------------------------------

    def _tutoring_dashboard_values(self, student):
        today = Date.context_today(student)
        exams = student.exam_ids.sorted(key=lambda e: (e.date or Date.MIN, e.id))[-10:]
        sessions = student.session_ids.sorted(key=lambda s: (s.date or Date.MIN, s.id))
        upcoming_sessions = sessions.filtered(lambda s: s.date and s.date >= today)[:5]
        recent_sessions = sessions.filtered(lambda s: not s.date or s.date < today)[-5:]
        points = student.point_ids.sorted(key=lambda p: (p.point_id.grade, p.point_id.name))

        return {
            'student': student,
            'upcoming_sessions': upcoming_sessions,
            'recent_sessions': recent_sessions,
            'recent_exams': student.exam_ids[:5],
            'exam_avg': student.exam_avg,
            'mistakes': student.mistake_ids[:5],
            'mistake_count': student.mistake_count,
            'difficulty_labels': dict(request.env['tutoring.mistake']._fields['difficulty'].selection),
            'points': points,
            'mastery_labels': dict(
                request.env['tutoring.student.point']._fields['mastery'].selection),
            'exam_chart_data': json.dumps({
                'labels': [e.name for e in exams],
                'datasets': [{
                    'label': _('得分率(%)'),
                    'data': [round(e.percentage, 1) for e in exams],
                    'fill': False,
                    'tension': 0.3,
                    'borderColor': '#714B67',
                    'backgroundColor': '#714B67',
                }],
            }),
        }

    @http.route('/my/learning', type='http', auth='user', website=True)
    def portal_my_learning(self, **kwargs):
        student = self._tutoring_student()
        if not student:
            # 未关联学生档案的账号（如教师本人）：显示提示页，不再跳回 /my
            return request.render('tutoring_center.portal_my_learning_empty',
                                  {'page_name': 'learning'})
        values = self._tutoring_dashboard_values(student)
        values.update({
            'page_name': 'learning',
            'exam_types': dict(request.env['tutoring.exam']._fields['exam_type'].selection),
        })
        return request.render('tutoring_center.portal_my_learning', values)

    # ------------------------------------------------------------
    # 辅导课次
    # ------------------------------------------------------------

    @http.route('/my/learning/sessions', type='http', auth='user', website=True)
    def portal_my_sessions(self, sortby=None, page=1, **kwargs):
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        values = self._tutoring_list_values(
            student.session_ids, sortby, page,
            sortings={
                'date': {
                    'label': _('最新上课'),
                    'key': lambda r: (r.date or Date.MIN, r.id), 'reverse': True,
                },
                'date_asc': {
                    'label': _('最早上课'),
                    'key': lambda r: (r.date or Date.MAX, r.id), 'reverse': False,
                },
            },
            url='/my/learning/sessions',
        )
        values.update({
            'page_name': 'tutoring_sessions',
            'sessions': values.pop('records'),
        })
        return request.render('tutoring_center.portal_my_learning_sessions', values)

    @http.route('/my/learning/sessions/<int:session_id>', type='http', auth='user', website=True)
    def portal_my_session(self, session_id, **kwargs):
        session = request.env['tutoring.session'].browse(session_id).exists()
        if not session or not session.has_access('read'):
            return request.not_found()
        return request.render('tutoring_center.portal_my_learning_session', {
            'page_name': 'tutoring_sessions',
            'session': session,
        })

    # ------------------------------------------------------------
    # 作业
    # ------------------------------------------------------------

    @http.route('/my/learning/homework', type='http', auth='user', website=True)
    def portal_my_homework(self, sortby=None, filterby=None, page=1, **kwargs):
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        searchbar_filters = {
            'all': {'label': _('全部'), 'domain': []},
            'draft': {'label': _('待完成'), 'domain': [('state', '=', 'draft')]},
            'done': {'label': _('已完成'), 'domain': [('state', '=', 'done')]},
            'reviewed': {'label': _('已批改'), 'domain': [('state', '=', 'reviewed')]},
        }
        if not filterby or filterby not in searchbar_filters:
            filterby = 'all'
        records = request.env['tutoring.homework'].search(
            [('student_id', '=', student.id)] + searchbar_filters[filterby]['domain'])
        values = self._tutoring_list_values(
            records, sortby, page,
            sortings={
                'assigned': {
                    'label': _('最新布置'),
                    'key': lambda r: (r.assigned_date or Date.MIN, r.id), 'reverse': True,
                },
                'assigned_asc': {
                    'label': _('最早布置'),
                    'key': lambda r: (r.assigned_date or Date.MAX, r.id), 'reverse': False,
                },
                'due': {
                    'label': _('按截止日期'),
                    'key': lambda r: (r.due_date or Date.MAX, r.id), 'reverse': False,
                },
            },
            url='/my/learning/homework', filterby=filterby, searchbar_filters=searchbar_filters,
        )
        values.update({
            'page_name': 'tutoring_homework',
            'homeworks': values.pop('records'),
            'states': dict(request.env['tutoring.homework']._fields['state'].selection),
        })
        return request.render('tutoring_center.portal_my_learning_homework', values)

    @http.route('/my/learning/homework/<int:homework_id>', type='http', auth='user', website=True)
    def portal_my_homework_detail(self, homework_id, **kwargs):
        homework = request.env['tutoring.homework'].browse(homework_id).exists()
        if not homework or not homework.has_access('read'):
            return request.not_found()
        return request.render('tutoring_center.portal_my_learning_homework_detail', {
            'page_name': 'tutoring_homework',
            'homework': homework,
            'states': dict(request.env['tutoring.homework']._fields['state'].selection),
        })

    # ------------------------------------------------------------
    # 考试
    # ------------------------------------------------------------

    @http.route('/my/learning/exams', type='http', auth='user', website=True)
    def portal_my_exams(self, sortby=None, filterby=None, page=1, **kwargs):
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        exam_type_selection = request.env['tutoring.exam']._fields['exam_type'].selection
        searchbar_filters = {'all': {'label': _('全部'), 'domain': []}}
        for key, label in exam_type_selection:
            searchbar_filters[key] = {
                'label': label, 'domain': [('exam_type', '=', key)]}
        if not filterby or filterby not in searchbar_filters:
            filterby = 'all'
        records = request.env['tutoring.exam'].search(
            [('student_id', '=', student.id)] + searchbar_filters[filterby]['domain'])
        values = self._tutoring_list_values(
            records, sortby, page,
            sortings={
                'date': {
                    'label': _('最新考试'),
                    'key': lambda r: (r.date or Date.MIN, r.id), 'reverse': True,
                },
                'date_asc': {
                    'label': _('最早考试'),
                    'key': lambda r: (r.date or Date.MAX, r.id), 'reverse': False,
                },
            },
            url='/my/learning/exams', filterby=filterby, searchbar_filters=searchbar_filters,
        )
        values.update({
            'page_name': 'tutoring_exams',
            'exams': values.pop('records'),
            'exam_types': dict(exam_type_selection),
        })
        return request.render('tutoring_center.portal_my_learning_exams', values)

    @http.route('/my/learning/exams/<int:exam_id>', type='http', auth='user', website=True)
    def portal_my_exam_detail(self, exam_id, **kwargs):
        exam = request.env['tutoring.exam'].browse(exam_id).exists()
        if not exam or not exam.has_access('read'):
            return request.not_found()
        return request.render('tutoring_center.portal_my_learning_exam_detail', {
            'page_name': 'tutoring_exams',
            'exam': exam,
            'exam_types': dict(request.env['tutoring.exam']._fields['exam_type'].selection),
        })

    # ------------------------------------------------------------
    # 错题
    # ------------------------------------------------------------

    MISTAKE_PAGE_SIZES = (10, 20, 50)
    # 分组视图必须跨页才有意义（"这个知识点下一共错了哪几道"），所以一次多取些；
    # 但不封顶就又回到以前那种"全量捞进内存"，所以给个上限并如实告诉用户被截断了。
    MISTAKE_GROUP_LIMIT = 400
    MISTAKE_GROUP_PREVIEW = 8

    def _mistake_sortings(self):
        return {
            # 默认顺序就是复习队列：到期最早的排最前，学生不需要知道机制。
            # next_review_at 在升级时已给存量行回填，不会因 NULL 而沉底。
            'review': {'label': _('该看的先看到'), 'order': 'next_review_at asc, id asc'},
            'recorded': {'label': _('最新记录'), 'order': 'create_date desc, id desc'},
            'date': {'label': _('发生日期（新→旧）'), 'order': 'date desc, id desc'},
            'date_asc': {'label': _('发生日期（旧→新）'), 'order': 'date asc, id asc'},
            'hard': {'label': _('难度（高→低）'), 'order': 'difficulty desc, date desc, id desc'},
        }

    def _mistake_filters(self, month_start):
        return {
            'all': {'label': _('全部'), 'domain': []},
            'month': {'label': _('本月'), 'domain': [('date', '>=', month_start)]},
            'hard': {'label': _('高难度'), 'domain': [('difficulty', 'in', ['4', '5'])]},
            'no_cause': {'label': _('未标错因'), 'domain': [('cause_id', '=', False)]},
            'no_point': {'label': _('未选知识点'), 'domain': [('point_id', '=', False)]},
        }

    def _mistake_groupbys(self):
        return {
            '': {'label': _('平铺')},
            'point': {'label': _('按知识点'), 'field': 'point_id'},
            'cause': {'label': _('按错因'), 'field': 'cause_id'},
            'month': {'label': _('按月份'), 'field': 'date'},
        }

    @staticmethod
    def _browse_allowed(model_name, raw_id):
        """按 id 取记录，取不到或读不了就回空集——门户表单里的 id 是不可信输入。"""
        empty = request.env[model_name].browse()
        try:
            rec_id = int(raw_id)
        except (TypeError, ValueError):
            return empty
        rec = request.env[model_name].browse(rec_id).exists()
        return rec if rec and rec.has_access('read') else empty

    def _mistake_search_domain(self, term):
        return [
            '|', '|', '|', '|', '|',
            ('page', 'ilike', term),
            ('question_no', 'ilike', term),
            ('note', 'ilike', term),
            ('workbook_id.name', 'ilike', term),
            ('point_id.name', 'ilike', term),
            ('cause_id.name', 'ilike', term),
        ]

    def _mistake_filter_counts(self, base_domain, month_start):
        """筛选药丸上的计数：三维各一次 read_group，替掉逐个 search_count。"""
        Mistake = request.env['tutoring.mistake']
        counts = {
            'all': 0, 'hard': 0, 'no_cause': 0, 'no_point': 0,
            'month': Mistake.search_count(base_domain + [('date', '>=', month_start)]),
        }
        for difficulty, count in Mistake._read_group(base_domain, ['difficulty'], ['__count']):
            counts['all'] += count
            if difficulty in ('4', '5'):
                counts['hard'] += count
        for cause, count in Mistake._read_group(base_domain, ['cause_id'], ['__count']):
            if not cause:
                counts['no_cause'] += count
        for point, count in Mistake._read_group(base_domain, ['point_id'], ['__count']):
            if not point:
                counts['no_point'] += count
        return counts

    def _mistake_point_groups(self, student):
        """按学生年级放开知识点，并带上上级专题给门户下拉的 optgroup 用。"""
        grades = student.knowledge_grades or [student.grade]
        groups, by_parent = [], {}
        for point in request.env['tutoring.knowledge.point'].search([('grade', 'in', grades)]):
            # 枝干层（无上级）按年级各自成组，否则高一和"高中"的散点会混进同一组
            key = (point.parent_id.id, point.grade)
            if key not in by_parent:
                by_parent[key] = {
                    'label': point.parent_id.name or GRADE_LABEL.get(point.grade) or _('其它'),
                    'points': []}
                groups.append(by_parent[key])
            by_parent[key]['points'].append(point)
        return groups

    def _mistake_groups(self, records, groupby, base_args):
        """把取到的记录切成"分组标题 + 该组卡片"，标题本身就是下钻入口。

        下钻链接在这里拼而不是在模板里：模板里要拿 keep_query 反推"去掉 groupby、
        加上这一组"，写出来既难读又容易把别的筛选条件弄丢。
        """
        spec = self._mistake_groupbys()[groupby]
        field = spec['field']
        empty_labels = {
            'point_id': _('未选知识点'), 'cause_id': _('未标错因'), 'date': _('未填日期'),
        }
        groups, index = [], {}
        for rec in records:
            if field == 'date':
                key = rec.date.strftime('%Y-%m') if rec.date else ''
                label = key or empty_labels[field]
                drill_id = None
            else:
                related = rec[field]
                key = related.id
                label = related.name or empty_labels[field]
                drill_id = related.id or None
            if key not in index:
                args = dict(base_args, groupby='')
                if drill_id:
                    args[field] = drill_id
                index[key] = {
                    'label': label,
                    'records': [],
                    'url': '/my/mistakes?%s' % urlencode(args),
                }
                groups.append(index[key])
            index[key]['records'].append(rec)
        for group in groups:
            group['total'] = len(group['records'])
            group['hidden'] = max(group['total'] - self.MISTAKE_GROUP_PREVIEW, 0)
            group['records'] = group['records'][:self.MISTAKE_GROUP_PREVIEW]
        return groups

    def _mistake_form_from_post(self, post):
        """速记条/编辑表单校验失败时的回填值（不让用户重打一遍）。"""
        def _to_int(val):
            try:
                return int(val) if val else False
            except (TypeError, ValueError):
                return False
        return {
            'workbook_id': _to_int(post.get('workbook_id')),
            'student_id': _to_int(post.get('student_id')),
            'page': post.get('page') or '',
            'question_no': post.get('question_no') or '',
            'cause_id': _to_int(post.get('cause_id')),
            'point_id': _to_int(post.get('point_id')),
            'difficulty': post.get('difficulty') or '3',
            'date': post.get('date') or '',
            'note': post.get('note') or '',
        }

    def _mistake_form_values(self, student, mistake=None, post=None):
        """错题新增/编辑表单的公共渲染值。form 为回填用的当前值字典。"""
        Mistake = request.env['tutoring.mistake']
        if post:
            form = self._mistake_form_from_post(post)
        elif mistake:
            form = {
                'workbook_id': mistake.workbook_id.id or False,
                'page': mistake.page or '',
                'question_no': mistake.question_no or '',
                'cause_id': mistake.cause_id.id or False,
                'point_id': mistake.point_id.id or False,
                'difficulty': mistake.difficulty or '3',
                'date': str(mistake.date) if mistake.date else '',
                'note': mistake.note or '',
            }
        else:
            form = {'workbook_id': False, 'page': '', 'question_no': '',
                    'cause_id': False, 'point_id': False, 'difficulty': '3', 'date': '',
                    'note': ''}

        return {
            'page_name': 'tutoring_mistakes',
            'student': student,
            'mistake': mistake,
            'form': form,
            'workbooks': request.env['tutoring.workbook'].search([]),
            'causes': request.env['tutoring.mistake.cause'].search([]),
            'point_groups': self._mistake_point_groups(student) if student else [],
            'difficulties': Mistake._fields['difficulty'].selection,
        }

    def _mistake_vals_from_post(self, student, kw):
        """从门户表单提交构造错题 vals；student_id 一律用本人，绝不取表单值。"""
        def _to_int(name):
            raw = kw.get(name)
            try:
                return int(raw) if raw else False
            except (TypeError, ValueError):
                return False
        vals = {
            'student_id': student.id,
            'workbook_id': _to_int('workbook_id'),
            'page': (kw.get('page') or '').strip() or False,
            'question_no': (kw.get('question_no') or '').strip() or False,
            'difficulty': kw.get('difficulty') if kw.get('difficulty') in ('2', '3', '4', '5') else '3',
            'note': (kw.get('note') or '').strip() or False,
        }
        cause = self._browse_allowed('tutoring.mistake.cause', kw.get('cause_id'))
        if cause:
            vals['cause_id'] = cause.id
        point = self._browse_allowed('tutoring.knowledge.point', kw.get('point_id'))
        # 年级域在服务端再校一次：下拉里看不到别的年级，不代表 POST 里塞不进来
        if point and point.grade in (student.knowledge_grades or [student.grade]):
            vals['point_id'] = point.id
        if kw.get('date'):
            vals['date'] = kw.get('date')
        return vals

    @http.route('/my/mistakes', type='http', auth='user', website=True)
    def portal_my_mistakes(self, **kwargs):
        """顶栏「错题」独立页：速记条 + 带计数的筛选药丸 + 卡片列表。

        老师/维护者看的是"哪个学生的错题"可切换的页面（`?scope=`），
        学生账号只有一份可读档案，切换器对他自然只剩自己，不必特判。
        """
        return request.render(
            'tutoring_center.portal_my_mistakes', self._mistake_page_values(kwargs))

    def _mistake_scope(self, kwargs):
        """解析 `?scope=` → (列表用的域, 当前档案, 范围键, 可切换的档案列表)。

        `mine`＝自己那份档案（老师是"我自己"，学生是他的学生档案），
        `all`＝当前账号能读到的全部，数字＝某个学生。
        能选到谁由 `tutoring.student` 的记录规则说话：门户只有一份，教师全都有。
        """
        Student = request.env['tutoring.student']
        own = self._tutoring_student()
        readable = Student.search([])
        raw = (kwargs.get('scope') or '').strip()
        if raw.isdigit():
            picked = readable.filtered(lambda s: s.id == int(raw))[:1]
            if picked:
                return ([('student_id', '=', picked.id)], picked,
                        str(picked.id), readable)
            raw = ''
        if not raw:
            raw = 'mine' if own else 'all'
        if raw == 'mine' and own:
            return [('student_id', '=', own.id)], own, 'mine', readable
        # 没有本人档案（迁移会给每个老师补一条，这里是兜底）：退回"全部可读"，
        # 别把页面卡在一个空范围上
        return [], Student.browse(), 'all', readable

    def _mistake_page_values(self, kwargs=None, form=None, error=None):
        """/my/mistakes 取数：域内分页 + 白名单排序；速记条校验失败时带 form/error 复用同一页。"""
        kwargs = kwargs or {}
        Mistake = request.env['tutoring.mistake']
        base_domain, student, scope_key, readable = self._mistake_scope(kwargs)
        # 速记条默认记到谁：当前范围选中的档案 > 自己的档案 > 第一个能读的档案
        form_student = student or self._tutoring_student() or readable[:1]
        today = fields.Date.context_today(request.env.user)
        month_start = today.replace(day=1)

        filters = self._mistake_filters(month_start)
        filterby = kwargs.get('filterby') if kwargs.get('filterby') in filters else 'all'
        sortings = self._mistake_sortings()
        sortby = kwargs.get('sortby') if kwargs.get('sortby') in sortings else 'review'
        groupbys = self._mistake_groupbys()
        groupby = kwargs.get('groupby') if kwargs.get('groupby') in groupbys else ''
        page_sizes = self.MISTAKE_PAGE_SIZES
        page_size = next((n for n in page_sizes if str(n) == str(kwargs.get('limit'))), 10)
        try:
            page = max(int(kwargs.get('page') or 1), 1)
        except (TypeError, ValueError):
            page = 1

        domain = base_domain + filters[filterby]['domain']
        term = (kwargs.get('search') or '').strip()
        if term:
            domain += self._mistake_search_domain(term)
        drilldowns = []
        for field, model, label in (('point_id', 'tutoring.knowledge.point', _('知识点')),
                                    ('cause_id', 'tutoring.mistake.cause', _('错因'))):
            rec = self._browse_allowed(model, kwargs.get(field))
            if rec:
                domain.append((field, '=', rec.id))
                drilldowns.append({'field': field, 'label': label,
                                   'value': rec.name, 'id': rec.id})

        url_args = {'sortby': sortby, 'filterby': filterby, 'limit': page_size,
                    'scope': scope_key}
        if groupby:
            url_args['groupby'] = groupby
        if term:
            url_args['search'] = term
        for drill in drilldowns:
            url_args[drill['field']] = drill['id']
            drill['remove_url'] = '/my/mistakes?%s' % urlencode(
                {k: v for k, v in url_args.items() if k != drill['field']})

        order = sortings[sortby]['order']
        groups = []
        if groupby:
            # 分组看的是"这一类一共有哪些"，分页会把一组拆两页，所以改成封顶取一次
            records = Mistake.search(domain, order=order, limit=self.MISTAKE_GROUP_LIMIT)
            base_args = {k: v for k, v in url_args.items() if k != 'groupby'}
            groups = self._mistake_groups(records, groupby, base_args)
            pager = None
            total = len(records)
        else:
            total = Mistake.search_count(domain)
            pager = portal_pager(
                url='/my/mistakes', url_args=url_args,
                total=total, page=page, step=page_size)
            records = Mistake.search(
                domain, order=order, limit=page_size, offset=(page - 1) * page_size)

        last_mistake = Mistake.search(base_domain, limit=1, order='create_date desc, id desc')
        try:
            created_count = int(kwargs.get('created') or 0)
        except (TypeError, ValueError):
            created_count = 0
        return {
            'page_name': 'tutoring_mistakes',
            'student': form_student,
            'scope_key': scope_key,
            'scope_students': readable,
            # 「我自己」那颗药丸是单独画的那颗（scope=mine），循环里再出现一次就成了两颗
            'other_students': readable - self._tutoring_student(),
            'mistakes': records,
            'result_total': total,
            'groups': groups,
            'group_truncated': bool(groupby) and len(records) >= self.MISTAKE_GROUP_LIMIT,
            'group_preview': self.MISTAKE_GROUP_PREVIEW,
            'group_limit': self.MISTAKE_GROUP_LIMIT,
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'filterby': filterby,
            'searchbar_filters': filters,
            'groupby': groupby,
            'searchbar_groupbys': groupbys,
            'default_url': '/my/mistakes',
            'search': term,
            'page_size': page_size,
            'page_sizes': page_sizes,
            'url_args': url_args,
            'difficulty_labels': dict(Mistake._fields['difficulty'].selection),
            'difficulties': list(Mistake._fields['difficulty'].selection),
            'filter_counts': self._mistake_filter_counts(base_domain, month_start),
            'drilldowns': drilldowns,
            # 速记条要往某个档案下写，所以"有可读档案"才给建（老师现在有自己的那份）
            'can_create': bool(readable) and Mistake.has_access('create'),
            # 跨档案浏览（scope=all）时卡片上要带档案名，否则分不清是谁的错题
            'show_student': scope_key == 'all',
            'default_workbook': last_mistake.workbook_id if last_mistake else False,
            'default_date': today.strftime('%Y-%m-%d'),
            'created_count': created_count,
            'form': form or {},
            'error': error,
            'workbooks': request.env['tutoring.workbook'].search([]),
            'causes': request.env['tutoring.mistake.cause'].search([]),
            'point_groups': self._mistake_point_groups(form_student) if form_student else [],
        }

    @http.route('/my/learning/mistakes', type='http', auth='user', website=True)
    def portal_my_mistakes_redirect(self, **kwargs):
        """旧列表入口并入顶栏错题页。"""
        return request.redirect('/my/mistakes')

    @http.route('/my/learning/mistakes/<int:mistake_id>', type='http', auth='user', website=True)
    def portal_my_mistake_detail(self, mistake_id, **kwargs):
        mistake = request.env['tutoring.mistake'].browse(mistake_id).exists()
        if not mistake or not mistake.has_access('read'):
            return request.not_found()
        if mistake.has_access('write'):
            # 打开一次＝复习过一次：排期自己往后推，界面上不留任何"复习"痕迹
            mistake.touch_review()
        return request.render('tutoring_center.portal_my_learning_mistake_detail', {
            'page_name': 'tutoring_mistakes',
            'mistake': mistake,
            'difficulty_labels': dict(request.env['tutoring.mistake']._fields['difficulty'].selection),
            'can_edit': mistake.has_access('write'),
            # 错题的固有属性之一：题目照片/说明就挂在知识库上，这一页要能看能加
            'library_items': mistake.library_item_ids.sorted('upload_date desc'),
            'quota': request.env['tutoring.library.item'].quota_state(),
            'just_saved': bool(kwargs.get('created') or kwargs.get('saved')),
            'just_attached': bool(kwargs.get('attached')),
            # 额度只拿来写提示，真正的拦截在任务模型的 create 里（越权/超额都那儿报）
            'quota_left': (request.env['tutoring.mistake.ai.job'].quota_left()
                           if mistake.can_ai_summary else None),
        })

    @http.route('/my/learning/mistakes/<int:mistake_id>/attach', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_mistake_attach(self, mistake_id, **kw):
        """给这道错题传一张题目照片/说明文件：落进知识库，分类固定错题，绑回本条。

        错题本身还是记在 tutoring.mistake 里，这里只是把"题目长什么样"当附件收进来；
        条目归属当前账号（学生传的就归学生），所以别人在知识库里看不到。
        """
        mistake = request.env['tutoring.mistake'].search([('id', '=', mistake_id)], limit=1)
        if not mistake:
            return request.not_found()
        model = request.env['tutoring.library.item']
        uploads = request.httprequest.files.getlist('file')[:5]
        attached, errors = 0, []
        for upload in uploads:
            filename = upload.filename or ''
            try:
                model.create({
                    'name': (kw.get('title') or '').strip() or filename.rpartition('.')[0] or _('错题照片'),
                    'filename': filename,
                    'content': base64.b64encode(upload.read()).decode(),
                    'category': 'mistake',
                    'mistake_id': mistake.id,
                    'tag_ids': model.tags_from_names(kw.get('tags')),
                })
                request.env.cr.commit()
                attached += 1
            except UserError as err:
                request.env.cr.rollback()
                errors.append(str(err))
        query = ['attached=%s' % attached if attached else 'error=%s' % quote(' '.join(errors)[:200])]
        return request.redirect('/my/learning/mistakes/%d?%s' % (mistake.id, query[0]))

    @http.route('/my/learning/mistakes/<int:mistake_id>/ai_summary', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_mistake_ai_summary(self, mistake_id, **kw):
        """发起一次 AI 摘要：只建任务，真正调用交给 ir.cron。

        一题一次、每人每天五条，都由 `tutoring.mistake.ai.job.create()` 说话；
        这里只负责把它的报错原样带回那一页显示。
        """
        mistake = request.env['tutoring.mistake'].search([('id', '=', mistake_id)], limit=1)
        if not mistake:
            return request.not_found()
        try:
            request.env['tutoring.mistake.ai.job'].create({'mistake_id': mistake.id})
        except ValidationError as err:
            return request.redirect('/my/learning/mistakes/%d?error=%s'
                                    % (mistake.id, quote(str(err)[:200])))
        return request.redirect('/my/learning/mistakes/%d?ai_queued=1' % mistake.id)

    @http.route('/my/learning/mistakes/<int:mistake_id>/note', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_my_mistake_note(self, mistake_id, **kw):
        """详情页里就地补一句想法：只动补充说明，不必跳去整张编辑表重填。"""
        mistake = request.env['tutoring.mistake'].browse(mistake_id).exists()
        if not mistake or not mistake.has_access('write'):
            return request.not_found()
        mistake.write({'note': (kw.get('note') or '').strip() or False})
        return request.redirect('/my/learning/mistakes/%d?saved=1' % mistake.id)

    def _mistake_target_student(self, kw):
        """速记条/编辑条要写到的那份档案：优先用表单选的，其次自己的，再其次第一个可读的。

        选的 id 必须过 `search`（记录规则会把别人家的档案滤掉），不能信前端传来的数字。
        """
        Student = request.env['tutoring.student']
        picked = Student.browse()
        raw = (kw.get('student_id') or '').strip() if isinstance(kw.get('student_id'), str) \
            else kw.get('student_id')
        if str(raw or '').isdigit():
            picked = Student.search([('id', '=', int(raw))], limit=1)
        return picked or self._tutoring_student() or Student.search([], limit=1)

    @http.route('/my/learning/mistakes/new', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_my_mistake_new(self, **kw):
        """记错题入口：GET 直接进顶栏错题页的速记条；POST 支持题号 1-5 拆多条。

        老师也能记自己的题——他有一份"我自己"的档案，速记条上的"记到谁"下拉
        默认就落在那份上，也可以选别的学生。
        """
        student = self._mistake_target_student(kw)
        if not student:
            values = self._mistake_page_values(
                kw, error=_('还没有可记录的学习档案，请先在后台建一条。'))
            return request.render('tutoring_center.portal_my_mistakes', values)
        if not request.env['tutoring.mistake'].has_access('create'):
            return request.not_found()
        if request.httprequest.method != 'POST':
            return request.redirect('/my/mistakes#quickadd')
        vals = self._mistake_vals_from_post(student, kw)
        if not vals['workbook_id']:
            # 带着已填的值回到速记条，不让用户重打一遍
            values = self._mistake_page_values(
                kw, form=self._mistake_form_from_post(kw), error=_('请先选择练习册。'))
            return request.render('tutoring_center.portal_my_mistakes', values)
        Mistake = request.env['tutoring.mistake']
        mistakes = Mistake.create([
            dict(vals, question_no=no if no else vals['question_no'])
            for no in split_question_numbers(vals['question_no'])
        ])
        count = len(mistakes)
        return request.redirect('/my/mistakes?created=%d' % count)

    @http.route('/my/learning/mistakes/<int:mistake_id>/edit', type='http', auth='user',
                website=True, methods=['GET', 'POST'])
    def portal_my_mistake_edit(self, mistake_id, **kw):
        mistake = request.env['tutoring.mistake'].browse(mistake_id).exists()
        if not mistake or not mistake.has_access('write'):
            return request.not_found()
        # 年级知识点域、默认练习册这些都跟着这条记录自己的档案走，
        # 不是跟着"当前登录的人是谁"——老师替学生改题时尤其明显
        student = mistake.student_id
        error = {}
        if request.httprequest.method == 'POST':
            vals = self._mistake_vals_from_post(student, kw)
            vals.pop('student_id')  # 不允许改归属学生
            if not vals['workbook_id']:
                error = {'message': _('请选择练习册。')}
            else:
                mistake.write(vals)
                return request.redirect('/my/learning/mistakes/%d?saved=1' % mistake.id)
        values = self._mistake_form_values(student, mistake=mistake, post=kw)
        values.update({'error': error, 'mode': 'edit'})
        return request.render('tutoring_center.portal_my_learning_mistake_form', values)

    # ------------------------------------------------------------
    # 教材（练习册 PDF）
    # ------------------------------------------------------------

    def _tutoring_workbooks(self, student):
        """该学生用过的练习册（按其错题出处归集），按书名排序。"""
        return student.mistake_ids.workbook_id.sorted(key=lambda w: w.name or '')

    @http.route('/my/learning/workbooks', type='http', auth='user', website=True)
    def portal_my_workbooks(self, **kwargs):
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        return request.render('tutoring_center.portal_my_learning_workbooks', {
            'page_name': 'tutoring_workbooks',
            'workbooks': self._tutoring_workbooks(student),
        })

    @http.route('/my/learning/workbooks/<int:workbook_id>', type='http', auth='user', website=True)
    def portal_my_workbook(self, workbook_id, **kwargs):
        workbook = request.env['tutoring.workbook'].browse(workbook_id).exists()
        if not workbook or not workbook.has_access('read'):
            return request.not_found()
        return request.render('tutoring_center.portal_my_learning_workbook', {
            'page_name': 'tutoring_workbooks',
            'workbook': workbook,
            'workbook_files': workbook.file_ids.sorted(key=lambda f: f.name or ''),
        })

    @http.route('/my/learning/workbook-files/<int:file_id>', type='http',
                auth='user', website=True)
    def portal_my_workbook_file(self, file_id, **kwargs):
        workbook_file = request.env['tutoring.workbook.file'].browse(file_id).exists()
        if not workbook_file or not workbook_file.has_access('read'):
            return request.not_found()
        content_url = '/web/content/tutoring.workbook.file/%d/content' % workbook_file.id
        return request.render('tutoring_center.portal_my_learning_workbook_file', {
            'page_name': 'tutoring_workbooks',
            'workbook_file': workbook_file,
            # 与后台 pdf_viewer 组件同一个静态查看器；正文走 /web/content，按 read 权限校验
            'viewer_url': '/web/static/lib/pdfjs/web/viewer.html?file=%s' % quote(content_url, safe=''),
        })

    # ------------------------------------------------------------
    # 知识库：每个人自己的内容空间，与后台共用同一套模型和容量配额
    # ------------------------------------------------------------

    LIBRARY_PAGE_SIZES = (10, 20, 50)

    def _library_categories(self):
        return dict(
            request.env['tutoring.library.item']._fields['category'].selection)

    def _library_sortings(self):
        """排序走数据库 order：这个页面是分页的，不能整表捞进内存再排。"""
        return {
            'date': {'label': _('最新上传'), 'order': 'upload_date desc, id desc'},
            'name': {'label': _('按名称'), 'order': 'name asc, id desc'},
            'size': {'label': _('按大小'), 'order': 'file_size desc, id desc'},
        }

    def _library_folder(self, folder_param):
        """folder 查询参数 → (追加域, 文件夹记录, 归一化后的键)。

        只认本人搜得到的文件夹：`search` 会拼记录规则，别人文件夹的 id 到这儿
        等价于没填——不给越权留缝。`all`/空＝不限，`none`＝未分类。
        """
        if not folder_param or folder_param == 'all':
            return [], None, 'all'
        if folder_param == 'none':
            return [('folder_id', '=', False)], None, 'none'
        try:
            folder_id = int(folder_param)
        except (TypeError, ValueError):
            return [], None, 'all'
        folder = request.env['tutoring.library.folder'].search(
            [('id', '=', folder_id)], limit=1)
        if not folder:
            return [], None, 'all'
        return [('folder_id', '=', folder.id)], folder, str(folder.id)

    def _library_folder_entries(self, base_domain, folder_key):
        """左侧文件夹栏：全部 / 各文件夹 / 未分类，计数一次 read_group 全拿。

        域用 base_domain（不含当前文件夹）：这样在某个文件夹里也看得见别的
        文件夹还有多少文件，切过去不用先退出来。
        """
        Item = request.env['tutoring.library.item']
        counts, unfiled = {}, 0
        for folder, count in Item._read_group(base_domain, ['folder_id'], ['__count']):
            if folder:
                counts[folder.id] = count
            else:
                unfiled = count
        entries = [{
            'key': 'all', 'label': _('全部文件'), 'icon': 'th-large',
            'count': sum(counts.values()) + unfiled,
        }]
        for folder in request.env['tutoring.library.folder'].search([]):
            entries.append({
                'key': str(folder.id), 'label': folder.name, 'icon': 'folder',
                'count': counts.get(folder.id, 0),
            })
        entries.append({
            'key': 'none', 'label': _('未分类'), 'icon': 'folder-open-o',
            'count': unfiled,
        })
        for entry in entries:
            entry['active'] = entry['key'] == folder_key
        return entries

    def _library_searchbar_filters(self):
        return dict(
            [('all', {'label': _('全部'), 'domain': []})] +
            [(key, {'label': label, 'domain': [('category', '=', key)]})
             for key, label in self._library_categories().items()])

    @http.route('/my/library', type='http', auth='user', website=True)
    def portal_my_library(self, sortby=None, filterby=None, search=None, folder=None,
                          page=1, limit=None, **kwargs):
        Item = request.env['tutoring.library.item']
        base_domain = [('user_id', '=', request.env.user.id)]
        folder_domain, active_folder, folder_key = self._library_folder(folder)
        scope_domain = base_domain + folder_domain

        searchbar_filters = self._library_searchbar_filters()
        if filterby not in searchbar_filters:
            filterby = 'all'
        domain = scope_domain + searchbar_filters[filterby]['domain']
        search_domain = []
        if search:
            search_domain = ['|', '|', ('name', 'ilike', search),
                             ('filename', 'ilike', search), ('tag_ids.name', 'ilike', search)]
            domain += search_domain

        sortings = self._library_sortings()
        if sortby not in sortings:
            sortby = 'date'
        try:
            page_size = int(limit)
        except (TypeError, ValueError):
            page_size = self.LIBRARY_PAGE_SIZES[0]
        if page_size not in self.LIBRARY_PAGE_SIZES:
            page_size = self.LIBRARY_PAGE_SIZES[0]
        try:
            page = max(int(page), 1)
        except (TypeError, ValueError):
            page = 1

        total = Item.search_count(domain)
        items = Item.search(
            domain, order=sortings[sortby]['order'],
            limit=page_size, offset=(page - 1) * page_size)

        # 分类药丸上的计数：在当前文件夹 + 搜索词下按分类一次 read_group
        filter_counts = {}
        for key, count in Item._read_group(scope_domain + search_domain, ['category'], ['__count']):
            filter_counts[key] = count
        filter_counts['all'] = sum(filter_counts.values())

        url_args = {
            'sortby': sortby, 'filterby': filterby,
            'folder': folder_key, 'limit': page_size,
        }
        if search:
            url_args['search'] = search
        values = {
            'page_name': 'library',
            'items': items,
            'total': total,
            'quota': Item.quota_state(),
            'categories': self._library_categories(),
            'search': search or '',
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'filterby': filterby,
            'searchbar_filters': searchbar_filters,
            'filter_counts': filter_counts,
            'page_size': page_size,
            'page_sizes': self.LIBRARY_PAGE_SIZES,
            'folder_entries': self._library_folder_entries(base_domain, folder_key),
            'active_folder': active_folder,
            'folder_key': folder_key,
            'url_args': url_args,
            'pager': portal_pager(
                url='/my/library', url_args=url_args,
                total=total, page=page, step=page_size),
        }
        return request.render('tutoring_center.portal_my_library', values)

    @http.route('/my/library/upload', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def portal_my_library_upload(self, **kw):
        """门户上传的无 JS 退路：拖拽那条走 /tutoring/library/upload 的 JSON 接口。

        两条路写的是同一个模型、同一份配额，参数也对齐（category/folder/tags）。
        """
        model = request.env['tutoring.library.item']
        category = kw.get('category') or 'other'
        if category not in self._library_categories():
            category = 'other'
        _domain, folder, folder_key = self._library_folder(kw.get('folder'))
        uploaded, errors = 0, []
        for upload in request.httprequest.files.getlist('file')[:10]:
            filename = upload.filename or ''
            try:
                model.create({
                    'name': (kw.get('title') or '').strip() or filename.rpartition('.')[0] or _('未命名文件'),
                    'filename': filename,
                    'content': base64.b64encode(upload.read()).decode(),
                    'category': category,
                    'folder_id': folder.id if folder else False,
                    'tag_ids': model.tags_from_names(kw.get('tags')),
                })
                # 逐个提交：下一个失败要回滚时不能把已成功的带走
                request.env.cr.commit()
                uploaded += 1
            except UserError as err:
                request.env.cr.rollback()
                errors.append('%s：%s' % (filename, err))
        params = ['folder=%s' % folder_key]
        if uploaded:
            params.append('uploaded=%s' % uploaded)
        if errors:
            params.append('error=%s' % quote(' '.join(errors)[:200]))
        return request.redirect('/my/library?' + '&'.join(params))

    @http.route('/my/library/new', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def portal_my_library_new(self, **kw):
        """「新建资料」：先只记一个名字，附件后面再补。

        没有电子版的人也得能把这本资料立起来——分类选「练习册/教辅」时条目会
        自动挂成一本练习册（见 `tutoring.library.item._ensure_workbook_link`），
        错题页那本下拉立刻就有得选，不至于因为"手上没 PDF"记不了错题。
        不填 content 就是不占配额的空条目，配额只在补附件那次算。
        """
        name = (kw.get('name') or '').strip()[:120]
        if not name:
            return request.redirect('/my/library?new=1&error=%s' % quote(_('先写个名字。')))
        category = kw.get('category') or 'other'
        if category not in self._library_categories():
            category = 'other'
        _domain, folder, _key = self._library_folder(kw.get('folder'))
        model = request.env['tutoring.library.item']
        try:
            item = model.create({
                'name': name,
                'category': category,
                'folder_id': folder.id if folder else False,
                'tag_ids': model.tags_from_names(kw.get('tags')),
            })
        except UserError as err:
            return request.redirect('/my/library?new=1&error=%s' % quote(str(err)[:200]))
        return request.redirect('/my/library/%s?created=1' % item.id)

    @http.route('/my/library/<int:item_id>/add_file', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_library_item_add_file(self, item_id, **kw):
        """给一条已有的资料补上附件（原生 multipart，不依赖 JS）。

        走条目的 write()：单文件上限与剩余配额那两道检查、以及"练习册/教辅"
        补完附件才挂进书，都在模型里，这里不重做一遍。
        """
        item = request.env['tutoring.library.item'].search([('id', '=', item_id)], limit=1)
        if not item:
            return request.not_found()
        upload = request.httprequest.files.get('file')
        if not upload or not upload.filename:
            return request.redirect('/my/library/%s?error=%s' % (item.id, quote(_('没选文件。'))))
        filename = SAFE_FILENAME.sub('_', upload.filename.strip()) or '附件'
        try:
            item.write({
                'content': base64.b64encode(upload.read()).decode(),
                'filename': filename,
            })
        except UserError as err:
            return request.redirect('/my/library/%s?error=%s' % (item.id, quote(str(err)[:200])))
        return request.redirect('/my/library/%s?attached=1' % item.id)

    # ---- 文件夹：新建 / 改名 / 删除（都只动本人可见的那一个） ----

    @http.route('/my/library/folder', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def portal_my_library_folder_new(self, **kw):
        name = (kw.get('name') or '').strip()[:80]
        if not name:
            return request.redirect('/my/library?error=%s' % quote(_('文件夹名字没填。')))
        Folder = request.env['tutoring.library.folder']
        # 判重按约束同一条域来查（规则已经把范围收成本人的了）
        if Folder.search_count([('name', '=', name)]):
            return request.redirect(
                '/my/library?error=%s' % quote(_('已经有同名文件夹了，换个名字。')))
        folder = Folder.create({'name': name})
        return request.redirect('/my/library?folder=%s' % folder.id)

    @http.route('/my/library/folder/<int:folder_id>/rename', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_library_folder_rename(self, folder_id, **kw):
        folder = request.env['tutoring.library.folder'].search(
            [('id', '=', folder_id)], limit=1)
        name = (kw.get('name') or '').strip()[:80]
        if not folder or not name:
            return request.redirect('/my/library')
        if folder.name == name:
            return request.redirect('/my/library?folder=%s' % folder.id)
        if request.env['tutoring.library.folder'].search_count(
                [('name', '=', name), ('id', '!=', folder.id)]):
            return request.redirect(
                '/my/library?folder=%s&error=%s'
                % (folder.id, quote(_('已经有同名文件夹了，换个名字。'))))
        folder.write({'name': name})
        return request.redirect('/my/library?folder=%s' % folder.id)

    @http.route('/my/library/folder/<int:folder_id>/delete', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_library_folder_delete(self, folder_id, **kw):
        folder = request.env['tutoring.library.folder'].search(
            [('id', '=', folder_id)], limit=1)
        if folder:
            # 条目上的 ondelete='set null' 会把里面的文件留在"未分类"，不动正文
            folder.unlink()
        return request.redirect('/my/library')

    @http.route('/my/library/<int:item_id>', type='http', auth='user', website=True)
    def portal_my_library_item(self, item_id, **kwargs):
        item = request.env['tutoring.library.item'].browse(item_id).exists()
        if not item or not item.has_access('read') or item.user_id != request.env.user:
            return request.not_found()
        return request.render('tutoring_center.portal_my_library_item', {
            'page_name': 'library',
            'item': item,
            'categories': dict(item._fields['category'].selection),
            'folders': request.env['tutoring.library.folder'].search([]),
        })

    @http.route('/my/library/<int:item_id>/edit', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def portal_my_library_item_edit(self, item_id, **kw):
        # 走 search 而不是 browse：规则会直接把别人那条过滤成"不存在"，
        # 用 browse 再读 user_id 判归属，越权请求是先炸 500 再被规则拦住
        item = request.env['tutoring.library.item'].search(
            [('id', '=', item_id)], limit=1)
        if not item:
            return request.not_found()
        category = kw.get('category') or item.category
        if category not in self._library_categories():
            category = item.category
        _domain, folder, _key = self._library_folder(kw.get('folder'))
        item.write({
            'name': (kw.get('name') or '').strip() or item.name,
            'category': category,
            'folder_id': folder.id if folder else False,
            'tag_ids': request.env['tutoring.library.item'].tags_from_names(kw.get('tags')),
        })
        return request.redirect('/my/library/%s' % item.id)

    @http.route('/my/library/<int:item_id>/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def portal_my_library_item_save(self, item_id, **kw):
        """就地改正文。

        只有 `editable` 的条目走得通——超限的二进制文件在模型那边就被判成不可编，
        页面不给按钮，这里再挡一次（免得有人直接 POST）。
        配额由条目的 write() 按增量重算，超了会抛 UserError，转成一句人话回去。
        """
        item = request.env['tutoring.library.item'].search([('id', '=', item_id)], limit=1)
        if not item:
            return request.not_found()
        if not item.editable:
            return request.redirect('/my/library/%s?error=%s' % (
                item.id, quote(item.read_note or _('这种文件不能在网页里编辑。'))))
        try:
            item.write({'text_body': kw.get('body') or ''})
        except UserError as err:
            return request.redirect('/my/library/%s?error=%s' % (
                item.id, quote(str(err)[:200])))
        return request.redirect('/my/library/%s?saved=1' % item.id)

    @http.route('/my/library/<int:item_id>/delete', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def portal_my_library_item_delete(self, item_id, **kw):
        item = request.env['tutoring.library.item'].search([('id', '=', item_id)], limit=1)
        if item:
            item.unlink()
        return request.redirect('/my/library')

    # ------------------------------------------------------------
    # 时间账本：Do1ng 桌面端同步上来的任务与计时
    # ------------------------------------------------------------

    TIME_PAGE_SIZES = (12, 24, 60)

    def _time_sortings(self):
        return {
            'recent': {'label': _('最近活动'),
                       'order': 'last_activity_at desc nulls last, id desc'},
            'duration': {'label': _('累计时长'), 'order': 'total_seconds desc, id desc'},
            'created': {'label': _('最新创建'),
                        'order': 'client_created desc nulls last, id desc'},
            'title': {'label': _('任务名'), 'order': 'title asc, id desc'},
        }

    def _time_filters(self):
        labels = dict(request.env['tutoring.time.task']._fields['status'].selection)
        filters = {'all': {'label': _('全部'), 'domain': []}}
        for key, label in labels.items():
            filters[key] = {'label': label, 'domain': [('status', '=', key)]}
        return filters

    @http.route('/my/time', type='http', auth='user', website=True)
    def portal_my_time(self, sortby=None, filterby=None, search=None, page=1, limit=None,
                       **kwargs):
        Task = request.env['tutoring.time.task']
        # 不写 [('user_id','=',user.id)]：五张表都挂了"仅本人"的记录规则，
        # 这里再写一遍只是多一处会漂移的重复。
        searchbar_filters = self._time_filters()
        if filterby not in searchbar_filters:
            filterby = 'all'
        domain = list(searchbar_filters[filterby]['domain'])
        search_domain = []
        if search:
            search_domain = ['|', ('title', 'ilike', search),
                             ('pool_item_ids.text', 'ilike', search)]
            domain += search_domain

        sortings = self._time_sortings()
        if sortby not in sortings:
            sortby = 'recent'
        try:
            page_size = int(limit)
        except (TypeError, ValueError):
            page_size = self.TIME_PAGE_SIZES[0]
        if page_size not in self.TIME_PAGE_SIZES:
            page_size = self.TIME_PAGE_SIZES[0]
        try:
            page = max(int(page), 1)
        except (TypeError, ValueError):
            page = 1

        total = Task.search_count(domain)
        tasks = Task.search(domain, order=sortings[sortby]['order'],
                            limit=page_size, offset=(page - 1) * page_size)

        # 状态药丸上的计数：不受当前状态筛选影响，受搜索词影响
        filter_counts = {}
        for key, count in Task._read_group(search_domain, ['status'], ['__count']):
            filter_counts[key] = count
        filter_counts['all'] = sum(filter_counts.values())

        url_args = {'sortby': sortby, 'filterby': filterby, 'limit': page_size}
        if search:
            url_args['search'] = search
        values = {
            'page_name': 'time',
            'overview': Task.overview(),
            'tasks': tasks,
            'total': total,
            'status_labels': dict(Task._fields['status'].selection),
            'search': search or '',
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'filterby': filterby,
            'searchbar_filters': searchbar_filters,
            'filter_counts': filter_counts,
            'page_size': page_size,
            'page_sizes': self.TIME_PAGE_SIZES,
            'devices': request.env['tutoring.time.device'].search([]),
            'syncs': request.env['tutoring.time.sync'].search([], limit=5),
            'url_args': url_args,
            'pager': portal_pager(
                url='/my/time', url_args=url_args,
                total=total, page=page, step=page_size),
        }
        return request.render('tutoring_center.portal_my_time', values)

    # ------------------------------------------------------------
    # 列表页公共准备（排序/筛选/分页）
    # ------------------------------------------------------------

    def _tutoring_list_values(self, records, sortby, page, sortings, url,
                              filterby=None, searchbar_filters=None):
        if not sortby or sortby not in sortings:
            sortby = next(iter(sortings))
        option = sortings[sortby]
        records = records.sorted(key=option['key'], reverse=option.get('reverse', False))
        page_size = 10
        pager = portal_pager(
            url=url,
            url_args={'sortby': sortby, 'filterby': filterby or 'all'},
            total=len(records), page=page, step=page_size)
        offset = (page - 1) * page_size
        return {
            'records': records[offset:offset + page_size],
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'filterby': filterby,
            'searchbar_filters': searchbar_filters,
            'default_url': url,
        }
