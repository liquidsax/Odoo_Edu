/**
 * 函数图像页「参数与滑块」的离线断言（不连库、不开浏览器）。
 *
 *     cd E:\Odoo && node dev/zz_plot_slider_check.mjs
 *
 * 被测文件是 Odoo 前端资产，顶部两行 @web/ 导入在 node 里解析不到，
 * 所以先读进来把导入换成桩、末尾补一份导出，再从临时文件 import。
 * 这样测的是**线上那一份源码**，不是抄出来的副本。
 */
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', 'server', 'addons', 'tutoring_center', 'static', 'src', 'function_plot.js');

const stubs = `
class Interaction {
    constructor(el) { this.el = el; }
    registerCleanup() {}
}
const registry = { category: () => ({ add() {} }) };
`;

async function loadModule() {
    const text = await readFile(source, 'utf8');
    const patched = text
        .replace('import { Interaction } from "@web/public/interaction";', stubs)
        .replace('import { registry } from "@web/core/registry";', '')
        .concat(
            '\nexport { buildModel, normalizeExpression, tokenize, toRPN, evalConstant,' +
            ' CURVE_TYPES, sliderTexts, fieldSliderText, sliderValueOf, fieldValueOf, prettyEquation };\n'
        );
    const dir = await mkdtemp(join(tmpdir(), 'zz_plot_'));
    const target = join(dir, 'function_plot.mjs');
    await writeFile(target, patched, 'utf8');
    return import(pathToFileURL(target).href);
}

const mod = await loadModule();
const {
    buildModel, evalConstant, CURVE_TYPES, sliderTexts, fieldSliderText,
    sliderValueOf, fieldValueOf, prettyEquation,
} = mod;

let ok = 0;
const failures = [];

function check(name, passed, detail) {
    if (passed) {
        ok++;
        return;
    }
    failures.push(`${name}${detail ? ` → ${detail}` : ''}`);
}

function equal(name, got, want) {
    check(name, got === want, `得到 ${JSON.stringify(got)}，期望 ${JSON.stringify(want)}`);
}

function close(name, got, want) {
    check(name, Number.isFinite(got) && Math.abs(got - want) < 1e-9, `得到 ${got}，期望 ${want}`);
}

function throws(name, fn, fragment) {
    try {
        fn();
    } catch (error) {
        check(name, !fragment || error.message.includes(fragment), `报错文案不含「${fragment}」：${error.message}`);
        return;
    }
    check(name, false, '本该报错却通过了');
}

// 取某类型某写法下"勾了这些字段为滑块"的方程写法
function composeWith(typeKey, mode, values, sliderKeys = []) {
    const spec = CURVE_TYPES[typeKey];
    const keys = sliderKeys.filter((key) => spec.fields(mode).some((field) => field.sym && field.key === key));
    return spec.compose(mode, values, sliderTexts(spec, mode, keys));
}

/* ------------------------------ 一、解析层 ------------------------------ */

const linear = buildModel('y=3x+b', {b: 2});
check('自由输入 y=3x+b 认出参数 b', JSON.stringify(linear.used) === '["b"]', JSON.stringify(linear.used));
equal('y=3x+b 走显式采样', linear.kind, 'explicit');
close('b=2 时 x=1 处 y=5', linear.explicit(1), 5);

const scaled = buildModel('y=ax^2', {a: -1});
close('a=-1 时 x=2 处 y=-4', scaled.explicit(2), -4);

check('参数名保留大小写', JSON.stringify(buildModel('y=Ax+B', {A: 1, B: 2}).used) === '["A","B"]',
    JSON.stringify(buildModel('y=Ax+B', {A: 1, B: 2}).used));
close('大写参数取到值', buildModel('y=Ax+B', {A: 1, B: 2}).explicit(3), 5);

equal('e 仍是自然常数，不是参数', buildModel('y=ex').used.length, 0);
close('e 当常数参与计算', buildModel('y=ex').explicit(2), Math.E * 2);
equal('pi 仍是常数，不是参数', buildModel('y=sin(pix)').used.length, 0);

close('函数名没被当成参数（sqrt）', buildModel('y=sqrt(x)').explicit(9), 3);
throws('打错的函数名要报错', () => buildModel('y=sn(x)'), '未知函数');
check('单字母跟括号仍按乘法（a(x+1)）', buildModel('y=a(x+1)', {a: 2}).explicit(1) === 4,
    String(buildModel('y=a(x+1)', {a: 2}).explicit(1)));

close('隐式乘法优先级未回退（2x^2）', buildModel('y=2x^2').explicit(3), 18);
close('一元负号未回退（-x^2）', buildModel('y=-x^2').explicit(2), -4);
check('多个参数一起认出来', JSON.stringify(buildModel('y=kx+m', {k: 2, m: 1}).used) === '["k","m"]',
    JSON.stringify(buildModel('y=kx+m', {k: 2, m: 1}).used));
throws('只有参数没有 x/y 仍报错', () => buildModel('a=2'), '需要包含 x 或 y');
equal('x=a 是竖直线', buildModel('x=a', {a: 2}).kind, 'vertical');

