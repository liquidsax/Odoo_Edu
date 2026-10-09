import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/* =========================================================================
 * 一、表达式解析
 *    归一化 → 分词 → 调度场算法（RPN）→ 编译成闭包 (x, y) => number
 * ========================================================================= */

const CONSTANTS = { pi: Math.PI, e: Math.E };

const FUNCTIONS = {
    sin: Math.sin,
    cos: Math.cos,
    tan: Math.tan,
    asin: Math.asin,
    acos: Math.acos,
    atan: Math.atan,
    sqrt: Math.sqrt,
    abs: Math.abs,
    exp: Math.exp,
    ln: Math.log,
    log: Math.log10,
};

const BINARY_PRECEDENCE = { "+": 1, "-": 1, "*": 2, "/": 2, "^": 4 };
const UNARY_PRECEDENCE = 3;

// 长的放前面：分解 "xy" 这类连写时先试 "sin"、"pi" 再试单字母
const KNOWN_NAMES = [...Object.keys(FUNCTIONS), ...Object.keys(CONSTANTS), "x", "y"].sort(
    (a, b) => b.length - a.length
);

const NORMALIZE_RULES = [
    [/（/g, "("],
    [/）/g, ")"],
    [/＝/g, "="],
    [/＋/g, "+"],
    [/－/g, "-"],
    [/[−–—]/g, "-"],
    [/[×·]/g, "*"],
    [/÷/g, "/"],
    [/²/g, "^2"],
    [/³/g, "^3"],
    [/π/g, "pi"],
];

function normalizeExpression(raw) {
    let text = String(raw);
    for (const [pattern, replacement] of NORMALIZE_RULES) {
        text = text.replace(pattern, replacement);
    }
    return text.replace(/\*\*/g, "^").replace(/\s+/g, "");
}

function tokenize(text) {
    const tokens = [];
    let index = 0;
    while (index < text.length) {
        const char = text[index];
        if (/[0-9.]/.test(char)) {
            let end = index;
            while (end < text.length && /[0-9.]/.test(text[end])) {
                end++;
            }
            const literal = text.slice(index, end);
            const value = Number(literal);
            if (!Number.isFinite(value)) {
                throw new Error(`无法识别的数字「${literal}」`);
            }
            tokens.push({ type: "num", value });
            index = end;
        } else if (/[a-z]/i.test(char)) {
            let end = index;
            while (end < text.length && /[a-z]/i.test(text[end])) {
                end++;
            }
            pushName(text.slice(index, end), tokens, text[end] === "(");
            index = end;
        } else if (char === "(" || char === ")") {
            tokens.push({ type: char === "(" ? "lparen" : "rparen" });
            index++;
        } else if ("+-*/^".includes(char)) {
            tokens.push({ type: "op", value: char });
            index++;
        } else {
            throw new Error(`无法识别的字符「${char}」`);
        }
    }
    return tokens;
}

// 连写的字母按已知符号拆开（"xy" → x*y、"2pi" → 2*pi 走隐式乘法）；
// 拆不出已知符号的单个字母就是参数——图上那条曲线用它时，页面上对应一个滑块。
function pushName(raw, tokens, followedByCall) {
    const lower = raw.toLowerCase();
    if (KNOWN_NAMES.includes(lower) && !(lower === "e" && raw === "E")) {
        tokens.push({ type: "name", name: lower });
        return;
    }
    // 一整串未知字母紧跟着括号，多半是函数名打错了（sn(x)）；单个字母仍按隐式乘法放行（a(x+1)）
    if (followedByCall && raw.length > 1) {
        throw new Error(`未知函数「${raw}」：函数只支持 ${Object.keys(FUNCTIONS).join(" ")}，其余字母是参数`);
    }
    let index = 0;
    while (index < raw.length) {
        const piece = knownPiece(raw, lower, index);
        if (piece) {
            tokens.push({ type: "name", name: piece });
            index += piece.length;
        } else {
            // 参数名保留大小写：唯一的大小写例外是小写 e 当自然常数、大写 E 当参数
            // （圆的一般式 x²+y²+Dx+Ey+F=0 要用 E，与 Desmos 一样把 E 和 e 看成两个符号）
            tokens.push({ type: "param", name: raw[index] });
            index++;
        }
    }
}

function knownPiece(raw, lower, index) {
    const piece = KNOWN_NAMES.find((known) => lower.startsWith(known, index));
    return piece === "e" && raw[index] === "E" ? null : piece;
}

function toRPN(tokens) {
    const output = [];
    const operators = [];
    const top = () => operators[operators.length - 1];
    // 上一个 token 能否作为值的结尾（用于区分一元负号与隐式乘法）
    const endsValue = (token) =>
        !!token && ["num", "name", "rparen", "var", "param"].includes(token.type);

    const pushBinary = (value) => {
        const precedence = BINARY_PRECEDENCE[value];
        const rightAssociative = value === "^";
        while (top()) {
            const head = top();
            if (head.type === "lparen") {
                break;
            }
            const headPrecedence =
                head.type === "func"
                    ? Infinity
                    : head.type === "unary"
                      ? UNARY_PRECEDENCE
                      : BINARY_PRECEDENCE[head.value];
            if (
                headPrecedence > precedence ||
                (headPrecedence === precedence && !rightAssociative)
            ) {
                output.push(operators.pop());
            } else {
                break;
            }
        }
        operators.push({ type: "op", value });
    };

    let previous = null;
    for (let index = 0; index < tokens.length; index++) {
        const token = tokens[index];
        const startsValue = ["num", "name", "lparen", "param"].includes(token.type);
        // 隐式乘法（2x、3(x+1)、(x+1)(x-1)）：优先级同 "*"，因此 2x^2 解析为 2*(x^2)
        if (startsValue && endsValue(previous)) {
            pushBinary("*");
        }

        if (token.type === "num" || token.type === "param") {
            output.push(token);
            previous = token;
        } else if (token.type === "name") {
            const { name } = token;
            if (name === "x" || name === "y") {
                output.push({ type: "var", name });
                previous = token;
            } else if (name in CONSTANTS) {
                output.push({ type: "num", value: CONSTANTS[name] });
                previous = token;
            } else {
                const next = tokens[index + 1];
                if (!next || next.type !== "lparen") {
                    throw new Error(`函数「${name}」后面要跟括号，例如 ${name}(x)`);
                }
                operators.push({ type: "func", name });
                // 标记为函数名：紧随的 "(" 是调用括号，不触发隐式乘法
                previous = { type: "func" };
            }
        } else if (token.type === "lparen") {
            operators.push(token);
            previous = token;
        } else if (token.type === "rparen") {
            while (top() && top().type !== "lparen") {
                output.push(operators.pop());
            }
            if (!top()) {
                throw new Error("括号不匹配");
            }
            operators.pop();
            if (top() && top().type === "func") {
                output.push(operators.pop());
            }
            previous = token;
        } else {
            // 一元负号：直接入栈，不弹出已有运算符（保证 2^-3、-x^2 都正确）
            if (token.value === "-" && !endsValue(previous)) {
                operators.push({ type: "unary" });
            } else {
                pushBinary(token.value);
            }
            previous = token;
        }
    }

    while (operators.length) {
        const head = operators.pop();
        if (head.type === "lparen") {
            throw new Error("括号不匹配");
        }
        output.push(head);
    }
    return output;
}

const BINARY_EVALUATORS = {
    "+": (a, b) => (x, y) => a(x, y) + b(x, y),
    "-": (a, b) => (x, y) => a(x, y) - b(x, y),
    "*": (a, b) => (x, y) => a(x, y) * b(x, y),
    "/": (a, b) => (x, y) => a(x, y) / b(x, y),
    "^": (a, b) => (x, y) => Math.pow(a(x, y), b(x, y)),
};

const INCOMPLETE = "表达式不完整，请检查运算符与括号";

function compileRPN(rpn, scope = {}) {
    const stack = [];
    const pop = () => {
        const operand = stack.pop();
        if (!operand) {
            throw new Error(INCOMPLETE);
        }
        return operand;
    };
    for (const token of rpn) {
        if (token.type === "num") {
            const { value } = token;
            stack.push(() => value);
        } else if (token.type === "var") {
            stack.push(token.name === "x" ? (x) => x : (x, y) => y);
        } else if (token.type === "param") {
            // 参数在编译时就绑成常量：滑块一动整条曲线重建一次模型，闭包就不必带第三个参数
            const value = scope[token.name];
            stack.push(() => (Number.isFinite(value) ? value : NaN));
        } else if (token.type === "func") {
            const operand = pop();
            const fn = FUNCTIONS[token.name];
            stack.push((x, y) => fn(operand(x, y)));
        } else if (token.type === "unary") {
            const operand = pop();
            stack.push((x, y) => -operand(x, y));
        } else {
            const right = pop();
            const left = pop();
            stack.push(BINARY_EVALUATORS[token.value](left, right));
        }
    }
    if (stack.length !== 1) {
        throw new Error(INCOMPLETE);
    }
    return stack[0];
}

/* --------------------------------- 方程处理 -------------------------------- */

const LINEAR_TOLERANCE = 1e-7;

// 用数值差分判断 F 对 y 是否线性：是则能解出 y = f(x)，走显式采样（更快更平滑）
function solveForY(F) {
    const probes = [0.37, 1.13];
    const slopes = [];
    for (const x of probes) {
        const v0 = F(x, 0);
        const v1 = F(x, 1);
        const v2 = F(x, 2);
        if (![v0, v1, v2].every(Number.isFinite)) {
            return null;
        }
        const scale = Math.max(1, Math.abs(v0), Math.abs(v1), Math.abs(v2));
        const curvature = v2 - 2 * v1 + v0;
        if (Math.abs(curvature) > LINEAR_TOLERANCE * scale) {
            return null;
        }
        slopes.push(v1 - v0);
    }
    const [first, second] = slopes;
    const scale = Math.max(1, Math.abs(first), Math.abs(second));
    if (Math.abs(first - second) > LINEAR_TOLERANCE * scale || Math.abs(first) <= LINEAR_TOLERANCE) {
        return null;
    }
    return (x) => -F(x, 0) / first;
}

// 新出现的参数没有历史值时先按 1 立起来，滑块条上再改
const DEFAULT_PARAM_VALUE = 1;

function buildModel(expression, params = {}) {
    const text = normalizeExpression(expression);
    if (!text) {
        throw new Error("请输入方程或函数式");
    }
    const parts = text.split("=");
    if (parts.length > 2) {
        throw new Error("一个方程里只能有一个等号");
    }
    let left;
    let right;
    if (parts.length === 2) {
        if (!parts[0] || !parts[1]) {
            throw new Error("等号两边都不能为空");
        }
        [left, right] = parts;
    } else if (text.includes("y")) {
        left = text;
        right = "0";
    } else {
        left = `y-(${text})`;
        right = "0";
    }

    const rpn = [...toRPN(tokenize(left)), ...toRPN(tokenize(right)), { type: "op", value: "-" }];
    const usesX = rpn.some((token) => token.type === "var" && token.name === "x");
    const usesY = rpn.some((token) => token.type === "var" && token.name === "y");
    if (!usesX && !usesY) {
        throw new Error("方程里需要包含 x 或 y");
    }
    const used = [...new Set(rpn.filter((token) => token.type === "param").map((token) => token.name))];
    const scope = {};
    for (const name of used) {
        const value = params[name];
        scope[name] = Number.isFinite(value) ? value : DEFAULT_PARAM_VALUE;
    }
    const F = compileRPN(rpn, scope);

    if (!usesY) {
        return { kind: "vertical", F, used }; // 如 x=2、x=a：竖直线
    }
    const explicit = solveForY(F);
    if (explicit) {
        const samples = [0.11, 0.73];
        if (samples.every((x) => Number.isFinite(explicit(x)))) {
            return { kind: "explicit", explicit, used };
        }
    }
    return { kind: "implicit", F, used }; // 圆、椭圆、双曲线等
}

/* =========================================================================
 * 一之二、按类型填参数 → 自动拼出方程
 * ========================================================================= */

function num(value) {
    if (!Number.isFinite(value)) {
        throw new Error("参数不是有效数值");
    }
    return String(Number(value.toFixed(6)));
}

// 输入框里除了数字，也允许 3/2、2pi、sqrt(5) 这类算式
function evalConstant(text) {
    const normalized = normalizeExpression(String(text ?? ""));
    if (!normalized) {
        throw new Error("不能为空");
    }
    const rpn = toRPN(tokenize(normalized));
    if (rpn.some((token) => token.type === "var")) {
        throw new Error("不能含 x 或 y");
    }
    if (rpn.some((token) => token.type === "param")) {
        throw new Error("这里只能填数值，不能引用滑块的字母");
    }
    const value = compileRPN(rpn)(0, 0);
    if (!Number.isFinite(value)) {
        throw new Error("不是有效数值");
    }
    return value;
}

