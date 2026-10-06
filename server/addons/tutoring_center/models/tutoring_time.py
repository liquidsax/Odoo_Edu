"""时间账本：桌面端 Do1ng 的任务与计时数据在云端的落点。

三张业务表（任务 / 计时区间 / 想法池）加两张簿记表（设备 / 同步日志）。
每一行都带 `client_id`——由**产生它的那一端**生成的稳定标识，云端不自己发明主键，
所以同一件事在多台机器上重复上报也只会落一行。

同步是"客户端上报变更 + 服务器按 rev 乐观锁落库"，不比较时间戳大小：
多机的本地时钟互相不可信，而 `rev` 是服务器自己发的号，只有它能定义"谁改过"。

删除是**墓碑**而不是真删：载荷里的 `deleted` 落到原生的 `active=False`。
用 `active` 而不是自造一个 deleted 布尔，是为了让门户、`search_count`、`read_group`
这些读路径全部自动跳过墓碑行；代价是同步自己查行时必须显式带 `active_test=False`
（集中在 `_lookup()` 一处），否则会查不到墓碑 → 重新 create → 撞唯一约束。
"""

import logging
from datetime import datetime, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TASK_STATUS = [
    ('active', '进行中'),
    ('interrupted', '被打断'),
    ('done', '已完成'),
]
# 桌面端的枚举名（ACTIVE/INTERRUPTED/DONE）小写后就能对上；另外几个别名是防它将来改名，
# 宁可显式列出来，也不要静默落成一个"未知状态"。
STATUS_ALIASES = {key: key for key, _label in TASK_STATUS}
STATUS_ALIASES.update({'in_progress': 'active', 'finished': 'done', 'completed': 'done'})

ORIGIN = [
    ('device', '桌面端'),
    ('web', '网页'),
]

# 一次推送的行数上限。数据量本来极小（作者本机 16 任务 / 33 区间 / 8.6KB），
# 这个闸只是防一个写坏的客户端把几万行塞进单个事务。
MAX_ROWS_PER_PUSH = 5000
MAX_TITLE = 300
MAX_TEXT = 500
MAX_NOTES = 200

SYNC_ACTIONS = ('created', 'updated', 'deleted', 'conflict', 'noop', 'rejected')


