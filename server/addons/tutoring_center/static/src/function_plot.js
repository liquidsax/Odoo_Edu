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
            pushName(text.slice(index, end).toLowerCase(), tokens);
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

// 连写的字母按已知符号拆开（"xy" → x*y、"2pi" → 2*pi 走隐式乘法）
function pushName(name, tokens) {
    if (KNOWN_NAMES.includes(name)) {
        tokens.push({ type: "name", name });
        return;
    }
    let index = 0;
    while (index < name.length) {
        const piece = KNOWN_NAMES.find((known) => name.startsWith(known, index));
        if (!piece) {
            throw new Error(`未知符号「${name}」：只支持 x、y、pi、e 与常见函数名`);
        }
        tokens.push({ type: "name", name: piece });
        index += piece.length;
    }
}

function toRPN(tokens) {
    const output = [];
    const operators = [];
    const top = () => operators[operators.length - 1];
    // 上一个 token 能否作为值的结尾（用于区分一元负号与隐式乘法）
    const endsValue = (token) =>
        !!token && ["num", "name", "rparen", "var"].includes(token.type);

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
        const startsValue = ["num", "name", "lparen"].includes(token.type);
        // 隐式乘法（2x、3(x+1)、(x+1)(x-1)）：优先级同 "*"，因此 2x^2 解析为 2*(x^2)
        if (startsValue && endsValue(previous)) {
            pushBinary("*");
        }

        if (token.type === "num") {
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

function compileRPN(rpn) {
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

function buildModel(expression) {
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
    const F = compileRPN(rpn);

    if (!usesY) {
        return { kind: "vertical", F }; // 如 x=2：竖直线
    }
    const explicit = solveForY(F);
    if (explicit) {
        const samples = [0.11, 0.73];
        if (samples.every((x) => Number.isFinite(explicit(x)))) {
            return { kind: "explicit", explicit };
        }
    }
    return { kind: "implicit", F }; // 圆、椭圆、双曲线等
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
    const value = compileRPN(rpn)(0, 0);
    if (!Number.isFinite(value)) {
        throw new Error("不是有效数值");
    }
    return value;
}

// 带平移的标准式片段：offset 为 0 时就是 "x"，否则 "(x-(h))"
function centered(axis, offset) {
    return offset === 0 ? axis : `(${axis}-(${num(offset)}))`;
}

// 分母为 1 时省略 "/1"，让方程贴近手写习惯
function squaredTerm(axis, offset, denominator) {
    const body = `${centered(axis, offset)}^2`;
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

// [[系数, "x"], [系数, "y"], [系数, ""]] → "x-2y-4"（省略系数 1、合并正负号）
function linearCombination(terms) {
    let text = "";
    for (const [coefficient, name] of terms) {
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
    for (const [coefficient, axisTerm] of terms) {
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
                      { key: "a", label: "圆心 x₀", value: 0 },
                      { key: "b", label: "圆心 y₀", value: 0 },
                      { key: "r", label: "半径 r", value: 2 },
                  ]
                : [
                      { key: "D", label: "D", value: -2 },
                      { key: "E", label: "E", value: -4 },
                      { key: "F", label: "F", value: 1 },
                  ],
        compose: (mode, v) => {
            if (mode === "standard") {
                if (v.r <= 0) {
                    throw new Error("半径 r 要大于 0");
                }
                return `${centered("x", v.a)}^2+${centered("y", v.b)}^2=${num(v.r * v.r)}`;
            }
            return `${linearCombination([[1, "x^2"], [1, "y^2"], [v.D, "x"], [v.E, "y"], [v.F, ""]])}=0`;
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
                      { key: "A", label: "x² 的系数", value: 1 },
                      { key: "B", label: "y² 的系数", value: 1 },
                      { key: "N", label: "等号右边", value: 1 },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0 },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0 },
                  ]
                : [
                      { key: "a2", label: "x² 分母 a²", value: 4 },
                      { key: "b2", label: "y² 分母 b²", value: 1 },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0 },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0 },
                  ],
        compose: (mode, v) => {
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
                return `${conicCombination([[v.A, centered("x", v.h)], [v.B, centered("y", v.k)]])}=${num(v.N)}`;
            }
            if (v.a2 <= 0 || v.b2 <= 0) {
                throw new Error("两个分母都要大于 0");
            }
            return `${squaredTerm("x", v.h, v.a2)}+${squaredTerm("y", v.k, v.b2)}=1`;
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
                      { key: "A", label: "x² 的系数", value: 1 },
                      { key: "B", label: "y² 的系数", value: -4 },
                      { key: "N", label: "等号右边", value: 4 },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0 },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0 },
                  ]
                : [
                      { key: "a2", label: "实半轴分母 A", value: 4 },
                      { key: "b2", label: "虚半轴分母 B", value: 9 },
                      { key: "h", label: "中心 x₀（默认 0）", value: 0 },
                      { key: "k", label: "中心 y₀（默认 0）", value: 0 },
                  ],
        compose: (mode, v) => {
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
                return `${conicCombination([[v.A, centered("x", v.h)], [v.B, centered("y", v.k)]])}=${num(v.N)}`;
            }
            if (v.a2 <= 0 || v.b2 <= 0) {
                throw new Error("两个分母都要大于 0");
            }
            // 实半轴分母 A 始终跟着正项：焦点在 x 轴是 x²/A，在 y 轴是 y²/A
            const focusY = mode === "y";
            const positive = focusY ? squaredTerm("y", v.k, v.a2) : squaredTerm("x", v.h, v.a2);
            const negative = focusY ? squaredTerm("x", v.h, v.b2) : squaredTerm("y", v.k, v.b2);
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
            { key: "twoP", label: "2p 的值", value: 4 },
            { key: "h", label: "顶点 x₀（默认 0）", value: 0 },
            { key: "k", label: "顶点 y₀（默认 0）", value: 0 },
        ],
        compose: (mode, v) => {
            const twoP = Math.abs(v.twoP);
            if (twoP === 0) {
                throw new Error("2p 不能为 0");
            }
            const x = centered("x", v.h);
            const y = centered("y", v.k);
            if (mode === "left") {
                return `${y}^2=-${num(twoP)}${x}`;
            }
            if (mode === "up") {
                return `${x}^2=${num(twoP)}${y}`;
            }
            if (mode === "down") {
                return `${x}^2=-${num(twoP)}${y}`;
            }
            return `${y}^2=${num(twoP)}${x}`;
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
                      { key: "A", label: "A", value: 1 },
                      { key: "B", label: "B", value: -2 },
                      { key: "C", label: "C", value: -4 },
                  ]
                : [
                      { key: "k", label: "斜率 k", value: 1 },
                      { key: "b", label: "截距 b", value: 0 },
                  ],
        compose: (mode, v) => {
            if (mode === "slope") {
                return `y=${linearCombination([[v.k, "x"], [v.b, ""]])}`;
            }
            if (v.A === 0 && v.B === 0) {
                throw new Error("A、B 不能同时为 0");
            }
            return `${linearCombination([[v.A, "x"], [v.B, "y"], [v.C, ""]])}=0`;
        },
    },
    quadratic: {
        label: "二次函数",
        hint: "y = ax² + bx + c，填三个系数。",
        fields: () => [
            { key: "a", label: "a", value: 1 },
            { key: "b", label: "b", value: -2 },
            { key: "c", label: "c", value: -3 },
        ],
        compose: (mode, v) => {
            if (v.a === 0) {
                throw new Error("a 不能为 0（否则是直线）");
            }
            return `y=${linearCombination([[v.a, "x^2"], [v.b, "x"], [v.c, ""]])}`;
        },
    },
    inverse: {
        label: "反比例",
        hint: "y = k/x，填 k（k 不能为 0）。",
        fields: () => [{ key: "k", label: "k", value: 1 }],
        compose: (mode, v) => {
            if (v.k === 0) {
                throw new Error("k 不能为 0");
            }
            return `y=${num(v.k)}/x`;
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
                      { key: "A", label: "振幅 A", value: 1 },
                      { key: "T", label: "周期 T", value: 2 },
                      { key: "phi", label: "初相 φ", value: 0 },
                  ]
                : [
                      { key: "A", label: "振幅 A", value: 1 },
                      { key: "w", label: "ω", value: 1 },
                      { key: "phi", label: "初相 φ", value: 0 },
                  ],
        compose: (mode, v) => {
            if (v.A === 0) {
                throw new Error("振幅 A 不能为 0");
            }
            let omega;
            if (mode === "period") {
                if (v.T === 0) {
                    throw new Error("周期 T 不能为 0");
                }
                omega = piText((2 * Math.PI) / v.T);
            } else {
                if (v.w === 0) {
                    throw new Error("ω 不能为 0");
                }
                omega = coefficientText(v.w);
            }
            // 只有纯数字才紧贴 x（2x）；含 pi 或用分数写的必须补 *，否则 pi/2x 会被读成 pi/(2x)
            const plainNumber = /^-?\d+(\.\d+)?$/.test(omega);
            const omegaPart = omega === "" ? "x" : plainNumber ? `${omega}x` : `${omega}*x`;
            let phase = "";
            if (v.phi !== 0) {
                phase = v.phi < 0 ? `-${piText(-v.phi)}` : `+${piText(v.phi)}`;
            }
            return `y=${coefficientText(v.A)}sin(${omegaPart}${phase})`;
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
    // 字母相邻时省掉点号：π·x → πx（π/2·x 保留点号，避免被读成分母里带 x）
    out = out.replace(/([a-zA-Zπ])·([a-zA-Z])/g, "$1$2");
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
        this.errorBox = root.querySelector("[data-plot-error]");
        this.input = root.querySelector("[data-plot-input]");
        this.curves = [];
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
        const model = buildModel(expression);
        const curve = {
            expression,
            model,
            color: PALETTE[this.curves.length % PALETTE.length],
            visible: true,
            meta,
        };
        this.curves.push(curve);
        this.renderLegend();
        this.drawMain();
        this.drawOverlay();
    }

    clearCurves() {
        this.curves = [];
        this.renderLegend();
        this.drawMain();
        this.drawOverlay();
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
            const wrap = document.createElement("span");
            wrap.className = "d-inline-flex align-items-center gap-1 border rounded px-2 py-1 small";

            const swatch = document.createElement("span");
            swatch.style.cssText = `display:inline-block;width:12px;height:12px;border-radius:3px;background:${curve.color}`;
            if (!curve.visible) {
                swatch.style.opacity = "0.3";
            }
            wrap.appendChild(swatch);

            const label = document.createElement("span");
            label.innerHTML = prettyEquation(curve.expression);
            label.title = curve.expression;
            label.style.opacity = curve.visible ? "1" : "0.45";
            if (curve.visible) {
                label.className = "fw-semibold";
            }
            wrap.appendChild(label);

            const info = curve.meta || {};
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
            remove.addEventListener("click", () => {
                this.curves.splice(index, 1);
                this.renderLegend();
                this.drawMain();
                this.drawOverlay();
            });
            wrap.appendChild(remove);

            this.legend.appendChild(wrap);
        });
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
            if (!curve.visible) {
                continue;
            }
            context.strokeStyle = curve.color;
            context.lineWidth = 2;
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
            if (!curve.visible || curve.model.kind !== "explicit") {
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

    /* ---------------------------- 按类型添加 ---------------------------- */

    openTypeModal(typeKey) {
        const spec = CURVE_TYPES[typeKey];
        if (!spec) {
            return;
        }
        this.modal = { spec, mode: spec.modes ? spec.modes[0].key : null };
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
            this.modalFields.appendChild(column);
            this.modalFieldInputs.push({ key: field.key, label: field.label, el: input });
        }
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
            const equation = spec.compose(mode, values);
            buildModel(equation); // 顺便验证能不能画出来
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
        const { spec, mode } = this.modal;
        try {
            const values = this.readModalValues();
            const equation = spec.compose(mode, values);
            const meta = spec.describe ? spec.describe(mode, values, this.modalExtras) : null;
            this.surface.addCurve(equation, meta);
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
