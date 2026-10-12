# -*- coding: utf-8 -*-
"""每日回顾：把"这一天"的错题收拢成**一张**大图。

卡片墙那道题的封面（一题一张）解决的是"这道题长什么样"；这一版解决的是
"我今天要回看的东西合起来是什么"。所以配方挂在**某一天**上而不是某条错题上——
一天只有一张图，重做就是覆盖它，不是再攒一张。

跟逐题封面同一套口径：AI 只报"用哪几个元素 + 三句短话"，图由我们按 `mistake_cover`
那张素材表渲染（8 个色板 id + 12 个内联 SVG 图案 id），回来的东西全过 `clean()` 白名单。
**模型永远不出颜色值、不出 SVG、不出图片。**

AI 不通畅时才退到文字回顾：没配密钥、接口连不上/非 200、回的是坏 JSON、
或者色板与图案全是认不出的 id。退让**照样出一张能看的封面**（用这一天已有的事实排版），
并把"为什么退让"写在封面上——失败的那句话存进 `note`，下次进这一页还读得到，
不是只在点按钮那一刻闪一下就没影了。
"""
import json
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import mistake_cover

# 一次喂给模型的条数上限：一天正常也就几道，20 条已经宽裕。
# 再多 prompt 会长得让模型开始复读最后几句，反而把概括写虚。
DAY_ITEM_LIMIT = 20
# 退让原因在封面上占一行，太长的接口报错截一截就好
NOTE_MAX = 180