def parse_client_datetime(value, default_offset=0):
    """客户端时间字符串 → (UTC naive datetime, 偏移分钟)。

    认 ISO-8601，带不带时区都收：带时区按它自己的偏移换算，不带的按 `default_offset`
    （客户端上报的当前偏移）当成当地时间。**必须区分**——Do1ng 存的是无时区的墙上时间，
    直接当 UTC 收进来会让所有数据整体偏 8 小时，按天分组全错。

    缺失/解析不出来一律返回 `False` 而不是 `None`：Odoo 字段读出来的空值是 `False`，
    同步要靠逐字段比对判断"这一版和库里是否一致"，`None != False` 会让每次重推都当成改动。
    """
    if not value:
        return False, default_offset
    text = str(value).strip()
    if not text:
        return False, default_offset
    if text.endswith(('Z', 'z')):
        text = text[:-1] + '+00:00'
    if 'T' not in text and ' ' in text:
        text = text.replace(' ', 'T', 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False, default_offset
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(minutes=default_offset)))
    offset = int(parsed.utcoffset().total_seconds() // 60)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None), offset


def local_date_of(utc_value, offset_minutes):
    """UTC 时刻 + 该行自己的偏移 → 客户端当地的日期。

    存这一列是为了按天分组：Odoo 的 `read_group(..., 'start_at:day')` 按 UTC 切，
    东八区早上 7 点的那段计时会被算进前一天。
    """
    if not utc_value:
        return False
    return (utc_value + timedelta(minutes=offset_minutes or 0)).date()


def _clip(text, limit):
    text = '' if text is None else str(text).strip()
    return text[:limit]


def _lookup(model, domain):
    """同步专用的查行：连墓碑一起查。

    只有这一个入口允许看见 `active=False` 的行，别处一律走原生过滤。
    """
    return model.with_context(active_test=False).search(domain, limit=1)


def _norm(value):
    """比对前的归一：把"空"的几种写法收敛成同一个值。

    Odoo 的 Json 字段 `convert_to_cache` 里有 `if not value: return None`——空数组存进库
    就是 NULL，读回来是 `False`；Char 的空串同样可能是 `False`。不归一的话，
    `notes=[]` 的行每轮同步都会被当成改动，rev 白涨、流水里全是假的 updated。
    """
    if value is None or value is False:
        return False
    if isinstance(value, (list, dict, str)) and not value:
        return False
    return value


def _same(record, values):
    """逐字段比对，判断客户端这一版和库里的是否完全一致。

    一致就当无事发生（`noop`）——这是让"服务器写成功了但响应在网络里丢了"能收敛的关键：
    客户端会拿着旧 rev 重推同一份内容，若不认这种情况就会永久停在冲突态。

    多对一字段读出来是记录集、写进去是 id，比对前先摊平成 id，否则永远"不相等"，
    每次重推都白涨一个 rev。
    """
    for fname, value in values.items():
        current = record[fname]
        if isinstance(current, models.BaseModel):
            current = current.id or False
        if _norm(current) != _norm(value):
            return False
    return True


def _upsert(row, values, base_rev):
    """把一行变更落到 `row`（空记录集＝新建）上，返回 `(record, action, rev)`。

    冲突时**不写库**，只把服务器当前 rev 回给客户端让它 rebase 后重推：
    一次冲突最多晚一轮同步，两端的数据都不丢。
    """
    if not row:
        if not values.get('active', True):
            # 本地删掉了一条云端从来没有的行：无事可做，也不算错
            return row, 'noop', 0
        return row.create(dict(values, rev=1)), 'created', 1

    current_rev = row.rev or 0
    if _same(row, values):
        return row, 'noop', current_rev
    if base_rev and base_rev != current_rev:
        return row, 'conflict', current_rev
    row.write(dict(values, rev=current_rev + 1))
    action = 'updated' if values.get('active', True) else 'deleted'
    return row, action, current_rev + 1


class TutoringTimeDevice(models.Model):
    """一台跑 Do1ng 的机器。

    存在的理由不只是"设备面板好看"：多机同步时，冲突与删除的归属要能追到是哪台机器写的。
    `device_key` 由客户端首次运行时生成并持久化，重装才会变。
    """
    _name = 'tutoring.time.device'
    _description = '时间账本同步设备'
    _order = 'last_seen_at desc nulls last, id desc'
    _rec_name = 'name'

    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    device_key = fields.Char('设备标识', required=True, index=True)
    name = fields.Char('设备名', required=True, default=lambda self: _('未命名设备'))
    platform = fields.Char('平台')
    client_version = fields.Char('客户端版本')
    first_seen_at = fields.Datetime('首次同步', default=fields.Datetime.now)
    last_seen_at = fields.Datetime('最近同步', index=True)
    last_status = fields.Selection(
        [('ok', '成功'), ('error', '失败')], string='最近结果')
    last_error = fields.Text('最近错误')
    sync_count = fields.Integer('同步次数', default=0)

    _user_device_uniq = models.Constraint(
        'unique(user_id, device_key)', _('这台设备已经登记过了。'))

    @api.model
    def resolve(self, info):
        """按 `device_key` 找到或登记一台设备，顺带刷新"最近见过"。"""
        info = info if isinstance(info, dict) else {}
        key = _clip(info.get('device_key'), 64)
        if not key:
            return self.browse()
        vals = {
            'name': _clip(info.get('device_name'), 120) or _('未命名设备'),
            'platform': _clip(info.get('platform'), 40) or False,
            'client_version': _clip(info.get('client_version'), 40) or False,
            'last_seen_at': fields.Datetime.now(),
        }
        device = _lookup(self, [('device_key', '=', key)])
        if device:
            device.write(vals)
        else:
            device = self.create(dict(vals, device_key=key))
        return device

    def note_result(self, status, error=False):
        self.write({
            'last_status': status,
            'last_error': _clip(error, 2000) or False,
            'sync_count': (self.sync_count or 0) + 1,
        })


class TutoringTimeSync(models.Model):
    """一次同步的流水。

    出问题时唯一能回答"到底传上来了什么、哪几行被拒了"的地方，所以宁可每次都写一行。
    """
    _name = 'tutoring.time.sync'
    _description = '时间账本同步记录'
    _order = 'id desc'

    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    device_id = fields.Many2one('tutoring.time.device', string='设备', ondelete='set null')
    kind = fields.Selection(
        [('push', '上传'), ('pull', '拉取'), ('both', '双向')],
        string='方向', default='push', required=True)
    status = fields.Selection(
        [('ok', '成功'), ('rejected', '有行被拒'), ('error', '失败')],
        string='结果', default='ok', required=True, index=True)
    created_count = fields.Integer('新增', default=0)
    updated_count = fields.Integer('更新', default=0)
    deleted_count = fields.Integer('标记删除', default=0)
    conflict_count = fields.Integer('冲突', default=0)
    noop_count = fields.Integer('无变化', default=0)
    rejected_count = fields.Integer('被拒', default=0)
    duration_ms = fields.Integer('耗时（毫秒）', default=0)
    error_text = fields.Text('错误详情')
    remote_addr = fields.Char('来源')
    client_version = fields.Char('客户端版本')

    @api.model
    def record(self, device, kind, stats, duration_ms=0, error=False, client_version=False,
               remote_addr=False):
        rejected = stats.get('rejected') or 0
        return self.create({
            'device_id': device.id if device else False,
            'kind': kind,
            'status': 'error' if error else ('rejected' if rejected else 'ok'),
            'created_count': stats.get('created') or 0,
            'updated_count': stats.get('updated') or 0,
            'deleted_count': stats.get('deleted') or 0,
            'conflict_count': stats.get('conflict') or 0,
            'noop_count': stats.get('noop') or 0,
            'rejected_count': rejected,
            'duration_ms': duration_ms,
            'error_text': _clip(error, 4000) or False,
            'client_version': _clip(client_version, 40) or False,
            'remote_addr': _clip(remote_addr, 64) or False,
        })


class TutoringTimeTask(models.Model):
    """一件"正在做/做过的事"。对应 Do1ng 的 `model/Task.java`。

    `total_seconds` 只累计**已结束**的区间，和 Do1ng 的 `totalMillis` 口径一致——
    两边数字必须对得上，否则网页上看到的和桌面上看到的打架，这功能就没人信了。
    正在进行的那一段单独用 `open_seconds`，不混进累计值。

    精度上有一处先天损耗：Do1ng 落盘的 `start`/`end` 只到秒，而它的 `totalMillis` 是内存里
    按毫秒累加的，所以云端按区间重算与本地累计值最多差「每段区间 1 秒」。展示层到分钟，
    看不出来；Do1ng 侧已把新数据的时间戳改成带毫秒，历史数据保持原样。
    """
    _name = 'tutoring.time.task'
    _description = '时间账本任务'
    _order = 'id desc'
    _rec_name = 'title'

    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    client_id = fields.Char('客户端标识', required=True, index=True)
    title = fields.Char('任务', required=True, default=lambda self: _('未命名任务'))
    status = fields.Selection(TASK_STATUS, string='状态', default='active',
                              required=True, index=True)
    client_created = fields.Datetime('创建于（客户端）', index=True)
    interrupted_count = fields.Integer('被打断次数', default=0)
    device_id = fields.Many2one('tutoring.time.device', string='最后写入设备',
                                ondelete='set null')
    origin = fields.Selection(ORIGIN, string='来源', default='device', required=True)
    rev = fields.Integer('版本', default=1, required=True)
    client_updated_at = fields.Datetime('客户端改动时刻')
    active = fields.Boolean('有效', default=True, index=True)

    session_ids = fields.One2many('tutoring.time.session', 'task_id', string='计时区间')
    pool_item_ids = fields.One2many('tutoring.time.pool.item', 'task_id', string='想法池')
    # 存量与非存量必须分两个 compute 方法：混在一起 Odoo 会警告
    # "inconsistent 'store'"，而且每次读非存量那个都会连带重算存量列
    total_seconds = fields.Integer('累计秒数', compute='_compute_totals', store=True)
    session_count = fields.Integer('区间数', compute='_compute_totals', store=True)
    last_activity_at = fields.Datetime('最近活动', compute='_compute_totals', store=True)
    open_seconds = fields.Integer('进行中秒数', compute='_compute_open')
    duration_text = fields.Char('累计时长', compute='_compute_duration_text')
    open_text = fields.Char('进行中时长', compute='_compute_duration_text')

    _user_client_uniq = models.Constraint(
        'unique(user_id, client_id)', _('这条任务已经同步过了。'))

    @api.depends('session_ids.start_at', 'session_ids.end_at', 'session_ids.active',
                 'client_created')
    def _compute_totals(self):
        for task in self:
            total = count = 0
            last = task.client_created or False
            # session_ids 自带 active_test，墓碑区间不会进来
            for session in task.session_ids:
                if not session.start_at:
                    continue
                count += 1
                if session.end_at:
                    total += max(int((session.end_at - session.start_at).total_seconds()), 0)
                    stamp = session.end_at
                else:
                    stamp = session.start_at
                if not last or stamp > last:
                    last = stamp
            task.total_seconds = total
            task.session_count = count
            task.last_activity_at = last

    @api.depends('session_ids.start_at', 'session_ids.end_at', 'session_ids.active')
    def _compute_open(self):
        """正在进行的那一段有多少秒。不入库：它每秒都在变，存了就是永远过期的数。"""
        now = fields.Datetime.now()
        for task in self:
            task.open_seconds = sum(
                max(int((now - session.start_at).total_seconds()), 0)
                for session in task.session_ids
                if session.start_at and not session.end_at)

    @api.depends('total_seconds', 'open_seconds')
    def _compute_duration_text(self):
        for task in self:
            task.duration_text = format_duration(task.total_seconds)
            task.open_text = format_duration(task.open_seconds)

    # ------------------------------------------------------------
    # 同步入口
    # ------------------------------------------------------------
    @api.model
    def sync_push(self, payload):
        """应用桌面端上报的一份变更，返回统计与每行的最新 rev。

        以当前登录用户身份跑（不 sudo），记录规则天然把可写范围锁在本人名下。
        """
        payload = payload if isinstance(payload, dict) else {}
        changes = payload.get('changes')
        changes = changes if isinstance(changes, dict) else {}
        offset = _offset_of(payload)
        device = self.env['tutoring.time.device'].resolve(payload.get('client'))

        task_rows = _as_list(changes.get('tasks'))
        session_rows = _as_list(changes.get('sessions'))
        pool_rows = _as_list(changes.get('pool'))
        total_rows = len(task_rows) + len(session_rows) + len(pool_rows)
        if total_rows > MAX_ROWS_PER_PUSH:
            raise UserError(_('一次最多同步 %(limit)s 行，这次来了 %(got)s 行。',
                              limit=MAX_ROWS_PER_PUSH, got=total_rows))

        stats = {key: 0 for key in SYNC_ACTIONS}
        revs, rejected = {}, []
        # 任务必须先于它的区间与想法落库：子行要靠 task_client_id 找到父任务
        tasks_by_client_id, task_stats, task_revs, task_rejected = self._sync_tasks(
            task_rows, device, offset)
        _merge_stats(stats, task_stats)
        revs.update(task_revs)
        rejected += task_rejected

        for model_name, rows in (('tutoring.time.session', session_rows),
                                 ('tutoring.time.pool.item', pool_rows)):
            child_stats, child_revs, child_rejected = self.env[model_name]._sync_rows(
                rows, tasks_by_client_id, device, offset)
            _merge_stats(stats, child_stats)
            revs.update(child_revs)
            rejected += child_rejected

        return {
            'stats': stats,
            'revs': revs,
            'rejected': rejected,
            'device_id': device.id if device else False,
            'device_key': device.device_key if device else False,
        }

    @api.model
    def _sync_tasks(self, rows, device, offset):
        stats = {key: 0 for key in SYNC_ACTIONS}
        revs, rejected = {}, []
        tasks_by_client_id = {}
        for row in rows:
            if not isinstance(row, dict):
                stats['rejected'] += 1
                rejected.append({'kind': 'task', 'reason': _('格式不对')})
                continue
            client_id, values, error = _task_values(row, offset, device)
            if error:
                stats['rejected'] += 1
                rejected.append({'kind': 'task', 'client_id': client_id, 'reason': error})
                continue
            existing = _lookup(self.browse(), [('client_id', '=', client_id)])
            record, action, rev = _upsert(existing, values, _base_rev(row))
            stats[action] += 1
            revs['task:%s' % client_id] = rev
            tasks_by_client_id[client_id] = record or existing
            if action == 'deleted' and record:
                # 桌面端删掉一个任务时，它名下的区间与想法在本地也一起没了。
                # 这里跟着归档，否则统计页会读到"任务没了但时长还在"的孤儿区间。
                record.with_context(active_test=False).mapped('session_ids').write(
                    {'active': False, 'rev': 1})
                record.with_context(active_test=False).mapped('pool_item_ids').write(
                    {'active': False, 'rev': 1})
        return tasks_by_client_id, stats, revs, rejected

    @api.model
    def overview(self):
        """门户概览条取数：今日 / 本周 / 任务计数 / 最近同步，一次拿齐。

        今日时长 = 已结束区间按**当地日期**归集 + 正在进行那段的实时秒数。
        正在进行的那段同一时刻只有一条（桌面端只计一件事），直接 Python 算，
        不值得为它再开一条 SQL 聚合。
        """
        Session = self.env['tutoring.time.session']
        today = fields.Date.context_today(self)
        week_start = today - timedelta(days=today.weekday())
        per_day = Session._read_group(
            [('end_at', '!=', False),
             ('local_date', '>=', week_start), ('local_date', '<=', today)],
            ['local_date:day'], ['duration_seconds:sum'])
        # 19 里 date/datetime 分组必须显式给粒度（models.py:2095），
        # 回来的键按粒度可能是 datetime，统一摊成 date 再当字典键
        closed = {}
        for day, total in per_day:
            if not day:
                continue
            closed[day.date() if isinstance(day, datetime) else day] = total or 0
        now = fields.Datetime.now()
        open_sessions = Session.search([('end_at', '=', False)])
        open_seconds = sum(
            max(int((now - session.start_at).total_seconds()), 0)
            for session in open_sessions if session.start_at)
        today_seconds = closed.get(today, 0) + open_seconds
        week_seconds = sum(closed.values()) + open_seconds
        sync = self.env['tutoring.time.sync'].search([], limit=1)
        if sync:
            when = fields.Datetime.context_timestamp(sync, sync.create_date)
            last_sync_text = '%s · %s' % (when.strftime('%m-%d %H:%M'),
                                          sync.device_id.name or _('未知设备'))
        else:
            last_sync_text = _('还没同步过')
        return {
            'today_seconds': today_seconds,
            'week_seconds': week_seconds,
            'open_seconds': open_seconds,
            'today_text': format_duration(today_seconds),
            'week_text': format_duration(week_seconds),
            'open_text': format_duration(open_seconds),
            'task_count': self.search_count([]),
            'active_count': self.search_count([('status', '=', 'active')]),
            'today': today,
            'week_start': week_start,
            'open_task': open_sessions[:1].task_id,
            'last_sync': sync,
            'last_sync_text': last_sync_text,
        }


class TutoringTimeSession(models.Model):
    """一段连续计时。对应 Do1ng 的 `model/Session.java`。

    `end_at` 为空＝正在进行。`notes` 是被打断时记下的快照（"我停在哪了"），
    桌面端是字符串数组，这里用 Json 原样存——它只被整读整写，拆表没有收益。
    """
    _name = 'tutoring.time.session'
    _description = '时间账本计时区间'
    _order = 'start_at desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    task_id = fields.Many2one('tutoring.time.task', string='所属任务', required=True,
                              index=True, ondelete='cascade')
    client_id = fields.Char('客户端标识', required=True, index=True)
    start_at = fields.Datetime('开始', required=True, index=True)
    end_at = fields.Datetime('结束', index=True)
    utc_offset = fields.Integer('当地时差（分钟）', default=0)
    local_date = fields.Date('当地日期', compute='_compute_local_date', store=True, index=True)
    notes = fields.Json('打断备注', default=list)
    duration_seconds = fields.Integer('时长（秒）', compute='_compute_duration', store=True)
    duration_text = fields.Char('时长', compute='_compute_duration_text')
    device_id = fields.Many2one('tutoring.time.device', string='最后写入设备',
                                ondelete='set null')
    origin = fields.Selection(ORIGIN, string='来源', default='device', required=True)
    rev = fields.Integer('版本', default=1, required=True)
    client_updated_at = fields.Datetime('客户端改动时刻')
    active = fields.Boolean('有效', default=True, index=True)

    _task_client_uniq = models.Constraint(
        'unique(task_id, client_id)', _('这段计时已经同步过了。'))

    @api.depends('start_at', 'utc_offset')
    def _compute_local_date(self):
        for session in self:
            session.local_date = local_date_of(session.start_at, session.utc_offset)

    @api.depends('start_at', 'end_at')
    def _compute_duration(self):
        for session in self:
            if not session.start_at or not session.end_at:
                session.duration_seconds = 0
            else:
                session.duration_seconds = max(
                    int((session.end_at - session.start_at).total_seconds()), 0)

    @api.depends('duration_seconds')
    def _compute_duration_text(self):
        for session in self:
            session.duration_text = format_duration(session.duration_seconds)

    @api.model
    def _sync_rows(self, rows, tasks_by_client_id, device, offset):
        stats = {key: 0 for key in SYNC_ACTIONS}
        revs, rejected = {}, []
        for row in rows:
            client_id, values, error = _child_values(
                row, tasks_by_client_id, offset, device, _session_values)
            if error:
                stats['rejected'] += 1
                rejected.append({'kind': 'session', 'client_id': client_id, 'reason': error})
                continue
            existing = _lookup(self.browse(), [
                ('task_id', '=', values['task_id']), ('client_id', '=', client_id)])
            record, action, rev = _upsert(existing, values, _base_rev(row))
            stats[action] += 1
            revs['session:%s' % client_id] = rev
        return stats, revs, rejected


