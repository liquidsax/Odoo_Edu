"""给小程序（以及其它移动端）用的 JSON 接口。

三条纪律与 `time_sync.py` 同源，只有认证方式不同：

1. **认证走核心自带的 `auth='bearer'`**（`odoo/http.py:777` 声明，
   `base/models/ir_http.py:_auth_method_bearer` 实现）：客户端在
   `Authorization: Bearer <API Key>` 里放一把 Odoo API Key，核心拿它去
   `res.users.apikeys._check_credentials`，失败直接抛 `Unauthorized`
   （401 + `WWW-Authenticate: bearer`）。**这一步是关键**：`type='http'`
   路由会话过期时核心会 302 到 `/web/login`（`odoo/http.py:2516`），
   那是给浏览器用的，程序跟着跳就会把登录页 HTML 当 JSON 解析。
   用 bearer 就不必自己写这条，核心替我们保证了"绝不 302"。
   —— 也正因如此，**本项目不需要自己建 token 表**：Key 由用户在
   「偏好设置 → 账户安全 → 新建 API Key」自己生成与吊销。

2. **权限一律由记录规则说话**：本文件**不出现 `sudo()`**，取数只用
   `search()` / `has_access()`。传进来的 id 是不可信输入，一律先过
   `search()`（会应用记录规则），**不用 `browse().exists()`**
   —— 后者与缓存值都不经过记录规则（陷阱 26），越权的人能靠猜 id 命中。

3. **取数口径不另写一份**：筛选药丸、排序白名单、搜索域、药丸计数、
   "当前账号是哪份学生档案"，全部借用 `portal.py` 的实现（`_portal()`）。
   两处各写一遍的话，接口看到的和网页看到的早晚会对不上，而这种不一致
   只会在真点开的时候才露出来。
"""

import base64
import logging
from datetime import datetime, timezone

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from .portal import TutoringPortal

_logger = logging.getLogger(__name__)

# 这个接口只接受客户端调用，不接受浏览器直接打开：浏览器发跨站请求时加不了
# 自定义头（会先触发 CORS 预检，而本站不发 CORS 头），所以这道头与 CSRF 令牌
# 等效，同时又不必让客户端去页面上抓令牌。与 Do1ng 那边同一套思路。
CLIENT_HEADER = 'X-R3ynA-Client'

# 协议版本：响应结构要破坏性变更时 +1，客户端据此判断"该升级了"
PROTOCOL = 1

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_SEARCH_LEN = 40


# ------------------------------------------------------------
# 响应与入参
# ------------------------------------------------------------

def _json(status, payload):
    return request.make_json_response(payload, status=status)


def _ok(**payload):
    return _json(200, dict({'ok': True, 'protocol': PROTOCOL}, **payload))


def _error(status, code, message, **extra):
    return _json(status, dict({'ok': False, 'error': code, 'message': message}, **extra))


def _binary(data, mime, name):
    """吐二进制（教材 PDF 那几条路由用）：内联 + 禁止改嗅类型。

    头纪律与门户 `_mistake_file_response` 同源：`nosniff` 不能省——
    吐回去的是用户上传的内容，别让今天这一口变成明天的存储型 XSS。
    文件名刻意用 ASCII（page-12.pdf 这种）：中文书名塞进裸 header 要走
    RFC 5987，而客户端（wx.downloadFile）根本不读这个文件名，不值得一险。
    """
    return request.make_response(data, [
        ('Content-Type', mime),
        ('Content-Disposition', 'inline; filename="%s"' % name),
        ('Cache-Control', 'private, max-age=300'),
        ('X-Content-Type-Options', 'nosniff'),
    ])


def _client_header_ok():
    return bool((request.httprequest.headers.get(CLIENT_HEADER) or '').strip())


def _guard():
    """公共前置：缺客户端头就直接回 400，不往下走。

    返回 None 表示放行；返回响应对象表示这次请求到此为止。
    """
    if not _client_header_ok():
        return _error(400, 'missing_client_header',
                      _('缺少 %s 头，这个接口只接受客户端调用。', CLIENT_HEADER))
    return None


