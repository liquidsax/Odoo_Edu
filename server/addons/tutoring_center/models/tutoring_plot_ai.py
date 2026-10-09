"""函数图像页的智能画图：一句话或一张题目图 → DeepSeek 出方程 → 前端 addCurve。

额度按发起人的自然日算，一天 10 次，记在本模型上，不靠页面上的数字。
分界线与错题摘要一致，只是更严一点：请求送出去之前的失败（空输入、超长、
图片不合格、没密钥、我们自己的代码）不扣；超时、连不上、非 200 也没看到用量，不扣；
接口 200（模型已经回话，含「画不了」和 JSON 不合约定）才扣一次。
模型把整道大题拒成「不是函数图像」时，若原文里已经有画布肯收的方程，仍按那条方程画，
这次已经花了 token，照样扣。
"""
import base64
import io
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
    MAX_IMAGE_BYTES,
    MAX_INPUT_CHARS,
    classify_image,
    extract_plot_equations,
    interpret_model_output,
    prepare_description,
)

_logger = logging.getLogger(__name__)

DAILY_QUOTA = 10
API_TIMEOUT = 30          # 纯文本小 JSON，留在 limit_time_real=120 之内
API_TIMEOUT_IMAGE = 60    # 识图比纯文本慢，仍留在 limit_time_real=120 之内
MAX_OUTPUT_TOKENS = 2048  # 16 条方程的 JSON 用 256 个 token 会被截断。过程仍不写进回复
IMAGE_LONG_SIDE = 1600    # 与错题摘要同一档：长边缩到 1600 仍能看清公式
IMAGE_JPEG_QUALITY = 82

