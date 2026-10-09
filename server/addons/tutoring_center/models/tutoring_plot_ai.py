"""函数图像页的智能画图：一句话描述 → DeepSeek 出方程 → 前端 addCurve。

额度按发起人的自然日算，一天 10 次，记在本模型上，不靠页面上的数字。
分界线与错题摘要一致，只是更严一点：请求送出去之前的失败（空输入、超长、
没密钥、我们自己的代码）不扣；超时、连不上、非 200 也没看到用量，不扣；
接口 200（模型已经回话，含「画不了」和 JSON 不合约定）才扣一次。
"""
import logging
import os

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import file_open

from .deepseek_config import ICP_PLOT_MODEL, deepseek_settings
from .deepseek_env import ENV_KEY, mask_secret, normalize_api_key, write_env_key
from .plot_expr import (
    MAX_CURVES,
    MAX_INPUT_CHARS,
    interpret_model_output,
    prepare_description,
)

_logger = logging.getLogger(__name__)

DAILY_QUOTA = 10
API_TIMEOUT = 30          # 纯文本小 JSON，留在 limit_time_real=120 之内
MAX_OUTPUT_TOKENS = 256   # 只要几条方程的 JSON，不给讲解留地方

PROMPT_FILES = {
    'system': 'tutoring_center/prompts/plot_system.txt',
    'user': 'tutoring_center/prompts/plot_user.txt',
}