class TutoringMistakeDigest(models.Model):
    _name = 'tutoring.mistake.digest'
    _description = '错题每日回顾'
    _order = 'date desc, id desc'

    student_id = fields.Many2one(
        'tutoring.student', string='学习档案', required=True,
        ondelete='cascade', index=True)
    date = fields.Date('回顾日期', required=True, index=True)
    # AI 报回来的配方：只存白名单过的结构化选择（色板 id + 图案 id + 三句短话）。
    # 空串/坏 JSON 都算"没有 AI 那一张"，页面会退到文字回顾。
    recipe = fields.Text('回顾配方', copy=False)
    # 上一次尝试为什么没成（没密钥 / 连不上 / 坏 JSON / 全是废 id）。
    # 刻意留着：封面上那句"这是文字回顾，因为……"要经得起重新打开页面还在。
    note = fields.Char('退让原因')

    mistake_count = fields.Integer('这一天的错题数', compute='_compute_mistake_count')
    ready = fields.Boolean('有 AI 配方', compute='_compute_plan')
    style = fields.Char('封面底色', compute='_compute_plan')
    motifs = fields.Html('封面图案', compute='_compute_plan', sanitize=False)
    headline = fields.Char('封面概括', compute='_compute_plan')
    sub = fields.Char('封面小字', compute='_compute_plan')
    badge = fields.Char('封面角标', compute='_compute_plan')
    reason = fields.Char('为什么是文字回顾', compute='_compute_plan')

    # 一天一张是这一版的全部意义：同一份档案同一天再建一张，页面上就说不清哪张算数
    _student_date_uniq = models.Constraint(
        'unique(student_id, date)',
        '这一份档案在这一天已经有回顾了，重做那一张就行，不用再建一张。')

    # ---- 取 ----

    @api.model
    def for_day(self, student, day):
        """某天某份档案的那一条回顾（没有就回空集）。走 search 所以记录规则说了算。"""
        if not student or not day:
            return self.browse()
        return self.search([('student_id', '=', student.id), ('date', '=', day)], limit=1)

    @api.depends('student_id', 'date')
    def _compute_mistake_count(self):
        # 一次 read_group 拿完整份计数：一天一条回顾，逐条 search_count 就是 N+1。
        # `date:day` 的粒度不能省——_read_group 对日期字段没写粒度会当场
        # `ValueError: Granularity not set on a date(time) field`（列表页就是一串 500）。
        counts = {}
        for study, day_value, count in self.env['tutoring.mistake']._read_group(
                [('student_id', 'in', self.student_id.ids),
                 ('date', 'in', [d for d in self.mapped('date') if d])],
                ['student_id', 'date:day'], ['__count']):
            # 分组回来的日期按粒度可能是 datetime，跟 Date 字段比之前先归一成 date
            key = (study.id, day_value.date() if hasattr(day_value, 'date') else day_value)
            counts[key] = count
        for rec in self:
            rec.mistake_count = counts.get((rec.student_id.id, rec.date), 0)

    # ---- 配方 → 渲染 ----

    def _plan(self):
        """配方原文 → 白名单过的 dict。

        坏 JSON、整串废 id 都当"没有 AI 那一张"，但**返回的形状永远一样**（`clean()` 保证
        五个键都在），调用方才可以放心写 `plan['headline']` 而不是满地 .get()。
        空记录集也回一份空配方：练习册可以空着、那一天也可以还没有回顾，
        这类"假定自己一定被单条调用"的方法必须先想好空集怎么办（批次③那条教训）。
        """
        if not self:
            return mistake_cover.clean({})
        self.ensure_one()
        try:
            plan = json.loads(self.recipe or '{}')
        except ValueError:
            plan = {}
        return mistake_cover.clean(plan if isinstance(plan, dict) else {})

    def _is_ready(self):
        """有没有"能画的 AI 配方"：判据与错题上那份逐题封面一致。"""
        plan = self._plan()
        return bool(plan['headline'] or plan['motifs'] or plan['bg'])

    def _fallback_reason(self):
        """这张为什么是文字回顾（写在封面上，不能让人猜）。"""
        if not self:
            return _('这一天还没做过回顾')
        if self._is_ready():
            return False
        if self.note:
            return self.note
        if self.recipe:
            return _('上一次那份配方用不了：色板与图案全都不认识，或者 JSON 本身就是坏的')
        return _('这一天还没做过回顾')

    @api.depends('recipe', 'note')
    def _compute_plan(self):
        for rec in self:
            plan = rec._plan()
            rec.ready = bool(plan['headline'] or plan['motifs'] or plan['bg'])
            rec.style = mistake_cover.style_for(plan)
            rec.motifs = mistake_cover.motifs_svg(plan)
            rec.headline = plan['headline']
            rec.sub = plan['sub']
            rec.badge = plan['badge']
            rec.reason = rec._fallback_reason()

    # ---- 退让那一张：文字回顾（仍然是一张封面，不是一片空白） ----

    @api.model
    def fallback_plan(self, student, day, mistakes):
        """AI 不通畅时那张封面：只用这一天**已经有**的事实排，一句都不替它编。

        返回的还是 `clean()` 那个形状，所以模板只有一条渲染路径；
        底色按"这一天有多硬"挑（高难度多就偏红，否则石墨），图案一个都不放——
        图案是"这道题在讲什么"的意思，AI 不在场时我们不该替它猜。
        """
        plan = mistake_cover.clean({})
        if not mistakes:
            return plan
        hard = len(mistakes.filtered(lambda m: m.difficulty in ('4', '5')))
        points = Counter(
            name for name in mistakes.mapped('point_id.name') if name)
        no_point = len(mistakes.filtered(lambda m: not m.point_id))
        no_cause = len(mistakes.filtered(lambda m: not m.cause_id))
        plan['bg'] = 'crimson' if hard >= max(2, len(mistakes) // 2) else 'slate'
        if points:
            top = ', '.join('%s×%d' % (name, n) for name, n in points.most_common(2))
            plan['headline'] = top[:40]
        else:
            plan['headline'] = _('这一天记下 %d 道题') % len(mistakes)
        bits = [_('%d 道') % len(mistakes)]
        if hard:
            bits.append(_('高难度 %d 道') % hard)
        if no_point:
            bits.append(_('没标知识点 %d 道') % no_point)
        if no_cause:
            bits.append(_('没标错因 %d 道') % no_cause)
        plan['sub'] = ' · '.join(bits)[:60]
        plan['badge'] = day.strftime('%m-%d') if day else False
        return plan

    # ---- 生成 ----

    def _day_facts(self, student, day, mistakes):
        """喂给模型的那一大段：一天的账目 + 逐条已有的文字。"""
        hard = len(mistakes.filtered(lambda m: m.difficulty in ('4', '5')))
        points = Counter(name for name in mistakes.mapped('point_id.name') if name)
        causes = Counter(name for name in mistakes.mapped('cause_id.name') if name)
        lines = [
            '档案：%s' % (student.name or '未命名'),
            '日期：%s' % day,
            '这一天一共 %d 道错题，其中高难度（4~5🌶）%d 道。' % (len(mistakes), hard),
        ]
        if points:
            lines.append('知识点分布：%s' % '、'.join(
                '%s %d 道' % (name, n) for name, n in points.most_common(6)))
        if causes:
            lines.append('错因分布：%s' % '、'.join(
                '%s %d 道' % (name, n) for name, n in causes.most_common(6)))
        missing = []
        no_point = len(mistakes) - sum(points.values())
        if no_point > 0:
            missing.append('没标知识点 %d 道' % no_point)
        if missing:
            lines.append('没标全的：%s' % '、'.join(missing))
        lines.append('')
        lines.append('这一天的逐条（每条都是这道题已有的文字，不要外推）：')
        for index, mistake in enumerate(mistakes[:DAY_ITEM_LIMIT], start=1):
            lines.append('%d) %s' % (index, mistake._cover_facts()))
        if len(mistakes) > DAY_ITEM_LIMIT:
            lines.append('（还有 %d 道没展开，只算进上面那些分布里）'
                         % (len(mistakes) - DAY_ITEM_LIMIT))
        return '\n'.join(lines)

    @api.model
    def generate(self, student, day, mistakes=None, force=False):
        """给某一天做那张回顾大图：一次模型往返，只回**一个**配方。

        同步做（纯文字往返、几秒回）——排队等 cron 会让"看一眼不满意再来一版"跑不动。
        已有配方的默认不重做（`force=True` 才覆盖）。
        接口那趟失败**不抛异常**：写一条退让原因、退到文字回顾，把状态和原因回给调用方，
        由页面显示（"没配密钥"这类话必须说在明面上，而不是当场 500）。

        返回 `(回顾记录或空集, 状态, 说给人看的那句话)`，状态是
        `done|kept|empty|failed|denied` 之一。
        """
        Mistake = self.env['tutoring.mistake']
        if not student:
            return self.browse(), 'denied', _('还没有可回顾的学习档案，请先在后台建一条。')
        if not self.has_access('write') and not self.has_access('create'):
            return self.browse(), 'denied', _('这个账号写不了回顾。')
        if mistakes is None:
            mistakes = Mistake.search([('student_id', '=', student.id), ('date', '=', day)])
        if not mistakes:
            return self.for_day(student, day), 'empty', _(
                '这一天（%s）没有错题，回顾就不用做了。') % day

        digest = self.for_day(student, day)
        if digest and digest.ready and not force:
            return digest, 'kept', _('这一天本来就有回顾那张图了，想换一版点「重做」。')

        facts = self._day_facts(student, day, mistakes)
        system = mistake_cover.prompt('digest_system') % {
            'palette': mistake_cover.palette_text(),
            'motifs': mistake_cover.motifs_text(),
        }
        user = mistake_cover.prompt('digest_user') % {'facts': facts}

        plan, reason = None, ''
        try:
            plan = mistake_cover.parse_single(mistake_cover.chat(self.env, system, user))
        except (UserError, ValueError) as err:
            # 接口的话原样留着给人看，但别把整坨响应体塞进 Char
            reason = (str(err) or _('接口没回东西'))[:NOTE_MAX]
        if plan and not (plan['headline'] or plan['motifs'] or plan['bg']):
            plan, reason = None, _('接口回的那份配方，色板与图案全都不认识')
        if plan:
            vals = {'recipe': json.dumps(plan, ensure_ascii=False), 'note': False}
        else:
            # 重做失败不该把已有那张好图毁掉：recipe 一律不动，只把原因记下
            vals = {'note': reason}
        if digest:
            digest.write(vals)
        else:
            digest = self.create(dict(vals, student_id=student.id, date=day))
        if plan:
            return digest, 'done', _('已经给这一天做好回顾那张图了。')
        return digest, 'failed', _(
            '这次没做出回顾（%(why)s），先拿文字版顶着；原因写在那张图上。') % {'why': reason}
