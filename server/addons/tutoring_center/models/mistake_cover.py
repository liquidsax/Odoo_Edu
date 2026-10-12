# -*- coding: utf-8 -*-
"""封面素材表与那一次模型往返：AI 只负责"选元素 + 写一句话"，图完全由我们按定死的素材渲染。

分工是刻意这么切的——
* 模型看的：某一天所有错题已有的文字（知识点、错因、难度、出处、AI 抄回的摘要与原文、补充说明）；
* 模型输出的：**一个**小 JSON，从我们给的色板 id 里挑一个背景、从图案库里挑 1~3 个、
  再写一句 ≤14 字的概括、一行小字、一个角标；
* 我们做的：按它给的 id 查表，渲染成 CSS 渐变 + 内联 SVG。

所以这条路上模型**永远不产出颜色值、不产出 SVG、不产出图片**——它给的东西全部要过 `clean()` 白名单，
认不出的直接丢掉。这既让它没法把版面弄坏，也让"同一天重做两次"的差异只体现在选哪几个元素上。

2026-10-12 那批"原页/文字/AI 三个封面版"收拢成一版「每日回顾」之后，这里只剩"一天一张"这条路：
一张大图属于某一天，不属于某道题（逐题的那份在 `tutoring.mistake.digest`）。
"""
import json

import requests
from markupsafe import Markup

from odoo import _, exceptions
from odoo.tools import file_open

from .deepseek_config import deepseek_settings

# 接口超时：输入是一天的事实（几千字），输出就一个小 JSON
API_TIMEOUT = 40
MAX_OUTPUT_TOKENS = 600

# ── 色板：id、名字、两端渐变色、前景色。AI 只能报 id ─────────────────────
PALETTE = (
    ('ink', '墨蓝', '#16213e', '#0f3460'),
    ('crimson', '深红', '#7f1d1d', '#b91c1c'),
    ('pine', '松绿', '#064e3b', '#065f46'),
    ('indigo', '靛紫', '#312e81', '#4338ca'),
    ('slate', '石墨', '#1f2937', '#374151'),
    ('brick', '砖橙', '#7c2d12', '#c2410c'),
    ('plum', '梅子紫', '#4a044e', '#86198f'),
    ('sea', '海青', '#0c4a6e', '#0369a1'),
)
PALETTE_BY_ID = {p[0]: p for p in PALETTE}
INK = '#ffffff'

# ── 图案库：每个都是 viewBox 0 0 100 100 的描边图形，颜色跟着前景走。
#     第二个元素是给模型看的一句话说明（它只读文字，不看图）────────────────
MOTIFS = (
    ('axes', '直角坐标系，带 x/y 轴与刻度'),
    ('parabola', '开口向上的抛物线 y=x²'),
    ('ellipse', '横放椭圆，标出左右两个焦点'),
    ('hyperbola', '双曲线配两条虚线渐近线'),
    ('sine', '一段正弦波'),
    ('unitcircle', '单位圆与一条终边射线'),
    ('numberline', '数轴上的一段区间'),
    ('absval', 'V 形绝对值折线'),
    ('bars', '三根高低不同的统计柱'),
    ('venn', '两个相交的集合圈'),
    ('triangle', '三角形与一条高'),
    ('vectors', '两个从同一点出发的向量箭头'),
)
MOTIF_IDS = {m[0] for m in MOTIFS}

# 每个图案的 SVG 主体（描边由外层统一给，这里只写形状）
MOTIF_SHAPES = {
    'axes': '<path d="M10 50h80M50 90V10"/><path d="M22 46v8M36 46v8M64 46v8M78 46v8'
            'M46 78h8M46 64h8M46 36h8M46 22h8"/>',
    'parabola': '<path d="M12 88Q50 -18 88 88"/>',
    'ellipse': '<ellipse cx="50" cy="50" rx="40" ry="24"/>'
               '<circle cx="26" cy="50" r="3.5" fill="currentColor" stroke="none"/>'
               '<circle cx="74" cy="50" r="3.5" fill="currentColor" stroke="none"/>',
    'hyperbola': '<path d="M50 50 12 12M50 50l38-38M50 50 12 88M50 50l38 38" stroke-dasharray="5 5"/>'
                 '<path d="M62 12c-14 20-14 56 0 76M38 12c14 20 14 56 0 76"/>',
    'sine': '<path d="M6 50q11-34 22 0t22 0 22 0 22 0"/>',
    'unitcircle': '<circle cx="50" cy="50" r="36"/><path d="M50 50 78 30"/>'
                  '<path d="M50 50h36" stroke-dasharray="4 4"/>',
    'numberline': '<path d="M8 55h84"/><path d="M28 45v20M66 45v20"/>'
                  '<path d="M28 55h38" stroke-width="6" opacity=".55"/>',
    'absval': '<path d="M10 85 50 15l40 70"/>',
    'bars': '<path d="M20 85V52M45 85V26M70 85V64" stroke-width="10"/>',
    'venn': '<circle cx="38" cy="50" r="26"/><circle cx="62" cy="50" r="26"/>',
    'triangle': '<path d="M14 82h72L52 18z"/><path d="M52 18v64"/>',
    'vectors': '<path d="M14 86 62 38M62 38l-14 2M62 38l-2 14"/>'
               '<path d="M14 86 86 66M86 66l-14-1M86 66l-3 13"/>',
}

# 图案在封面上的落位（写死三档，AI 不管布局）：右上、右中、右下
MOTIF_SLOTS = (
    ('62%', '8%', 1.0, -8),
    ('70%', '38%', 0.72, 6),
    ('58%', '62%', 0.55, -3),
)


def palette_text():
    """给 prompt 用的色板清单。"""
    return '\n'.join('- %s：%s' % (pid, name) for pid, name, _a, _b in PALETTE)


