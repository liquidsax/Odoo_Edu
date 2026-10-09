"""函数图像表达式的服务端校验。

与 static/src/function_plot.js 的「归一化 → 分词 → 调度场」对齐，只判断
前端画布肯不肯收下这条式子，**不求值、不 exec**。两边漂移时以
dev/zz_plot_ai_unit.py 里对 buildModel 的对照为准。
"""
import json
import math
import re

MAX_EXPR_LEN = 160
MAX_CURVES = 16
MAX_LABEL_LEN = 16
MAX_PARAM_ABS = 1_000_000
MAX_INPUT_CHARS = 400
MAX_IMAGE_BYTES = 8 * 1024 * 1024

FUNCTIONS = (
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan',
    'arcsin', 'arccos', 'arctan',
    'sqrt', 'abs', 'exp', 'ln', 'log', 'lg',
)
CONSTANTS = {'pi': math.pi, 'e': math.e}
KNOWN_NAMES = tuple(sorted([*FUNCTIONS, *CONSTANTS, 'x', 'y'], key=len, reverse=True))

BINARY_PRECEDENCE = {'+': 1, '-': 1, '*': 2, '/': 2, '^': 4}
UNARY_PRECEDENCE = 3

NORMALIZE_RULES = (
    ('（', '('), ('）', ')'), ('＝', '='), ('＋', '+'), ('－', '-'),
    ('−', '-'), ('–', '-'), ('—', '-'), ('×', '*'), ('·', '*'), ('÷', '/'),
    ('²', '^2'), ('³', '^3'), ('π', 'pi'),
)


class PlotExprError(ValueError):
    """式子不是画布能解析的方程。"""


def prepare_description(text, limit=MAX_INPUT_CHARS):
    """用户描述进模型之前的门槛。返回 (code, text)，code 为 ok/bad_type/empty/too_long。"""
    if not isinstance(text, str):
        return 'bad_type', ''
    cleaned = ''.join(ch for ch in text if ch in '\n\t' or ord(ch) >= 32).strip()
    if not cleaned:
        return 'empty', ''
    if len(cleaned) > limit:
        return 'too_long', ''
    return 'ok', cleaned


def normalize_expression(raw):
    text = str(raw)
    for src, dst in NORMALIZE_RULES:
        text = text.replace(src, dst)
    # 与前端一致：先把 ** 收成 ^，再去掉空白。* * 不会被当成乘方。
    return re.sub(r'\s+', '', text.replace('**', '^'))


def _parse_number(literal):
    try:
        value = float(literal)
    except ValueError as exc:
        raise PlotExprError('无法识别的数字「%s」' % literal) from exc
    if not math.isfinite(value):
        raise PlotExprError('无法识别的数字「%s」' % literal)
    return value


def _known_piece(raw, lower, index):
    for known in KNOWN_NAMES:
        if lower.startswith(known, index):
            if known == 'e' and raw[index] == 'E':
                return None
            return known
    return None


def _push_name(raw, tokens, followed_by_call):
    lower = raw.lower()
    if lower in KNOWN_NAMES and not (lower == 'e' and raw == 'E'):
        tokens.append({'type': 'name', 'name': lower})
        return
    if followed_by_call and len(raw) > 1:
        raise PlotExprError('未知函数「%s」' % raw)
    index = 0
    while index < len(raw):
        piece = _known_piece(raw, lower, index)
        if piece:
            tokens.append({'type': 'name', 'name': piece})
            index += len(piece)
        else:
            tokens.append({'type': 'param', 'name': raw[index]})
            index += 1


def _is_ascii_digit(char):
    return '0' <= char <= '9'


def _is_ascii_letter(char):
    # 与前端 /[a-z]/i 一致：汉字不是名字，是无法识别的字符
    return ('a' <= char <= 'z') or ('A' <= char <= 'Z')


def tokenize(text):
    tokens = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if _is_ascii_digit(char) or char == '.':
            end = index
            while end < length and (_is_ascii_digit(text[end]) or text[end] == '.'):
                end += 1
            literal = text[index:end]
            tokens.append({'type': 'num', 'value': _parse_number(literal)})
            index = end
        elif _is_ascii_letter(char):
            end = index
            while end < length and _is_ascii_letter(text[end]):
                end += 1
            _push_name(text[index:end], tokens, end < length and text[end] == '(')
            index = end
        elif char in '()':
            tokens.append({'type': 'lparen' if char == '(' else 'rparen'})
            index += 1
        elif char == '|':
            # 绝对值竖线：开还是合要到 to_rpn 里看前一个 token 才能定
            tokens.append({'type': 'bar'})
            index += 1
        elif char in '+-*/^':
            tokens.append({'type': 'op', 'value': char})
            index += 1
        else:
            raise PlotExprError('无法识别的字符「%s」' % char)
    return tokens