class TutoringTimePoolItem(models.Model):
    """任务上挂的一条想法。对应 Do1ng 的 `model/PoolItem.java`。

    `done_at` 为空＝还没勾掉。桌面端原来没有 id，而同步要求每条都能被认出来，
    所以客户端那边补了 id 并给旧数据回填。
    """
    _name = 'tutoring.time.pool.item'
    _description = '时间账本想法池'
    _order = 'client_created desc, id desc'
    _rec_name = 'text'

    user_id = fields.Many2one(
        'res.users', string='所属用户', required=True, index=True,
        default=lambda self: self.env.user, ondelete='cascade')
    task_id = fields.Many2one('tutoring.time.task', string='所属任务', required=True,
                              index=True, ondelete='cascade')
    client_id = fields.Char('客户端标识', required=True, index=True)
    text = fields.Char('想法', required=True, default=lambda self: _('（空）'))
    client_created = fields.Datetime('记于')
    done_at = fields.Datetime('勾掉于')
    device_id = fields.Many2one('tutoring.time.device', string='最后写入设备',
                                ondelete='set null')
    origin = fields.Selection(ORIGIN, string='来源', default='device', required=True)
    rev = fields.Integer('版本', default=1, required=True)
    client_updated_at = fields.Datetime('客户端改动时刻')
    active = fields.Boolean('有效', default=True, index=True)

    _task_client_uniq = models.Constraint(
        'unique(task_id, client_id)', _('这条想法已经同步过了。'))

    @api.model
    def _sync_rows(self, rows, tasks_by_client_id, device, offset):
        stats = {key: 0 for key in SYNC_ACTIONS}
        revs, rejected = {}, []
        for row in rows:
            client_id, values, error = _child_values(
                row, tasks_by_client_id, offset, device, _pool_values)
            if error:
                stats['rejected'] += 1
                rejected.append({'kind': 'pool', 'client_id': client_id, 'reason': error})
                continue
            existing = _lookup(self.browse(), [
                ('task_id', '=', values['task_id']), ('client_id', '=', client_id)])
            record, action, rev = _upsert(existing, values, _base_rev(row))
            stats[action] += 1
            revs['pool:%s' % client_id] = rev
        return stats, revs, rejected


