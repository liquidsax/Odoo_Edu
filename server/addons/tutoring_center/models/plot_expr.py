"""函数图像表达式的服务端校验。

与 static/src/function_plot.js 的「归一化 → 分词 → 调度场」对齐，只判断
前端画布肯不肯收下这条式子，**不求值、不 exec**。两边漂移时以
dev/zz_plot_ai_unit.py 里对 buildModel 的对照为准。
"""
import math
import re

MAX_EXPR_LEN = 160
MAX_CURVES = 4
MAX_LABEL_LEN = 16
MAX_PARAM_ABS = 1_000_000
MAX_INPUT_CHARS = 400

FUNCTIONS = (
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sqrt', 'abs', 'exp', 'ln', 'log',
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
            if head['type'] == 'lparen':
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
            info = validate_plot_expression(expr.strip())
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


def parse_plot_response(text):
    """只认首尾大括号之间的 JSON 对象，且必须有布尔 found。围栏、前后废话都剥掉。"""
    cleaned = text or ''
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        import json
        data = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get('found'), bool):
        return None
    return data


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
    """HTTP 200 的正文怎么处理。ok 为假时这次仍然算花过 token（由调用方记账）。"""
    data = parse_plot_response(content)
    if data is None:
        return {
            'ok': False, 'code': 'unparseable', 'detail': '',
            'curves': [], 'skipped': 0, 'truncated': False,
        }
    if not data.get('found'):
        return {
            'ok': False, 'code': 'not_plottable', 'detail': sanitize_reason(data.get('error')),
            'curves': [], 'skipped': 0, 'truncated': False,
        }
    accepted = accept_curves(data.get('curves'))
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