// 带平移的标准式片段：offset 为 0 时就是 "x"，否则 "(x-(h))"。
// 平移量设成滑块时字母必须留在式子里（哪怕当前值是 0），不然那个滑块没有可绑的对象。
function centered(axis, offset, offsetSym) {
    if (offsetSym) {
        return `(${axis}-${offsetSym})`;
    }
    return offset === 0 ? axis : `(${axis}-(${num(offset)}))`;
}

// 分母为 1 时省略 "/1"，让方程贴近手写习惯；分母设成滑块时写的是字母（分母类是 "a^2" 这种带指数的写法）
function squaredTerm(axis, offset, denominator, denominatorSym, offsetSym) {
    const body = `${centered(axis, offset, offsetSym)}^2`;
    if (denominatorSym) {
        return `${body}/${denominatorSym}`;
    }
    return denominator === 1 ? body : `${body}/${num(denominator)}`;
}

// 系数 1 省略、-1 只留负号
function coefficientText(value) {
    if (value === 1) {
        return "";
    }
    if (value === -1) {
        return "-";
    }
    return num(value);
}

// 把 ω、φ 这类值写成课本里的 π 倍数（pi、pi/2、2pi/3…），不是整数倍就退回小数
function piText(value) {
    if (value === 0) {
        return "0";
    }
    const ratio = value / Math.PI;
    for (let denominator = 1; denominator <= 12; denominator++) {
        const numerator = ratio * denominator;
        if (Math.abs(numerator - Math.round(numerator)) < 1e-9) {
            const whole = Math.round(numerator);
            if (denominator === 1) {
                return Math.abs(whole) === 1 ? `${whole < 0 ? "-" : ""}pi` : `${whole}pi`;
            }
            const sign = whole < 0 ? "-" : "";
            const head = Math.abs(whole) === 1 ? "" : Math.abs(whole);
            return `${sign}${head}pi/${denominator}`;
        }
    }
    return num(value);
}

// [[系数, "x"], [系数, "y"], [系数, ""]] → "x-2y-4"（省略系数 1、合并正负号）。
// 第三项是该字段的滑块在方程里的写法：字母自带正负号，所以一律用加号衔接、不做符号美化。
function linearCombination(terms) {
    let text = "";
    for (const [coefficient, name, sym] of terms) {
        if (sym) {
            text += text ? `+${sym}${name}` : `${sym}${name}`;
            continue;
        }
        if (coefficient === 0) {
            continue;
        }
        const sign = coefficient < 0 ? "-" : text ? "+" : "";
        const absolute = Math.abs(coefficient);
        const coefficientText = absolute === 1 && name ? "" : num(absolute);
        text += `${sign}${coefficientText}${name}`;
    }
    return text || "0";
}

// 圆锥曲线系数式：A·x² ± B·y² 拼成课本样子（4x²、x²/4、-4y²、y²）
function conicCombination(terms) {
    const parts = [];
    for (const [coefficient, axisTerm, sym] of terms) {
        if (sym) {
            parts.push({ negative: false, body: `${sym}*${axisTerm}^2` });
            continue;
        }
        if (coefficient === 0) {
            continue;
        }
        const absolute = Math.abs(coefficient);
        const inverse = 1 / absolute;
        const useFraction = Math.round(inverse) > 1 && Math.abs(inverse - Math.round(inverse)) < 1e-9;
        const body = useFraction
            ? `${axisTerm}^2/${Math.round(inverse)}`
            : absolute === 1
              ? `${axisTerm}^2`
              : `${num(absolute)}${axisTerm}^2`;
        parts.push({ negative: coefficient < 0, body });
    }
    if (!parts.length) {
        throw new Error("两项系数不能同时为 0");
    }
    return parts
        .map((part, index) => {
            if (index === 0) {
                return (part.negative ? "-" : "") + part.body;
            }
            return (part.negative ? "-" : "+") + part.body;
        })
        .join("");
}

// 把数值尽量写成课本里的根式/分数（√3/2、2√5/3、1/2）；写不出就返回 null 由调用方退回小数
function radicalText(value) {
    if (!Number.isFinite(value) || value <= 0) {
        return null;
    }
    const gcd = (a, b) => (b ? gcd(b, a % b) : a);
    const square = value * value;
    for (let denominator = 1; denominator <= 64; denominator++) {
        const numerator = Math.round(square * denominator);
        if (numerator <= 0 || numerator > 100000) {
            continue;
        }
        if (Math.abs(square - numerator / denominator) > 1e-9 * Math.max(1, square)) {
            continue;
        }
        // value = √(numerator/denominator) = √(numerator·denominator)/denominator
        // 把根号里能开出来的因数提到根号外：√12/4 → 2√3/4 → √3/2
        let rest = numerator * denominator;
        let outside = 1;
        for (let divisor = 2; divisor * divisor <= rest; divisor++) {
            while (rest % (divisor * divisor) === 0) {
                rest /= divisor * divisor;
                outside *= divisor;
            }
        }
        const common = gcd(outside, denominator) || 1;
        const head = outside / common;
        const tail = denominator / common;
        if (rest === 1) {
            return tail === 1 ? String(head) : `${head}/${tail}`;
        }
        const radical = `${head === 1 ? "" : head}√${rest}`;
        return tail === 1 ? radical : `${radical}/${tail}`;
    }
    return null;
}

// 课本写法优先，化不出就退回小数：√3/2 ≈ 0.866
function exactNumberText(value) {
    if (!Number.isFinite(value)) {
        return "—";
    }
    if (value === 0) {
        return "0";
    }
    const radical = radicalText(value);
    return radical ? `${radical} ≈ ${formatNumber(value)}` : formatNumber(value);
}

// 椭圆离心率 e = c/a = √(1 - b²/a²)（a 长半轴、b 短半轴）；两轴相等时是圆，e=0
function eccentricityInfo(semiAxisX2, semiAxisY2) {
    if (!(semiAxisX2 > 0) || !(semiAxisY2 > 0)) {
        return null;
    }
    const major2 = Math.max(semiAxisX2, semiAxisY2);
    const minor2 = Math.min(semiAxisX2, semiAxisY2);
    const value = Math.sqrt(Math.max(0, 1 - minor2 / major2));
    return { value, text: exactNumberText(value), circle: value <= 1e-12 };
}

// 双曲线渐近线：过中心 (h,k) 的两条直线 y-k = ±slope·(x-h)。
// 实轴在 x 轴是 y-k = ±(b/a)(x-h)，在 y 轴是 y-k = ±(a/b)(x-h)。
function hyperbolaAsymptotes(mode, v) {
    let transverse2; // a²
    let conjugate2; // b²
    let transverseY = false;
    if (mode === "coefficient") {
        // Ax²+By²=N：先按 N 的符号归一化，正系数那一项就是实轴
        const sign = v.N > 0 ? 1 : -1;
        const coefficientX = sign * v.A;
        const coefficientY = sign * v.B;
        const total = Math.abs(v.N);
        if (coefficientX > 0) {
            transverse2 = total / coefficientX;
            conjugate2 = total / Math.abs(coefficientY);
        } else {
            transverse2 = total / coefficientY;
            conjugate2 = total / Math.abs(coefficientX);
            transverseY = true;
        }
    } else {
        transverse2 = v.a2;
        conjugate2 = v.b2;
        transverseY = mode === "y";
    }
    if (!(transverse2 > 0) || !(conjugate2 > 0)) {
        return [];
    }
    const transverse = Math.sqrt(transverse2);
    const conjugate = Math.sqrt(conjugate2);
    const slope = transverseY ? transverse / conjugate : conjugate / transverse;
    const h = v.h || 0;
    const k = v.k || 0;
    return [
        { h, k, slope },
        { h, k, slope: -slope },
    ].map((line) => ({
        ...line,
        text: asymptoteLineText(line),
        slopeIntercept: asymptoteSlopeIntercept(line),
    }));
}

// ---- 渐近线方程的课本写法 ----
// 系数先试根式/分数（3/2、√5/2、2√3/3），化不出才退回四位小数；±1 返回空串（省掉系数）
function slopeCoefficientText(value) {
    const abs = Math.abs(value);
    if (Math.abs(abs - 1) < 1e-12) {
        return "";
    }
    return radicalText(abs) || formatNumber(abs);
}

// 带符号的斜率片段：2 → 2、3/2 → (3/2)、−√2 → −(√2)、−1 → −（配括号读成 y = −(x−h)）
function signedSlopeText(slope) {
    const body = slopeCoefficientText(slope);
    const sign = slope < 0 ? "−" : "";
    if (!body) {
        return sign;
    }
    return body.includes("/") || body.includes("√") ? `${sign}(${body})` : `${sign}${body}`;
}

// 常数项写法：2 → 2、−3/2 → −(3/2)
function constantText(value) {
    if (Math.abs(value) < 1e-12) {
        return "0";
    }
    const abs = Math.abs(value);
    return `${value < 0 ? "−" : ""}${radicalText(abs) || formatNumber(abs)}`;
}

// 变量与中心偏移的组合：k=2 → "y − 2"、k=−2 → "y + 2"、k=0 → "y"
function shiftedTerm(variable, value) {
    if (Math.abs(value) < 1e-12) {
        return variable;
    }
    return `${variable} ${value > 0 ? "−" : "+"} ${constantText(Math.abs(value))}`;
}

// 单条渐近线：过中心 (h,k) 写成 y − k = m(x − h)，中心在原点时简写成 y = m x
function asymptoteLineText({ h, k, slope }) {
    const m = signedSlopeText(slope);
    if (Math.abs(h) < 1e-12 && Math.abs(k) < 1e-12) {
        return `y = ${m}x`;
    }
    return `${shiftedTerm("y", k)} = ${m}(${shiftedTerm("x", h)})`;
}

// 两条合并的简写：y − k = ±m(x − h)
function asymptoteSummaryText(lines) {
    const { h, k, slope } = lines[0];
    const m = signedSlopeText(Math.abs(slope));
    if (Math.abs(h) < 1e-12 && Math.abs(k) < 1e-12) {
        return `y = ±${m}x`;
    }
    return `${shiftedTerm("y", k)} = ±${m}(${shiftedTerm("x", h)})`;
}

// 斜截式 y = m x + b（b = k − m·h），给悬浮提示补全用
function asymptoteSlopeIntercept({ h, k, slope }) {
    const intercept = k - slope * h;
    const m = signedSlopeText(slope);
    if (Math.abs(intercept) < 1e-12) {
        return `y = ${m}x`;
    }
    return `y = ${m}x ${intercept > 0 ? "+ " : "− "}${constantText(Math.abs(intercept))}`;
}

/* ---------------------------- 字段与滑块的对应 ---------------------------- */
// 字段声明 sym ＝ "这个参数可以变成滑块"，sym 是它在方程里的字母；
// pow 是字母在方程里带的指数（半径 r 写成 r^2、椭圆分母也写成 a^2）；
// storesPower 表示字段存的数本身就是那个幂（分母 a2=4），所以滑块带的是 a=2——
// 半径字段没有这个标记，它存的就是 r，滑块拖的也是 r。
function fieldSliderText(field) {
    if (!field.sym) {
        return null;
    }
    return field.pow > 1 ? `${field.sym}^${field.pow}` : field.sym;
}

function sliderValueOf(field, value) {
    if (field.pow > 1 && field.storesPower) {
        return Math.sign(value || 1) * Math.pow(Math.abs(value), 1 / field.pow);
    }
    return value;
}

function fieldValueOf(field, sliderValue) {
    if (field.pow > 1 && field.storesPower) {
        return Math.pow(sliderValue, field.pow);
    }
    return sliderValue;
}

// 某条曲线当前勾了滑块的字段 → compose 用的 {字段键: 方程里的写法}
function sliderTexts(spec, mode, sliderKeys) {
    const texts = {};
    for (const field of spec.fields(mode)) {
        if (field.sym && sliderKeys.includes(field.key)) {
            texts[field.key] = fieldSliderText(field);
        }
    }
    return texts;
}

// 每条曲线自己带一张 字母 → 滑块 的表：同一个 a 在两条曲线里是两个互不相干的旋钮
function paramValues(params) {
    const values = {};
    for (const [name, param] of params) {
        values[name] = param.value;
    }
    return values;
}

function ensureParam(params, name, options = {}) {
    const existing = params.get(name);
    if (existing) {
        return existing;
    }
    const value = Number.isFinite(options.value) ? options.value : DEFAULT_PARAM_VALUE;
    const range = options.range || [-DEFAULT_SLIDER_HALF, DEFAULT_SLIDER_HALF];
    const param = {
        value,
        min: Math.min(range[0], value),
        max: Math.max(range[1], value),
        step: DEFAULT_SLIDER_STEP,
        label: options.label || "自己写的方程",
    };
    params.set(name, param);
    return param;
}

