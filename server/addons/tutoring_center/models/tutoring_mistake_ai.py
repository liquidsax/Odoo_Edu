"""错题的 AI 摘要任务：把题目照片（没有照片时是教辅那一页）交给视觉模型，抄回题目、生成一句摘要、比对知识点。

设计口径（维护者定的，别改）：
* 生成成功就定这一版，不再自动重生成；**没成功允许再点**——2026-10-13 他推翻了自己当初
  "一题一次、失败也永久锁死"那条：锁死的本意是防烧钱，可那道题压根没生成出摘要时锁住没道理，
  防烧钱交给当日额度管；
* 额度按**发起人**按自然日算，一天几条由 `DAILY_QUOTA` 说话（页面文案读 `quota_left()`），
  真发起过就扣，不管最后有没有生成出来；
* 素材取不到（没照片又定位不到页、那一页里没有位图、照片读不出来）走 `_abort()`——
  token 还没花出去，不扣额度、这道题退回未生成；
* AI 不解题、不讲思路；题不在给它的素材里时它该立刻回 `{"found": false}` 而不是硬猜；
* 知识点**只在为空时**由 AI 填，且只能从候选列表里逐字选一个，选不出就留空。
"""
import base64
import io
import json
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import file_open

from .deepseek_config import deepseek_settings
from .math_text import to_plain_math
from .tutoring_knowledge import GRADE_LABEL
from .tutoring_library_item import b64_to_bytes

_logger = logging.getLogger(__name__)

DAILY_QUOTA = 25          # 每人每天几条（2026-10-12 由 5 提到 25：页面文案读这个常量，不再写死）
PER_TICK = 2              # 每个 cron tick 最多处理几条（就算连点也不会一次打出一堆请求）
API_TIMEOUT = 90          # 实测 2~4 秒；上限仍留在 limit_time_real=120 之内
MAX_OUTPUT_TOKENS = 700   # 输出就是一个小 JSON，700 已经宽裕
LONG_SIDE = 1600          # 扫描页缩到长边 1600 仍能抄对公式（探针实测）
JPEG_QUALITY = 82
CANDIDATE_LIMIT = 200     # 候选知识点条数，控输入 token

# 提示词存在模块里的独立文件，改文案不必碰代码（维护者要求的）。
# 措辞会直接影响 token 数与"找不到题时是否快速回绝"，改之前先看一眼实测记录。
# 两套话术按素材分开：教辅那一页上往往好几道题，要给它出处去定位；
# 题目照片里就是这道题本身，硬塞"第几页"反而让它去找不存在的东西。
PROMPT_FILES = {
    'system': 'tutoring_center/prompts/summary_system.txt',
    'user': 'tutoring_center/prompts/summary_user.txt',
    'system_photo': 'tutoring_center/prompts/summary_system_photo.txt',
    'user_photo': 'tutoring_center/prompts/summary_user_photo.txt',
}

# 失败时写在题上的那句话：现在说得清"还能再来一次"，也说得清额度是人的
FAIL_HINT = _(
    '这次自动生成没成功，可以再点一次「生成摘要」（每次发起都算一条当日额度）；'
    '也可以先手工填知识点与一句话摘要。')


