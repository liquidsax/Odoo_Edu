"""知识库的 Markdown 子集渲染器：纯 Python、零第三方依赖。

只实现讲题笔记/错题说明真正用得上的那部分语法。**明确不做**：内嵌原始 HTML、
HTML 块、脚注、引用式链接（`[x][1]`）、任务列表。理由有两条：这个渲染器的输出会
进 `preview_html`（`sanitize=False` 的字段），少一条语法就少一类意外；要完整
CommonMark 就得引库，而这个项目的前端一直是零依赖。

安全口径（改动前请先读）：
1. 源文本整体 `escape`，之后只由本模块插入自己生成的标签，原始 HTML 一律当文本；
2. 链接与图片地址过协议白名单，通不过就退化成纯文本，不生成标签；
3. 收尾再走一遍 `odoo.tools.html_sanitize` 兜底。

行内码用占位符摘出来再还原，顺序不能乱：先 `code`，再链接/图片，最后强调，
否则 ``**a`b`c**`` 这类写法会互相吃掉。
"""
import re

from markupsafe import escape

from odoo.tools import html_sanitize

# 笔记里的 # 从 h2 起：门户页顶部已经有标题，别让一段笔记抢主标题的级
HEADING_TAGS = {1: 'h2', 2: 'h3', 3: 'h4', 4: 'h5', 5: 'h6', 6: 'h6'}
HARD_BREAK = '\x01'      # 行尾两个空格 = 硬换行的哨兵，走过 _inline 之后再换成 <br/>
CODE_SLOT = '\x00%d\x00'  # 行内码的占位符

RE_FENCE = re.compile(r'^ {0,3}(?:```|~~~)[ \t]*([\w+#.-]*)[ \t]*$')
RE_ATX = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$')
RE_HR = re.compile(r'^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$')
RE_QUOTE = re.compile(r'^ {0,3}>[ \t]?(.*)$')
RE_UL = re.compile(r'^([ \t]*)([-+*])[ \t]+(.*)$')
RE_OL = re.compile(r'^([ \t]*)([0-9]{1,9})[.)][ \t]+(.*)$')
RE_TABLE_SEP = re.compile(r'^[ \t]*\|?[ \t]*:?-{1,}[ \t:|-]*$')
RE_CODE_SPAN = re.compile(r'`([^`]+)`')
RE_SLOT = re.compile('\x00(\\d+)\x00')
RE_IMG = re.compile(r'!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+&quot;[^)&]*&quot;)?\s*\)')
RE_LINK = re.compile(r'\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+&quot;[^)&]*&quot;)?\s*\)')
RE_AUTOLINK = re.compile(r'&lt;(https?://[^\s&]+)&gt;')
RE_STRONG = re.compile(r'\*\*(?=\S)(.+?\S)\*\*|__(?=\S)(.+?\S)__')
RE_EM = re.compile(r'(?<![*\w])\*(?!\s)([^*]+?)(?<!\s)\*(?![*\w])|(?<![_\w])_(?!\s)([^_]+?)(?<!\s)_(?![_\w])')
RE_STRIKE = re.compile(r'~~(?=\S)(.+?\S)~~')

ALLOWED_SCHEMES = ('http:', 'https:', 'mailto:')
# 图片只认同源与 http(s)：data: 常见于 SVG（能带脚本），而外链图床等于把
# 读者的 IP 泄露给第三方——笔记里真需要图就把它当文件传进知识库
ALLOWED_IMAGE_PREFIXES = ('/', './', '../', 'http://', 'https://')


def _safe_target(raw, image=False):
    """链接/图片地址的守门人：通不过白名单返回 None，调用处退化成纯文本。"""
    target = (raw or '').strip().rstrip('.,;')
    if not target:
        return None
    if target.lower().startswith(('javascript:', 'vbscript:', 'file:', 'data:', 'blob:')):
        return None
    if target.startswith(('#', '/', './', '../')):
        return target
    head = target.split('/', 1)[0]
    scheme = head.split(':', 1)[0].lower() + ':' if ':' in head else ''
    if image:
        return target if scheme in ('http:', 'https:') else None
    return target if scheme in ALLOWED_SCHEMES else None