def _ends_value(token):
    return bool(token) and token['type'] in ('num', 'name', 'rparen', 'var', 'param')


def to_rpn(tokens):
    output = []
    operators = []

    def top():
        return operators[-1] if operators else None

    def push_binary(value):
        precedence = BINARY_PRECEDENCE[value]
        right_assoc = value == '^'
        while top():
            head = top()
            if head['type'] in ('lparen', 'absopen'):
                break
            if head['type'] == 'func':
                head_prec = math.inf
            elif head['type'] == 'unary':
                head_prec = UNARY_PRECEDENCE
            else:
                head_prec = BINARY_PRECEDENCE[head['value']]
            if head_prec > precedence or (head_prec == precedence and not right_assoc):
                output.append(operators.pop())
            else:
                break
        operators.append({'type': 'op', 'value': value})

    previous = None
    for index, token in enumerate(tokens):
        starts_value = token['type'] in ('num', 'name', 'lparen', 'param')
        if starts_value and _ends_value(previous):
            push_binary('*')
        if token['type'] in ('num', 'param'):
            output.append(token)
            previous = token
        elif token['type'] == 'name':
            name = token['name']
            if name in ('x', 'y'):
                output.append({'type': 'var', 'name': name})
                previous = token
            elif name in CONSTANTS:
                output.append({'type': 'num', 'value': CONSTANTS[name]})
                previous = token
            else:
                nxt = tokens[index + 1] if index + 1 < len(tokens) else None
                if not nxt or nxt['type'] != 'lparen':
                    raise PlotExprError('函数「%s」后面要跟括号' % name)
                operators.append({'type': 'func', 'name': name})
                previous = {'type': 'func'}
        elif token['type'] == 'lparen':
            operators.append(token)
            previous = token
        elif token['type'] == 'rparen':
            while top() and top()['type'] != 'lparen':
                output.append(operators.pop())
            if not top():
                raise PlotExprError('括号不匹配')
            operators.pop()
            if top() and top()['type'] == 'func':
                output.append(operators.pop())
            previous = token
        elif token['type'] == 'bar':
            # 竖线是开还是合，看前一个 token 收不收尾、栈里有没有等合的：
            # |x|+|y| 第二条合、第三条开；||x|-1| 前两条都开、第三条合最里层
            closing = _ends_value(previous) and any(op['type'] == 'absopen' for op in operators)
            if closing:
                while top() and top()['type'] != 'absopen':
                    output.append(operators.pop())
                operators.pop()
                output.append({'type': 'func', 'name': 'abs'})
                previous = {'type': 'rparen'}
            else:
                if _ends_value(previous):
                    push_binary('*')  # 2|x|、|x||y| 里的隐式乘法
                operators.append({'type': 'absopen'})
                previous = {'type': 'baropen'}
        else:
            if token['value'] == '-' and not _ends_value(previous):
                operators.append({'type': 'unary'})
            else:
                push_binary(token['value'])
            previous = token
    while operators:
        head = operators.pop()
        if head['type'] == 'lparen':
            raise PlotExprError('括号不匹配')
        if head['type'] == 'absopen':
            raise PlotExprError('绝对值少了一条竖线「|」')
        output.append(head)
    return output


def _check_rpn(rpn):
    stack = 0
    for token in rpn:
        kind = token['type']
        if kind in ('num', 'var', 'param'):
            stack += 1
        elif kind in ('func', 'unary'):
            if stack < 1:
                raise PlotExprError('表达式不完整')
        elif kind == 'op':
            if stack < 2:
                raise PlotExprError('表达式不完整')
            stack -= 1
        else:
            raise PlotExprError('表达式不完整')
    if stack != 1:
        raise PlotExprError('表达式不完整')