// 每个类型：字段默认值可直接用；fields 随"写法"切换；compose 抛错即校验失败
const CURVE_TYPES = {
    circle: {
        label: "圆",
        hint: "标准式 (x-a)²+(y-b)²=r²：圆心填 0、0 就是 x²+y²=r²。",
        modes: [
            { key: "standard", label: "圆心 + 半径" },
            { key: "general", label: "一般式 x²+y²+Dx+Ey+F=0" },
        ],
        fields: (mode) =>
            mode === "standard"
                ? [
                      { key: "a", label: "圆心 x₀", value: 0, sym: "a" },
                      { key: "b", label: "圆心 y₀", value: 0, sym: "b" },
                      { key: "r", label: "半径 r", value: 2, sym: "r", pow: 2, range: [0.1, 10] },
                  ]
                : [
                      { key: "D", label: "D", value: -2, sym: "D" },
                      { key: "E", label: "E", value: -4, sym: "E" },
                      { key: "F", label: "F", value: 1, sym: "F" },
                  ],
        compose: (mode, v, sym) => {
            if (mode === "standard") {
                if (v.r <= 0) {
                    throw new Error("半径 r 要大于 0");
                }
                return `${centered("x", v.a, sym.a)}^2+${centered("y", v.b, sym.b)}^2=${sym.r || num(v.r * v.r)}`;
            }
            return `${linearCombination([[1, "x^2"], [1, "y^2"], [v.D, "x", sym.D], [v.E, "y", sym.E], [v.F, "", sym.F]])}=0`;
        },
    },
    ellipse: {
        label: "椭圆",
        hint: (mode) =>
            mode === "coefficient"
                ? "系数式：题目给 4x²+9y²=36 就填 4、9、36；两项系数必须同号（一正一负是双曲线）。"
                : "分母式：题目给 x²/5+y²=1 就填 5 和 1；焦点在哪个轴由程序判断。",
        modes: [
            { key: "denominator", label: "分母式 x²/A+y²/B=1" },
            { key: "coefficient", label: "系数式 Ax²+By²=N" },
        ],
        fields: (mode) =>
            mode === "coefficient"
                ? [
                      { key: "A", label: "x² 的系数", value: 1, sym: "A" },
                      { key: "B", label: "y² 的系数", value: 1, sym: "B" },
                      { key: "N", label: "等号右边", value: 1, sym: "N" },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0, sym: "h" },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0, sym: "k" },
                  ]
                : [
                      { key: "a2", label: "x² 分母 a²", value: 4, sym: "a", pow: 2, storesPower: true, range: [0.1, 10] },
                      { key: "b2", label: "y² 分母 b²", value: 1, sym: "b", pow: 2, storesPower: true, range: [0.1, 10] },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0, sym: "h" },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0, sym: "k" },
                  ],
        compose: (mode, v, sym) => {
            if (mode === "coefficient") {
                if (v.A === 0 || v.B === 0) {
                    throw new Error("x²、y² 的系数都不能为 0");
                }
                if (v.N === 0) {
                    throw new Error("等号右边不能为 0");
                }
                if ((v.A > 0) !== (v.B > 0)) {
                    throw new Error("两项系数同号才是椭圆；一正一负请改选「双曲线」");
                }
                if ((v.A > 0) !== (v.N > 0)) {
                    throw new Error("等号右边的符号与系数相反，图像是空集");
                }
                return `${conicCombination([[v.A, centered("x", v.h, sym.h), sym.A], [v.B, centered("y", v.k, sym.k), sym.B]])}=${sym.N || num(v.N)}`;
            }
            if (v.a2 <= 0 || v.b2 <= 0) {
                throw new Error("两个分母都要大于 0");
            }
            return `${squaredTerm("x", v.h, v.a2, sym.a2, sym.h)}+${squaredTerm("y", v.k, v.b2, sym.b2, sym.k)}=1`;
        },
        // 离心率 e = c/a：分母式直接是两分母，系数式先换算成 x²/(N/A)+y²/(N/B)=1
        describe: (mode, v) => {
            const info =
                mode === "coefficient"
                    ? eccentricityInfo(v.N / v.A, v.N / v.B)
                    : eccentricityInfo(v.a2, v.b2);
            return info ? { eccentricity: info } : null;
        },
    },
    hyperbola: {
        label: "双曲线",
        hint: (mode) =>
            mode === "coefficient"
                ? "系数式：题目给 x²-4y²=4 就填 1、-4、4；两项系数必须一正一负。"
                : "分母式：标准式中间是减号；填两个正的分母，再选焦点在哪个轴。",
        modes: [
            { key: "x", label: "焦点在 x 轴" },
            { key: "y", label: "焦点在 y 轴" },
            { key: "coefficient", label: "系数式 Ax²+By²=N" },
        ],
        fields: (mode) =>
            mode === "coefficient"
                ? [
                      { key: "A", label: "x² 的系数", value: 1, sym: "A" },
                      { key: "B", label: "y² 的系数", value: -4, sym: "B" },
                      { key: "N", label: "等号右边", value: 4, sym: "N" },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0, sym: "h" },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0, sym: "k" },
                  ]
                : [
                      { key: "a2", label: "实半轴分母 a²", value: 4, sym: "a", pow: 2, storesPower: true, range: [0.1, 10] },
                      { key: "b2", label: "虚半轴分母 b²", value: 9, sym: "b", pow: 2, storesPower: true, range: [0.1, 10] },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0, sym: "h" },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0, sym: "k" },
                  ],
        compose: (mode, v, sym) => {
            if (mode === "coefficient") {
                if (v.A === 0 || v.B === 0) {
                    throw new Error("x²、y² 的系数都不能为 0");
                }
                if (v.N === 0) {
                    throw new Error("等号右边不能为 0");
                }
                if ((v.A > 0) === (v.B > 0)) {
                    throw new Error("两项系数一正一负才是双曲线；同号请改选「椭圆」");
                }
                return `${conicCombination([[v.A, centered("x", v.h, sym.h), sym.A], [v.B, centered("y", v.k, sym.k), sym.B]])}=${sym.N || num(v.N)}`;
            }
            if (v.a2 <= 0 || v.b2 <= 0) {
                throw new Error("两个分母都要大于 0");
            }
            // 实半轴分母 A 始终跟着正项：焦点在 x 轴是 x²/A，在 y 轴是 y²/A
            const focusY = mode === "y";
            const positive = focusY
                ? squaredTerm("y", v.k, v.a2, sym.a2, sym.k)
                : squaredTerm("x", v.h, v.a2, sym.a2, sym.h);
            const negative = focusY
                ? squaredTerm("x", v.h, v.b2, sym.b2, sym.h)
                : squaredTerm("y", v.k, v.b2, sym.b2, sym.k);
            return `${positive}-${negative}=1`;
        },
        // 勾选后才带渐近线；三种写法都从 a、b 反推斜率
        extras: () => [{ key: "showAsymptotes", label: "画出渐近线（虚线）", value: false }],
        describe: (mode, v, extras) =>
            extras.showAsymptotes ? { asymptotes: hyperbolaAsymptotes(mode, v) } : null,
    },
    parabola: {
        label: "抛物线",
        hint: "把题目里 2p 的数填进来（y²=4x 就填 4），再选开口方向。",
        modes: [
            { key: "right", label: "开口向右 y²=2px" },
            { key: "left", label: "开口向左 y²=-2px" },
            { key: "up", label: "开口向上 x²=2py" },
            { key: "down", label: "开口向下 x²=-2py" },
        ],
        fields: () => [
            { key: "twoP", label: "2p 的值", value: 4, sym: "m" },
            { key: "h", label: "顶点 x₀（默认 0）", value: 0, sym: "h" },
            { key: "k", label: "顶点 y₀（默认 0）", value: 0, sym: "k" },
        ],
        compose: (mode, v, sym) => {
            const twoP = Math.abs(v.twoP);
            if (twoP === 0) {
                throw new Error("2p 不能为 0");
            }
            const x = centered("x", v.h, sym.h);
            const y = centered("y", v.k, sym.k);
            // 滑块字母 m 代表"2p 这个整体"（课本里 2p 常整体系数），所以方程是 y²=mx，不再拆出 p
            const scale = sym.twoP ? `${sym.twoP}*` : num(twoP);
            if (mode === "left") {
                return `${y}^2=-${scale}${x}`;
            }
            if (mode === "up") {
                return `${x}^2=${scale}${y}`;
            }
            if (mode === "down") {
                return `${x}^2=-${scale}${y}`;
            }
            return `${y}^2=${scale}${x}`;
        },
    },
    line: {
        label: "直线",
        hint: "一般式 Ax+By+C=0，如题目 x-2y-4=0 → A=1、B=-2、C=-4。",
        modes: [
            { key: "general", label: "一般式 Ax+By+C=0" },
            { key: "slope", label: "斜截式 y=kx+b" },
        ],
        fields: (mode) =>
            mode === "general"
                ? [
                      { key: "A", label: "A", value: 1, sym: "A" },
                      { key: "B", label: "B", value: -2, sym: "B" },
                      { key: "C", label: "C", value: -4, sym: "C" },
                  ]
                : [
                      { key: "k", label: "斜率 k", value: 1, sym: "k" },
                      { key: "b", label: "截距 b", value: 0, sym: "b" },
                  ],
        compose: (mode, v, sym) => {
            if (mode === "slope") {
                return `y=${linearCombination([[v.k, "x", sym.k], [v.b, "", sym.b]])}`;
            }
            if (v.A === 0 && v.B === 0) {
                throw new Error("A、B 不能同时为 0");
            }
            return `${linearCombination([[v.A, "x", sym.A], [v.B, "y", sym.B], [v.C, "", sym.C]])}=0`;
        },
    },
    quadratic: {
        label: "二次函数",
        hint: "y = ax² + bx + c，填三个系数。",
        fields: () => [
            { key: "a", label: "a", value: 1, sym: "a" },
            { key: "b", label: "b", value: -2, sym: "b" },
            { key: "c", label: "c", value: -3, sym: "c" },
        ],
        compose: (mode, v, sym) => {
            if (v.a === 0) {
                throw new Error("a 不能为 0（否则是直线）");
            }
            return `y=${linearCombination([[v.a, "x^2", sym.a], [v.b, "x", sym.b], [v.c, "", sym.c]])}`;
        },
    },
    inverse: {
        label: "反比例",
        hint: "y = k/x，填 k（k 不能为 0）。",
        fields: () => [{ key: "k", label: "k", value: 1, sym: "k" }],
        compose: (mode, v, sym) => {
            if (v.k === 0) {
                throw new Error("k 不能为 0");
            }
            return `y=${sym.k || num(v.k)}/x`;
        },
    },
    sine: {
        label: "三角函数",
        hint: "y = A·sin(ωx + φ)；题目给周期 T 时选「用周期」，程序按 ω=2π/T 换算。",
        modes: [
            { key: "omega", label: "用 ω" },
            { key: "period", label: "用周期 T" },
        ],
        fields: (mode) =>
            mode === "period"
                ? [
                      { key: "A", label: "振幅 A", value: 1, sym: "A" },
                      { key: "T", label: "周期 T", value: 2, sym: "T", range: [0.1, 20] },
                      { key: "phi", label: "初相 φ", value: 0, sym: "p" },
                  ]
                : [
                      { key: "A", label: "振幅 A", value: 1, sym: "A" },
                      { key: "w", label: "ω", value: 1, sym: "w" },
                      { key: "phi", label: "初相 φ", value: 0, sym: "p" },
                  ],
        compose: (mode, v, sym) => {
            if (v.A === 0) {
                throw new Error("振幅 A 不能为 0");
            }
            let omega;
            if (mode === "period") {
                if (v.T === 0) {
                    throw new Error("周期 T 不能为 0");
                }
                omega = sym.T ? `2pi/${sym.T}` : piText((2 * Math.PI) / v.T);
            } else {
                if (v.w === 0) {
                    throw new Error("ω 不能为 0");
                }
                omega = sym.w || coefficientText(v.w);
            }
            // 只有纯数字才紧贴 x（2x）；含 pi 或字母的必须补 *，否则 pi/2x 会被读成 pi/(2x)
            const plainNumber = /^-?\d+(\.\d+)?$/.test(omega);
            const omegaPart = omega === "" ? "x" : plainNumber ? `${omega}x` : `${omega}*x`;
            let phase = "";
            if (sym.phi) {
                phase = `+${sym.phi}`; // 字母自带正负号，不再按当前值的正负挑加号还是减号
            } else if (v.phi !== 0) {
                phase = v.phi < 0 ? `-${piText(-v.phi)}` : `+${piText(v.phi)}`;
            }
            // 振幅与 sin 之间那个 * 不能省：连写的 "Asin" 会被读成反三角函数 asin
            const amplitude = sym.A ? `${sym.A}*` : coefficientText(v.A);
            return `y=${amplitude}sin(${omegaPart}${phase})`;
        },
        // 勾选后坐标轴刻度、悬停读数、与两轴的交点都改用 π 表示（数学书上的弧度制写法）
        extras: () => [{ key: "radianTicks", label: "坐标轴与交点用弧度制（π）表示", value: false }],
        describe: (mode, v, extras) => {
            if (!extras.radianTicks) {
                return null;
            }
            const omega = mode === "period" ? (2 * Math.PI) / v.T : v.w;
            return { radian: true, sine: { amplitude: v.A, omega, phi: v.phi || 0 } };
        },
    },
};

