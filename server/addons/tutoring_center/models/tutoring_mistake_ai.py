"""错题的 AI 摘要任务：把出错那一页交给视觉模型，抄回题目、生成一句摘要、比对知识点。

设计口径（维护者定的，别改）：
* 一题一次——成功也好、失败也好，都只允许发起一次，失败后这道题只能手工填；
* 额度按**发起人**按自然日算，一天 5 条，成败都扣；
* AI 不解题、不讲思路；页码/资料对不上时它该立刻回 `{"found": false}` 而不是硬猜；
* 知识点**只在为空时**由 AI 填，且只能从候选列表里逐字选一个，选不出就留空。
"""
import base64
import io
import json
import logging
import os

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

DAILY_QUOTA = 5           # 每人每天几条
PER_TICK = 2              # 每个 cron tick 最多处理几条（就算连点也不会一次打出一堆请求）
API_TIMEOUT = 90          # 实测 2~4 秒；上限仍留在 limit_time_real=120 之内
MAX_OUTPUT_TOKENS = 700   # 输出就是一个小 JSON，700 已经宽裕
LONG_SIDE = 1600          # 扫描页缩到长边 1600 仍能抄对公式（探针实测）
JPEG_QUALITY = 82
CANDIDATE_LIMIT = 200     # 候选知识点条数，控输入 token

SYSTEM_PROMPT = (
    '你是学习记录助手。给你的是教辅书的**其中一页**，以及要在这页里找的一道题的出处。\n'
    '只做三件事：1) 找到这道题并把题目原文抄出来；2) 用不超过 40 个字概括它在问什么；'
    '3) 从候选知识点里挑出这道题真正考的那一个。\n'
    '规则：\n'
    '- 只依据给你的这一页。这一页里没有这道题时，**立刻**只回 {"found": false}，'
    '不要解释、不要猜测、不要输出别的字。\n'
    '- 不要解题、不要讲思路、不要给答案。\n'
    '- 知识点必须从候选列表里逐字选一个，列表里没有就填 null，不要自己造名字。\n'
    '- 只输出一个 JSON 对象，不要 markdown 代码块，不要多余文字。\n'
    '输出字段：{"found": true, "question_text": "题目原文", '
    '"summary": "≤40字摘要", "point": "候选中的知识点原名或 null"}'
)

# 失败时写在题上的那句话：告诉人要手工补，而不是再点一次
FAIL_HINT = _(
    '自动生成没有成功，这道题不再重复生成。请手工填写知识点与一句话摘要。')


class AiPageError(UserError):
    """资料侧的问题（定位不到页、页里没有位图）——不去调 API，直接算失败。"""


