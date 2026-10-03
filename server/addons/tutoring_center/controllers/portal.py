import json
from urllib.parse import quote

from odoo import _, fields, http
from odoo.fields import Date, Datetime
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager

from ..models.tutoring_mistake import split_question_numbers


class TutoringPortal(CustomerPortal):

    def _tutoring_student(self):
        """当前门户用户绑定的学生档案（记录规则已按门户联系人过滤）。"""
        return request.env['tutoring.student'].search(
            [('partner_id', '=', request.env.user.partner_id.id)], limit=1)

    def home(self, **kw):
        """已绑定学生档案的门户用户，访问 /my 直接进入学习页。"""
        if self._tutoring_student():
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
            values['tutoring_mistake_count'] = (
                request.env['tutoring.mistake'].search_count([('student_id', '=', student.id)])
                if student and request.env['tutoring.mistake'].has_access('read') else 0)
        if 'tutoring_workbook_count' in counters:
            values['tutoring_workbook_count'] = (
                len(self._tutoring_workbooks(student))
                if student and request.env['tutoring.workbook'].has_access('read') else 0)
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

    def _mistake_form_values(self, student, mistake=None, post=None):
        """错题新增/编辑表单的公共渲染值。form 为回填用的当前值字典。"""
        Mistake = request.env['tutoring.mistake']
        post = post or {}

        def _to_int(val):
            try:
                return int(val) if val else False
            except (TypeError, ValueError):
                return False

        if post:
            form = {
                'workbook_id': _to_int(post.get('workbook_id')),
                'page': post.get('page') or '',
                'question_no': post.get('question_no') or '',
                'topic_id': _to_int(post.get('topic_id')),
                'difficulty': post.get('difficulty') or '3',
                'date': post.get('date') or '',
                'note': post.get('note') or '',
            }
        elif mistake:
            form = {
                'workbook_id': mistake.workbook_id.id or False,
                'page': mistake.page or '',
                'question_no': mistake.question_no or '',
                'topic_id': mistake.topic_id.id or False,
                'difficulty': mistake.difficulty or '3',
                'date': str(mistake.date) if mistake.date else '',
                'note': mistake.note or '',
            }
        else:
            form = {'workbook_id': False, 'page': '', 'question_no': '', 'topic_id': False,
                    'difficulty': '3', 'date': '', 'note': ''}

        return {
            'page_name': 'tutoring_mistakes',
            'student': student,
            'mistake': mistake,
            'form': form,
            'workbooks': request.env['tutoring.workbook'].search([]),
            'topics': request.env['tutoring.topic'].search([]),
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
            'topic_id': _to_int('topic_id'),
            'difficulty': kw.get('difficulty') if kw.get('difficulty') in ('2', '3', '4', '5') else '3',
            'note': (kw.get('note') or '').strip() or False,
        }
        if kw.get('date'):
            vals['date'] = kw.get('date')
        return vals

    @http.route('/my/mistakes', type='http', auth='user', website=True)
    def portal_my_mistakes(self, sortby=None, filterby=None, page=1, **kwargs):
        """顶栏「错题」独立页：速记条 + 带计数的筛选药丸 + 卡片列表。"""
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        values = self._mistake_page_values(student, sortby, filterby, page, kwargs)
        return request.render('tutoring_center.portal_my_mistakes', values)

    def _mistake_page_values(self, student, sortby=None, filterby=None, page=1,
                             kwargs=None, form=None, error=None):
        """/my/mistakes 页面取数；速记条校验失败时带 form/error 复用同一页。"""
        Mistake = request.env['tutoring.mistake']
        base_domain = [('student_id', '=', student.id)]
        today = fields.Date.context_today(request.env.user)
        month_start = today.replace(day=1)
        searchbar_filters = {
            'all': {'label': _('全部'), 'domain': []},
            'month': {'label': _('本月'), 'domain': [('date', '>=', month_start)]},
            'hard': {'label': _('高难度'), 'domain': [('difficulty', 'in', ['4', '5'])]},
            'no_note': {'label': _('未填错因'), 'domain': [('note', '=', False)]},
        }
        filter_counts = {
            key: Mistake.search_count(base_domain + option['domain'])
            for key, option in searchbar_filters.items()
        }
        if not filterby or filterby not in searchbar_filters:
            filterby = 'all'
        records = Mistake.search(base_domain + searchbar_filters[filterby]['domain'])
        values = self._tutoring_list_values(
            records, sortby, page,
            sortings={
                'recorded': {
                    'label': _('最新记录'),
                    'key': lambda r: (r.create_date or Datetime.MIN, r.id), 'reverse': True,
                },
                'date': {
                    'label': _('发生日期（新→旧）'),
                    'key': lambda r: (r.date or Date.MIN, r.id), 'reverse': True,
                },
                'date_asc': {
                    'label': _('发生日期（旧→新）'),
                    'key': lambda r: (r.date or Date.MAX, r.id), 'reverse': False,
                },
            },
            url='/my/mistakes', filterby=filterby, searchbar_filters=searchbar_filters,
        )
        last_mistake = Mistake.search(base_domain, limit=1, order='create_date desc, id desc')
        values.update({
            'page_name': 'tutoring_mistakes',
            'mistakes': values.pop('records'),
            'difficulty_labels': dict(Mistake._fields['difficulty'].selection),
            'difficulties': list(Mistake._fields['difficulty'].selection),
            'filter_counts': filter_counts,
            'can_create': Mistake.has_access('create'),
            'default_workbook': last_mistake.workbook_id if last_mistake else False,
            'default_date': today.strftime('%Y-%m-%d'),
            'created_count': int((kwargs or {}).get('created') or 0),
            'form': form or {},
            'error': error,
            'workbooks': request.env['tutoring.workbook'].search([]),
            'topics': request.env['tutoring.topic'].search([]),
        })
        return values

    @http.route('/my/learning/mistakes', type='http', auth='user', website=True)
    def portal_my_mistakes_redirect(self, **kwargs):
        """旧列表入口并入顶栏错题页。"""
        return request.redirect('/my/mistakes')

    @http.route('/my/learning/mistakes/<int:mistake_id>', type='http', auth='user', website=True)
    def portal_my_mistake_detail(self, mistake_id, **kwargs):
        mistake = request.env['tutoring.mistake'].browse(mistake_id).exists()
        if not mistake or not mistake.has_access('read'):
            return request.not_found()
        return request.render('tutoring_center.portal_my_learning_mistake_detail', {
            'page_name': 'tutoring_mistakes',
            'mistake': mistake,
            'difficulty_labels': dict(request.env['tutoring.mistake']._fields['difficulty'].selection),
            'can_edit': mistake.has_access('write'),
            'just_saved': bool(kwargs.get('created') or kwargs.get('saved')),
        })

    @http.route('/my/learning/mistakes/new', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_my_mistake_new(self, **kw):
        """记错题入口：GET 直接进顶栏错题页的速记条；POST 支持题号 1-5 拆多条。"""
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        if not request.env['tutoring.mistake'].has_access('create'):
            return request.not_found()
        if request.httprequest.method != 'POST':
            return request.redirect('/my/mistakes#quickadd')
        vals = self._mistake_vals_from_post(student, kw)
        if not vals['workbook_id']:
            # 带着已填的值回到速记条，不让用户重打一遍
            form = {key: (kw.get(key) or '') for key in
                    ('page', 'question_no', 'difficulty', 'date', 'note')}
            form['workbook_id'] = False
            try:
                form['topic_id'] = int(kw.get('topic_id') or 0) or False
            except (TypeError, ValueError):
                form['topic_id'] = False
            values = self._mistake_page_values(
                student, kw.get('sortby'), kw.get('filterby'), 1, kw,
                form=form, error=_('请先选择练习册。'))
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
        student = self._tutoring_student()
        if not student:
            return request.redirect('/my')
        mistake = request.env['tutoring.mistake'].browse(mistake_id).exists()
        if not mistake or not mistake.has_access('write'):
            return request.not_found()
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