/* =========================================================================
 * 二、绘图面板
 * ========================================================================= */

const PALETTE = ["#714B67", "#2C8397", "#E0A100", "#F06050", "#28B08A", "#5B8FF9", "#875A7B", "#D6145F"];
const DEFAULT_HALF_WIDTH = 10;
// 新滑块的默认区间与步长：区间跟 Desmos 一样取 -10~10，步长取 0.1（拖出来是 2、2.1 这种能给全班念的数）
const DEFAULT_SLIDER_HALF = 10;
const DEFAULT_SLIDER_STEP = 0.1;

function niceStep(range, targetCount) {
    const raw = range / Math.max(1, targetCount);
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const normalized = raw / magnitude;
    const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return multiplier * magnitude;
}

function formatNumber(value) {
    if (!Number.isFinite(value)) {
        return "—";
    }
    const magnitude = Math.abs(value);
    if (magnitude !== 0 && (magnitude >= 1e5 || magnitude < 1e-4)) {
        return value.toExponential(2);
    }
    return String(Number(value.toFixed(4)));
}

function formatTick(value, step) {
    const decimals = Math.max(0, Math.min(6, -Math.floor(Math.log10(step))));
    const text = value.toFixed(decimals);
    return text === "-0" ? "0" : text;
}

// 弧度制下的刻度间隔：只在 π 的有理分数里挑（π/12、π/6、π/4、π/3、π/2、π、2π…），
// 这样落点一定是 π 的整数倍或简单分数，标签才写得成 π/2、3π/2 这种课本样子。
function piStep(range, targetCount) {
    const fractions = [
        1 / 12, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64,
    ];
    const raw = range / Math.max(1, targetCount);
    for (const fraction of fractions) {
        if (Math.PI * fraction >= raw) {
            return Math.PI * fraction;
        }
    }
    return Math.PI * 64;
}