const conic = buildModel('x^2/a^2+y^2/b^2=1', {a: 2, b: 1});
equal('带参数的二次曲线走等值线', conic.kind, 'implicit');
close('椭圆上点 (2,0) 满足方程', conic.F(2, 0), 0);
close('原点处 F=-1', conic.F(0, 0), -1);
close('参数改到 a=3 后 (3,0) 才在曲线上', buildModel('x^2/a^2+y^2/b^2=1', {a: 3, b: 1}).F(3, 0), 0);

const sloped = buildModel('Ax+By=0', {A: 1, B: -2});
equal('含参数的直线仍解得 out y', sloped.kind, 'explicit');
close('x-2y=0 在 x=4 时 y=2', sloped.explicit(4), 2);
equal('B 拖到 0（对 y 不再线性）退回等值线', buildModel('Ax+By=0', {A: 1, B: 0}).kind, 'implicit');

throws('滑块数值框不接受字母', () => evalConstant('a+1'), '滑块的字母');
close('数值框仍接受 3/2', evalConstant('3/2'), 1.5);
close('数值框仍接受 2pi', evalConstant('2pi'), Math.PI * 2);

/* ---------------------------- 二、拼式与滑块 ---------------------------- */

equal('圆：不勾滑块照旧烤数字',
    composeWith('circle', 'standard', {a: 1, b: 2, r: 3}),
    '(x-(1))^2+(y-(2))^2=9');
equal('圆：圆心与半径都勾滑块',
    composeWith('circle', 'standard', {a: 1, b: 2, r: 3}, ['a', 'b', 'r']),
    '(x-a)^2+(y-b)^2=r^2');
equal('圆一般式：D、E、F 勾滑块',
    composeWith('circle', 'general', {D: -2, E: -4, F: 1}, ['D', 'E', 'F']),
    'x^2+y^2+Dx+Ey+F=0');

equal('椭圆分母式：四个参数全勾滑块写成课本形式',
    composeWith('ellipse', 'denominator', {a2: 4, b2: 1, h: 1, k: -1}, ['a2', 'b2', 'h', 'k']),
    '(x-h)^2/a^2+(y-k)^2/b^2=1');
equal('椭圆分母式：不勾滑块照旧',
    composeWith('ellipse', 'denominator', {a2: 5, b2: 1, h: 0, k: 0}),
    'x^2/5+y^2=1');
equal('椭圆系数式：勾滑块',
    composeWith('ellipse', 'coefficient', {A: 4, B: 9, N: 36, h: 0, k: 0}, ['A', 'B', 'N']),
    'A*x^2+B*y^2=N');
throws('椭圆系数式一正一负仍报错',
    () => composeWith('ellipse', 'coefficient', {A: 1, B: -1, N: 1, h: 0, k: 0}, ['A', 'B']),
    '一正一负');

equal('双曲线焦点在 x：勾滑块',
    composeWith('hyperbola', 'x', {a2: 4, b2: 9, h: 0, k: 0}, ['a2', 'b2']),
    'x^2/a^2-y^2/b^2=1');
equal('双曲线焦点在 y：正项跟着 y',
    composeWith('hyperbola', 'y', {a2: 4, b2: 9, h: 2, k: 0}, ['a2', 'b2', 'h']),
    'y^2/a^2-(x-h)^2/b^2=1');
equal('双曲线系数式：勾滑块',
    composeWith('hyperbola', 'coefficient', {A: 1, B: -4, N: 4, h: 0, k: 0}, ['A', 'B', 'N']),
    'A*x^2+B*y^2=N');

equal('抛物线开口向右：m 就是 2p 这个整体',
    composeWith('parabola', 'right', {twoP: 4, h: 0, k: 0}, ['twoP']),
    'y^2=m*x');
equal('抛物线开口向上：顶点也勾滑块',
    composeWith('parabola', 'up', {twoP: 4, h: 1, k: -2}, ['twoP', 'h', 'k']),
    '(x-h)^2=m*(y-k)');
equal('抛物线开口向左：负号照旧',
    composeWith('parabola', 'left', {twoP: 4, h: 0, k: 0}, ['twoP']),
    'y^2=-m*x');

equal('直线斜截式：勾滑块', composeWith('line', 'slope', {k: -2, b: 3}, ['k', 'b']), 'y=kx+b');
equal('直线一般式：勾滑块', composeWith('line', 'general', {A: 1, B: -2, C: -4}, ['A', 'B', 'C']), 'Ax+By+C=0');
equal('直线一般式：不勾滑块照旧', composeWith('line', 'general', {A: 1, B: -2, C: -4}), 'x-2y-4=0');
equal('二次函数：勾滑块', composeWith('quadratic', null, {a: 1, b: -2, c: -3}, ['a', 'b', 'c']), 'y=ax^2+bx+c');
equal('反比例：勾滑块', composeWith('inverse', null, {k: 2}, ['k']), 'y=k/x');
equal('反比例：不勾照旧', composeWith('inverse', null, {k: -3}), 'y=-3/x');

