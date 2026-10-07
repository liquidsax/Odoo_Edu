"""时间账本的机器接口：Do1ng 桌面端登录、探活、同步。

三条路由都是给**程序**调的，不是给浏览器调的，所以有两处刻意偏离模块里其它控制器：

1. 一律返回 JSON + 明确的 HTTP 状态码，绝不 302 到登录页。核心对 `type='http'` 路由的
   会话过期处理是重定向到 `/web/login`（`odoo/http.py:2516`），桌面客户端跟着跳就会把
   登录页的 HTML 当成同步结果解析。所以同步路由用 `auth='public'` 再自己判空会话，
   把 401 握在自己手里。
2. `csrf=False`，改成要求自定义头 `X-Do1ng-Sync`。浏览器发跨站请求时加不了自定义头
   （会先触发 CORS 预检，而本站不发 CORS 头），所以这道头和 CSRF 令牌等效，
   同时又不需要桌面端去页面上抓令牌。
"""

import json
import logging
import time
from datetime import datetime, timezone

from odoo import _, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

CLIENT_HEADER = 'X-Do1ng-Sync'
# 协议版本：载荷或响应结构要破坏性变更时 +1，客户端据此判断"该升级了"
PROTOCOL = 1
# 4MB。真实载荷是几十 KB（作者本机全量 8.6KB），这个闸只防写坏的客户端。
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_REJECTED_REPORTED = 50


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(status, payload):
    return request.make_json_response(payload, status=status)


def _error(status, code, message, **extra):
    return _json(status, dict({'ok': False, 'error': code, 'message': message}, **extra))


def _client_header_value():
    return (request.httprequest.headers.get(CLIENT_HEADER) or '').strip()


