r"""把 AI 抄回来的 LaTeX 式子转成人能直接读的**纯文本**。

为什么只做纯文本：这一份实现要到处用——门户详情页、后台只读弹窗、看板卡片、列表列、
导出，拿到的必须是同一个字符串。后台的 Char/Text 字段不渲染 HTML，所以产 `<sup>`
那种写法在这里等于自断一路。真要排版（分式上下叠、根号带横线）得引 KaTeX/MathJax，
而核心没有这两样（`web/static/lib` 里只有 prismjs/dompurify 那批），
前端零依赖是这个项目一直守着的纪律。

覆盖的是高中题目里真会出现的记号：上下标、分式、根号、分段函数 cases、
绝对值、希腊字母与常见关系/运算符、数集黑板体。

**碰到不认识的记号一律原样留着**——宁可看见 `\pmod` 这样的残骸，
也不要把题目悄悄改成另一个意思（这条比"好看"优先级高）。
"""
import re

# 上标/下标表：只有这些字符有对应的 Unicode 形式，凑不出来的退回 ^(…) / _(…)
SUPERSCRIPTS = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶',
    '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽',
    ')': '⁾', 'n': 'ⁿ', 'i': 'ⁱ', 'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ',
    'e': 'ᵉ', 'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'j': 'ʲ', 'k': 'ᵏ', 'l': 'ˡ',
    'm': 'ᵐ', 'o': 'ᵒ', 'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
    'v': 'ᵛ', 'x': 'ˣ',
}
SUBSCRIPTS = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆',
    '7': '₇', '8': '₈', '9': '₉', '+': '₊', '-': '₋', '=': '₌', '(': '₍',
    ')': '₎', 'a': 'ₐ', 'e': 'ₑ', 'i': 'ᵢ', 'j': 'ⱼ', 'k': 'ₖ', 'l': 'ₗ',
    'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ', 'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ',
    'u': 'ᵤ', 'v': 'ᵥ', 'x': 'ₓ',
}

# 长名字要排在前边，否则 \le 会抢在 \left 之前被吃掉
SYMBOLS = [
    ('notin', '∉'), ('subseteq', '⊆'), ('supseteq', '⊇'), ('emptyset', '∅'),
    ('varnothing', '∅'), ('rightleftharpoons', '⇌'), ('Leftrightarrow', '⇔'),
    ('longrightarrow', '⟶'), ('rightarrow', '→'), ('Rightarrow', '⇒'),
    ('leqslant', '≤'), ('geqslant', '≥'), ('neq', '≠'), ('approx', '≈'),
    ('equiv', '≡'), ('infty', '∞'), ('partial', '∂'), ('nabla', '∇'),
    ('cdots', '⋯'), ('ldots', '…'), ('vdots', '⋮'),
    ('ast', '∗'), ('star', '⋆'), ('bullet', '•'),
    ('circ', '∘'), ('cdot', '·'), ('times', '×'), ('div', '÷'),
    ('pm', '±'), ('mp', '∓'), ('in', '∈'), ('ni', '∋'),
    ('cup', '∪'), ('cap', '∩'), ('setminus', '\\'), ('subset', '⊂'),
    ('supset', '⊃'), ('forall', '∀'), ('exists', '∃'), ('perp', '⊥'),
    ('parallel', '∥'), ('wedge', '∧'), ('vee', '∨'), ('angle', '∠'),
    ('triangle', '△'), ('odot', '⊙'), ('oplus', '⊕'), ('otimes', '⊗'),
    ('leq', '≤'), ('geq', '≥'), ('le', '≤'), ('ge', '≥'), ('lt', '<'), ('gt', '>'), ('ne', '≠'),
    ('to', '→'), ('sim', '∼'), ('simeq', '≃'), ('cong', '≅'),
    ('propto', '∝'), ('ll', '≪'), ('gg', '≫'), ('langle', '⟨'),
    ('rangle', '⟩'), ('vert', '|'), ('Vert', '‖'), ('lvert', '|'),
    ('rvert', '|'), ('lVert', '‖'), ('rVert', '‖'), ('mid', '|'),
    ('alpha', 'α'), ('beta', 'β'), ('gamma', 'γ'), ('Gamma', 'Γ'),
    ('delta', 'δ'), ('Delta', 'Δ'), ('epsilon', 'ε'), ('varepsilon', 'ε'),
    ('zeta', 'ζ'), ('eta', 'η'), ('theta', 'θ'), ('Theta', 'Θ'),
    ('iota', 'ι'), ('kappa', 'κ'), ('lambda', 'λ'), ('Lambda', 'Λ'),
    ('mu', 'μ'), ('nu', 'ν'), ('xi', 'ξ'), ('Xi', 'Ξ'), ('pi', 'π'),
    ('Pi', 'Π'), ('rho', 'ρ'), ('sigma', 'σ'), ('Sigma', 'Σ'),
    ('tau', 'τ'), ('upsilon', 'υ'), ('phi', 'φ'), ('Phi', 'Φ'),
    ('varphi', 'φ'), ('chi', 'χ'), ('psi', 'ψ'), ('Psi', 'Ψ'),
    ('omega', 'ω'), ('Omega', 'Ω'),
]