equal('三角函数：ω 写法勾满', composeWith('sine', 'omega', {A: 2, w: 3, phi: 1}, ['A', 'w', 'phi']), 'y=A*sin(w*x+p)');
equal('三角函数：周期写法', composeWith('sine', 'period', {A: 1, T: 2, phi: 0}, ['T']), 'y=sin(2pi/T*x)');
equal('三角函数：不勾滑块照旧', composeWith('sine', 'omega', {A: 1, w: 2, phi: 0}), 'y=sin(2x)');
equal('三角函数：初相为负仍写减号', composeWith('sine', 'omega', {A: 2, w: 1, phi: -Math.PI / 2}), 'y=2sin(x-pi/2)');

throws('振幅为 0 时勾了滑块也照样拦',
    () => composeWith('sine', 'omega', {A: 0, w: 1, phi: 0}, ['A', 'w']), '振幅 A 不能为 0');

// 分母类字段存的是 a²，滑块带的是 a
const a2Field = CURVE_TYPES.ellipse.fields('denominator')[0];
close('分母字段：滑块初值取平方根', sliderValueOf(a2Field, 4), 2);
close('分母字段：拖回 a=3 时分母变 9', fieldValueOf(a2Field, 3), 9);
equal('分母字段：方程里写 a^2', fieldSliderText(a2Field), 'a^2');
const rField = CURVE_TYPES.circle.fields('standard')[2];
close('半径字段：滑块带的就是 r 本身', sliderValueOf(rField, 3), 3);
equal('半径字段：方程里仍写 r^2', fieldSliderText(rField), 'r^2');
const kField = CURVE_TYPES.inverse.fields(null)[0];
equal('普通字段：不带指数', fieldSliderText(kField), 'k');

/* ---------------------------- 三、图例渲染 ---------------------------- */

check('A·sin 不被合成 Asin', prettyEquation('y=A*sin(w*x+p)').includes('A·sin('),
    prettyEquation('y=A*sin(w*x+p)'));
check('分母位保留点号', prettyEquation('y=sin(2pi/T*x)').includes('2π/T·x'),
    prettyEquation('y=sin(2pi/T*x)'));
check('π/2·x 仍保留点号', prettyEquation('y=sin(pi/2*x)').includes('π/2·x'),
    prettyEquation('y=sin(pi/2*x)'));
equal('课本式椭圆渲染', prettyEquation('x^2/a^2+y^2/b^2=1'), 'x<sup>2</sup>/a<sup>2</sup>+y<sup>2</sup>/b<sup>2</sup>=1');
equal('抛物线顶点式渲染', prettyEquation('(y-k)^2=m*(x-h)'), '(y-k)<sup>2</sup>=m·(x-h)');
equal('数字写法未回退', prettyEquation('(y-(1))^2=4(x-(1))'), '(y-1)<sup>2</sup>=4(x-1)');
check('注入仍被转义', !prettyEquation('<img src=x onerror=alert(1)>y=x').includes('<img'),
    prettyEquation('<img src=x onerror=alert(1)>y=x'));

/* ---------------------- 四、每种类型勾满滑块的往返 ---------------------- */

for (const [typeKey, spec] of Object.entries(CURVE_TYPES)) {
    for (const mode of spec.modes ? spec.modes.map((item) => item.key) : [null]) {
        const fields = spec.fields(mode);
        const values = {};
        for (const field of fields) {
            values[field.key] = field.value;
        }
        const sliderKeys = fields.filter((field) => field.sym).map((field) => field.key);
        const equation = composeWith(typeKey, mode, values, sliderKeys);
        const params = {};
        for (const field of fields) {
            if (field.sym) {
                params[field.sym] = sliderValueOf(field, field.value);
            }
        }
        const name = `${spec.label} · ${mode || '默认写法'}`;
        let model = null;
        let reason = '';
        try {
            model = buildModel(equation, params);
        } catch (error) {
            reason = error.message;
        }
        check(`${name}：勾满滑块的方程能解析`, !!model, reason || equation);
        if (model) {
            const swallowed = Object.keys(params).filter((letter) => !model.used.includes(letter));
            check(`${name}：每个滑块字母都没被当成已知符号`, !swallowed.length, `被吞的：${swallowed}｜${equation}`);
        }
    }
}

equal('小写 e 仍是自然常数', buildModel('y=ex').used.length, 0);
check('大写 E 是参数（圆一般式要用它）', JSON.stringify(buildModel('y=Ex', {E: 3}).used) === '["E"]',
    JSON.stringify(buildModel('y=Ex', {E: 3}).used));
close('大写 E 取得到滑块值', buildModel('y=Ex', {E: 3}).explicit(2), 6);

/* ------------------------------ 汇总 ------------------------------ */

console.log(`解析层与拼式层：${ok} 项通过，${failures.length} 项失败`);
for (const failure of failures) {
    console.log(`  ✗ ${failure}`);
}
process.exit(failures.length ? 1 : 0);