def validate_plot_expression(expression):
    """收下前端 buildModel 肯解析的方程。返回 {'expr', 'params'}，params 按出现顺序。"""
    if not isinstance(expression, str):
        raise PlotExprError('请输入方程或函数式')
    raw = expression.strip()
    if not raw:
        raise PlotExprError('请输入方程或函数式')
    if len(raw) > MAX_EXPR_LEN or any(ord(ch) < 32 for ch in raw):
        raise PlotExprError('方程无法识别')
    text = normalize_expression(raw)
    if not text:
        raise PlotExprError('请输入方程或函数式')
    parts = text.split('=')
    if len(parts) > 2:
        raise PlotExprError('一个方程里只能有一个等号')
    if len(parts) == 2:
        if not parts[0] or not parts[1]:
            raise PlotExprError('等号两边都不能为空')
        left, right = parts
    elif 'y' in text:
        left, right = text, '0'
    else:
        left, right = 'y-(%s)' % text, '0'
    rpn = [*to_rpn(tokenize(left)), *to_rpn(tokenize(right)), {'type': 'op', 'value': '-'}]
    _check_rpn(rpn)
    uses_x = any(token['type'] == 'var' and token['name'] == 'x' for token in rpn)
    uses_y = any(token['type'] == 'var' and token['name'] == 'y' for token in rpn)
    if not uses_x and not uses_y:
        raise PlotExprError('方程里需要包含 x 或 y')
    params = []
    seen = set()
    for token in rpn:
        if token['type'] == 'param' and token['name'] not in seen:
            seen.add(token['name'])
            params.append(token['name'])
    return {'expr': raw, 'params': params}


def clean_label(value):
    if not isinstance(value, str):
        return ''
    text = ' '.join(value.split())
    if not text or len(text) > MAX_LABEL_LEN:
        return ''
    if any(ch in text for ch in '<>{}[]`$\\') or any(ord(ch) < 32 for ch in text):
        return ''
    return text


def clean_params(raw, allowed):
    """只留方程里真出现的字母，值必须是有限数字（允许纯数字字符串，不算式）。"""
    if not isinstance(raw, dict):
        return {}
    allowed = set(allowed)
    cleaned = {}
    for name, value in raw.items():
        if name not in allowed:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not math.isfinite(value) or abs(value) > MAX_PARAM_ABS:
            continue
        cleaned[name] = int(value) if isinstance(value, float) and value.is_integer() else value
    return cleaned


def accept_curves(items):
    """从模型给的 curves 里留下画布肯画的那些。非法的整条丢掉，不执行其中任何代码。"""
    if not isinstance(items, list):
        return {'curves': [], 'skipped': 0, 'truncated': False}
    truncated = len(items) > MAX_CURVES
    items = items[:MAX_CURVES]
    curves = []
    skipped = 0
    for item in items:
        if isinstance(item, str):
            item = {'expr': item}
        if not isinstance(item, dict):
            skipped += 1
            continue
        expr = item.get('expr', item.get('equation', ''))
        if not isinstance(expr, str):
            skipped += 1
            continue
        try:
            # 模型常把课本分式原样抄回来。先收成画布的写法，再决定收不收。
            info = validate_plot_expression(normalize_textbook_math(expr))
        except PlotExprError:
            skipped += 1
            continue
        curve = {'expr': info['expr']}
        label = clean_label(item.get('label'))
        if label:
            curve['label'] = label
        params = clean_params(item.get('params'), info['params'])
        if params:
            curve['params'] = params
        curves.append(curve)
    return {'curves': curves, 'skipped': skipped, 'truncated': truncated}


def iter_json_values(text):
    """按出现顺序取出顶层 JSON 对象或数组。围栏、前后废话都跳过。

    从一个 `{` 或 `[` 起用 raw_decode，失败就前进一个字符。这样连续的多个
    JSON 体（中间可以换行）都能留下，不会把第一对到最后一对大括号糊成一段。
    """
    decoder = json.JSONDecoder()
    index = 0
    length = len(text or '')
    while index < length:
        if text[index] not in '{[':
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        yield value
        index = max(end, index + 1)


def _gather_curve_items(value, items, refusals):
    """一个 JSON 体里能画的曲线放进 items。found 为 false 的记一笔拒绝。"""
    if isinstance(value, list):
        bare = value and all(
            isinstance(item, dict) and ('expr' in item or 'equation' in item) and 'found' not in item
            for item in value)
        if bare:
            items.extend(value)
            return
        for item in value:
            _gather_curve_items(item, items, refusals)
        return
    if not isinstance(value, dict):
        return
    found = value.get('found')
    if isinstance(found, bool):
        if found:
            curves = value.get('curves')
            if isinstance(curves, list):
                items.extend(curves)
            elif 'expr' in value or 'equation' in value:
                items.append(value)
        else:
            refusals.append(value.get('error'))
        return
    if isinstance(value.get('curves'), list):
        items.extend(value['curves'])
        return
    if 'expr' in value or 'equation' in value:
        items.append(value)


def sanitize_reason(reason):
    if not isinstance(reason, str):
        return ''
    text = ' '.join(reason.replace('%', '').split())
    if not text or len(text) > 40 or any(ch in text for ch in '<>{}\\`$'):
        return ''
    if any(ord(ch) < 32 for ch in text):
        return ''
    return text


