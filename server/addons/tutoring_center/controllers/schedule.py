"""排课：给小程序的校长与老师那一面供数（`19.0.1.39.0`）。

**真源用原生 `calendar.event`**，这批刻意不给 `tutoring.session` 加老师字段。理由都来自读过的源码：

- `calendar.event` 天生就是"日期 + 时段 + 人"三件套：`name`/`start`/`stop` 必填
  （`calendar/models/calendar_event.py:131,176,179`），`partner_ids` 是**真存的 m2m**（L206），
  写它核心会自动补齐 `calendar.attendee`（create L665 / write L784），不需要另立参与人表；
- 参与人只要一个 `res.partner`：老师是 `res.users`（有 `.partner_id`），学生那边
  `tutoring.student.partner_id` 已经是必填级的事（建档案时没有就自动立一个，
  `models/tutoring_student.py:13-15,48-55`）；
- calendar 已经随 `crm` 装进库里（`tutoring_center` 的 depends 含 crm），
  所以这一批**不新增模块、不新增字段、不写迁移**，纯 Python。

**任课老师的口径钉在 `user_id` 上**（原生那个 Organizer，L136）：排课写入口建事件时
`user_id` 放任课老师、`partner_ids` 放老师＋学生。读侧 `?teacher=` 就是按这个字段筛，
两边一处口径，别一个写在 `user_id` 一个读在 `attendee_ids`。

**分权这一层要说清代价。** 原生 calendar 对内部用户的记录规则是 `[('1','=',1)]`
（`calendar/security/calendar_security.xml:12-17`），意味着老师账号在 ORM 层**读得到同事的课**。
所以"老师只看自己的课"由本文件按角色把域拼死，不是装完 calendar 就自动有；客户端传不进域，
唯一的受控口子是 `?teacher=`，非校长用它直接 403。维护者 2026-10-19 明确选了"只在接口层拼域"，
不给 `calendar.event` 加记录规则——那会连带改掉 Odoo 网页端原生日历对内部用户的共享语义。

**这一屏三种身份都接**（校长看全校、老师看自己的、学生/家长看孩子这周由谁上），
所以本文件有**接口层第二处 `sudo()`**，只在 `_organizers()` 里，边界写在那个函数的文档里。
`api.py` 那条"本文件不出现 sudo()"的纪律没变——这一份是另一个文件，而且用的是同一套"sudo 后逐字段白名单"。

信封、客户端头、分页这些纪律复用 `api.py` 那一份（`from .api import ...`），这里不重写。
"""

import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import _, fields, http
from odoo.http import request

from .api import _date, _error, _guard, _int, _ok, _pager, _role

_logger = logging.getLogger(__name__)

# 一次最多查这么宽：域里带日期就能把结果集钉死，别让"看今年全部的课"把整表拖下来
MAX_WINDOW_DAYS = 90
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def _timezone(raw):
    """`?tz=` → `(名字, pytz 时区)`；乱写或没传就退回账号自己的时区，再退回 UTC。

    宽松的（`api.py` 的 `_int` 同款：乱写的值退回默认而不是报错），但**把最终生效的那份回显在
    响应里**（`tz` 与 `window`），所以"我按 +8 查的、你按 UTC 算的"这类错位当场能看出来。
    """
    for name in ((raw or '').strip(), request.env.user.tz, 'UTC'):
        if not name:
            continue
        try:
            return name, pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            _logger.info('r3yna schedule: 不认的时区 %r，继续往下退', name)
    return 'UTC', pytz.UTC


def _to_local(naive, tz):
    """naive UTC（Odoo 存 Datetime 的方式）→ 带 tzinfo 的本地时间。"""
    if not naive:
        return False
    return pytz.UTC.localize(naive).astimezone(tz)


def _utc_bounds(lo, hi, tz):
    """本地日历日区间 `[lo, hi]` → 那个时区对应的 UTC naive 区间 `(起, 止)`。

    按整天算：`lo` 的 00:00 到 `hi+1` 的 00:00。换 UTC 时把 tzinfo 摘掉，
    因为 Odoo 的 Datetime 列存的就是 naive UTC，带着 tzinfo 进域会按字符串比对不上。
    """
    start = tz.localize(datetime.combine(lo, time.min))
    stop = tz.localize(datetime.combine(hi + timedelta(days=1), time.min))
    return (start.astimezone(pytz.UTC).replace(tzinfo=None),
            stop.astimezone(pytz.UTC).replace(tzinfo=None))