class TutoringPlotAiCall(models.Model):
    _name = 'tutoring.plot.ai.call'
    _description = '函数图像智能画图'
    _order = 'id desc'

    user_id = fields.Many2one(
        'res.users', string='发起人', required=True, index=True,
        default=lambda self: self.env.uid)
    day = fields.Date(
        '日期', required=True, index=True, default=fields.Date.context_today)
    state = fields.Selection([
        ('pending', '进行中'),
        ('done', '已画出'),
        ('failed', '未画出'),
        ('error', '未扣次'),
    ], string='状态', required=True, default='pending', index=True)
    error = fields.Char('说明')
    description = fields.Char('描述', size=200)
    prompt_tokens = fields.Integer('输入 token')
    completion_tokens = fields.Integer('输出 token')
    response_raw = fields.Text('响应原文')

    # pending 先占住名额，避免两次点击同时穿过「还剩 1 次」。
    # error 是没花到 token 的那些，不算。
    CHARGED = ('pending', 'done', 'failed')

    @api.model
    def quota_left(self):
        user = self.env.user
        if not user or user._is_public():
            return 0
        used = self.sudo().search_count([
            ('user_id', '=', user.id),
            ('day', '=', fields.Date.context_today(self)),
            ('state', 'in', self.CHARGED),
        ])
        return max(0, DAILY_QUOTA - used)

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            if not self.env.su:
                vals['user_id'] = self.env.uid
            vals.setdefault('user_id', self.env.uid)
            vals.setdefault('day', today)
            vals.setdefault('state', 'pending')
            prepared.append(vals)
        uids = sorted({vals['user_id'] for vals in prepared})
        for uid in uids:
            self.env.cr.execute('SELECT id FROM res_users WHERE id = %s FOR UPDATE', [uid])
        adding = {}
        for vals in prepared:
            if vals['state'] in self.CHARGED:
                adding[vals['user_id']] = adding.get(vals['user_id'], 0) + 1
        for uid, count in adding.items():
            day = next(vals['day'] for vals in prepared if vals['user_id'] == uid)
            used = self.sudo().search_count([
                ('user_id', '=', uid),
                ('day', '=', day),
                ('state', 'in', self.CHARGED),
            ])
            if used + count > DAILY_QUOTA:
                raise UserError(_('今天 %d 次智能画图已经用完了，明天再来。') % DAILY_QUOTA)
        return super().create(prepared)

    # ---- 配置与密钥（管理员） ----

    def _check_settings_admin(self):
        user = self.env.user
        if not user or user._is_public() or not user.has_group('base.group_system'):
            raise AccessError(_('只有系统管理员可以保存密钥。'))

    @api.model
    def key_status(self):
        """给页面看的状态。只有 masked / source / configured，没有密钥原文。"""
        self._check_settings_admin()
        conf = deepseek_settings(self.env)
        return {
            'configured': bool(conf['key']),
            'masked': mask_secret(conf['key']),
            'source': conf['source'],
        }

    @api.model
    def save_api_key(self, api_key):
        """写入 .env（0600）并放进当前进程的环境变量，不必重启。"""
        self._check_settings_admin()
        try:
            key = normalize_api_key(api_key)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        path = deepseek_settings(self.env)['env_file']
        try:
            write_env_key(path, key)
        except OSError as exc:
            _logger.exception('写入 DeepSeek 密钥文件失败')
            raise UserError(_(
                '密钥没有保存成功：服务进程写不了 .env 文件。'
                '可以在系统参数 tutoring_center.deepseek_env_file 里改成一个进程有权写入、'
                '且文件名必须是 .env 的路径。')) from exc
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        os.environ[ENV_KEY] = key
        return self.key_status()

    # ---- 画图 ----

    @api.model
    def _prompt(self, kind):
        path = PROMPT_FILES[kind]
        try:
            return file_open(path, 'rb').read().decode('utf-8').strip()
        except (OSError, FileNotFoundError) as exc:
            raise RuntimeError('missing plot prompt %s' % kind) from exc

    @api.model
    def _user_text(self, description):
        template = self._prompt('user')
        token = '%%DESCRIPTION%%'
        if token not in template:
            raise RuntimeError('plot user prompt missing placeholder')
        head, tail = template.split(token, 1)
        return head + description + tail

    @api.model
    def _payload(self, description, model):
        return {
            'model': model,
            'messages': [
                {'role': 'system', 'content': self._prompt('system')},
                {'role': 'user', 'content': self._user_text(description)},
            ],
            'temperature': 0,
            'max_tokens': MAX_OUTPUT_TOKENS,
            # 不传就自己思考，输出额度会被推理吃掉；与错题摘要一样显式关掉
            'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'},
        }

    def _message(self, code, detail):
        if code == 'not_plottable' and detail:
            return _('画不出来（%s）。这次已计入今日次数。') % detail
        return {
            'unparseable': _('模型没有按约定的 JSON 回话。这次已计入今日次数。'),
            'not_plottable': _('这句话不是能画的函数图像。这次已计入今日次数。'),
            'bad_expr': _('模型给的式子没法画，请换种说法再试一次。这次已计入今日次数。'),
        }.get(code, _('模型没有按约定的 JSON 回话。这次已计入今日次数。'))

    def _note(self, outcome):
        parts = []
        if outcome['truncated']:
            parts.append(_('只绘制前 %d 条。') % MAX_CURVES)
        if outcome['skipped']:
            parts.append(_('有 %d 条式子没法识别，已略过。') % outcome['skipped'])
        return ''.join(parts)

    @api.model
    def draw(self, description):
        user = self.env.user
        if not user or user._is_public():
            raise AccessError(_('请先登录后再使用智能画图。'))
        code, text = prepare_description(description, MAX_INPUT_CHARS)
        if code == 'empty' or code == 'bad_type':
            raise UserError(_(
                '请先写一句要画的图像，例如「焦点在 x 轴、离心率 √5/3、长轴长 6 的椭圆」。'))
        if code == 'too_long':
            raise UserError(_(
                '描述太长了（最多 %d 个字），请缩短后再试。这次没有扣次数。') % MAX_INPUT_CHARS)
        conf = deepseek_settings(self.env, model_param=ICP_PLOT_MODEL)
        if not conf['key']:
            raise UserError(_(
                '还没有配置 DeepSeek 密钥。请管理员在本页保存密钥，'
                '或给服务设置环境变量 DEEPSEEK_API_KEY。'))
        # sudo 只为了记账；返回给页面的额度必须按发起人算，不能按超级用户算。
        job = self.sudo().create({
            'user_id': user.id,
            'day': fields.Date.context_today(self),
            'state': 'pending',
            'description': text[:200],
        })
        try:
            result = job._execute(conf, text)
        except UserError:
            if job.state == 'pending':
                job.sudo().write({'state': 'error', 'error': 'aborted'})
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.exception('智能画图失败 call=%s', job.id)
            if job.state == 'pending':
                job.sudo().write({'state': 'error', 'error': type(exc).__name__[:80]})
            raise UserError(_('智能画图出了点问题，请稍后再试。这次没有扣次数。')) from exc
        result['quota_left'] = self.quota_left()
        result['quota_max'] = DAILY_QUOTA
        return result

    def _execute(self, conf, text):
        self.ensure_one()
        payload = self._payload(text, conf['model'])
        try:
            resp = requests.post(
                conf['url'],
                headers={'Authorization': 'Bearer ' + conf['key']},
                json=payload,
                timeout=API_TIMEOUT,
                allow_redirects=False,
            )
        except requests.Timeout:
            self.sudo().write({'state': 'error', 'error': 'timeout'})
            raise UserError(_('画图请求超时了，请稍后再试。这次没有扣次数。'))
        except requests.RequestException:
            self.sudo().write({'state': 'error', 'error': 'network'})
            raise UserError(_('暂时连不上 DeepSeek，请稍后再试。这次没有扣次数。'))
        if resp.status_code != 200:
            _logger.warning('智能画图接口 HTTP %s', resp.status_code)
            self.sudo().write({'state': 'error', 'error': 'http %s' % resp.status_code})
            raise UserError(_(
                'DeepSeek 接口返回了错误（HTTP %s）。这次没有扣次数。') % resp.status_code)
        try:
            body = resp.json()
            content = body['choices'][0]['message'].get('content') or ''
        except Exception:  # noqa: BLE001
            self.sudo().write({
                'state': 'failed',
                'error': 'bad shape',
                'response_raw': (resp.text or '')[:500],
            })
            raise UserError(self._message('unparseable', ''))
        usage = body.get('usage') or {}
        outcome = interpret_model_output(content)
        self.sudo().write({
            'state': 'done' if outcome['ok'] else 'failed',
            'error': False if outcome['ok'] else outcome['code'],
            'prompt_tokens': _token_count(usage.get('prompt_tokens')),
            'completion_tokens': _token_count(usage.get('completion_tokens')),
            'response_raw': content[:2000],
        })
        if not outcome['ok']:
            raise UserError(self._message(outcome['code'], outcome['detail']))
        return {
            'curves': outcome['curves'],
            'note': str(self._note(outcome)),
        }


def _token_count(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(number, 10_000_000))