def interpret_model_output(content):
    """HTTP 200 的正文怎么处理。ok 为假时这次仍然算花过 token（由调用方记账）。

    一个 JSON 对象，或连续多个 JSON 体，都收。方程合并后再套 16 条上限。
    """
    items = []
    refusals = []
    saw_found_true = False
    for value in iter_json_values(content or ''):
        before = len(items)
        _gather_curve_items(value, items, refusals)
        if isinstance(value, dict) and value.get('found') is True:
            saw_found_true = True
        elif len(items) > before:
            saw_found_true = True
    if not items and not refusals and not saw_found_true:
        return {
            'ok': False, 'code': 'unparseable', 'detail': '',
            'curves': [], 'skipped': 0, 'truncated': False,
        }
    if not items and not saw_found_true:
        detail = ''
        for reason in refusals:
            detail = sanitize_reason(reason)
            if detail:
                break
        return {
            'ok': False, 'code': 'not_plottable', 'detail': detail,
            'curves': [], 'skipped': 0, 'truncated': False,
        }
    if not items:
        return {
            'ok': False, 'code': 'bad_expr', 'detail': '',
            'curves': [], 'skipped': 0, 'truncated': False,
        }
    accepted = accept_curves(items)
    if not accepted['curves'] and not saw_found_true:
        detail = ''
        for reason in refusals:
            detail = sanitize_reason(reason)
            if detail:
                break
        return {
            'ok': False, 'code': 'not_plottable', 'detail': detail,
            'curves': [], 'skipped': accepted['skipped'], 'truncated': accepted['truncated'],
        }
    if not accepted['curves']:
        return {
            'ok': False, 'code': 'bad_expr', 'detail': '',
            'curves': [], 'skipped': accepted['skipped'], 'truncated': accepted['truncated'],
        }
    return {
        'ok': True, 'code': 'ok', 'detail': '',
        'curves': accepted['curves'],
        'skipped': accepted['skipped'],
        'truncated': accepted['truncated'],
    }


# 丢了反斜杠的 frac{a}{b} 和正式的 \frac{a}{b} 都认。fraction 这种单词不会撞上，因为后面必须是花括号。
_FRAC_MARK = re.compile(r'(?:\\(?:d|t)?frac|(?<![A-Za-z\\])frac)\s*\{')
_SQRT_MARK = re.compile(r'(?:\\sqrt|(?<![A-Za-z\\])sqrt)(?=\s*\[|\s*\{)')
_SUPER_BRACED = re.compile(r'\^\s*\{([^{}]*)\}')
_SUB_BRACED = re.compile(r'_\s*\{([^{}]*)\}')
_LATEX_DROP = re.compile(
    r'\\(?:left|right|displaystyle|textstyle|quad|qquad|,|;|!|big|Big|bigg|Bigg)\s*')
_CANDIDATE = re.compile(r'[0-9A-Za-z+\-*/^=().]+')
_TRIVIAL_LINE = re.compile(r'^[xy]=-?(?:\d+(?:\.\d+)?)$')
_KIND_LABELS = (
    ('双曲线', '双曲线'),
    ('抛物线', '抛物线'),
    ('椭圆', '椭圆'),
    ('直线', '直线'),
    ('圆', '圆'),
)


def _read_group(text, pos):
    """从 text[pos] 的左花括号读到配对的右花括号。不合则尽量把剩余算进去。"""
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


def _apply_until_stable(text, func):
    for _ in range(12):
        out = func(text)
        if out == text:
            return text
        text = out
    return text


def _skip_space(text, pos):
    while pos < len(text) and text[pos] in ' \t\n':
        pos += 1
    return pos


def _replace_fracs(text):
    """\\frac{a}{b} 与 frac{a}{b} → (a)/(b)。嵌套靠反复扫。"""

    def once(src):
        out, pos = [], 0
        while True:
            match = _FRAC_MARK.search(src, pos)
            if not match:
                out.append(src[pos:])
                break
            num, after = _read_group(src, match.end() - 1)
            if num is None:
                out.append(src[pos:match.end()])
                pos = match.end()
                continue
            after = _skip_space(src, after)
            if after < len(src) and src[after] == '{':
                den, after = _read_group(src, after)
            else:
                word = re.match(r'(\w+)', src[after:])
                den = word.group(1) if word else ''
                after += word.end() if word else 0
            out.append(src[pos:match.start()])
            out.append('(%s)/(%s)' % (num.strip(), (den or '').strip()))
            pos = after
        return ''.join(out)

    return _apply_until_stable(text, once)