# 这些是"函数名"，去掉反斜杠当普通词用，别跟符号混在一起
PLAIN_WORDS = ('log', 'ln', 'lg', 'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
               'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh', 'exp',
               'max', 'min', 'lim', 'deg', 'gcd', 'lcm', 'dom', 'rang')

BBDOUBLE = {'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ', 'Q': 'ℚ', 'C': 'ℂ', 'H': 'ℍ'}

# 只是排版/间距，没有语义，直接丢
DROP_MACROS = ('displaystyle', 'textstyle', 'limits', 'nonumber', 'quad',
               'qquad', 'big', 'Big', 'bigg', 'Bigg', 'left', 'right',
               'mathopen', 'mathclose', 'mathbin', 'mathrel')

RE_ENV = re.compile(r'\\begin\{(\*?[\w*]+)\}(.*?)\\end\{\1\}', re.S)
RE_SPACING = re.compile(r'\\[,;!]')
RE_WRAPPER = re.compile(
    r'\\(?:text|textrm|textnormal|mathrm|mathbf|mathit|mathsf|mathbb|bm|boldsymbol)\s*\{')
RE_FRAC = re.compile(r'\\(?:d|t)?frac\s*\{')
RE_SQRT = re.compile(r'\\sqrt(?=\[|\{)')
RE_SUPER = re.compile(r'\^\s*(?:\{([^{}]*)\}|([A-Za-z0-9]))')
RE_SUB = re.compile(r'_\s*(?:\{([^{}]*)\}|([A-Za-z0-9]))')
RE_DELIMS = re.compile(r'\\[(|)]|\\[|[]')

ESCAPED = (('\\%', '%'), ('\\_', '_'), ('\\{', '{'), ('\\}', '}'),
           ('\\#', '#'), ('\\&', '&'))


def _read_group(text, pos):
    r"""从 text[pos] 起读一个平衡的 `{...}`，返回 (内容, 之后的位置)。

    不是左花括号就返回 (None, pos)；括号不闭合就把剩下的都算进去（宁可多带一个字）。
    """
    if pos >= len(text) or text[pos] != '{':
        return None, pos
    depth, idx = 0, pos
    while idx < len(text):
        if text[idx] == '{':
            depth += 1
        elif text[idx] == '}':
            depth -= 1
            if not depth:
                return text[pos + 1:idx], idx + 1
        idx += 1
    return text[pos + 1:], len(text)


def _apply_all(text, func):
    r"""反复扫到不再变化：处理 \frac{\frac{a}{b}}{c} 这类嵌套。"""
    for _ in range(12):
        out = func(text)
        if out == text:
            break
        text = out
    return text


def _convert_cases(body):
    r"""cases 环境：每行是 `表达式, 条件`，并成一行用分号隔开。"""
    rows = []
    for raw in re.split(r'\\\\|\\cr\b', body):
        row = raw.strip().strip('&').strip()
        if not row:
            continue
        depth, cut = 0, -1
        for i, ch in enumerate(row):
            if ch in '({[':
                depth += 1
            elif ch in ')}]':
                depth -= 1
            elif ch == ',' and depth == 0:
                cut = i
                break
        if cut < 0:
            rows.append(row)
        else:
            rows.append('%s（%s）' % (row[:cut].strip().rstrip(',;'),
                             row[cut + 1:].strip().rstrip(',;')))
    return '分段：' + '；'.join(rows) if rows else body


def _strip_envs(text):
    r"""去掉 `\begin{...}\end{...}` 外壳；只认识 cases，其余环境保留内容、丢掉壳。"""
    def once(src):
        out, at = [], 0
        for m in RE_ENV.finditer(src):
            name, body = m.group(1), m.group(2)
            out.append(src[at:m.start()])
            out.append(_convert_cases(body) if name.lstrip('*') == 'cases'
                       else body.strip())
            at = m.end()
        out.append(src[at:])
        return ''.join(out)
    return _apply_all(text, once)