PROMPT_FILES = {
    'system': 'tutoring_center/prompts/plot_system.txt',
    'user': 'tutoring_center/prompts/plot_user.txt',
    'image': 'tutoring_center/prompts/plot_user_image.txt',
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
    def _fill_prompt(self, kind, description):
        template = self._prompt(kind)
        token = '%%DESCRIPTION%%'
        if token not in template:
            raise RuntimeError('plot %s prompt missing placeholder' % kind)
        head, tail = template.split(token, 1)
        return head + (description or '（无）') + tail

    @api.model
    def _user_content(self, description, image_b64):
        if not image_b64:
            return self._fill_prompt('user', description)
        # 与错题摘要同一条识图格式：JPEG data URL，detail=high。不要把原图写进日志。
        return [
            {'type': 'text', 'text': self._fill_prompt('image', description)},
            {'type': 'image_url', 'image_url': {
                'url': 'data:image/jpeg;base64,' + image_b64,
                'detail': 'high',
            }},
        ]

    @api.model
    def _payload(self, description, model, image_b64=None):
        return {
            'model': model,
            'messages': [
                {'role': 'system', 'content': self._prompt('system')},
                {'role': 'user', 'content': self._user_content(description, image_b64)},
            ],
            'temperature': 0,
            'max_tokens': MAX_OUTPUT_TOKENS,
            # 不传就自己思考，输出额度会被推理吃掉；与错题摘要一样显式关掉
            'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'},
        }

    @api.model
    def _jpeg_base64(self, raw):
        """收成 JPEG。文件头已经在调用前检查过；这里打不开就当图片不合格。"""
        from PIL import Image, UnidentifiedImageError

        Image.MAX_IMAGE_PIXELS = 16_000_000
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('type') from exc
        if getattr(img, 'n_frames', 1) > 1:
            img.seek(0)
        img = img.convert('RGB')
        long_side = max(img.size)
        if long_side > IMAGE_LONG_SIDE:
            ratio = float(IMAGE_LONG_SIDE) / long_side
            img = img.resize(
                (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=IMAGE_JPEG_QUALITY, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('ascii')

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
        if outcome.get('recovered'):
            parts.append(_('题目里已经有方程，已按该方程绘制。'))
        if outcome['truncated']:
            parts.append(_('只绘制前 %d 条。') % MAX_CURVES)
        if outcome['skipped']:
            parts.append(_('有 %d 条式子没法识别，已略过。') % outcome['skipped'])
        return ''.join(parts)

    @api.model
    def _image_failure(self, code):
        if code == 'too_big':
            return UserError(_(
                '图片太大了（最大 %dMB），请换一张小一点的。这次没有扣次数。') % (
                    MAX_IMAGE_BYTES // (1024 * 1024)))
        return UserError(_(
            '这张图片打不开，或不是 jpg、png、webp、gif。这次没有扣次数。'))

    @api.model
    def draw(self, description='', image=None):
        user = self.env.user
        if not user or user._is_public():
            raise AccessError(_('请先登录后再使用智能画图。'))
        if image is not None and not isinstance(image, (bytes, bytearray)):
            raise self._image_failure('type')
        if image is not None and len(image) == 0:
            image = None
        code, text = prepare_description(description, MAX_INPUT_CHARS)
        if code == 'bad_type':
            code, text = 'empty', ''
        if code == 'too_long':
            raise UserError(_(
                '描述太长了（最多 %d 个字），请缩短后再试。这次没有扣次数。') % MAX_INPUT_CHARS)
        if code == 'empty' and image is None:
            raise UserError(_(
                '请先写一句要画的图像，或上传一张题目图片。'
                '例如「焦点在 x 轴、离心率 √5/3、长轴长 6 的椭圆」。'))
        image_code = classify_image(image)
        if image is not None and image_code != 'ok':
            raise self._image_failure(image_code)
        image_b64 = None
        if image is not None:
            try:
                image_b64 = self._jpeg_base64(image)
            except ValueError as exc:
                raise self._image_failure('type') from exc
        conf = deepseek_settings(self.env, model_param=ICP_PLOT_MODEL)
        if not conf['key']:
            raise UserError(_(
                '还没有配置 DeepSeek 密钥。请管理员在本页保存密钥，'
                '或给服务设置环境变量 DEEPSEEK_API_KEY。'))
        # sudo 只为了记账；返回给页面的额度必须按发起人算，不能按超级用户算。
        # 图片正文不入库。
        job = self.sudo().create({
            'user_id': user.id,
            'day': fields.Date.context_today(self),
            'state': 'pending',
            'description': (text or '（图片）')[:200],
        })
        try:
            result = job._execute(conf, text, image_b64)
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

    def _execute(self, conf, text, image_b64=None):
        self.ensure_one()
        payload = self._payload(text, conf['model'], image_b64)
        try:
            resp = requests.post(
                conf['url'],
                headers={'Authorization': 'Bearer ' + conf['key']},
                json=payload,
                timeout=API_TIMEOUT_IMAGE if image_b64 else API_TIMEOUT,
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
            recovered = extract_plot_equations(text)
            if recovered['curves']:
                self.sudo().write({
                    'state': 'done',
                    'error': False,
                    'response_raw': (resp.text or '')[:500],
                })
                return {
                    'curves': recovered['curves'],
                    'note': str(self._note({
                        'recovered': True,
                        'truncated': recovered['truncated'],
                        'skipped': 0,
                    })),
                }
            self.sudo().write({
                'state': 'failed',
                'error': 'bad shape',
                'response_raw': (resp.text or '')[:500],
            })
            raise UserError(self._message('unparseable', ''))
        usage = body.get('usage') or {}
        outcome = interpret_model_output(content)
        if not outcome['ok']:
            # 模型把整道题拒了，或把 frac 抄成画布不认的式子。原文里已经有方程就直接画。
            recovered = extract_plot_equations(text)
            if recovered['curves']:
                outcome = {
                    'ok': True,
                    'code': 'ok',
                    'detail': '',
                    'curves': recovered['curves'],
                    'skipped': 0,
                    'truncated': recovered['truncated'],
                    'recovered': True,
                }
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