// 数值写成 π 形式（π/2、3π/2、−π、0）；不是 π 的简单倍数时退回小数
function piTick(value) {
    if (!Number.isFinite(value)) {
        return "—";
    }
    if (Math.abs(value) < 1e-9) {
        return "0";
    }
    return piText(value).replace(/pi/g, "π").replace(/-/g, "−");
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// 把"给解析器看的"方程渲染成教师读得懂的写法：
// (y-(1))^2=4(x-(1)) → (y-1)²=4(x-1)、x^2/5 → x²/5、2sin(pi/2*x) → 2sin(π/2·x)
// 先转义再替换，注入的只有 <sup> 这类固定标签，用户输入不会被当 HTML 解析。
function prettyEquation(text) {
    let out = escapeHtml(text);
    out = out.replace(/\((x|y)-\((-?[0-9.]+)\)\)/g, (match, axis, number) => {
        const value = Number(number);
        return value < 0 ? `(${axis}+${Math.abs(value)})` : `(${axis}-${number})`;
    });
    out = out.replace(/\+\(0\)/g, "");
    out = out.replace(/\+\((-?[0-9.]+)\)/g, "+$1");
    out = out.replace(/\+-([0-9.]+)/g, "-$1");
    out = out.replace(/\^\((-?[0-9.]+)\)/g, "<sup>$1</sup>");
    out = out.replace(/\^(-?[0-9.]+)/g, "<sup>$1</sup>");
    out = out.replace(/pi/g, "π");
    out = out.replace(/log\(/g, "lg(");
    out = out.replace(/sqrt\(/g, "√(");
    out = out.replace(/\*/g, "·");
    // 字母相邻时省掉点号：π·x → πx。两种情况必须保留点号：
    // ① 2π/T·x 这种分母位（点号左边是斜杠），省掉就被读成"分母里带着 x"；
    // ② A·sin 后面紧跟函数名，省掉就成了反三角函数 asin。
    out = out.replace(
        /(^|[^/])([a-zA-Zπ])·(?!(?:asin|acos|atan|sqrt|sin|cos|tan|abs|exp|log|ln)\b)([a-zA-Z])/g,
        "$1$2$3"
    );
    return out;
}

// 图例里挂在曲线后面的小标签（离心率、渐近线这类附带信息）
function infoBadge(text, title) {
    const badge = document.createElement("span");
    badge.className = "badge bg-light text-dark border fw-normal";
    badge.textContent = text;
    badge.title = title;
    return badge;
}

class PlotSurface {
    constructor(root) {
        this.root = root;
        this.stage = root.querySelector(".tutoring_plot_stage");
        this.mainCanvas = root.querySelector("[data-plot-main]");
        this.overlayCanvas = root.querySelector("[data-plot-overlay]");
        this.readout = root.querySelector("[data-plot-readout]");
        this.mainCtx = this.mainCanvas.getContext("2d");
        this.overlayCtx = this.overlayCanvas.getContext("2d");
        this.legend = root.querySelector("[data-plot-legend]");
        this.sliderBar = root.querySelector("[data-plot-sliders]");
        this.errorBox = root.querySelector("[data-plot-error]");
        this.input = root.querySelector("[data-plot-input]");
        this.curves = [];
        // 选中哪条曲线，滑块条就只摆哪条的参数：参数是每条曲线自己的，不跨曲线共用
        this.selected = null;
        this.sliderEls = new Map();
        this.view = { cx: 0, cy: 0, hw: DEFAULT_HALF_WIDTH };
        this.hover = null;
        this.drag = null;
        this.frame = null;
        this.coarse = false;
        this.width = 0;
        this.height = 0;
        this.scale = 1;
    }

    /* ------------------------------ 视图与坐标 ------------------------------ */

    get xmin() {
        return this.view.cx - this.view.hw;
    }

    get xmax() {
        return this.view.cx + this.view.hw;
    }

    get ymin() {
        return this.view.cy - this.halfHeight();
    }

    get ymax() {
        return this.view.cy + this.halfHeight();
    }

    halfHeight() {
        return (this.view.hw * this.height) / Math.max(1, this.width);
    }

    toPixelX(x) {
        return (x - this.xmin) * this.scale;
    }

    toPixelY(y) {
        return (this.ymax - y) * this.scale;
    }

    toDataX(pixelX) {
        return this.xmin + pixelX / this.scale;
    }

    toDataY(pixelY) {
        return this.ymax - pixelY / this.scale;
    }

    resetView() {
        this.view = { cx: 0, cy: 0, hw: DEFAULT_HALF_WIDTH };
        this.drawMain();
    }

    resize() {
        const rect = this.stage.getBoundingClientRect();
        this.width = Math.max(1, Math.round(rect.width));
        this.height = Math.max(1, Math.round(rect.height));
        const ratio = window.devicePixelRatio || 1;
        for (const canvas of [this.mainCanvas, this.overlayCanvas]) {
            canvas.width = Math.round(this.width * ratio);
            canvas.height = Math.round(this.height * ratio);
            canvas.style.width = `${this.width}px`;
            canvas.style.height = `${this.height}px`;
        }
        for (const context of [this.mainCtx, this.overlayCtx]) {
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
        }
        this.updateScale();
        this.drawMain();
    }

    // 两个方向共用同一比例，圆才是正圆、椭圆才不变形
    updateScale() {
        this.scale = this.width / (2 * this.view.hw);
    }

    /* -------------------------------- 曲线管理 ------------------------------- */

    // meta 是"这条曲线的附带信息"：椭圆的离心率、双曲线勾选的渐近线
    addCurve(expression, meta = null) {
        // 先按默认参数编译一次：语法不过就别进列表。智能画图带回来的初值只播种
        // 这条式子里真出现的字母，别的键（以及 label 以外的杂项）不进图例。
        const preview = buildModel(expression, {});
        const params = new Map();
        const seed = meta && meta.params && typeof meta.params === "object" ? meta.params : null;
        if (seed) {
            for (const name of preview.used) {
                const value = Number(seed[name]);
                if (Number.isFinite(value)) {
                    ensureParam(params, name, { value, label: "智能画图" });
                }
            }
        }
        let display = meta;
        if (
            meta &&
            (Object.prototype.hasOwnProperty.call(meta, "params") ||
                Object.prototype.hasOwnProperty.call(meta, "label"))
        ) {
            display = { ...meta };
            delete display.params;
            if (typeof display.label === "string") {
                const label = display.label.trim().slice(0, 16);
                display.label = label && !/[<>]/.test(label) ? label : undefined;
            } else {
                delete display.label;
            }
            if (!display.label) {
                delete display.label;
            }
            if (!Object.keys(display).length) {
                display = null;
            }
        }
        this.pushCurve({ expression, typed: null, meta: display, params });
    }

    // 按类型添加：把"当初填的那份数"一起存下，滑块一动就用同一套 compose 重出附带信息。
    // 方程本身带的是字母（y²=mx、x²/a²+y²/b²=1），所以拖滑块时图例那行不会跳数字。
    addTypedCurve(typed) {
        const spec = CURVE_TYPES[typed.typeKey];
        const sym = sliderTexts(spec, typed.mode, typed.sliderKeys);
        const curve = {
            expression: spec.compose(typed.mode, typed.fixed, sym),
            typed,
            meta: null,
            params: new Map(),
        };
        for (const field of spec.fields(typed.mode)) {
            if (field.sym && typed.sliderKeys.includes(field.key)) {
                ensureParam(curve.params, field.sym, {
                    value: sliderValueOf(field, typed.fixed[field.key]),
                    range: field.range,
                    label: field.label,
                });
            }
        }
        this.pushCurve(curve);
    }

    pushCurve(curve) {
        curve.color = PALETTE[this.curves.length % PALETTE.length];
        curve.visible = true;
        this.curves.push(curve);
        this.selected = curve; // 新加的这条就是当前选中的，滑块条跟着它摆
        this.rebuildCurve(curve);
        this.renderLegend();
        this.renderSliders();
        this.syncError();
        this.drawMain();
        this.drawOverlay();
    }

    // 按这条曲线自己的滑块值重建模型与附带信息；拖进非法区间只坏这一条，其它曲线照画
    rebuildCurve(curve) {
        curve.error = null;
        try {
            if (curve.typed) {
                const { typeKey, mode, fixed, extras, sliderKeys } = curve.typed;
                const spec = CURVE_TYPES[typeKey];
                const values = { ...fixed };
                for (const field of spec.fields(mode)) {
                    if (!field.sym || !sliderKeys.includes(field.key)) {
                        continue;
                    }
                    const param = curve.params.get(field.sym);
                    if (param) {
                        values[field.key] = fieldValueOf(field, param.value);
                    }
                }
                spec.compose(mode, values, sliderTexts(spec, mode, sliderKeys)); // 只为校验，方程文字用 curve.expression
                curve.meta = spec.describe ? spec.describe(mode, values, extras) : null;
            }
            curve.model = buildModel(curve.expression, paramValues(curve.params));
            // 自己写的方程里冒出来的字母，在这条曲线名下长一个滑块；别的曲线用同一个字母互不相干
            for (const name of curve.model.used) {
                ensureParam(curve.params, name, { label: "自己写的方程" });
            }
        } catch (error) {
            curve.error = error.message;
            curve.model = null;
        }
    }

    // 参数只属于那一条曲线，所以拖动时只重建它自己
    refreshCurve(curve, coarse = false) {
        this.rebuildCurve(curve);
        this.renderLegend();
        this.syncSliders();
        this.syncError();
        this.scheduleDraw(coarse);
        this.drawOverlay();
    }

    removeCurve(index) {
        const removed = this.curves.splice(index, 1)[0];
        if (this.selected === removed) {
            this.selected = this.curves[this.curves.length - 1] || null;
        }
        this.renderLegend();
        this.renderSliders();
        this.syncError();
        this.drawMain();
        this.drawOverlay();
    }

    // 选中哪条，滑块条就摆哪条的参数
    selectCurve(curve) {
        if (!curve || this.selected === curve) {
            return;
        }
        this.selected = curve;
        this.renderLegend();
        this.renderSliders();
        this.drawMain();
    }

    clearCurves() {
        this.curves = [];
        this.selected = null;
        this.sliderEls.clear();
        this.renderLegend();
        this.renderSliders();
        this.clearError();
        this.drawMain();
        this.drawOverlay();
    }

    /* -------------------------------- 滑块参数 ------------------------------- */

    setParam(name, value, coarse = false) {
        const curve = this.selected;
        const param = curve ? curve.params.get(name) : null;
        if (!param || !Number.isFinite(value) || param.value === value) {
            return;
        }
        param.value = value;
        // 越界就撑开区间，别把值夹回去——数值框里填 40 不该只到 10
        if (value < param.min) {
            param.min = value;
        }
        if (value > param.max) {
            param.max = value;
        }
        this.refreshCurve(curve, coarse);
    }

    showError(message) {
        this.errorBox.textContent = message;
        this.errorBox.classList.remove("d-none");
    }

    clearError() {
        this.errorBox.classList.add("d-none");
    }

    renderLegend() {
        this.legend.textContent = "";
        this.curves.forEach((curve, index) => {
            const selected = curve === this.selected;
            const wrap = document.createElement("span");
            wrap.className = "tutoring_plot_legend_item d-inline-flex align-items-center gap-1 border rounded px-2 py-1 small";
            wrap.title = "点这一行：下面的滑块条换成这条曲线的参数";
            if (selected) {
                wrap.classList.add("tutoring_plot_legend_item_selected", "border-primary");
            }
            // 图例行本身要能点，但"隐藏/删除"两个按钮得自己收 click
            wrap.addEventListener("click", (event) => {
                if (!event.target.closest("button")) {
                    this.selectCurve(curve);
                }
            });

            const swatch = document.createElement("span");
            swatch.style.cssText = `display:inline-block;width:12px;height:12px;border-radius:3px;background:${curve.color}`;
            if (!curve.visible) {
                swatch.style.opacity = "0.3";
            }
            wrap.appendChild(swatch);

            // 方程那一行做成真按钮：鼠标点、Tab 聚焦回车都能选中，纯文本节点键盘够不着
            const label = document.createElement("button");
            label.type = "button";
            label.className = "btn btn-link p-0 text-decoration-none tutoring_plot_legend_pick";
            label.innerHTML = prettyEquation(curve.expression);
            label.title = "点这一行：下面的滑块条换成这条曲线的参数";
            label.style.opacity = curve.visible ? "1" : "0.45";
            if (curve.visible) {
                label.classList.add("fw-semibold");
            }
            label.addEventListener("click", () => this.selectCurve(curve));
            wrap.appendChild(label);

            const info = curve.meta || {};
            if (info.label) {
                wrap.appendChild(infoBadge(info.label, "智能画图给出的名称"));
            }
            if (curve.error) {
                wrap.appendChild(infoBadge("这个值画不出来", curve.error));
            }
            if (info.radian) {
                wrap.appendChild(infoBadge("弧度制 π", "坐标轴刻度、读数与交点都用 π 表示"));
            }
            if (info.eccentricity) {
                wrap.appendChild(infoBadge(`e = ${info.eccentricity.text}`, "离心率 e = c/a"));
            }
            if (info.asymptotes && info.asymptotes.length) {
                const detail = info.asymptotes
                    .map((line) => `${line.text}　（斜截式 ${line.slopeIntercept}）`)
                    .join("\n");
                wrap.appendChild(
                    infoBadge(
                        `渐近线 ${asymptoteSummaryText(info.asymptotes)}`,
                        `${detail}\n虚线是这条双曲线的两条渐近线`
                    )
                );
            }

            // 没选中也要看得出这条线身上有几个旋钮，否则参数藏在点一下之后
            if (curve.params.size && !selected) {
                const letters = [...curve.params.keys()].join("、");
                wrap.appendChild(infoBadge(`${curve.params.size} 个参数`, `点这一行调 ${letters}`));
            }

            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "btn btn-link btn-sm p-0 ms-1 text-decoration-none";
            toggle.textContent = curve.visible ? "隐藏" : "显示";
            toggle.addEventListener("click", () => {
                curve.visible = !curve.visible;
                this.renderLegend();
                this.drawMain();
                this.drawOverlay();
            });
            wrap.appendChild(toggle);

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "btn btn-link btn-sm p-0 ms-1 text-decoration-none text-danger";
            remove.textContent = "删除";
            remove.addEventListener("click", () => this.removeCurve(index));
            wrap.appendChild(remove);

            this.legend.appendChild(wrap);
        });
    }

    /* --------------------------------- 滑块条 --------------------------------- */

    syncError() {
        const broken = this.curves.filter((curve) => curve.error);
        if (!broken.length) {
            this.clearError();
            return;
        }
        const first = broken[0];
        const prefix = broken.length > 1 ? `${broken.length} 条曲线画不出来，第一条：` : "";
        this.showError(`${prefix}${first.expression}：${first.error}`);
    }

    // 只摆当前选中那条曲线的参数；一条曲线都没有、或选中的那条没参数，整条收起
    renderSliders() {
        this.sliderBar.textContent = "";
        this.sliderEls.clear();
        const params = this.selected ? this.selected.params : null;
        if (!params || !params.size) {
            this.sliderBar.classList.add("d-none");
            return;
        }
        this.sliderBar.classList.remove("d-none");
        const caption = document.createElement("span");
        caption.className = "text-muted small align-self-center";
        caption.textContent = `「${this.selected.expression}」的参数`;
        caption.title = "点图例里的其它曲线，这一条就换成那一条的参数";
        this.sliderBar.appendChild(caption);
        for (const [name, param] of params) {
            this.sliderBar.appendChild(this.buildSlider(name, param));
        }
    }

    // 一个字母一格：字母名 + 拖动条 + 数值框 + 区间设置
    buildSlider(name, param) {
        const wrap = document.createElement("div");
        wrap.className = "tutoring_plot_slider d-inline-flex flex-column";

        const row = document.createElement("div");
        row.className = "d-flex align-items-center gap-2";

        const sym = document.createElement("span");
        sym.className = "tutoring_plot_slider_sym";
        sym.textContent = name;
        sym.title = param.label;
        row.appendChild(sym);

        const range = document.createElement("input");
        range.type = "range";
        range.className = "form-range";
        range.setAttribute("aria-label", `滑块 ${name}`);
        // 拖动过程中按粗采样重画（松手再补一次细的），与滚轮缩放同一套节流
        range.addEventListener("input", () => this.setParam(name, Number(range.value), true));
        range.addEventListener("change", () => {
            this.setParam(name, Number(range.value));
            // 停在原位时 setParam 会提前返回，这里无条件补一次细描，否则隐式曲线会一直停在粗采样
            this.scheduleDraw(false);
        });
        row.appendChild(range);

        const value = document.createElement("input");
        value.type = "text";
        value.inputMode = "decimal";
        value.autocomplete = "off";
        value.className = "form-control form-control-sm tutoring_plot_slider_value";
        value.title = "可以直接填 3/2、2pi、sqrt(5) 这种算式";
        value.addEventListener("change", () => this.commitSliderValue(name, value));
        row.appendChild(value);

        const gear = document.createElement("button");
        gear.type = "button";
        gear.className = "btn btn-sm btn-link text-muted p-0 tutoring_plot_slider_gear";
        gear.title = "设置区间与步长";
        gear.innerHTML = '<i class="fa fa-sliders" role="img"></i>';
        row.appendChild(gear);
        wrap.appendChild(row);

        const cfg = document.createElement("div");
        cfg.className = "tutoring_plot_slider_cfg d-none align-items-center gap-1 small text-muted";
        const inputs = {};
        for (const [key, label] of [["min", "从"], ["step", "步进"], ["max", "到"]]) {
            const caption = document.createElement("span");
            caption.textContent = label;
            const box = document.createElement("input");
            box.type = "text";
            box.className = "form-control form-control-sm";
            box.addEventListener("change", () => this.commitSliderConfig(name, key, box));
            cfg.appendChild(caption);
            cfg.appendChild(box);
            inputs[key] = box;
        }
        gear.addEventListener("click", () => {
            const open = cfg.classList.contains("d-none");
            cfg.classList.toggle("d-none", !open);
            cfg.classList.toggle("d-flex", open);
        });
        wrap.appendChild(cfg);

        this.sliderEls.set(name, { range, value, inputs });
        this.syncSlider(name, param);
        return wrap;
    }

    syncSliders() {
        if (!this.selected) {
            return;
        }
        for (const [name, param] of this.selected.params) {
            this.syncSlider(name, param);
        }
    }

    // 就地改属性，不重建 DOM：拖动时重建会把正在拖的那根 range 一起换掉
    syncSlider(name, param) {
        const els = this.sliderEls.get(name);
        if (!els) {
            return;
        }
        els.range.min = param.min;
        els.range.max = param.max;
        els.range.step = param.step;
        els.range.value = param.value;
        const texts = {
            value: formatNumber(param.value),
            min: formatNumber(param.min),
            max: formatNumber(param.max),
            step: formatNumber(param.step),
        };
        if (document.activeElement !== els.value) {
            els.value.value = texts.value;
        }
        for (const [key, box] of Object.entries(els.inputs)) {
            if (document.activeElement !== box) {
                box.value = texts[key];
            }
        }
    }

    commitSliderValue(name, box) {
        const param = this.selected.params.get(name);
        try {
            this.setParam(name, evalConstant(box.value));
            box.classList.remove("is-invalid");
            box.title = "可以直接填 3/2、2pi、sqrt(5) 这种算式";
            // 刚填的是算式就把得数写回去：不然屏幕上留着的还是 "pi/2"，看不出到底生效了哪个数
            box.value = formatNumber(param.value);
        } catch (error) {
            box.classList.add("is-invalid");
            box.title = error.message;
            box.value = formatNumber(param.value); // 填不进就回弹到当前值，别留一个看着像生效了的数
        }
    }

    // 区间与步长：步进接受 pi/4 这类写法，讲三角函数时按 π 的分数一格一格走
    commitSliderConfig(name, key, box) {
        const param = this.selected.params.get(name);
        let parsed;
        try {
            parsed = evalConstant(box.value);
        } catch {
            box.value = formatNumber(param[key]);
            return;
        }
        if (key === "step" ? parsed > 0 : key === "min" ? parsed < param.max : parsed > param.min) {
            param[key] = parsed;
        }
        // 区间挪了要把当前值夹回来，否则数值框与拖动条的指示位置会不一致
        param.value = Math.min(param.max, Math.max(param.min, param.value));
        this.refreshCurve(this.selected);
    }

    /* --------------------------------- 绘制 --------------------------------- */

    scheduleDraw(coarse) {
        this.coarse = coarse;
        if (this.frame) {
            return;
        }
        this.frame = window.requestAnimationFrame(() => {
            this.frame = null;
            this.updateScale();
            this.drawMain(this.coarse);
        });
    }

    drawMain(coarse = false) {
        const context = this.mainCtx;
        this.updateScale();
        context.clearRect(0, 0, this.width, this.height);
        this.drawGrid(context);
        for (const curve of this.curves) {
            if (!curve.visible || !curve.model) {
                continue;
            }
            context.strokeStyle = curve.color;
            // 选中的那条粗一点：滑块条只摆它的参数，画布上得能一眼认出是哪条
            context.lineWidth = curve === this.selected ? 3 : 2;
            context.lineJoin = "round";
            context.lineCap = "round";
            // 渐近线先画（在曲线下面），再画曲线本身
            this.strokeAsymptotes(context, curve);
            if (curve.model.kind === "explicit") {
                this.strokeExplicit(context, curve.model.explicit);
            } else if (curve.model.kind === "implicit") {
                this.strokeImplicit(context, curve.model.F, coarse);
            } else {
                this.strokeVertical(context, curve.model.F);
            }
        }
        // 交点最后画，压在曲线上面
        for (const curve of this.curves) {
            if (curve.visible && curve.meta?.radian && curve.meta.sine) {
                this.drawIntercepts(context, curve);
            }
        }
    }

    // 只要有任意一条可见曲线开了弧度制，坐标轴就改用 π 刻度（轴是整块画布共用的一把尺子）
    radianTicks() {
        return this.curves.some((curve) => curve.visible && curve.meta?.radian);
    }

    drawGrid(context) {
        const radian = this.radianTicks();
        // 弧度制下横竖两轴各按自己的跨度挑 π 步长（y 方向通常短得多，用同一个步长会让刻度只剩两三条）
        const stepY = radian ? piStep(this.ymax - this.ymin, 8) : niceStep(2 * this.view.hw, 12);
        const stepX = radian ? piStep(this.xmax - this.xmin, 14) : stepY;
        const tickX = (value) => (radian ? piTick(value) : formatTick(value, stepX));
        const tickY = (value) => (radian ? piTick(value) : formatTick(value, stepY));
        const firstX = Math.ceil(this.xmin / stepX) * stepX;
        const firstY = Math.ceil(this.ymin / stepY) * stepY;
        const columns = Math.floor((this.xmax - firstX) / stepX) + 1;
        const rows = Math.floor((this.ymax - firstY) / stepY) + 1;

        context.lineWidth = 1;
        context.strokeStyle = "#e7e7ec";
        context.beginPath();
        for (let index = 0; index < columns; index++) {
            const pixelX = Math.round(this.toPixelX(firstX + index * stepX)) + 0.5;
            context.moveTo(pixelX, 0);
            context.lineTo(pixelX, this.height);
        }
        for (let index = 0; index < rows; index++) {
            const pixelY = Math.round(this.toPixelY(firstY + index * stepY)) + 0.5;
            context.moveTo(0, pixelY);
            context.lineTo(this.width, pixelY);
        }
        context.stroke();

        const axisX = Math.round(this.toPixelX(0)) + 0.5;
        const axisY = Math.round(this.toPixelY(0)) + 0.5;
        const showAxisX = this.ymin <= 0 && this.ymax >= 0;
        const showAxisY = this.xmin <= 0 && this.xmax >= 0;
        context.strokeStyle = "#9aa0a6";
        context.beginPath();
        if (showAxisX) {
            context.moveTo(0, axisY);
            context.lineTo(this.width, axisY);
        }
        if (showAxisY) {
            context.moveTo(axisX, 0);
            context.lineTo(axisX, this.height);
        }
        context.stroke();

        context.fillStyle = "#6b7280";
        context.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
        context.textAlign = "center";
        context.textBaseline = "top";
        const labelY = Math.min(showAxisX ? axisY + 4 : this.height - 16, this.height - 14);
        for (let index = 0; index < columns; index++) {
            const value = firstX + index * stepX;
            if (Math.abs(value) < stepX / 1000) {
                continue;
            }
            context.fillText(
                tickX(value),
                Math.min(Math.max(this.toPixelX(value), 14), this.width - 14),
                labelY
            );
        }
        context.textAlign = "right";
        context.textBaseline = "middle";
        for (let index = 0; index < rows; index++) {
            const value = firstY + index * stepY;
            if (Math.abs(value) < stepY / 1000) {
                continue;
            }
            const labelX = showAxisY ? axisX - 6 : this.width - 6;
            context.fillText(tickY(value), Math.max(16, labelX), this.toPixelY(value));
        }
    }

    // 弧度制下把三角函数与两轴的交点标出来：与 x 轴是 ωx+φ=nπ（零点），与 y 轴是 x=0 处
    drawIntercepts(context, curve) {
        const { amplitude, omega, phi } = curve.meta.sine;
        if (!Number.isFinite(omega) || Math.abs(omega) < 1e-12) {
            return;
        }
        const marks = [];
        const nFrom = Math.ceil((omega * this.xmin + phi) / Math.PI);
        const nTo = Math.floor((omega * this.xmax + phi) / Math.PI);
        for (let n = nFrom; n <= nTo && marks.length < 16; n++) {
            marks.push({ x: (n * Math.PI - phi) / omega, y: 0, text: `(${piTick((n * Math.PI - phi) / omega)}, 0)` });
        }
        const yAtZero = amplitude * Math.sin(phi);
        if (
            Math.abs(yAtZero) > 1e-12 &&
            this.xmin <= 0 &&
            this.xmax >= 0 &&
            yAtZero >= this.ymin &&
            yAtZero <= this.ymax
        ) {
            marks.push({ x: 0, y: yAtZero, text: `(0, ${piTick(yAtZero)})` });
        }

        context.save();
        context.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
        context.textBaseline = "middle";
        let lastLabelX = -Infinity; // ω 很大时零点密集，标签挤在一起就只画点不写字
        for (const mark of marks) {
            const pixelX = this.toPixelX(mark.x);
            const pixelY = this.toPixelY(mark.y);
            context.fillStyle = curve.color;
            context.beginPath();
            context.arc(pixelX, pixelY, 3.5, 0, Math.PI * 2);
            context.fill();
            if (Math.abs(pixelX - lastLabelX) < 58) {
                continue;
            }
            lastLabelX = pixelX;
            const atRight = pixelX > this.width - 110;
            context.textAlign = atRight ? "right" : "left";
            const labelX = Math.min(Math.max(pixelX + (atRight ? -7 : 7), 6), this.width - 6);
            const labelY = Math.min(Math.max(pixelY - 10, 14), this.height - 8);
            context.lineWidth = 3;
            context.strokeStyle = "#ffffff";
            context.strokeText(mark.text, labelX, labelY); // 白描边压住网格线与曲线
            context.fillStyle = curve.color;
            context.fillText(mark.text, labelX, labelY);
        }
        context.restore();
    }

    // 渐近线：过中心的两条虚线，只画视口内的一段（斜率大时不让坐标爆到画布外）
    strokeAsymptotes(context, curve) {
        const lines = curve.meta?.asymptotes || [];
        if (!lines.length) {
            return;
        }
        context.save();
        context.setLineDash([7, 5]);
        context.globalAlpha = 0.55;
        context.strokeStyle = curve.color;
        context.lineWidth = 1.5;
        context.beginPath();
        for (const { h, k, slope } of lines) {
            const segment = this.clipLineToView(h, k, 1, slope);
            if (!segment) {
                continue;
            }
            context.moveTo(this.toPixelX(segment[0][0]), this.toPixelY(segment[0][1]));
            context.lineTo(this.toPixelX(segment[1][0]), this.toPixelY(segment[1][1]));
        }
        context.stroke();
        // 顺手把方程标在虚线旁边：取视口内那段 72% 处，靠右边界时改成右对齐
        context.setLineDash([]);
        context.globalAlpha = 0.9;
        context.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
        context.textBaseline = "middle";
        for (const line of lines) {
            const segment = this.clipLineToView(line.h, line.k, 1, line.slope);
            if (!segment) {
                continue;
            }
            const x = segment[0][0] + (segment[1][0] - segment[0][0]) * 0.72;
            const y = segment[0][1] + (segment[1][1] - segment[0][1]) * 0.72;
            const pixelX = this.toPixelX(x);
            const pixelY = this.toPixelY(y);
            const atRight = pixelX > this.width - 130;
            context.textAlign = atRight ? "right" : "left";
            const labelX = Math.min(Math.max(pixelX + (atRight ? -8 : 8), 6), this.width - 6);
            const labelY = Math.min(Math.max(pixelY - 9, 14), this.height - 8);
            context.lineWidth = 3;
            context.strokeStyle = "#ffffff";
            context.strokeText(line.text, labelX, labelY); // 白描边压住网格线，保证读得清
            context.fillStyle = curve.color;
            context.fillText(line.text, labelX, labelY);
        }
        context.restore();
    }

    // 参数式直线 (x0,y0)+t·(dx,dy) 与当前视口矩形的交段，不相交返回 null
    clipLineToView(x0, y0, dx, dy) {
        let tStart = -Infinity;
        let tEnd = Infinity;
        const slabs = [
            [this.xmin, this.xmax, x0, dx],
            [this.ymin, this.ymax, y0, dy],
        ];
        for (const [min, max, start, delta] of slabs) {
            if (Math.abs(delta) < 1e-12) {
                if (start < min || start > max) {
                    return null;
                }
                continue;
            }
            const first = (min - start) / delta;
            const second = (max - start) / delta;
            tStart = Math.max(tStart, Math.min(first, second));
            tEnd = Math.min(tEnd, Math.max(first, second));
        }
        if (!(tStart < tEnd)) {
            return null;
        }
        return [
            [x0 + dx * tStart, y0 + dy * tStart],
            [x0 + dx * tEnd, y0 + dy * tEnd],
        ];
    }

    strokeExplicit(context, explicit) {
        const total = Math.min(6000, Math.max(600, Math.round(this.width * 2)));
        const span = this.xmax - this.xmin;
        const jumpLimit = this.height * 2;
        context.beginPath();
        let drawing = false;
        let previousPixelY = 0;
        for (let index = 0; index <= total; index++) {
            const x = this.xmin + (span * index) / total;
            const y = explicit(x);
            if (!Number.isFinite(y)) {
                drawing = false;
                continue;
            }
            const pixelY = this.toPixelY(y);
            if (!Number.isFinite(pixelY) || Math.abs(pixelY) > this.height * 50) {
                drawing = false;
                continue;
            }
            if (drawing && Math.abs(pixelY - previousPixelY) > jumpLimit) {
                drawing = false; // 断点：tan、1/x 等
            }
            const pixelX = this.toPixelX(x);
            if (drawing) {
                context.lineTo(pixelX, pixelY);
            } else {
                context.moveTo(pixelX, pixelY);
                drawing = true;
            }
            previousPixelY = pixelY;
        }
        context.stroke();
    }

    // 隐式方程用 marching squares 在网格上取 F(x,y)=0 的等值线
    strokeImplicit(context, F, coarse) {
        const cell = coarse ? 12 : 3;
        const cols = Math.ceil(this.width / cell) + 1;
        const rows = Math.ceil(this.height / cell) + 1;
        const values = new Float64Array(cols * rows);
        for (let row = 0; row < rows; row++) {
            const y = this.toDataY(row * cell);
            for (let col = 0; col < cols; col++) {
                values[row * cols + col] = F(this.toDataX(col * cell), y);
            }
        }

        const crosses = (a, b) =>
            Number.isFinite(a) && Number.isFinite(b) && (a < 0) !== (b < 0);
        const ratio = (a, b) => (Math.abs(a) + Math.abs(b) === 0 ? 0 : a / (a - b));

        context.beginPath();
        for (let row = 0; row < rows - 1; row++) {
            const pixelY0 = row * cell;
            const pixelY1 = (row + 1) * cell;
            for (let col = 0; col < cols - 1; col++) {
                const pixelX0 = col * cell;
                const pixelX1 = (col + 1) * cell;
                const v00 = values[row * cols + col];
                const v10 = values[row * cols + col + 1];
                const v11 = values[(row + 1) * cols + col + 1];
                const v01 = values[(row + 1) * cols + col];

                const points = [];
                if (crosses(v00, v10)) {
                    points.push([pixelX0 + (pixelX1 - pixelX0) * ratio(v00, v10), pixelY0]);
                }
                if (crosses(v10, v11)) {
                    points.push([pixelX1, pixelY0 + (pixelY1 - pixelY0) * ratio(v10, v11)]);
                }
                if (crosses(v01, v11)) {
                    points.push([pixelX0 + (pixelX1 - pixelX0) * ratio(v01, v11), pixelY1]);
                }
                if (crosses(v00, v01)) {
                    points.push([pixelX0, pixelY0 + (pixelY1 - pixelY0) * ratio(v00, v01)]);
                }

                if (points.length === 2) {
                    context.moveTo(points[0][0], points[0][1]);
                    context.lineTo(points[1][0], points[1][1]);
                } else if (points.length === 4) {
                    // 鞍点：按中心值决定连接方式，避免线段交叉
                    const center = F((pixelX0 + pixelX1) / 2, (pixelY0 + pixelY1) / 2);
                    const pairs = center > 0 === v00 > 0 ? [[0, 1], [2, 3]] : [[0, 3], [1, 2]];
                    for (const [from, to] of pairs) {
                        context.moveTo(points[from][0], points[from][1]);
                        context.lineTo(points[to][0], points[to][1]);
                    }
                }
            }
        }
        context.stroke();
    }

    // F 只含 x（如 x=2、x^2-4=0）：按像素列扫描找零点，画竖直线
    strokeVertical(context, F) {
        let previousValue = null;
        let previousPixelX = 0;
        for (let pixelX = 0; pixelX <= this.width; pixelX++) {
            const value = F(this.toDataX(pixelX), 0);
            if (
                previousValue !== null &&
                Number.isFinite(previousValue) &&
                Number.isFinite(value) &&
                (previousValue < 0) !== (value < 0)
            ) {
                const ratio = previousValue / (previousValue - value);
                const rootPixelX = Math.round(previousPixelX + (pixelX - previousPixelX) * ratio) + 0.5;
                context.beginPath();
                context.moveTo(rootPixelX, 0);
                context.lineTo(rootPixelX, this.height);
                context.stroke();
            }
            previousValue = value;
            previousPixelX = pixelX;
        }
    }

    drawOverlay() {
        const context = this.overlayCtx;
        context.clearRect(0, 0, this.width, this.height);
        if (!this.hover || this.drag) {
            return;
        }
        const { pixelX, pixelY } = this.hover;
        const dataX = this.toDataX(pixelX);
        const dataY = this.toDataY(pixelY);

        context.save();
        context.setLineDash([4, 4]);
        context.strokeStyle = "#9aa0a6";
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(pixelX + 0.5, 0);
        context.lineTo(pixelX + 0.5, this.height);
        context.moveTo(0, pixelY + 0.5);
        context.lineTo(this.width, pixelY + 0.5);
        context.stroke();
        context.restore();

        for (const curve of this.curves) {
            if (!curve.visible || !curve.model || curve.model.kind !== "explicit") {
                continue;
            }
            const y = curve.model.explicit(dataX);
            if (!Number.isFinite(y)) {
                continue;
            }
            const markerY = this.toPixelY(y);
            if (markerY < 0 || markerY > this.height) {
                continue;
            }
            context.fillStyle = curve.color;
            context.beginPath();
            context.arc(this.toPixelX(dataX), markerY, 3.5, 0, Math.PI * 2);
            context.fill();
        }

        const radian = this.radianTicks();
        const text = (value) => (radian ? piTick(value) : formatNumber(value));
        const label = `(${text(dataX)}, ${text(dataY)})`;
        context.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
        const textWidth = context.measureText(label).width;
        const boxX = pixelX + textWidth + 20 > this.width ? pixelX - textWidth - 12 : pixelX + 8;
        const boxY = pixelY < 24 ? pixelY + 8 : pixelY - 20;
        context.fillStyle = "#ffffff";
        context.strokeStyle = "#d0d0d8";
        context.lineWidth = 1;
        context.fillRect(boxX, boxY, textWidth + 10, 18);
        context.strokeRect(boxX, boxY, textWidth + 10, 18);
        context.fillStyle = "#374151";
        context.textAlign = "left";
        context.textBaseline = "middle";
        context.fillText(label, boxX + 5, boxY + 9);
    }
}

/* =========================================================================
 * 三、页面交互
 * ========================================================================= */

// 页面只接受「未配置 / **** / ****加末四位」这种掩码，免得接口哪天把整把钥匙吐回来还被画上去。
function displayMasked(value) {
    if (value === "未配置" || value === "****") {
        return value;
    }
    if (typeof value === "string" && /^\*{4}[A-Za-z0-9._-]{4}$/.test(value)) {
        return value;
    }
    return "已保存";
}

const PLOT_AI_IMAGE_LIMIT = 8 * 1024 * 1024;

async function postPlotForm(url, fields, file) {
    let body;
    const headers = {};
    if (file) {
        body = new FormData();
        for (const [name, value] of Object.entries(fields)) {
            body.set(name, value ?? "");
        }
        body.set("image", file);
    } else {
        body = new URLSearchParams();
        for (const [name, value] of Object.entries(fields)) {
            body.set(name, value ?? "");
        }
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8";
    }
    const resp = await fetch(url, {
        method: "POST",
        headers,
        body,
    });
    try {
        return await resp.json();
    } catch {
        return null;
    }
}

export class FunctionPlot extends Interaction {
    static selector = ".tutoring_plot";

    start() {
        this.surface = new PlotSurface(this.el);
        const abort = new AbortController();
        const { signal } = abort;
        this.registerCleanup(() => abort.abort());

        const stage = this.surface.stage;
        const input = this.surface.input;
        stage.style.cursor = "grab";

        stage.addEventListener(
            "wheel",
            (event) => {
                event.preventDefault();
                const rect = stage.getBoundingClientRect();
                const factor = Math.exp(-event.deltaY * 0.0015);
                this.zoomAt(factor, event.clientX - rect.left, event.clientY - rect.top);
            },
            { passive: false, signal }
        );
        stage.addEventListener("pointerdown", (event) => this.onPointerDown(event), { signal });
        stage.addEventListener("pointermove", (event) => this.onPointerMove(event), { signal });
        stage.addEventListener("pointerup", (event) => this.onPointerUp(event), { signal });
        stage.addEventListener("pointerleave", () => this.onPointerLeave(), { signal });

        this.el.querySelector("[data-plot-add]").addEventListener(
            "click",
            () => this.submit(),
            { signal }
        );
        this.el.querySelector("[data-plot-clear]").addEventListener(
            "click",
            () => {
                this.surface.clearCurves();
                this.surface.clearError();
            },
            { signal }
        );
        this.el.querySelector("[data-plot-reset]").addEventListener(
            "click",
            () => this.surface.resetView(),
            { signal }
        );

        // 参数弹层元素与「按类型添加」按钮
        this.modalEl = this.el.querySelector("[data-plot-modal]");
        this.modalTitle = this.el.querySelector("[data-plot-modal-title]");
        this.modalHint = this.el.querySelector("[data-plot-modal-hint]");
        this.modalModes = this.el.querySelector("[data-plot-modal-modes]");
        this.modalFields = this.el.querySelector("[data-plot-modal-fields]");
        this.modalPreview = this.el.querySelector("[data-plot-modal-preview]");
        this.modalExtrasEl = this.el.querySelector("[data-plot-modal-extras]");
        this.modalMeta = this.el.querySelector("[data-plot-modal-meta]");
        this.modal = null;
        this.modalFieldInputs = [];
        this.modalExtraInputs = [];
        this.modalExtras = {};
        this.lastPointerDownAt = 0;
        for (const button of this.el.querySelectorAll("[data-plot-type]")) {
            button.addEventListener("click", () => this.openTypeModal(button.dataset.plotType), { signal });
        }
        for (const closer of this.el.querySelectorAll("[data-plot-modal-close]")) {
            closer.addEventListener("click", () => this.closeTypeModal(), { signal });
        }
        this.el.querySelector("[data-plot-modal-confirm]").addEventListener(
            "click",
            () => this.confirmTypeModal(),
            { signal }
        );

        // 全屏
        this.fullscreenButton = this.el.querySelector("[data-plot-fullscreen]");
        this.fullscreenButton.addEventListener("click", () => this.toggleFullscreen(), { signal });
        document.addEventListener(
            "fullscreenchange",
            () => {
                const fullscreenClass = "tutoring_plot_stage_fullscreen";
                if (!document.fullscreenElement && stage.classList.contains(fullscreenClass)) {
                    this.exitFullscreen();
                }
            },
            { signal }
        );
        document.addEventListener(
            "keydown",
            (event) => {
                if (event.key !== "Escape") {
                    return;
                }
                if (!this.modalEl.classList.contains("d-none")) {
                    this.closeTypeModal();
                } else if (stage.classList.contains("tutoring_plot_stage_fullscreen")) {
                    this.exitFullscreen();
                }
            },
            { signal }
        );
        input.addEventListener(
            "keydown",
            (event) => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    this.submit();
                }
            },
            { signal }
        );

        const observer = new ResizeObserver(() => this.surface.resize());
        observer.observe(stage);
        this.registerCleanup(() => observer.disconnect());

        const aiOpen = this.el.querySelector("[data-plot-ai-open]");
        const aiPanel = this.el.querySelector("[data-plot-ai-panel]");
        if (aiOpen && aiPanel) {
            aiOpen.addEventListener(
                "click",
                () => {
                    aiPanel.classList.toggle("d-none");
                    const box = aiPanel.querySelector("[data-plot-ai-input]");
                    if (box && !aiPanel.classList.contains("d-none")) {
                        box.focus();
                    }
                },
                { signal }
            );
        }
        const aiSubmit = this.el.querySelector("[data-plot-ai-submit]");
        if (aiSubmit) {
            aiSubmit.addEventListener("click", () => this.submitAi(), { signal });
            const aiInput = this.el.querySelector("[data-plot-ai-input]");
            if (aiInput) {
                aiInput.addEventListener(
                    "keydown",
                    (event) => {
                        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                            event.preventDefault();
                            this.submitAi();
                        }
                    },
                    { signal }
                );
            }
        }
        const keySave = this.el.querySelector("[data-plot-ai-key-save]");
        if (keySave) {
            keySave.addEventListener("click", () => this.saveAiKey(), { signal });
        }

        this.surface.resize();
        this.presetDefault();
    }

    presetDefault() {
        try {
            // 预置的椭圆也带上离心率（x²/4+y²/9=1 → a=3、b=2）
            this.surface.addCurve("x^2/4+y^2/9=1", { eccentricity: eccentricityInfo(4, 9) });
        } catch {
            // 预置示例失败不影响使用
        }
    }

    submit() {
        const value = this.surface.input.value.trim();
        if (!value) {
            this.surface.showError("请输入方程或函数式");
            return;
        }
        try {
            this.surface.addCurve(value);
            this.surface.clearError();
            this.surface.input.value = "";
            this.surface.input.focus();
        } catch (error) {
            this.surface.showError(error.message);
        }
    }

    updateAiQuota(left, max) {
        const el = this.el.querySelector("[data-plot-ai-quota]");
        if (!el || left == null || max == null) {
            return;
        }
        el.textContent = `今日还可智能画图 ${left}/${max} 次`;
    }

    async submitAi() {
        if (this.aiBusy) {
            return;
        }
        const input = this.el.querySelector("[data-plot-ai-input]");
        const status = this.el.querySelector("[data-plot-ai-status]");
        const button = this.el.querySelector("[data-plot-ai-submit]");
        const text = (input?.value || "").trim();
        const fileInput = this.el.querySelector("[data-plot-ai-file]");
        const file = fileInput?.files?.[0] || null;
        if (!text && !file) {
            this.surface.showError("请先写一句要画的图像，或上传一张图片");
            return;
        }
        if (file && file.size > PLOT_AI_IMAGE_LIMIT) {
            this.surface.showError("图片太大了（最大 8MB），请换一张小一点的。这次没有扣次数。");
            return;
        }
        this.aiBusy = true;
        if (button) {
            button.disabled = true;
        }
        if (status) {
            status.textContent = "正在生成方程…";
        }
        try {
            const data = await postPlotForm("/tools/function-plot/ai", {
                csrf_token: this.el.querySelector("[data-plot-ai-csrf]")?.value || "",
                description: text,
            }, file);
            if (!data) {
                this.surface.showError("没有得到有效结果。若刚退出登录，请重新登录后再试。");
                if (status) {
                    status.textContent = "";
                }
                return;
            }
            this.updateAiQuota(data.quota_left, data.quota_max);
            if (!data.ok) {
                this.surface.showError(data.error || "智能画图没有完成");
                if (status) {
                    status.textContent = "";
                }
                return;
            }
            const curves = Array.isArray(data.curves) ? data.curves : [];
            let drawn = 0;
            for (const curve of curves) {
                if (!curve || typeof curve.expr !== "string") {
                    continue;
                }
                try {
                    this.surface.addCurve(curve.expr, {
                        label: typeof curve.label === "string" ? curve.label : "",
                        params: curve.params && typeof curve.params === "object" ? curve.params : {},
                    });
                    drawn += 1;
                } catch (error) {
                    this.surface.showError(error.message);
                }
            }
            if (!drawn) {
                this.surface.showError("没有画出曲线");
                if (status) {
                    status.textContent = "";
                }
                return;
            }
            this.surface.clearError();
            if (fileInput) {
                fileInput.value = "";
            }
            if (status) {
                status.textContent = data.note ? `已绘制 ${drawn} 条。${data.note}` : `已绘制 ${drawn} 条`;
            }
        } finally {
            this.aiBusy = false;
            if (button) {
                button.disabled = false;
            }
        }
    }

    async saveAiKey() {
        const input = this.el.querySelector("[data-plot-ai-key]");
        const note = this.el.querySelector("[data-plot-ai-key-note]");
        const key = input?.value.trim() || "";
        if (!key) {
            if (note) {
                note.textContent = "请先粘贴密钥。";
            }
            return;
        }
        let data;
        try {
            data = await postPlotForm("/tools/function-plot/ai-key", {
                csrf_token: this.el.querySelector("[data-plot-ai-csrf]")?.value || "",
                api_key: key,
            });
        } finally {
            if (input) {
                input.value = "";
            }
        }
        if (!data) {
            if (note) {
                note.textContent = "保存没有完成，请稍后再试。";
            }
            return;
        }
        if (!data.ok) {
            if (note) {
                note.textContent = data.error || "没有保存。";
            }
            return;
        }
        const current = this.el.querySelector("[data-plot-ai-key-current]");
        if (current) {
            current.textContent = displayMasked(data.masked);
        }
        if (note) {
            note.textContent = "已保存，当前进程立刻生效。页面不显示完整密钥。";
        }
    }

    /* ---------------------------- 按类型添加 ---------------------------- */

    openTypeModal(typeKey) {
        const spec = CURVE_TYPES[typeKey];
        if (!spec) {
            return;
        }
        this.modal = {typeKey, spec, mode: spec.modes ? spec.modes[0].key : null};
        this.modalSliders = new Set();
        this.modalExtras = {};
        for (const extra of spec.extras ? spec.extras(this.modal.mode) : []) {
            this.modalExtras[extra.key] = !!extra.value;
        }
        this.modalTitle.textContent = spec.label;
        this.updateModalHint();
        this.renderModalModes();
        this.renderModalFields();
        this.renderModalExtras();
        this.updateModalPreview();
        this.modalEl.classList.remove("d-none");
    }

    closeTypeModal() {
        this.modalEl.classList.add("d-none");
        this.modal = null;
    }

    updateModalHint() {
        const { spec, mode } = this.modal;
        this.modalHint.textContent = (typeof spec.hint === "function" ? spec.hint(mode) : spec.hint) || "";
    }

    renderModalModes() {
        const { spec, mode } = this.modal;
        this.modalModes.textContent = "";
        if (!spec.modes) {
            this.modalModes.classList.add("d-none");
            return;
        }
        this.modalModes.classList.remove("d-none");
        for (const option of spec.modes) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `btn btn-sm ${option.key === mode ? "btn-primary" : "btn-outline-secondary"}`;
            button.textContent = option.label;
            button.addEventListener("click", () => {
                this.modal.mode = option.key;
                this.updateModalHint();
                this.renderModalModes();
                this.renderModalFields();
                this.renderModalExtras();
                this.updateModalPreview();
            });
            this.modalModes.appendChild(button);
        }
    }

    renderModalFields() {
        const { spec, mode } = this.modal;
        this.modalFields.textContent = "";
        this.modalFieldInputs = [];
        for (const field of spec.fields(mode)) {
            const column = document.createElement("div");
            column.className = "col-6 col-sm-4";

            const label = document.createElement("label");
            label.className = "form-label small text-muted mb-1";
            label.textContent = field.label;

            const input = document.createElement("input");
            input.type = "text";
            input.inputMode = "decimal";
            input.autocomplete = "off";
            input.className = "form-control";
            input.value = field.value === undefined ? "" : String(field.value);
            input.addEventListener("input", () => this.updateModalPreview());

            column.appendChild(label);
            column.appendChild(input);
            if (field.sym) {
                column.appendChild(this.buildSliderToggle(field));
            }
            this.modalFields.appendChild(column);
            this.modalFieldInputs.push({ key: field.key, label: field.label, el: input });
        }
    }

    // 「滑块 a」勾选框：勾上就把这个参数从烤死的数字变成方程里活着的字母
    buildSliderToggle(field) {
        const wrapper = document.createElement("div");
        wrapper.className = "form-check mt-1 mb-0";

        const input = document.createElement("input");
        input.type = "checkbox";
        input.className = "form-check-input";
        input.id = `tutoring_plot_sym_${field.key}`;
        input.checked = this.modalSliders.has(field.key);
        input.addEventListener("change", () => {
            if (input.checked) {
                this.modalSliders.add(field.key);
            } else {
                this.modalSliders.delete(field.key);
            }
            this.updateModalPreview();
        });

        const label = document.createElement("label");
        label.className = "form-check-label small";
        label.setAttribute("for", input.id);
        label.textContent = `滑块 ${field.sym}`;
        label.title = `这条曲线自己的参数，方程里写 ${field.sym}`;

        wrapper.appendChild(input);
        wrapper.appendChild(label);
        return wrapper;
    }

    // 当前勾了的字段 → compose 用的 {字段键: 方程里的写法}
    modalSliderKeys() {
        const { spec, mode } = this.modal;
        return [...this.modalSliders].filter((key) =>
            spec.fields(mode).some((field) => field.sym && field.key === key)
        );
    }

    modalSliderTexts() {
        const { spec, mode } = this.modal;
        return sliderTexts(spec, mode, this.modalSliderKeys());
    }

    // 复选项（目前只有双曲线的"画出渐近线"）：切换写法时保留已勾的状态
    renderModalExtras() {
        const { spec, mode } = this.modal;
        const container = this.modalExtrasEl;
        container.textContent = "";
        this.modalExtraInputs = [];
        const extras = spec.extras ? spec.extras(mode) : [];
        if (!extras.length) {
            container.classList.add("d-none");
            return;
        }
        container.classList.remove("d-none");
        for (const extra of extras) {
            const wrapper = document.createElement("div");
            wrapper.className = "form-check mb-1";

            const input = document.createElement("input");
            input.type = "checkbox";
            input.className = "form-check-input";
            input.id = `tutoring_plot_extra_${extra.key}`;
            input.checked = !!this.modalExtras[extra.key];
            input.addEventListener("change", () => {
                this.modalExtras[extra.key] = input.checked;
                this.updateModalPreview();
            });

            const label = document.createElement("label");
            label.className = "form-check-label small";
            label.setAttribute("for", input.id);
            label.textContent = extra.label;

            wrapper.appendChild(input);
            wrapper.appendChild(label);
            container.appendChild(wrapper);
            this.modalExtraInputs.push({ key: extra.key, el: input });
        }
    }

    readModalValues() {
        const values = {};
        for (const field of this.modalFieldInputs) {
            try {
                values[field.key] = evalConstant(field.el.value);
            } catch (error) {
                throw new Error(`${field.label}：${error.message}`);
            }
        }
        return values;
    }

    updateModalPreview() {
        if (!this.modal) {
            return;
        }
        const { spec, mode } = this.modal;
        try {
            const values = this.readModalValues();
            const equation = spec.compose(mode, values, this.modalSliderTexts());
            buildModel(equation, {}); // 顺便验证能不能画出来（滑块字母按默认值 1 代入，只查语法与可解性）
            this.modalPreview.innerHTML = prettyEquation(equation);
            this.modalPreview.classList.remove("text-danger");
            this.modalPreview.classList.add("text-muted");
            this.renderModalMeta(spec.describe ? spec.describe(mode, values, this.modalExtras) : null);
        } catch (error) {
            this.modalPreview.textContent = error.message;
            this.modalPreview.classList.add("text-danger");
            this.modalPreview.classList.remove("text-muted");
            this.renderModalMeta(null);
        }
    }

    // 预览区下面那一行小字：椭圆的离心率、双曲线的渐近线说明
    renderModalMeta(meta) {
        const info = meta || {};
        const texts = [];
        if (info.eccentricity) {
            texts.push(
                `离心率 e = ${info.eccentricity.text}${info.eccentricity.circle ? "（这是圆）" : ""}`
            );
        }
        if (info.radian) {
            texts.push("坐标轴刻度、读数与交点改用 π 表示");
        }
        if (info.asymptotes && info.asymptotes.length) {
            texts.push(`渐近线 ${asymptoteSummaryText(info.asymptotes)}`);
            texts.push(
                `　即 ${info.asymptotes.map((line) => line.slopeIntercept).join(" 与 ")}`
            );
        }
        this.modalMeta.innerHTML = texts.map((text) => escapeHtml(text)).join("<br/>");
        this.modalMeta.classList.toggle("d-none", texts.length === 0);
    }

    confirmTypeModal() {
        if (!this.modal) {
            return;
        }
        const { mode } = this.modal;
        try {
            const values = this.readModalValues();
            // 附带信息（离心率、渐近线）由 rebuildCurve 按滑块当前值算，这里只交"当初填的那份数"
            this.surface.addTypedCurve({
                typeKey: this.modal.typeKey,
                mode,
                fixed: values,
                extras: { ...this.modalExtras },
                sliderKeys: this.modalSliderKeys(),
            });
            this.surface.clearError();
            this.closeTypeModal();
        } catch (error) {
            this.modalPreview.textContent = error.message;
            this.modalPreview.classList.add("text-danger");
            this.modalPreview.classList.remove("text-muted");
        }
    }

    /* ------------------------------ 全屏查看 ------------------------------ */

    toggleFullscreen() {
        const stage = this.surface.stage;
        if (stage.classList.contains("tutoring_plot_stage_fullscreen")) {
            this.exitFullscreen();
            return;
        }
        stage.classList.add("tutoring_plot_stage_fullscreen");
        document.body.classList.add("tutoring_plot_noscroll");
        this.updateFullscreenButton(true);
        this.surface.resize(); // 不依赖 ResizeObserver 的时序，避免首帧拉伸
        try {
            const request = stage.requestFullscreen?.();
            if (request && typeof request.catch === "function") {
                request.catch(() => {
                    // 原生全屏被拒绝（如移动端限制）时 CSS 全屏已生效
                });
            }
        } catch {
            // 部分移动端浏览器不支持原生全屏，CSS 全屏已经生效
        }
    }

    exitFullscreen() {
        const stage = this.surface.stage;
        stage.classList.remove("tutoring_plot_stage_fullscreen");
        document.body.classList.remove("tutoring_plot_noscroll");
        this.updateFullscreenButton(false);
        this.surface.resize();
        try {
            if (document.fullscreenElement) {
                document.exitFullscreen?.();
            }
        } catch {
            // 忽略
        }
    }

    updateFullscreenButton(active) {
        this.fullscreenButton.title = active ? "退出全屏" : "全屏查看";
        this.fullscreenButton.textContent = "";
        const icon = document.createElement("i");
        icon.className = active ? "fa fa-compress" : "fa fa-expand";
        icon.setAttribute("role", "img");
        this.fullscreenButton.appendChild(icon);
    }

    zoomAt(factor, pixelX, pixelY) {
        const surface = this.surface;
        const anchorX = surface.toDataX(pixelX);
        const anchorY = surface.toDataY(pixelY);
        const halfWidth = Math.min(1e6, Math.max(1e-4, surface.view.hw / factor));
        surface.view.hw = halfWidth;
        surface.updateScale();
        surface.view.cx = anchorX - pixelX / surface.scale + halfWidth;
        surface.view.cy = anchorY + pixelY / surface.scale - surface.halfHeight();
        surface.scheduleDraw(true);
    }

    onPointerDown(event) {
        // 画布内的按钮/链接要自己收 click：对它们的 pointerdown 调 preventDefault
        // 会让浏览器不再派发后续的 mousedown/click，按钮就彻底失效了
        if (event.target.closest("button, a, input, label, .tutoring_plot_modal")) {
            return;
        }
        event.preventDefault();

        // 双击重置自己判定：上面那句 preventDefault 会抑制浏览器合成的 dblclick
        const now = Date.now();
        if (now - this.lastPointerDownAt < 300) {
            this.lastPointerDownAt = 0;
            this.surface.resetView();
            return;
        }
        this.lastPointerDownAt = now;

        try {
            this.surface.stage.setPointerCapture(event.pointerId);
        } catch {
            // 合成事件/无有效指针 id 时无需捕获，拖动仍按 clientX/clientY 计算
        }
        this.surface.drag = {
            clientX: event.clientX,
            clientY: event.clientY,
            cx: this.surface.view.cx,
            cy: this.surface.view.cy,
        };
        this.surface.stage.style.cursor = "grabbing";
        this.surface.drawOverlay();
    }

    onPointerMove(event) {
        const surface = this.surface;
        const rect = surface.stage.getBoundingClientRect();
        if (surface.drag) {
            surface.view.cx = surface.drag.cx - (event.clientX - surface.drag.clientX) / surface.scale;
            surface.view.cy = surface.drag.cy + (event.clientY - surface.drag.clientY) / surface.scale;
            surface.scheduleDraw(true);
            return;
        }
        surface.hover = { pixelX: event.clientX - rect.left, pixelY: event.clientY - rect.top };
        surface.drawOverlay();
        this.updateReadout();
    }

    onPointerUp(event) {
        const surface = this.surface;
        if (!surface.drag) {
            return;
        }
        surface.drag = null;
        surface.stage.style.cursor = "grab";
        try {
            surface.stage.releasePointerCapture(event.pointerId);
        } catch {
            // 未成功捕获时忽略
        }
        surface.scheduleDraw(false);
    }

    onPointerLeave() {
        this.surface.hover = null;
        this.surface.drawOverlay();
        this.readoutDefault();
    }

    updateReadout() {
        const { hover } = this.surface;
        if (!hover) {
            this.readoutDefault();
            return;
        }
        const x = this.surface.toDataX(hover.pixelX);
        const y = this.surface.toDataY(hover.pixelY);
        const text = (value) => (this.surface.radianTicks() ? piTick(value) : formatNumber(value));
        this.surface.readout.textContent = `x = ${text(x)}　y = ${text(y)}`;
    }

    readoutDefault() {
        this.surface.readout.textContent = "滚轮缩放 · 拖动平移 · 双击重置";
    }
}

registry.category("public.interactions").add("tutoring_center.function_plot", FunctionPlot);