class TutoringMistakeAiJob(models.Model):
    _name = 'tutoring.mistake.ai.job'
    _description = '错题 AI 摘要任务'
    _order = 'id desc'

    mistake_id = fields.Many2one(
        'tutoring.mistake', string='错题', required=True, index=True, ondelete='cascade')
    user_id = fields.Many2one(
        'res.users', string='发起人', required=True, index=True,
        default=lambda self: self.env.uid,
        help='额度按发起人算，成败都算一次。')
    day = fields.Date(
        '日期', required=True, index=True, default=fields.Date.context_today)
    state = fields.Selection([
        ('pending', '排队中'), ('done', '已生成'), ('failed', '失败'),
    ], string='状态', required=True, default='pending', index=True)
    error = fields.Char('失败原因')
    prompt_tokens = fields.Integer('输入 token')
    completion_tokens = fields.Integer('输出 token')
    response_raw = fields.Text('响应原文')

    _mistake_uniq = models.Constraint(
        'unique(mistake_id)',
        _('这道题已经生成过一次，不能再生成摘要。'))

    # ---- 发起 ----

    @api.model
    def quota_left(self):
        """今天还剩几条额度（只给页面提示用；真正的拦截在 create 里）。"""
        used = self.search_count([
            ('user_id', '=', self.env.uid),
            ('day', '=', fields.Date.context_today(self)),
        ])
        return max(0, DAILY_QUOTA - used)

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        used = {}
        for vals in vals_list:
            vals.setdefault('day', today)
            mistake = self.env['tutoring.mistake'].browse(vals.get('mistake_id'))
            # 只有 search 会拼记录规则：browse().exists() 挡不住越权引用
            if not self.env['tutoring.mistake'].search_count([('id', '=', mistake.id)]):
                raise ValidationError(_('你选不到这条错题记录。'))
            if mistake.ai_state and mistake.ai_state != 'none':
                raise ValidationError(_(
                    '这道题已经%s过，一道题只能生成一次。' % (
                        {'pending': '排进队列', 'done': '生成过摘要',
                         'failed': '尝试过生成'}.get(mistake.ai_state), )))
            uid = vals.get('user_id') or self.env.uid
            if uid not in used:
                used[uid] = self.sudo().search_count([
                    ('user_id', '=', uid), ('day', '=', vals['day'])])
            if used[uid] >= DAILY_QUOTA:
                raise ValidationError(_(
                    '今天 %d 条摘要额度已经用完了，明天再来。' % DAILY_QUOTA))
            used[uid] += 1
        jobs = super().create(vals_list)
        # ai_state 是机器字段：发起人不必然有整条记录的写权限（比如老师替学生点），
        # 这里只动这一个字段，所以走 sudo。
        jobs.mistake_id.sudo().write({'ai_state': 'pending'})
        return jobs

    def action_open_mistake(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tutoring.mistake',
            'res_id': self.mistake_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ---- 配置 ----

    @api.model
    def _config(self):
        """密钥优先读环境变量，读不到再退到系统参数（值只在业务库里，不进 git）。"""
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'key': os.environ.get('DEEPSEEK_API_KEY')
                   or icp.get_param('tutoring_center.deepseek_api_key', ''),
            'model': icp.get_param('tutoring_center.deepseek_model', 'deepseek-flash'),
            'url': icp.get_param(
                'tutoring_center.deepseek_base_url',
                'https://api.deepseek.com/v1/chat/completions'),
        }

    # ---- 取料 ----

    @api.model
    def _page_image(self, mistake):
        """把"出错那一页"变成可发送的 JPEG base64。

        教辅是扫描版、没有文字层，而那一页本身就是一张内嵌位图，取出来缩放即可，
        不需要光栅化引擎（DeepSeek 的 image_url 只收 webp/png/jpeg/gif，PDF 直传会被拒）。
        """
        from odoo.tools.pdf import PdfReader
        from PIL import Image

        file, local, hint = mistake.workbook_id._locate_page(mistake.page)
        if not file:
            raise AiPageError(hint or _('定位不到这一页。'))
        data = self.env['tutoring.workbook.page']._pdf_for(file, local)
        if not data:
            raise AiPageError(_('《%s》里抽不出第 %s 页。') % (
                mistake.workbook_id.name, mistake.page))
        if isinstance(data, bytes):
            data = data.decode('ascii', 'ignore')
        pages = PdfReader(io.BytesIO(base64.b64decode(data))).pages
        if not pages:
            raise AiPageError(_('抽出来的那一页是空的。'))
        images = list(pages[0].images)
        if not images:
            raise AiPageError(_('这一页里没有位图（可能是纯文字排版的页），无法交给视觉模型。'))
        img = Image.open(io.BytesIO(images[0].data))
        ratio = min(1.0, float(LONG_SIDE) / max(img.size))
        if ratio < 1.0:
            img = img.resize(
                (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                Image.LANCZOS)
        buf = io.BytesIO()
        img.convert('RGB').save(buf, 'JPEG', quality=JPEG_QUALITY, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('ascii')

    @api.model
    def _candidates(self, mistake):
        """候选知识点：与门户那个挑选域同源（按学生年级放开），返回 {完整路径: id}。"""
        grades = [g for g in (mistake.student_id.knowledge_grades or []) if g]
        if not grades:
            return {}
        points = self.env['tutoring.knowledge.point'].sudo().search(
            [('grade', 'in', grades)], order='grade, name', limit=CANDIDATE_LIMIT)
        return {p.full_name: p.id for p in points}

    def _user_text(self, mistake, candidates):
        return _(
            '出处：《%(book)s》第 %(page)s 页，题号：%(no)s。\n'
            '学生年级：%(grade)s。当前已填知识点：%(point)s。\n'
            '候选知识点（只能从中选，逐字）：\n%(points)s\n') % {
            'book': mistake.workbook_id.name,
            'page': mistake.page,
            'no': mistake.question_no or _('（未填题号）'),
            'grade': mistake.student_id.grade_label,
            'point': mistake.point_id.name or _('（无）'),
            'points': '\n'.join('- ' + name for name in candidates),
        }

    # ---- 执行 ----

    @api.model
    def _cron_process_pending(self):
        """ir.cron 入口：每次最多处理 PER_TICK 条。"""
        jobs = self.sudo().search([('state', '=', 'pending')], order='id', limit=PER_TICK)
        for job in jobs:
            try:
                job._run()
            except Exception as exc:  # noqa: BLE001 - 一条坏任务不能带崩整个 cron
                _logger.exception('AI 摘要任务 %s 异常', job.id)
                job._fail('%s: %s' % (type(exc).__name__, exc))
            # 一条一提交：中途服务被重启，已完成的结果与已扣的额度不会一起回滚
            self.env.cr.commit()
        return len(jobs)

    def _run(self):
        self.ensure_one()
        mistake = self.mistake_id
        conf = self._config()
        if not conf['key']:
            return self._fail(_('没有 DeepSeek 密钥：在系统参数 tutoring_center.deepseek_api_key '
                               '里填，或给服务配环境变量 DEEPSEEK_API_KEY。'))
        try:
            img_b64 = self._page_image(mistake)
        except AiPageError as exc:
            return self._fail(str(exc))
        candidates = self._candidates(mistake)
        payload = {
            'model': conf['model'],
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': self._user_text(mistake, candidates)},
                    {'type': 'image_url',
                     'image_url': {'url': 'data:image/jpeg;base64,' + img_b64,
                                   'detail': 'high'}},
                ]},
            ],
            'temperature': 0,
            'max_tokens': MAX_OUTPUT_TOKENS,
            # 这版模型不传就自己思考（实测默认烧掉 150+ reasoning token），必须显式关掉
            'thinking': {'type': 'disabled'},
        }
        try:
            resp = requests.post(
                conf['url'], headers={'Authorization': 'Bearer ' + conf['key']},
                json=payload, timeout=API_TIMEOUT)
        except requests.RequestException as exc:
            return self._fail(_('接口没连通：%s') % exc)
        if resp.status_code != 200:
            return self._fail(_('接口返回 HTTP %s：%s') % (
                resp.status_code, (resp.text or '')[:200]))
        try:
            body = resp.json()
            message = body['choices'][0]['message']
        except Exception:  # noqa: BLE001
            return self._fail(_('接口响应不是预期的形状。'))
        usage = body.get('usage') or {}
        self.sudo().write({
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'response_raw': (message.get('content') or '')[:2000],
        })
        data = self._parse(message.get('content') or '')
        if data is None:
            return self._fail(_('模型没有按约定的 JSON 回话。'))
        if not data.get('found'):
            return self._fail(_(
                '这一页里没找到「%s」——多半是页码或教材对不上。') % (mistake.question_no or mistake.page))
        return self._apply(mistake, data, candidates)

    @api.model
    def _parse(self, text):
        """容错解析：模型偶尔会裹一层代码块围栏，所以只认首尾大括号之间的那段。"""
        cleaned = text or ''
        start, end = cleaned.find('{'), cleaned.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start:end + 1])
        except ValueError:
            return None
        return data if isinstance(data, dict) and 'found' in data else None

    def _apply(self, mistake, data, candidates):
        vals = {
            'ai_state': 'done',
            'ai_done_at': fields.Datetime.now(),
            'ai_summary': (data.get('summary') or '')[:200],
            'ai_question_text': (data.get('question_text') or '')[:4000],
            'ai_hint': False,
        }
        # 只在为空时填，且必须是候选里逐字存在的那一个——不许模型自己造名字
        picked = False
        if not mistake.point_id:
            picked = candidates.get((data.get('point') or '').strip())
            if picked:
                vals['point_id'] = picked
        mistake.sudo().write(vals)
        self.sudo().write({'state': 'done', 'error': False})

    def _fail(self, reason):
        self.ensure_one()
        self.sudo().write({'state': 'failed', 'error': str(reason)[:400]})
        self.mistake_id.sudo().write({
            'ai_state': 'failed',
            'ai_hint': '%s（%s）' % (FAIL_HINT, reason) if reason else FAIL_HINT,
        })