def _inline(raw):
    """一行（或一段）文本的行内语法。"""
    slots = []

    def stash(html):
        slots.append(html)
        return CODE_SLOT % (len(slots) - 1)

    text = escape(raw)
    text = RE_CODE_SPAN.sub(lambda m: stash('<code>%s</code>' % m.group(1)), text)

    def image(match):
        alt, target = match.group(1), _safe_target(match.group(2), image=True)
        if not target or not target.startswith(ALLOWED_IMAGE_PREFIXES):
            return stash('<span class="o_lib_md_dead">[图片 %s]</span>' % alt)
        return stash('<img src="%s" alt="%s" loading="lazy"/>' % (target, alt))

    def link(match):
        label, target = match.group(1), _safe_target(match.group(2))
        if not target:
            return stash('<span class="o_lib_md_dead">%s</span>' % label)
        return stash('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                     % (target, label))

    text = RE_IMG.sub(image, text)
    text = RE_LINK.sub(link, text)
    text = RE_AUTOLINK.sub(
        lambda m: stash('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                        % (m.group(1), m.group(1))), text)
    text = RE_STRONG.sub(
        lambda m: stash('<strong>%s</strong>' % (m.group(1) or m.group(2))), text)
    text = RE_EM.sub(
        lambda m: stash('<em>%s</em>' % (m.group(1) or m.group(2))), text)
    text = RE_STRIKE.sub(lambda m: stash('<del>%s</del>' % m.group(1)), text)

    return RE_SLOT.sub(lambda m: slots[int(m.group(1))], text)


def _split_row(line):
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _render_table(header, sep, rows):
    aligns = []
    for cell in _split_row(sep):
        left, right = cell.startswith(':'), cell.endswith(':')
        aligns.append('center' if left and right else 'right' if right else 'left')

    def tr(cells, tag):
        out = []
        for idx, cell in enumerate(cells):
            align = aligns[idx] if idx < len(aligns) else 'left'
            style = ' style="text-align: %s;"' % align if align != 'left' else ''
            out.append('<%s%s>%s</%s>' % (tag, style, _inline(cell), tag))
        return '<tr>%s</tr>' % ''.join(out)

    return ('<table class="table table-sm table-bordered o_lib_md_table">'
            '<thead>%s</thead><tbody>%s</tbody></table>'
            % (tr(_split_row(header), 'th'),
               ''.join(tr(_split_row(row), 'td') for row in rows)))


def _emit_list(items, pos, level):
    """递归吐一个列表层，返回 (html, 下一个未消费的下标)。标签在这里就闭合。"""
    ordered = items[pos][1]
    tag = 'ol' if ordered else 'ul'
    buf = ['<%s class="o_lib_md_list"><li>%s' % (tag, _inline(items[pos][2]))]
    pos += 1
    while pos < len(items):
        depth, item_ordered, content = items[pos]
        if depth < level:
            break
        if depth == level:
            want = 'ol' if item_ordered else 'ul'
            if want != tag:
                # 同一层从 - 切到 1. —— 不闭合重开的话整段会被并进上一个列表
                buf.append('</li></%s><%s class="o_lib_md_list"><li>%s'
                           % (tag, want, _inline(content)))
                tag = want
            else:
                buf.append('</li><li>%s' % _inline(content))
            pos += 1
            continue
        nested, pos = _emit_list(items, pos, depth)
        buf.append(nested)
    buf.append('</li></%s>' % tag)
    return ''.join(buf), pos


def _render_list(items):
    """把 (原始缩进, 是否有序, 内容) 归一到层级，再递归。

    缩进按"比上一层深就算一层"处理，所以 2 空格、3 空格、制表符混着用也塌得平。
    """
    normalized, stack = [], []
    for indent, ordered, content in items:
        width = len(indent.replace('\t', '  '))
        while stack and stack[-1] > width:
            stack.pop()
        if not stack or stack[-1] < width:
            stack.append(width)
        normalized.append((len(stack) - 1, ordered, content))
    html, _pos = _emit_list(normalized, 0, 0)
    return html


def _render_blocks(lines):
    out, para, i, n = [], [], 0, len(lines)

    def flush_para():
        if not para:
            return
        text = ' '.join(part.strip() for part in para).strip()
        para.clear()
        if not text:
            return
        parts = [_inline(part) for part in text.split(HARD_BREAK)]
        out.append('<p>%s</p>' % '<br/>'.join(part.strip() for part in parts))

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_para()
            i += 1
            continue

        fence = RE_FENCE.match(stripped)
        if fence:
            flush_para()
            language = fence.group(1).lower()
            i += 1
            buf = []
            while i < n and not RE_FENCE.match(lines[i].strip()):
                buf.append(lines[i])
                i += 1
            i += 1  # 收尾的 ```
            cls = ' class="language-%s"' % language if language else ''
            out.append('<pre class="o_lib_md_pre"><code%s>%s</code></pre>'
                       % (cls, escape('\n'.join(buf))))
            continue

        atx = RE_ATX.match(line)
        if atx:
            flush_para()
            tag = HEADING_TAGS[len(atx.group(1))]
            out.append('<%s>%s</%s>' % (tag, _inline(atx.group(2)), tag))
            i += 1
            continue

        if RE_HR.match(line):
            flush_para()
            out.append('<hr/>')
            i += 1
            continue

        if RE_QUOTE.match(line):
            flush_para()
            buf = []
            while i < n and RE_QUOTE.match(lines[i]):
                buf.append(RE_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append('<blockquote>%s</blockquote>' % _render_blocks(buf))
            continue

        if '|' in line and i + 1 < n and RE_TABLE_SEP.match(lines[i + 1] or '') \
                and '-' in lines[i + 1]:
            flush_para()
            header, sep = line, lines[i + 1]
            rows = []
            i += 2
            while i < n and '|' in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            out.append(_render_table(header, sep, rows))
            continue

        if RE_UL.match(line) or RE_OL.match(line):
            flush_para()
            items = []
            while i < n:
                match = RE_UL.match(lines[i]) or RE_OL.match(lines[i])
                if match:
                    ordered = RE_OL.match(lines[i]) is not None
                    items.append([match.group(1), ordered, match.group(3)])
                    i += 1
                    continue
                # 缩进的续行并进上一条（笔记里一条要点写两行很常见）
                if items and lines[i].startswith((' ', '\t')) and lines[i].strip():
                    items[-1][2] += ' ' + lines[i].strip()
                    i += 1
                    continue
                break
            out.append(_render_list(items))
            continue

        # 行尾两个空格 = 硬换行；其余软换行合成一个空格
        para.append(stripped + (HARD_BREAK if line.endswith('  ') else ''))
        i += 1

    flush_para()
    return ''.join(out)


def render_markdown(text):
    """Markdown 源文本 → 可以安全内嵌的 HTML 片段。"""
    if not text:
        return ''
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return html_sanitize(_render_blocks(lines), silent=True)