def _parse_date(raw):
    """`YYYY-MM-DD` → date；不合法返回 None，由调用方回 400（日期写错不该闷着查）。"""
    try:
        return fields.Date.from_string((raw or '').strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _week_bounds(day):
    """所在 ISO 周的周一与周日（`today` 用调用方那个时区，不用服务器时区）。"""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def _student_names(partner_ids):
    """一批联系人 → `{partner_id: [学生名]}`。

    走 `tutoring.student.search()` 而不是事件上的反向关系：后者不过记录规则（陷阱 26），
    会把读不到的档案名一起带出去。
    """
    if not partner_ids:
        return {}
    names = {}
    for student in request.env['tutoring.student'].search(
            [('partner_id', 'in', list(set(partner_ids)))], order='name'):
        names.setdefault(student.partner_id.id, []).append(student.name)
    return names


def _organizers(events):
    """这批事件的任课老师 → `{user_id: {'id', 'name', 'partner_id'}}`，一次查齐。

    **这是接口层第二处 `sudo()`**（第一处在 `public_api.py`，纪律照抄：sudo 之后只按
    字段白名单取值，绝不把整条记录吐出去）。为什么非用不可：任课老师是 `res.users`，
    而门户账号读不到 `res.users`（原生记录规则，实测 `Access Denied ... model: res.users`），
    可家长这一屏要看的恰恰就是"这节是谁上的"——维护者 2026-10-19 拍了：学生也要看到老师名。

    边界钉死在这三样，不是"能按 id 捞任意账号"的口子：

    - 待查的 id **只能来自这次请求已经按身份拼域拿到的那些事件**（校长拿到全校、老师与学生只拿到自己的）；
    - 白名单就 `id` / `name` / `partner_id` 三个字段，登录名、邮箱、Key、权限一律不碰；
    - 整页一次查，不在循环里逐条读。
    """
    user_ids = list({event.user_id.id for event in events if event.user_id})
    if not user_ids:
        return {}
    users = request.env['res.users'].sudo().browse(user_ids).exists()
    return {
        user.id: {
            'id': user.id,
            'name': user.name or '',
            'partner_id': user.partner_id.id or 0,
        }
        for user in users
    }


class TutoringScheduleApi(http.Controller):

    @http.route('/r3yna/api/schedule', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_schedule(self, date=None, date_from=None, date_to=None, teacher=None,
                     tz=None, page=1, page_size=None, **kw):
        """按时间窗回排课。**校长看全校，老师与学生/家长只看自己参与的那几节。**

        - `?date=YYYY-MM-DD` 单天；`?date_from=&date_to=` 区间；都不传就是调用方时区的本周一~周日。
        - `?teacher=<res.users id>` 只有校长能用，非校长直接 403（不是忽略——静默忽略筛选条件
          会让小程序带着 bug 上线）。
        - `?tz=Asia/Shanghai` 决定"哪天"和显示用的时分；不传按账号 `tz`，再按 UTC。
        """
        guarded = _guard()
        if guarded:
            return guarded

        tz_name, tzinfo = _timezone(tz)
        role = _role()
        today = datetime.now(tzinfo).date()

        # 窗口：单天 `?date=` 优先，其次区间；两种写法都不传就是本周一~周日。
        # 传了但解析不出来一律 400——日期写错却安静地查到别的天，是最难查的那种错。
        single = _parse_date(date)
        raw_lo, raw_hi = _parse_date(date_from), _parse_date(date_to)
        if (date and not single) or (date_from and not raw_lo) or (date_to and not raw_hi):
            return _error(400, 'bad_date', _('日期要写成 YYYY-MM-DD。'))
        if single:
            lo = hi = single
        elif raw_lo or raw_hi:
            lo = raw_lo or today
            hi = raw_hi or today
        else:
            lo, hi = _week_bounds(today)
        if lo > hi:
            lo, hi = hi, lo
        if (hi - lo).days + 1 > MAX_WINDOW_DAYS:
            hi = lo + timedelta(days=MAX_WINDOW_DAYS - 1)

        # 非校长传 `?teacher=` 一律 403，不是"忽略这个条件"：静默忽略会让小程序带着
        # "我以为筛了、其实没筛"的 bug 上线，而画面上看起来完全正常
        if teacher and role != 'principal':
            return _error(403, 'not_principal', _('按老师筛排课，只有机构管理员能用。'))

        domain = []
        if role != 'principal':
            # 老师/学生：只看自己作为参与人的课。这条就是"看不到别人的课"的全部实现处。
            domain.append(('partner_ids', 'in', request.env.user.partner_id.id))
        elif teacher:
            try:
                teacher_id = int(teacher)
            except (TypeError, ValueError):
                return _error(400, 'bad_teacher', _('老师 id 要是一个数字。'))
            # 过 search 而不是 browse().exists()：后者不过记录规则
            picked = request.env['res.users'].search([('id', '=', teacher_id)], limit=1)
            if not picked:
                return _error(404, 'teacher_not_found', _('没有这位老师，或者你读不到他。'))
            domain.append(('user_id', '=', picked.id))

        # 时间窗用 `start`/`stop` 这两个真存的 Datetime 拼。
        # **不能用 `start_date`/`stop_date`**：它们虽然 store=True，但 `_compute_dates` 只在
        # `allday` 时赋值，定时课一律留空（calendar_event.py:373-379）——本轮真建了五节课，
        # 那两列全是 False，拿它们进域的结果是"接口活着但永远查空"。
        # 于是把调用方那个时区的 [lo 00:00, hi+1 00:00) 换成 UTC 边界：跨午夜的课按重叠也算进来。
        lo_utc, hi_utc = _utc_bounds(lo, hi, tzinfo)
        events = request.env['calendar.event'].search(
            domain + [('start', '<', hi_utc), ('stop', '>', lo_utc)],
            order='start asc, id asc')

        rows = []
        for event in events:
            local_start = _to_local(event.start, tzinfo)
            local_stop = _to_local(event.stop, tzinfo)
            if local_start:
                # 周期事件只按第一次出现的那天判，实例不展开（见 _event_item 里的 recurrency）
                rows.append((event, local_start, local_stop))

        total = len(rows)
        page = _int(page, 1, 1, 10000)
        size = _int(page_size, DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        rows = rows[(page - 1) * size:page * size]
        page_events = [event for event, _ls, _lp in rows]

        # 学生名与老师名各一次取齐：循环里逐条查会变成 N 条 SQL
        partners = set()
        for event in page_events:
            partners.update(event.partner_ids.ids)
        students_by_partner = _student_names(partners)
        organizers = _organizers(page_events)

        return _ok(
            role=role,
            scope='all' if role == 'principal' else 'mine',
            tz=tz_name,
            window={'from': _date(lo), 'to': _date(hi)},
            items=[
                self._event_item(event, local_start, local_stop,
                                 organizers, students_by_partner)
                for event, local_start, local_stop in rows
            ],
            pager=_pager(total, page, size),
        )

    @staticmethod
    def _event_item(event, local_start, local_stop, organizers, students_by_partner):
        """一节排课 → 客户端卡片。

        时分、星期、时长这些**服务端排好了再吐**（与 `/meta` 同一口径：小程序不硬编码常量、
        也不自己算时区）；`start`/`stop` 那两串原始 UTC 一并留着，客户端要算跨度或排序用它。
        """
        minutes = 0
        if local_start and local_stop:
            minutes = int((local_stop - local_start).total_seconds() // 60)
        hours, mins = divmod(max(minutes, 0), 60)
        duration_text = ('%d 小时 %d 分钟' % (hours, mins)) if hours else '%d 分钟' % mins
        teacher = organizers.get(event.user_id.id) or False
        # **任课老师那个联系人一律不当学生报**：老师也有「我自己」那份本人档案
        # （`tutoring_student.py` 的 `ensure_teacher_profiles`），它挂在老师自己的联系人上，
        # 不摘掉的话校长看到的名单会多出一行"我自己"。
        names = []
        for partner_id in event.partner_ids.ids:
            if teacher and partner_id == teacher['partner_id']:
                continue
            names.extend(students_by_partner.get(partner_id, []))
        return {
            'id': event.id,
            'name': event.name or '',
            'allday': bool(event.allday),
            'start': fields.Datetime.to_string(event.start) if event.start else False,
            'stop': fields.Datetime.to_string(event.stop) if event.stop else False,
            'date': _date(local_start.date()) if local_start else False,
            'weekday': WEEKDAYS[local_start.weekday()] if local_start else '',
            'start_text': local_start.strftime('%H:%M') if local_start and not event.allday else '',
            'stop_text': local_stop.strftime('%H:%M') if local_stop and not event.allday else '',
            'duration_minutes': minutes,
            'duration_text': duration_text if minutes else '',
            'teacher': {'id': teacher['id'], 'name': teacher['name']} if teacher else False,
            'students': sorted(set(names)),
            # 周期事件只回第一次出现的那一节，实例不展开——客户端看到 recurrency=True
            # 就该说明"这一条是排好的循环安排"
            'recurrency': bool(event.recurrency),
            'is_mine': request.env.user.partner_id.id in event.partner_ids.ids,
            'has_description': bool(event.description),
            'location': event.location or '',
        }

    @http.route('/r3yna/api/teachers', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def api_teachers(self, **kw):
        """整个学校的老师名单——**只有校长打得开**。

        口径是 `res.users` 在 `tutoring_center.group_teacher` 里的成员（不是门面页那个
        「师资展示」联系人标签：那是"用谁的脸招生"的口径，挂了标签的人未必有账号，
        没账号就排不了课）。只回 id 与名字：partner id、登录名这些客户端用不上，别多吐。
        """
        guarded = _guard()
        if guarded:
            return guarded
        if _role() != 'principal':
            # 403 而不是 404：这不是"记录读不到"，是"这个身份没这个口子"，
            # 客户端要能分出"该藏起来"和"数据不存在"两种表现
            return _error(403, 'not_principal', _('排课名单只有机构管理员能看。'))

        group = request.env.ref('tutoring_center.group_teacher', raise_if_not_found=False)
        # 显式成员就够：group_user 那一堆内部用户不该因为"被 imply 了"混进老师名单
        members = group.user_ids.ids if group else []
        teachers = request.env['res.users'].search(
            [('id', 'in', members), ('active', '=', True), ('share', '=', False)],
            order='name')
        return _ok(
            items=[{'id': t.id, 'name': t.name} for t in teachers],
            count=len(teachers),
        )