def _int(raw, default, low, high):
    """不可信入参 → 夹在 [low, high] 里的整数。乱写的值一律退回默认，不报错。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _pager(total, page, page_size):
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'page_count': max((total + page_size - 1) // page_size, 1),
    }


def _date(value):
    return fields.Date.to_string(value) if value else False


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _portal():
    """门户控制器实例。

    借它调用 `_mistake_sortings` / `_mistake_filters` / `_mistake_search_domain` /
    `_mistake_filter_counts` / `_tutoring_student`——这些方法只读 `request.env`，
    不依赖实例状态，所以复用的是"口径"而不是"某个对象"。
    """
    return TutoringPortal()


def _readable_students():
    """当前账号能读到的学生档案（记录规则过滤；老师能看到全部，学生只有自己那份）。"""
    return request.env['tutoring.student'].search([])


def _own_student():
    """与门户同一判据：当前用户绑定的学生档案。"""
    return _portal()._tutoring_student()


def _student_brief(student):
    return {
        'id': student.id,
        'name': student.name,
        'grade': student.grade,
        'grade_label': dict(request.env['tutoring.student']._fields['grade'].selection).get(
            student.grade, student.grade),
        'school': student.school or '',
        'is_self_profile': bool(student.is_self_profile),
        'partner_id': student.partner_id.id or False,
    }


def _resolve_scope(student_raw, scope_raw):
    """解析 `?student=<id>` / `?scope=all|mine` → `(域, 档案, 范围键)`。

    与门户 `_mistake_scope` 同一套语义，但**不复制它的实现**：它要处理
    URL 形态（数字/关键词/兜底），这里要的是 JSON 形态（显式 404 更好调试）。

    取不到那一份档案时回 `(None, …, …)`，由调用方决定回什么状态码——
    绝不能"把域放宽"继续查，那等于越权。
    """
    Student = request.env['tutoring.student']
    empty = Student.browse()
    own = _own_student()

    raw = (student_raw or '').strip()
    if raw:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            return None, empty, 'bad'
        # 走 search 而不是 browse().exists()：前者过记录规则，后者不过（陷阱 26）
        picked = Student.search([('id', '=', sid)], limit=1)
        if not picked:
            return None, empty, 'not_readable'
        return [('student_id', '=', picked.id)], picked, str(picked.id)

    if (scope_raw or '').strip() == 'all':
        return [], empty, 'all'
    if own:
        return [('student_id', '=', own.id)], own, 'mine'
    # 没有本人档案的账号（理论上门户用户都有，这里是兜底）：退回"全部可读"，
    # 别把接口卡死在一个空范围上
    return [], empty, 'all'


# ------------------------------------------------------------
# 控制器
# ------------------------------------------------------------

class TutoringApi(http.Controller):

    # ------------------------------------------------------------
    # 探活
    # ------------------------------------------------------------

    @http.route('/r3yna/api/ping', type='http', auth='none',
                methods=['GET'], csrf=False, readonly=True)
    def api_ping(self, **kw):
        """探活：小程序首次配置后"测试连接"用。

        刻意不回答库名、模块版本、账号数这类只有管理员才需要的东西——
        它是 `auth='none'`，任何人都能打。客户端只需要知道
        "服务在、协议对得上、我这次带没带 Key"。
        """
        guarded = _guard()
        if guarded:
            return guarded
        auth = (request.httprequest.headers.get('Authorization') or '').strip()
        return _ok(
            service='r3yna-edu',
            server_time=_now_iso(),
            has_key=auth.lower().startswith('bearer '),
        )

    # ------------------------------------------------------------
    # 身份与档案
    # ------------------------------------------------------------

    @http.route('/r3yna/api/me', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_me(self, **kw):
        """我是谁 + 我有哪些学生档案（决定小程序里那个"范围切换"能列出谁）。"""
        guarded = _guard()
        if guarded:
            return guarded
        user = request.env.user
        own = _own_student()
        return _ok(
            user={
                'id': user.id,
                'login': user.login,
                'name': user.name,
                'is_internal': user._is_internal(),
            },
            own_student_id=own.id or False,
            students=[_student_brief(s) for s in _readable_students()],
        )

    @http.route('/r3yna/api/meta', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_meta(self, **kw):
        """常量表：难度、错因、年级、筛选药丸、排序白名单。

        小程序不硬编码这些——改文案或加一个错因，只改服务端。
        """
        guarded = _guard()
        if guarded:
            return guarded
        Mistake = request.env['tutoring.mistake']
        today = fields.Date.context_today(request.env.user)
        month_start = today.replace(day=1)
        sorts = _portal()._mistake_sortings()
        filters = _portal()._mistake_filters(month_start)
        return _ok(
            difficulties=[
                {'value': key, 'label': label}
                for key, label in Mistake._fields['difficulty'].selection
            ],
            causes=[
                {'id': c.id, 'name': c.name, 'category': c.category or False}
                for c in request.env['tutoring.mistake.cause'].search([])
            ],
            causes_readable=request.env['tutoring.mistake.cause'].has_access('read'),
            filters=[{'key': k, 'label': v['label']} for k, v in filters.items()],
            sortings=[{'key': k, 'label': v['label']} for k, v in sorts.items()],
        )

    # ------------------------------------------------------------
    # 学习概览
    # ------------------------------------------------------------

    @http.route('/r3yna/api/summary', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_summary(self, student=None, scope=None, **kw):
        """学习看板的取数：四张卡 + 最近与接下来的课次 + 最近考试。

        口径与门户 `_tutoring_dashboard_values` 一致，但**不渲染模板**，
        只回结构化数据——门户那份是给 QWeb 的，跟着它改会连累模板。
        """
        guarded = _guard()
        if guarded:
            return guarded
        domain, picked, scope_key = _resolve_scope(student, scope)
        if domain is None:
            return _error(404, 'student_not_found', _('没有这份学生档案，或者你读不到它。'))

        Session = request.env['tutoring.session']
        Exam = request.env['tutoring.exam']
        Mistake = request.env['tutoring.mistake']
        today = fields.Date.context_today(request.env.user)

        s_domain = domain if domain else []
        sessions = Session.search(s_domain, order='date desc, id desc')
        upcoming = sessions.filtered(lambda s: s.date and s.date >= today).sorted(
            key=lambda s: (s.date, s.id))[:5]
        # 考试用 `student_id` 那个域（与课次同形），取最近 5 场
        exams = Exam.search(s_domain, order='date desc, id desc', limit=5)
        # 「该翻出来的」与错题页共用同一份判据（模型上的 _due_domain）
        due_count = Mistake.search_count(domain + Mistake._due_domain())

        return _ok(
            scope=scope_key,
            student=_student_brief(picked) if picked else False,
            counts={
                'sessions': Session.search_count(s_domain),
                'exams': Exam.search_count(s_domain),
                'mistakes': Mistake.search_count(domain),
                'mistakes_due': due_count,
            },
            exam_avg=round(picked.exam_avg, 1) if picked else False,
            upcoming_sessions=[self._session_item(s) for s in upcoming],
            recent_exams=[self._exam_item(e) for e in exams],
        )

    # ------------------------------------------------------------
    # 课次
    # ------------------------------------------------------------

    @http.route('/r3yna/api/sessions', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_sessions(self, student=None, scope=None, page=1, page_size=None, **kw):
        """辅导课次列表（倒序）。"""
        guarded = _guard()
        if guarded:
            return guarded
        domain, _picked, scope_key = _resolve_scope(student, scope)
        if domain is None:
            return _error(404, 'student_not_found', _('没有这份学生档案，或者你读不到它。'))

        Session = request.env['tutoring.session']
        page = _int(page, 1, 1, 10000)
        size = _int(page_size, DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        total = Session.search_count(domain)
        records = Session.search(domain, order='date desc, id desc',
                                 limit=size, offset=(page - 1) * size)
        return _ok(
            scope=scope_key,
            items=[self._session_item(s) for s in records],
            pager=_pager(total, page, size),
        )

    @staticmethod
    def _session_item(session):
        return {
            'id': session.id,
            'student_id': session.student_id.id,
            'date': _date(session.date),
            'duration': session.duration,
            'topics': [t.name for t in session.topic_ids],
            # 正文可能很长（HTML），列表只给"有没有"；要看内容走详情端点，
            # 避免一屏十几条把几十 KB 的富文本一起拖下来
            'has_performance': bool(session.performance),
            'has_plan': bool(session.plan),
        }

    @http.route('/r3yna/api/sessions/<int:session_id>', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_session_detail(self, session_id, **kw):
        """一节课的内容与表现。取不到（含"读不到"）一律 404，不区分这两种情况。"""
        guarded = _guard()
        if guarded:
            return guarded
        # 先过记录规则：读不到就是"不存在"
        session = request.env['tutoring.session'].search([('id', '=', session_id)], limit=1)
        if not session or not session.has_access('read'):
            return _error(404, 'not_found', _('这节课找不到，或者你读不到它。'))
        data = self._session_item(session)
        data.update({
            'student_name': session.student_id.name,
            'performance': session.performance or '',
            'plan': session.plan or '',
        })
        return _ok(item=data)

    # ------------------------------------------------------------
    # 考试
    # ------------------------------------------------------------

    @http.route('/r3yna/api/exams', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_exams(self, student=None, scope=None, page=1, page_size=None, **kw):
        """在校考试成绩列表（倒序）。只录成绩，不在线考试。"""
        guarded = _guard()
        if guarded:
            return guarded
        domain, _picked, scope_key = _resolve_scope(student, scope)
        if domain is None:
            return _error(404, 'student_not_found', _('没有这份学生档案，或者你读不到它。'))

        Exam = request.env['tutoring.exam']
        page = _int(page, 1, 1, 10000)
        size = _int(page_size, DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        total = Exam.search_count(domain)
        records = Exam.search(domain, order='date desc, id desc',
                              limit=size, offset=(page - 1) * size)
        return _ok(
            scope=scope_key,
            items=[self._exam_item(e) for e in records],
            pager=_pager(total, page, size),
        )

    @staticmethod
    def _exam_item(exam):
        return {
            'id': exam.id,
            'student_id': exam.student_id.id,
            'name': exam.name,
            'date': _date(exam.date),
            'exam_type': exam.exam_type or False,
            'exam_type_label': dict(exam._fields['exam_type'].selection).get(
                exam.exam_type, exam.exam_type or ''),
            'total_score': exam.total_score,
            'total_full': exam.total_full,
            'percentage': round(exam.percentage, 1),
        }

    # ------------------------------------------------------------
    # 错题
    # ------------------------------------------------------------

    @http.route('/r3yna/api/mistakes', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_mistakes(self, student=None, scope=None, filterby=None, sortby=None,
                     search=None, point_id=None, cause_id=None,
                     page=1, page_size=None, **kw):
        """错题列表：范围 + 药丸 + 排序 + 搜索 + 下钻 + 分页。

        筛选/排序/搜索域三样**全部借用门户那一份**（`_portal()`），
        否则"网页上筛出来的"和"小程序里筛出来的"早晚不是同一批题。
        """
        guarded = _guard()
        if guarded:
            return guarded
        domain, _picked, scope_key = _resolve_scope(student, scope)
        if domain is None:
            return _error(404, 'student_not_found', _('没有这份学生档案，或者你读不到它。'))

        Mistake = request.env['tutoring.mistake']
        portal = _portal()
        today = fields.Date.context_today(request.env.user)
        month_start = today.replace(day=1)
        filters = portal._mistake_filters(month_start)
        sorts = portal._mistake_sortings()

        filter_key = filterby if filterby in filters else 'all'
        sort_key = sortby if sortby in sorts else 'review'
        list_domain = domain + filters[filter_key]['domain']

        term = (search or '').strip()[:MAX_SEARCH_LEN]
        if term:
            list_domain += portal._mistake_search_domain(term)

        # 下钻的 id 也要过记录规则：知识点/错因是全库可读的字典，
        # 但万一将来收紧了，这里不该成为绕过去的缝
        for field, model in (('point_id', 'tutoring.knowledge.point'),
                             ('cause_id', 'tutoring.mistake.cause')):
            raw = point_id if field == 'point_id' else cause_id
            try:
                rid = int(raw)
            except (TypeError, ValueError):
                continue
            rec = request.env[model].search([('id', '=', rid)], limit=1)
            if rec:
                list_domain.append((field, '=', rec.id))

        page = _int(page, 1, 1, 10000)
        size = _int(page_size, DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        total = Mistake.search_count(list_domain)
        records = Mistake.search(list_domain, order=sorts[sort_key]['order'],
                                 limit=size, offset=(page - 1) * size)

        return _ok(
            scope=scope_key,
            filterby=filter_key,
            sortby=sort_key,
            search=term,
            counts=portal._mistake_filter_counts(domain, month_start),
            items=[self._mistake_item(m) for m in records],
            pager=_pager(total, page, size),
        )

    @http.route('/r3yna/api/mistakes/<int:mistake_id>', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_mistake_detail(self, mistake_id, **kw):
        """错题详情。归档的（active=False）在有 id 时仍可读——归档是降级不是销毁。"""
        guarded = _guard()
        if guarded:
            return guarded
        Mistake = request.env['tutoring.mistake']
        # 归档的行不在默认域里，要显式 active_test=False 才捞得回来
        mistake = Mistake.with_context(active_test=False).search(
            [('id', '=', mistake_id)], limit=1)
        if not mistake or not mistake.has_access('read'):
            return _error(404, 'not_found', _('这道题找不到，或者你读不到它。'))
        data = self._mistake_item(mistake)
        data.update({
            'student_name': mistake.student_id.name,
            'question_text': mistake.ai_readable_text or '',
            'ai_state': mistake.ai_state or False,
            'ai_hint': mistake.ai_hint or '',
            'recorded_at': fields.Datetime.to_string(mistake.create_date) if mistake.create_date else False,
            # "看那一页"按钮亮不亮。判据与门户封面同一份（cover_pdf_ready 走 sudo，
            # 对学生它只说"有原页可画"）；真取那一页还要过本人权限，可能 404——
            # 客户端必须有退路（门户就是这么定的，见错题试用版本批次②）。
            'page_pdf_ready': bool(mistake.cover_pdf_ready),
        })
        return _ok(item=data)

    @staticmethod
    def _mistake_item(mistake):
        """错题 → 客户端卡片。

        **刻意不吐 `next_review_at` / `review_count` / `last_review_at`**：
        复习排期是纯服务端机制，学生看不到任何"复习"字样、也不需要维护状态
        （门户就是这样）。接口只吐由它派生出来的两样东西——排序与配色。
        """
        return {
            'id': mistake.id,
            'student_id': mistake.student_id.id,
            'student_name': mistake.student_id.name,
            'date': _date(mistake.date),
            'difficulty': mistake.difficulty,
            'difficulty_label': dict(mistake._fields['difficulty'].selection).get(
                mistake.difficulty, ''),
            'cause_id': mistake.cause_id.id or False,
            'cause_name': mistake.cause_id.name or '',
            'point_id': mistake.point_id.id or False,
            'point_name': mistake.point_id.name or '',
            # 出处是这条记录的本体（平台不做题、只记哪儿错了），卡片上就要能看见
            'workbook_id': mistake.workbook_id.id or False,
            'workbook_name': mistake.workbook_id.name or '',
            'page': mistake.page or '',
            'question_no': mistake.question_no or '',
            'note': mistake.note or '',
            # 摘要给卡片直接看，不必点开（与门户同一份可读化结果）
            'summary': mistake.ai_readable_summary or '',
            'photo_count': mistake.library_photo_count or 0,
            # 归档是"收走"，不是"删掉"
            'archived': not mistake.active,
            # 派生量：这一道现在该不该翻出来（口径＝模型上的 _due_domain）
            'due': mistake.next_review_at is False or mistake.next_review_at <= fields.Datetime.now(),
            'heat': mistake.portal_heat or '',
            'heat_note': mistake.portal_heat_note or '',
        }

    # ------------------------------------------------------------
    # 教材（练习册 PDF）
    # ------------------------------------------------------------

    @http.route('/r3yna/api/workbooks', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_workbooks(self, student=None, scope=None, **kw):
        """教材页的书单：当前范围内错题里出现过的练习册，一本一行、行里带分册。

        口径与门户「教材」页同源（`_tutoring_workbooks`：书单按错题出处归集，
        不是全库练习册清单）。这里改用 `read_group` 在 SQL 里做同一件事：
        顺带拿到"这本书在当前范围内记了多少条错题"，也不把错题整捞进内存。

        分册（上册/下册/答案册…）只列**当前账号读得到**的：教材正文放在知识库
        条目里、按人隔离，学生要靠共享（security/tutoring_security.xml 那两条
        规则就是墙）。`search()` 过规则天然只回能读的那几份，这里绝不 sudo
        补全——列出来却打不开，比少列一行更骗人。一本书一份分册都读不到时，
        照样回这本书（错题数还在），`files` 为空，客户端自己说明原因。
        """
        guarded = _guard()
        if guarded:
            return guarded
        domain, _picked, scope_key = _resolve_scope(student, scope)
        if domain is None:
            return _error(404, 'student_not_found', _('没有这份学生档案，或者你读不到它。'))

        Mistake = request.env['tutoring.mistake']
        groups = Mistake.read_group(
            domain + [('workbook_id', '!=', False)], ['workbook_id'], ['workbook_id'])
        counts = {g['workbook_id'][0]: g['workbook_id_count'] for g in groups}
        if not counts:
            return _ok(scope=scope_key, items=[])
        workbooks = request.env['tutoring.workbook'].search(
            [('id', 'in', list(counts))], order='name, id')
        files = request.env['tutoring.workbook.file'].search(
            [('workbook_id', 'in', workbooks.ids)], order='workbook_id, page_from, id')
        by_book = {}
        for f in files:
            by_book.setdefault(f.workbook_id.id, []).append({
                'id': f.id,
                'name': f.name or '',
                'page_from': f.page_from or 0,
                'page_to': f.page_to or 0,
                # bytea 在库里就是 base64，大小这列是算好存着的整数（不触正文）
                'size': f.file_size or 0,
                'content_path': '/r3yna/api/workbooks/files/%d/content.pdf' % f.id,
            })
        return _ok(
            scope=scope_key,
            items=[{
                'id': w.id,
                'name': w.name,
                'note': w.note or '',
                'mistake_count': counts.get(w.id, 0),
                'files': by_book.get(w.id, []),
            } for w in workbooks],
        )

    @http.route('/r3yna/api/workbooks/files/<int:file_id>/content.pdf', type='http',
                auth='bearer', methods=['GET'], csrf=False, readonly=True)
    def api_workbook_file_pdf(self, file_id, **kw):
        """一份分册的整本 PDF（小程序 `wx.downloadFile` + 微信内置阅读器那条路）。

        与网页不同，手机上没有 pdf.js，也没有"翻到第 N 页"——客户端只能整份
        下载后交给 `wx.openDocument`，所以这里给的就是原件。**大小自知**：
        分册按页切开正是为了把单份压在 96MB 上限内，客户端拿到 `size` 要先
        提示再下载，别让流量在用户不知情时跑掉。

        权限：`search()` 过记录规则（教材条目按人隔离，学生靠共享），
        读不到＝不存在，一律 404，不区分这两种情况。
        """
        guarded = _guard()
        if guarded:
            return guarded
        workbook_file = request.env['tutoring.workbook.file'].search(
            [('id', '=', file_id)], limit=1)
        if not workbook_file:
            return _error(404, 'not_found', _('这份教材找不到，或者你读不到它。'))
        data = base64.b64decode(workbook_file.content) if workbook_file.content else None
        if not data:
            return _error(404, 'no_content', _('这份教材还没有正文。'))
        return _binary(data, 'application/pdf', 'workbook-file-%d.pdf' % file_id)

    @http.route('/r3yna/api/mistakes/<int:mistake_id>/page.pdf', type='http',
                auth='bearer', methods=['GET'], csrf=False, readonly=False)
    def api_mistake_page_pdf(self, mistake_id, **kw):
        """这道题"出处那一页"的单页 PDF——错题详情页那颗「看那一页」。

        与门户 `/my/learning/mistakes/<id>/page.pdf` 同一份实现（读 `page_pdf`
        计算字段，`_locate_page` 自己管权限与缓存），只是认证换 bearer。
        单页 PDF 只有几 KB，正是手机上"回到出错那一页"的正确粒度——
        整本下载是教材页的事，不该混进错题详情。

        **`readonly=False` 是刻意的**：第一次取某一页会把抽出的单页写进
        `tutoring.workbook.page` 缓存表（同页多题共用）。这是派生缓存、
        可随时重建，但 readonly 路由的事务不让写，挂上它首抽必 500。
        """
        guarded = _guard()
        if guarded:
            return guarded
        mistake = request.env['tutoring.mistake'].with_context(
            active_test=False).search([('id', '=', mistake_id)], limit=1)
        if not mistake or not mistake.has_access('read'):
            return _error(404, 'not_found', _('这道题找不到，或者你读不到它。'))
        data = base64.b64decode(mistake.page_pdf) if mistake.page_pdf else None
        if not data:
            # 没填出处 / 页码翻不出来 / 教材没共享，都归这一句：抽不出来不是错误
            return _error(404, 'page_unavailable',
                          _('定位不到那一页：出处没填、页码越界或教材读不到。'))
        return _binary(data, 'application/pdf', 'page-%d.pdf' % mistake_id)