def motifs_text():
    return '\n'.join('- %s：%s' % (mid, desc) for mid, desc in MOTIFS)


def parse_single(text):
    """把模型回的那**一个**配方抠出来并过白名单。

    模型可能规规矩矩回 `{"bg":…}`，也可能沿用它熟悉的 `{"covers":[{…}]}`、
    甚至前后带一句解释——所以先抠出第一个 `[`/`{` 到最后一个匹配的括号，再按形状收成一个 dict。
    抠不到、或抠出来的不是对象就抛 `ValueError`：调用方按"这次没成、退到文字回顾"处理，
    绝不能静默当成"有个配方但全是空的"（那样封面上连一句退让原因都没有）。
    """
    raw = (text or '').strip()
    start = min([i for i in (raw.find('['), raw.find('{')) if i >= 0], default=-1)
    end = max(raw.rfind(']'), raw.rfind('}'))
    if start < 0 or end <= start:
        raise ValueError(_('回复里找不到 JSON'))
    data = json.loads(raw[start:end + 1])
    if isinstance(data, dict):
        for key in ('digest', 'cover', 'covers', 'items'):
            nested = data.get(key)
            if isinstance(nested, list):
                data = nested[0] if nested and isinstance(nested[0], dict) else {}
                break
            if isinstance(nested, dict):
                data = nested
                break
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        raise ValueError(_('回复不是一个配方对象'))
    return clean(data)


def clean(item):
    """白名单：认不出的色板/图案直接丢，文字截断，绝不把模型给的原样塞进样式里。"""
    def text(key, max_len):
        return (str(item.get(key) or '').strip()[:max_len]) or False
    return {
        'bg': item.get('bg') if item.get('bg') in PALETTE_BY_ID else None,
        'motifs': [m for m in (item.get('motifs') or []) if m in MOTIF_IDS][:3],
        'headline': text('headline', 40),
        'sub': text('sub', 60),
        'badge': text('badge', 24),
    }


def style_for(recipe):
    """配方 → 一段 CSS 自定义属性。色值只可能来自 PALETTE 表，不来自模型。"""
    pid = (recipe or {}).get('bg')
    entry = PALETTE_BY_ID.get(pid) or PALETTE_BY_ID['slate']
    return '--cbg-a:%s;--cbg-b:%s;--cbg-ink:%s' % (entry[2], entry[3], INK)


def motifs_svg(recipe):
    """配方里的图案 id → 内联 SVG。写死的形状 + 写死的落位，模型插不上手。"""
    ids = (recipe or {}).get('motifs') or []
    parts = []
    for index, mid in enumerate(ids[:len(MOTIF_SLOTS)]):
        left, top, scale, rotate = MOTIF_SLOTS[index]
        parts.append(
            '<svg class="o_cover_motif" viewBox="0 0 100 100" aria-hidden="true" '
            'style="left:%s;top:%s;width:%s;height:%s;transform:rotate(%ddeg)">'
            '<g fill="none" stroke="currentColor" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g></svg>'
            % (left, top, '%g%%' % (28 * scale), '%g%%' % (28 * scale), rotate,
               MOTIF_SHAPES[mid])
        )
    return Markup(''.join(parts))


def chat(env, system, user_text):
    """一次纯文字对话：输入是一天的错题事实，输出是一个配方 JSON。

    没复用摘要那条 `_call`：那口绑着"一页扫描图 + 单条结果"的形状与失败口径，
    套在封面上会把两边的错误处理搅在一起。这里只借同一套配置读取。
    没密钥 / 连不上 / 非 200 一律 `UserError`，由调用方转成"退到文字回顾"那句话。

    ⚠️ 参数刻意不叫 `user`：模块级函数里调 `_()` 时，Odoo 会顺着调用栈找翻译上下文，
    `_get_uid()` 先看 `f_locals['uid']` 再看 `f_locals['user']` 并直接 `int()` 它
    （`tools/translate.py`）——一个装着提示词的 `user` 会让它拿整段 prompt 去 `int()`，
    于是"没配密钥"那句本该好好说的话，变成 `ValueError: invalid literal for int()`。
    有请求上下文时 `_get_lang()` 提前返回所以看不出来，shell/cron 里必炸（见陷阱 87）。
    """
    conf = deepseek_settings(env)
    if not conf['key']:
        raise exceptions.UserError(_('还没配置 DeepSeek 密钥，做不了回顾封面。'))
    payload = {
        'model': conf['model'],
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_text},
        ],
        'max_tokens': MAX_OUTPUT_TOKENS,
        'temperature': 0.8,
    }
    try:
        resp = requests.post(
            '%s/chat/completions' % conf['url'].rstrip('/'),
            headers={'Authorization': 'Bearer %s' % conf['key'],
                     'Content-Type': 'application/json'},
            json=payload, timeout=API_TIMEOUT,
        )
    except (requests.ConnectionError, requests.Timeout) as err:
        raise exceptions.UserError(_('连不上 DeepSeek：%s') % type(err).__name__) from err
    if resp.status_code != 200:
        raise exceptions.UserError(_('接口回了 %s') % resp.status_code)
    return resp.json()['choices'][0]['message']['content']


PROMPT_FILES = {
    'digest_system': 'tutoring_center/prompts/digest_system.txt',
    'digest_user': 'tutoring_center/prompts/digest_user.txt',
}


def prompt(kind):
    """读 prompts/ 下的回顾文案。rb + 显式 decode：Windows 文本模式会按控制台代码页读。"""
    path = PROMPT_FILES[kind]
    try:
        return file_open(path, 'rb').read().decode('utf-8').strip()
    except (FileNotFoundError, IsADirectoryError) as err:
        raise exceptions.UserError(_('找不到提示词文件 %s') % path) from err