# ----------------------------------------------------------------
# 载荷 → 字段值
# ----------------------------------------------------------------
def _as_list(value):
    return value if isinstance(value, list) else []


def _offset_of(payload):
    """客户端当前时差（分钟）。没报就按 0，比替它猜一个 +8 安全。"""
    try:
        offset = int((payload or {}).get('utc_offset_minutes'))
    except (TypeError, ValueError):
        return 0
    return max(min(offset, 14 * 60), -12 * 60)


def _base_rev(row):
    try:
        return max(int(row.get('rev') or 0), 0)
    except (TypeError, ValueError):
        return 0


def _merge_stats(target, extra):
    for key, value in extra.items():
        target[key] = target.get(key, 0) + value


def _common_values(row, device):
    return {
        'origin': 'web' if row.get('origin') == 'web' else 'device',
        'device_id': device.id if device else False,
        'client_updated_at': parse_client_datetime(row.get('updated_at'))[0],
        'active': not bool(row.get('deleted')),
    }


def _task_values(row, offset, device):
    """返回 `(client_id, values, error)`；error 非空表示这一行该被拒。"""
    client_id = _clip(row.get('client_id'), 64)
    if not client_id:
        return '', {}, _('缺少客户端标识')
    title = _clip(row.get('title'), MAX_TITLE)
    if not title:
        return client_id, {}, _('任务标题是空的')
    status = STATUS_ALIASES.get(str(row.get('status') or '').strip().lower())
    if not status:
        return client_id, {}, _('认不出的状态：%s', row.get('status'))
    created, _created_offset = parse_client_datetime(row.get('created'), offset)
    try:
        interrupted = max(int(row.get('interrupted_count') or 0), 0)
    except (TypeError, ValueError):
        interrupted = 0
    values = _common_values(row, device)
    values.update({
        'client_id': client_id,
        'title': title,
        'status': status,
        'client_created': created,
        'interrupted_count': interrupted,
    })
    return client_id, values, False