def _replace_sqrts(text):
    """\\sqrt{x} 与 sqrt{x} → sqrt(x)。带方括号的开方写成 (x)^(1/n)。"""

    def once(src):
        out, pos = [], 0
        while True:
            match = _SQRT_MARK.search(src, pos)
            if not match:
                out.append(src[pos:])
                break
            at = _skip_space(src, match.end())
            root = ''
            if at < len(src) and src[at] == '[':
                close = src.find(']', at)
                if close > 0:
                    root, at = src[at + 1:close].strip(), close + 1
                    at = _skip_space(src, at)
            body, at = _read_group(src, at)
            if body is None:
                out.append(src[pos:match.end()])
                pos = match.end()
                continue
            out.append(src[pos:match.start()])
            if root.isdigit() and root != '2':
                out.append('(%s)^(1/%s)' % (body.strip(), root))
            else:
                out.append('sqrt(%s)' % body.strip())
            pos = at
        return ''.join(out)

    return _apply_until_stable(text, once)


def _script_exponent(body):
    body = (body or '').strip()
    if re.fullmatch(r'-?\d+', body) or re.fullmatch(r'[A-Za-z]', body):
        return '^' + body
    return '^(%s)' % body


def normalize_textbook_math(raw):
    """把课本 / LaTeX 记号收成画布那套写法。不认识的命令丢掉，不在这里求值。

    覆盖高中题里常见、而且会让「不是函数图像」误伤的几种：
    frac{x^{2}}{16}、\\frac{x^{2}}{16}、x^{2}、\\sqrt{5}、\\left(\\right)。
    """
    if not isinstance(raw, str):
        return ''
    text = raw.replace('$', '')
    text = text.replace('\\{', '(').replace('\\}', ')')
    # \lvert x \rvert 先收成竖线，否则末尾那条「丢掉未知命令」会把绝对值抹成没有
    text = re.sub(r'\\[lr]?vert\b', '|', text)
    text = _LATEX_DROP.sub('', text)
    text = _replace_fracs(text)
    text = _replace_sqrts(text)
    text = _SUPER_BRACED.sub(lambda match: _script_exponent(match.group(1)), text)
    text = _SUB_BRACED.sub('', text)
    text = re.sub(r'\\(?:cdot|times|ast)\b', '*', text)
    text = re.sub(r'\\div\b', '/', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    return text


def _guess_label(source):
    if not isinstance(source, str):
        return ''
    for word, label in _KIND_LABELS:
        if word in source:
            return label
    return ''


def extract_plot_equations(text):
    """从一段题目原文里把已经写明的、画布肯收的方程捞出来。

    捞不到就返回空列表。调用方在模型拒绝或式子对不上时用它兜底，
    避免「椭圆方程夹在求周长的大题里」被当成不是函数图像。
    """
    normalized = normalize_textbook_math(text or '')
    found = []
    seen = set()
    trivial = []
    for match in _CANDIDATE.finditer(normalized):
        piece = match.group(0)
        if '=' not in piece or len(piece) > MAX_EXPR_LEN:
            continue
        try:
            info = validate_plot_expression(piece)
        except PlotExprError:
            continue
        expr = normalize_expression(info['expr'])
        if expr in seen:
            continue
        seen.add(expr)
        curve = {'expr': info['expr']}
        if _TRIVIAL_LINE.fullmatch(expr):
            trivial.append(curve)
        else:
            found.append(curve)
    curves = found or trivial
    truncated = len(curves) > MAX_CURVES
    curves = curves[:MAX_CURVES]
    if len(curves) == 1:
        label = _guess_label(text)
        if label:
            curves[0]['label'] = label
    return {'curves': curves, 'truncated': truncated}


def sniff_image(raw):
    """只认 jpg / png / gif / webp 的文件头。SVG 和随便改了后缀的文本不要。"""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 12:
        return ''
    if raw[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'webp'
    return ''


def classify_image(raw, limit=MAX_IMAGE_BYTES):
    """进模型之前的图片门槛。返回 ok / absent / empty / too_big / type。"""
    if raw is None:
        return 'absent'
    if not isinstance(raw, (bytes, bytearray)):
        return 'type'
    if len(raw) == 0:
        return 'empty'
    if len(raw) > limit:
        return 'too_big'
    if not sniff_image(raw):
        return 'type'
    return 'ok'


_MODEL_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def clean_model_id(value, fallback):
    text = (value or '').strip()
    if _MODEL_RE.fullmatch(text):
        return text
    return fallback


def clean_api_url(value, fallback):
    text = (value or '').strip()
    if text.startswith(('https://', 'http://')) and len(text) <= 200 and ' ' not in text:
        return text
    return fallback