def _strip_wrappers(text):
    r"""\text{…} \mathrm{…} \mathbb{…} 这类只改字体的壳：留内容；数集换成黑板体。"""
    def once(src):
        out, pos = [], 0
        while True:
            m = RE_WRAPPER.search(src, pos)
            if not m:
                out.append(src[pos:])
                break
            body, nxt = _read_group(src, m.end() - 1)
            out.append(src[pos:m.start()])
            if body is None:
                out.append(src[m.start():m.end()])
            elif 'mathbb' in m.group(0) and len(body.strip()) == 1:
                out.append(BBDOUBLE.get(body.strip(), body))
            else:
                out.append(body)
            pos = nxt
        return ''.join(out)
    return _apply_all(text, once)


def _replace_frac(text):
    r"""\frac{a}{b} → (a)/(b)。少一个花括号时退化成读一个词，不吞掉整行。"""
    def once(src):
        out, pos = [], 0
        while True:
            m = RE_FRAC.search(src, pos)
            if not m:
                out.append(src[pos:])
                break
            num, after = _read_group(src, m.end() - 1)
            if num is None:
                out.append(src[pos:m.end()])
                pos = m.end()
                continue
            if after < len(src) and src[after] == '{':
                den, after = _read_group(src, after)
            else:
                m2 = re.match(r'(\{[^{}]*\}|\w)', src[after:])
                den = m2.group(1).strip('{}') if m2 else ''
                after += m2.end() if m2 else 0
            out.append(src[pos:m.start()])
            out.append('(%s)/(%s)' % (num.strip(), (den or '').strip()))
            pos = after
        return ''.join(out)
    return _apply_all(text, once)


def _replace_sqrt(text):
    r"""\sqrt{x} → √(x)；\sqrt[3]{x} → 3√(x)。"""
    def once(src):
        out, pos = [], 0
        while True:
            m = RE_SQRT.search(src, pos)
            if not m:
                out.append(src[pos:])
                break
            at, root = m.end(), ''
            if at < len(src) and src[at] == '[':
                close = src.find(']', at)
                if close > 0:
                    root, at = src[at + 1:close], close + 1
            body, at = _read_group(src, at)
            if body is None:
                out.append(src[pos:m.end()])
                pos = m.end()
                continue
            out.append(src[pos:m.start()])
            out.append('%s√(%s)' % (root, body.strip()) if root
                     else '√(%s)' % body.strip())
            pos = at
        return ''.join(out)
    return _apply_all(text, once)


def _replace_scripts(text):
    r"""^ 与 _ → Unicode 上下标；表里没有的字符退回 ^(…) / _(…)，语义不丢。"""
    def one(table, pattern, fallback, src):
        out, pos = [], 0
        while True:
            m = pattern.search(src, pos)
            if not m:
                out.append(src[pos:])
                break
            body = m.group(1) if m.group(1) is not None else m.group(2)
            mapped = ''.join(table.get(ch) or '' for ch in body)
            out.append(src[pos:m.start()])
            out.append(mapped if (body and len(mapped) == len(body))
                       else '%s(%s)' % (fallback, body))
            pos = m.end()
        return ''.join(out)
    text = _apply_all(text, lambda s: one(SUPERSCRIPTS, RE_SUPER, '^', s))
    return _apply_all(text, lambda s: one(SUBSCRIPTS, RE_SUB, '_', s))


def _replace_symbols(text):
    # 替换串走 lambda：setminus 的替换值是单个反斜杠，直接当字符串传会被 re.sub 当转义吃掉
    for name, glyph in SYMBOLS:
        text = re.sub(r'\\%s(?![a-zA-Z])' % name, lambda m, g=glyph: g, text)
    for word in PLAIN_WORDS:
        text = re.sub(r'\\%s(?![a-zA-Z])' % word, lambda m, w=word: w, text)
    for macro in DROP_MACROS:
        text = re.sub(r'\\%s(?![a-zA-Z])\s*' % macro, '', text)
    return text


def _tidy(text):
    text = RE_SPACING.sub(' ', text)
    text = text.replace('\\\\', '\n')             # 行分隔符（cases 之外）
    text = text.replace('$', '')                  # 数学定界符
    text = RE_DELIMS.sub('', text)
    for esc, plain in ESCAPED:
        text = text.replace(esc, plain)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' ?([,;.]) ?', r'\1', text)    # 标点前多余的空格
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def to_plain_math(value):
    r"""AI 抄回来的题目文本 → 人能直接读的纯文本。空值原样返回。"""
    if not value:
        return value
    text = str(value).strip()
    text = _strip_envs(text)
    text = _strip_wrappers(text)
    text = _replace_frac(text)
    text = _replace_sqrt(text)
    text = _replace_scripts(text)
    text = _replace_symbols(text)
    return _tidy(text)