class AiSourceError(UserError):
    """素材侧的问题（定位不到页、页里没有位图、照片读不出来）——
    token 还没花出去，所以不扣额度、这道题退回未生成。"""


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
        ('error', '系统出错'),
    ], string='状态', required=True, default='pending', index=True)
    error = fields.Char('失败原因')
    prompt_tokens = fields.Integer('输入 token')
    completion_tokens = fields.Integer('输出 token')
    response_raw = fields.Text('响应原文')

    # 刻意不加 unique(mistake_id)：没生成出来的那道题要能重来，同一题就会留下多行历史。
    # "成功就定稿"由错题上的 ai_state 与下面的 create() 把关，比数据库约束更贴合语义。
    CHARGED = ('pending', 'done', 'failed')   # 算进当日额度的三种
    # error 不算：那一档全是"钱还没花出去"——没密钥、素材取不到、我们自己的代码出错

    # ---- 发起 ----

    @api.model
    def quota_left(self):
        """今天还剩几条额度（只给页面提示用；真正的拦截在 create 里）。"""
        used = self.search_count([
            ('user_id', '=', self.env.uid),
            ('day', '=', fields.Date.context_today(self)),
            ('state', 'in', self.CHARGED),
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
            if mistake.ai_state == 'pending':
                raise ValidationError(_('这道题已经排进队列，正在生成中。'))
            if mistake.ai_state == 'done':
                raise ValidationError(_('这道题已经生成过摘要，不再重复生成。'))
            # 兜一层：同一题不许有第二条"排队中/已生成"的任务。这里刻意不管 failed 与 error，
            # 否则这道题就被上一次失败焊死了——额度才是防烧钱的那道闸。
            if self.sudo().search_count([
                    ('mistake_id', '=', mistake.id), ('state', 'in', ('pending', 'done'))]):
                raise ValidationError(_('这道题正在生成或已经生成过，不能再生成摘要。'))
            uid = vals.get('user_id') or self.env.uid
            if uid not in used:
                used[uid] = self.sudo().search_count([
                    ('user_id', '=', uid), ('day', '=', vals['day']),
                    ('state', 'in', self.CHARGED)])
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
        """与智能画图共用一条密钥路径：环境变量，其次 .env，最后系统参数。"""
        conf = deepseek_settings(self.env)
        return {'key': conf['key'], 'model': conf['model'], 'url': conf['url']}

    # ---- 取料 ----

    @api.model
    def _images(self, mistake):
        """这道题能发给视觉模型的素材：返回 (JPEG base64 列表, 种类)。

        种类是 `photo` 或 `page`，决定用哪套话术。**照片优先**（2026-10-13 维护者拍的）：
        他自己拍的那张往往正是不会的那道题，而教辅那一页上还印着别的题。
        """
        photos = self._photo_images(mistake)
        if photos:
            return photos, 'photo'
        return [self._page_image(mistake)], 'page'

    @api.model
    def _photo_images(self, mistake):
        """挂在错题上的题目照片，全部发，按上传先后排（一张题被拍成两张时要有顺序）。

        读正文走 sudo：条目归上传人自己，而"这道题该不该分析"不该由权限决定。
        坏掉的那张跳过而不是报错——连拍三张有一张没存全，不该挡住另外两张。
        """
        from PIL import Image

        items = mistake.sudo().library_item_ids.filtered(
            lambda item: item.kind == 'image' and item.file_size).sorted('id')
        images = []
        for item in items:
            try:
                images.append(self._to_jpeg(Image.open(io.BytesIO(
                    b64_to_bytes(item.content)))))
            except Exception:  # noqa: BLE001 截断/伪扩展名/格式不支持，都只是这一张用不了
                _logger.warning('错题 %s 的附件「%s」读不出图片，跳过', mistake.id, item.name)
        return images

    @api.model
    def _page_image(self, mistake):
        """把"出错那一页"变成可发送的 JPEG base64。

        教辅是扫描版、没有文字层，而那一页本身就是一张内嵌位图，取出来缩放即可，
        不需要光栅化引擎（DeepSeek 的 image_url 只收 webp/png/jpeg/gif，PDF 直传会被拒）。
        """
        from odoo.tools.pdf import PdfReader
        from PIL import Image

        file, local, hint = mistake.sudo().workbook_id._locate_page(mistake.page)
        if not file:
            raise AiSourceError(hint or _('定位不到这一页。'))
        # 整条取页都走 sudo：教材正文挂在上传者自己的知识库条目上，门户用户按记录规则
        # 读不到那些行（这是另一条待修的既有 bug），而"能不能分析这一页"不该由他决定。
        data = self.env['tutoring.workbook.page'].sudo()._pdf_for(file, local)
        if not data:
            raise AiSourceError(_('《%s》里抽不出第 %s 页。') % (
                mistake.workbook_id.name, mistake.page))
        if isinstance(data, bytes):
            data = data.decode('ascii', 'ignore')
        pages = PdfReader(io.BytesIO(base64.b64decode(data))).pages
        if not pages:
            raise AiSourceError(_('抽出来的那一页是空的。'))
        images = list(pages[0].images)
        if not images:
            raise AiSourceError(_(
                '《%(book)s》第 %(page)s 页里没有位图（多半是纯文字排版的那一页），'
                '交不给视觉模型——传一张题目照片再点一次就行。') % {
                'book': mistake.workbook_id.name, 'page': mistake.page})
        return self._to_jpeg(Image.open(io.BytesIO(images[0].data)))

    @api.model
    def _to_jpeg(self, img):
        """两套素材共用那道缩放：长边 1600、JPEG 质量 82（探针实测这样仍能抄对公式），
        顺便把 png/webp/bmp/gif 收成同一种类型——请求里只会出现 image/jpeg。"""
        from PIL import Image

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

    @api.model
    def _prompt(self, kind):
        r"""读 prompts/ 下的文案。rb + 显式 decode：Windows 上文本模式会按控制台代码页读。"""
        path = PROMPT_FILES[kind]
        try:
            return file_open(path, 'rb').read().decode('utf-8').strip()
        except (FileNotFoundError, IsADirectoryError):
            raise UserError(_('找不到提示词文件 %s') % path)

    def _user_text(self, mistake, candidates, kind='page', count=1):
        points = '\n'.join('- ' + name for name in candidates)
        facts = {
            'no': mistake.question_no or _('（未填题号）'),
            'grade': GRADE_LABEL.get(mistake.student_id.grade, mistake.student_id.grade or '—'),
            'point': mistake.point_id.name or _('（无）'),
            'points': points,
        }
        if kind == 'photo':
            # 照片版不写"第几页"——那一页上有别的题，硬给它出处反而让模型去找不存在的东西。
            # 但出处填了就一并带上，抄回来的题目能跟记录对上是人要看的。
            facts['n'] = count
            facts['where'] = (_('《%s》第 %s 页') % (mistake.workbook_id.name, mistake.page)
                              if mistake.workbook_id and mistake.page else _('没填'))
            return self._prompt('user_photo') % facts
        facts['book'] = mistake.workbook_id.name
        facts['page'] = mistake.page
        return self._prompt('user') % facts

    # ---- 执行 ----

    @api.model
    def _cron_process_pending(self):
        """ir.cron 入口：每次最多处理 PER_TICK 条。"""
        jobs = self.sudo().search([('state', '=', 'pending')], order='id', limit=PER_TICK)
        for job in jobs:
            job._run()
            # 一条一提交：中途服务被重启，已完成的结果与已扣的额度不会一起回滚
            self.env.cr.commit()
        return len(jobs)

    def _run(self):
        """跑一条任务。分界线是"token 花出去了没有"。

        花出去之前崩掉（没密钥、素材取不到、取料/组装时我们自己的代码出错）→ `_abort()`：
        不扣额度、这道题退回未生成，用户可以重来——我们的错与"根本没看图"都不该让人承担。
        花出去之后（含这道题不在素材里）→ `_fail()`：扣一条额度，但**不锁死**，
        他要再来一次就再来一条（防烧钱交给当日额度，不是把题焊死）。
        """
        self.ensure_one()
        mistake = self.mistake_id
        conf = self._config()
        if not conf['key']:
            return self._abort(_(
                '没有 DeepSeek 密钥：填系统参数 tutoring_center.deepseek_api_key，'
                '或给服务配环境变量 DEEPSEEK_API_KEY。'))
        try:
            candidates = self._candidates(mistake)
            images, kind = self._images(mistake)
            payload = self._payload(mistake, images, candidates, conf['model'], kind)
        except AiSourceError as exc:
            return self._abort(str(exc))
        except Exception as exc:  # noqa: BLE001
            _logger.exception('AI 摘要任务 %s 取料或组装出错', self.id)
            return self._abort('%s: %s' % (type(exc).__name__, exc))
        try:
            return self._call(conf, payload, mistake, candidates, kind)
        except Exception as exc:  # noqa: BLE001
            _logger.exception('AI 摘要任务 %s 调用或回写出错', self.id)
            return self._fail('%s: %s' % (type(exc).__name__, exc))

    @api.model
    def _payload(self, mistake, images, candidates, model, kind='page'):
        """多图就是把照片按上传先后排进同一个 content 列表；一张照片时形状和以前一样。"""
        content = [{'type': 'text',
                    'text': self._user_text(mistake, candidates, kind, len(images))}]
        content += [
            {'type': 'image_url',
             'image_url': {'url': 'data:image/jpeg;base64,' + img, 'detail': 'high'}}
            for img in images
        ]
        return {
            'model': model,
            'messages': [
                {'role': 'system', 'content': self._prompt(
                    'system_photo' if kind == 'photo' else 'system')},
                {'role': 'user', 'content': content},
            ],
            'temperature': 0,
            'max_tokens': MAX_OUTPUT_TOKENS,
            # 这版模型不传就自己思考（实测默认烧掉 150+ reasoning token），必须显式关掉
            'thinking': {'type': 'disabled'},
        }

    def _call(self, conf, payload, mistake, candidates, kind='page'):
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
                '%s里没找到「%s」——多半是页码或教材对不上。') % (
                _('这几张照片') if kind == 'photo' else _('这一页'),
                mistake.question_no or mistake.page or _('这道题')))
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

    def _abort(self, reason):
        """我们这边出错（还没花钱）：记一行审计，不扣额度，这道题退回未生成。

        原因必须写回题上（2026-10-13）：以前这里把 `ai_hint` 一起抹成空，于是
        「素材取不到」在门户上表现为——按钮亮着、点下去转一圈、什么都没发生，
        维护者据此判断成"DeepSeek 没响应"。留痕不等于状态：`ai_state` 照旧回 `none`。
        """
        self.ensure_one()
        self.sudo().write({'state': 'error', 'error': str(reason)[:400]})
        self.mistake_id.sudo().write({
            'ai_state': 'none',
            'ai_hint': _('%s 这次没扣额度。') % reason,
        })