def _read_payload():
    """请求体 → dict。返回 `None` 表示不是合法 JSON 对象。"""
    try:
        payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class TutoringTimeSyncController(http.Controller):

    @http.route('/tutoring/time/ping', type='http', auth='public',
                methods=['GET'], readonly=True)
    def time_ping(self, **kw):
        """探活：桌面端"测试连接"按钮与首次配置时用。

        不回答库名、模块版本这类只有管理员才需要知道的东西——它是 `auth='public'`，
        任何人都能打。客户端只需要知道"服务在、协议对得上、我现在是不是登录着"。
        """
        return _json(200, {
            'ok': True,
            'service': 'r3yna-time',
            'protocol': PROTOCOL,
            'server_time': _now_iso(),
            'logged_in': not request.env.user._is_public(),
        })

    @http.route('/tutoring/time/login', type='http', auth='none',
                methods=['POST'], csrf=False, readonly=False)
    def time_login(self, **kw):
        """账号密码换会话。

        不复用核心的 `/web/session/authenticate`，只为了省掉客户端一件事：那条路由要求
        请求体里带库名，而云机 `list_db=False`、`/web/database/list` 拿不到，等于逼用户
        在桌面端手填一个他根本不关心的 `OdooForDB`。这里服务端自己解析（`request.db`
        或 dbfilter 唯一命中），客户端只要给地址、账号、密码。
        """
        if not _client_header_value():
            return _error(400, 'missing_client_header',
                          _('缺少 %s 头，这个接口只接受 Do1ng 客户端调用。', CLIENT_HEADER))
        payload = _read_payload()
        if payload is None:
            return _error(400, 'bad_json', _('请求体不是合法的 JSON 对象。'))
        login = str(payload.get('login') or '').strip()
        password = payload.get('password') or ''
        if not login or not password:
            return _error(400, 'missing_credentials', _('账号和密码都要填。'))

        db = request.db
        if not db:
            # 走到这里说明服务端既没配 db_name 也没配 dbfilter，且库不止一个
            # （单库时核心会自动认出来，见 http.py 的 monodb 分支）：运维问题，客户端重试无用。
            # 刻意不用 X-Odoo-Database 头兜底——那条路径会把 session 标成 can_save=False，
            # 登录就发不出 cookie 了。
            return _error(503, 'no_database',
                          _('服务器没能确定要登录哪个库，请检查 db_name / dbfilter 配置。'))

        credential = {'login': login, 'password': password, 'type': 'password'}
        try:
            auth_info = request.session.authenticate(request.env, credential)
        except AccessDenied:
            return _error(401, 'bad_credentials', _('账号或密码不对。'))
        except UserError as err:
            # 登录防爆破的冷却期走这条（默认 5 次失败 / 60 秒）：客户端要退避，不要重试
            return _error(429, 'login_throttled', str(err))
        except AccessError as err:
            return _error(403, 'access_denied', str(err))

        if request.session.uid != auth_info.get('uid'):
            return _error(401, 'mfa_required',
                          _('这个账号开了两步验证，桌面端登不进来。'
                            '请在网页上关掉该账号的两步验证，或改用一个没开的账号。'))

        request.session.db = db
        request._save_session(request.env)
        user = request.env(user=request.session.uid).user
        return _json(200, {
            'ok': True,
            'protocol': PROTOCOL,
            'server_time': _now_iso(),
            'uid': user.id,
            'login': user.login,
            'name': user.name,
        })

    @http.route('/tutoring/time/sync', type='http', auth='public',
                methods=['POST'], csrf=False)
    def time_sync(self, **kw):
        """收一份桌面端的变更并落库，回每一行的最新 rev。

        用 `auth='public'` 而不是 `auth='user'` 只为拿到"自己回 401"的权利（见文件头注释）；
        真正的写权限仍由记录规则与 ACL 把关——匿名/公开用户在这里第一道就被挡回去。
        """
        if not _client_header_value():
            return _error(400, 'missing_client_header',
                          _('缺少 %s 头，这个接口只接受 Do1ng 客户端调用。', CLIENT_HEADER))
        if request.env.user._is_public():
            return _error(401, 'not_logged_in', _('会话失效了，请先登录。'))

        raw = request.httprequest.get_data()
        if len(raw) > MAX_BODY_BYTES:
            return _error(413, 'payload_too_large',
                          _('一次提交的数据太大（上限 %(limit)s MB）。',
                            limit=MAX_BODY_BYTES // 1024 // 1024))
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return _error(400, 'bad_json', _('请求体不是合法的 JSON 对象。'))

        started = time.monotonic()
        result, error, internal = {}, False, False
        try:
            # savepoint 是必需的：约束冲突之类的数据库错误会把整个事务标成 aborted，
            # 不回滚到保存点，后面那条同步日志就写不进去（本项目踩过）
            with request.env.cr.savepoint():
                result = request.env['tutoring.time.task'].sync_push(payload)
        except (UserError, ValidationError, AccessError) as err:
            error = str(err)
        except Exception:  # noqa: BLE001 - 要回 500 并留下堆栈，不能把裸异常抛给客户端
            _logger.exception('时间账本同步失败')
            error = _('服务器内部错误，详见 odoo.log。')
            internal = True
        duration_ms = int((time.monotonic() - started) * 1000)

        stats = result.get('stats') or {}
        device = request.env['tutoring.time.device'].browse(result.get('device_id') or [])
        client_info = payload.get('client') if isinstance(payload.get('client'), dict) else {}
        # 不 sudo：日志与设备都属于当前用户，sudo 会把 user_id 默认值写成超级用户，
        # 那样记录规则反而让用户看不见自己的同步历史
        sync_log = request.env['tutoring.time.sync'].record(
            device, 'push', stats, duration_ms, error,
            client_info.get('client_version'), request.httprequest.remote_addr)
        if device:
            device.note_result('error' if error else 'ok', error)

        rejected = result.get('rejected') or []
        status = 200 if not error else (500 if internal else 422)
        return _json(status, {
            'ok': not error,
            'error': error or False,
            'protocol': PROTOCOL,
            'server_time': _now_iso(),
            'stats': stats,
            'revs': result.get('revs') or {},
            # 逐行动作：客户端要靠它分清"这行成了（记 rev）"、"冲突了（换 rev 但保持脏）"、
            # "被拒了（原样留着下次再试）"。只有聚合计数是做不到的。
            'actions': result.get('actions') or {},
            'rejected': rejected[:MAX_REJECTED_REPORTED],
            'rejected_total': len(rejected),
            'device_key': result.get('device_key') or False,
            'sync_id': sync_log.id,
            'duration_ms': duration_ms,
        })