def _child_values(row, tasks_by_client_id, offset, device, builder):
    """区间与想法共用的前置校验：认得出自己、也认得出所属任务，才谈落库。"""
    if not isinstance(row, dict):
        return '', {}, _('格式不对')
    client_id = _clip(row.get('client_id'), 64)
    if not client_id:
        return '', {}, _('缺少客户端标识')
    task_key = _clip(row.get('task_client_id'), 64)
    task = tasks_by_client_id.get(task_key)
    if not task:
        # 父任务这一轮没上来（被拒或还没同步）：子行不能挂空，
        # 记成被拒，让客户端下一轮连同任务一起重推
        return client_id, {}, _('找不到它所属的任务：%s', task_key or '（空）')
    values, error = builder(row, task, offset, device)
    return client_id, values, error


def _session_values(row, task, offset, device):
    start, start_offset = parse_client_datetime(row.get('start'), offset)
    if not start:
        return {}, _('开始时间缺失或格式不对：%s', row.get('start'))
    end, end_offset = parse_client_datetime(row.get('end'), offset)
    if end and end < start:
        return {}, _('结束时间早于开始时间')
    notes = row.get('notes')
    if notes is None:
        notes = []
    elif not isinstance(notes, list):
        notes = [notes]
    notes = [_clip(note, MAX_TEXT) for note in notes[:MAX_NOTES] if _clip(note, MAX_TEXT)]
    values = _common_values(row, device)
    values.update({
        'client_id': _clip(row.get('client_id'), 64),
        'task_id': task.id,
        'start_at': start,
        'end_at': end,
        'utc_offset': start_offset or end_offset or offset,
        'notes': notes,
    })
    return values, False


def _pool_values(row, task, offset, device):
    text = _clip(row.get('text'), MAX_TEXT)
    if not text:
        return {}, _('想法内容是空的')
    created, _ = parse_client_datetime(row.get('created'), offset)
    done_at, _ = parse_client_datetime(row.get('done_at'), offset)
    values = _common_values(row, device)
    values.update({
        'client_id': _clip(row.get('client_id'), 64),
        'task_id': task.id,
        'text': text,
        'client_created': created,
        'done_at': done_at,
    })
    return values, False


def format_duration(seconds):
    """秒 → 中文时长。全站只显示这一种写法，免得各处四舍五入口径不一。"""
    seconds = max(int(seconds or 0), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return '%d 小时 %d 分' % (hours, minutes)
    if minutes:
        return '%d 分 %d 秒' % (minutes, secs) if secs else '%d 分' % minutes
    return '%d 秒' % secs
