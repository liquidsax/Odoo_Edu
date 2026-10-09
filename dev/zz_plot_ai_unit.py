# -*- coding: utf-8 -*-
"""智能画图里不依赖 Odoo 的部分：表达式校验、模型输出、密钥文件。

    python3 dev/zz_plot_ai_unit.py

表达式是否「画布肯收」会再跟线上那份 function_plot.js 的 buildModel 对一次。
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'server' / 'addons' / 'tutoring_center'


def load(name, relative):
    path = ADDON / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


expr = load('plot_expr', 'models/plot_expr.py')
envfile = load('deepseek_env', 'models/deepseek_env.py')

ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS', label)
    else:
        fail += 1
        print('  FAIL', label, extra)


def eq(label, got, want):
    check(label, got == want, '得到 %r 期望 %r' % (got, want))


print('\n== 描述门槛 ==')
eq('空', expr.prepare_description('  \n')[0], 'empty')
eq('非字符串', expr.prepare_description(None)[0], 'bad_type')
eq('正好 400', expr.prepare_description('椭圆' * 200)[0], 'ok')
eq('超长', expr.prepare_description('椭圆' * 201)[0], 'too_long')
eq('去掉控制符后仍在', expr.prepare_description('椭圆\x00')[1], '椭圆')

print('\n== 方程校验 ==')
SAMPLES = [
    'x^2/9+y^2/4=1',
    'x^2-4*y^2=4',
    'x-2*y-4=0',
    'x^2+y^2=4',
    'y=1/x',
    'y=sin(x)',
    'y=a*x+b',
    'x^2+y^2+D*x+E*y+F=0',
    '(x-1)^2+(y+2)^2=4',
    'y=sqrt(x)',
    'x^2/4+y^2/9=1',
    'y=3*x+b',
    'x²/9+y²/4=1',
    'y=2x',
    'sin(x)',
    'a(x+1)',
    'x',
    'y=A*sin(x)',
    'y=Asin(x)',
    'y=e*x',
    'y=E*x',
    'y=2pi*x',
    'y=（x）',
    'import os',
    '(x^2)/(16)+(y^2)/(7)=1',
    'y=|x|',
    'y=|x-1|',
    'y=2|x|',
    'y=||x|-1|',
    '|x|*|y|=4',
    'y=|sin(x)|',
    'x=|y|',
    'y=|x-a|+b',
    'y=lg(x)',
    'y=arcsin(x)',
    'y=arccos(x)',
    'y=arctan(x)',
]
for sample in SAMPLES:
    try:
        expr.validate_plot_expression(sample)
        check('收下 %s' % sample, True)
    except expr.PlotExprError as exc:
        check('收下 %s' % sample, False, exc)

# 「import os」去掉空格后是一串字母，画布会当成参数乘积，不会执行。
# 服务端必须跟着收下，但不能因此去跑它。带引号和下划线的 __import__ 才是非法字符。
info = expr.validate_plot_expression('import os')
eq('import os 只是参数', info['params'], ['i', 'm', 'p', 'o', 'r', 't', 's'])
REJECTS = ['', '   ', '1+1=2', 'y=sn(x)', 'y=x=1', "y=__import__('os')", 'y=<script>', '只是中文', 'y=x+甲',
           'y=|x', 'y=x|', 'y=|x|+|y']
for sample in REJECTS:
    try:
        expr.validate_plot_expression(sample)
        check('拒绝 %r' % sample, False, '竟然通过了')
    except expr.PlotExprError:
        check('拒绝 %r' % sample, True)

info = expr.validate_plot_expression('x^2+y^2+D*x+E*y+F=0')
eq('一般式参数含 E 不含常数 e', info['params'], ['D', 'E', 'F'])
eq('A*sin 留着振幅', expr.validate_plot_expression('y=A*sin(x)')['params'], ['A'])
eq('Asin 被当成反正弦', expr.validate_plot_expression('y=Asin(x)')['params'], [])
eq('e 是常数', expr.validate_plot_expression('y=e*x')['params'], [])
eq('E 是参数', expr.validate_plot_expression('y=E*x')['params'], ['E'])
eq('竖线不产生参数', expr.validate_plot_expression('y=|x|')['params'], [])
eq('竖线里的字母照旧是参数', expr.validate_plot_expression('y=|x-a|+b')['params'], ['a', 'b'])
eq('lg 不拆成 l 与 g', expr.validate_plot_expression('y=lg(x)')['params'], [])
eq('arcsin 不拆成六个参数', expr.validate_plot_expression('y=arcsin(x)')['params'], [])
eq('竖线合上才收', expr.validate_plot_expression('|x|*|y|=4')['expr'], '|x|*|y|=4')

print('\n== 课本 LaTeX 记号收成画布写法 ==')
eq('\\lvert x \\rvert 收成竖线', expr.normalize_textbook_math('\\lvert x \\rvert'), '| x |')
eq('\\left|\\frac{x}{2}\\right| 收下',
   expr.validate_plot_expression(expr.normalize_textbook_math('\\left|\\frac{x}{2}\\right|'))['expr'],
   '|(x)/(2)|')
eq('\\frac{x^{2}}{16}+\\frac{y^{2}}{9}=1 仍收下',
   expr.validate_plot_expression(expr.normalize_textbook_math('\\frac{x^{2}}{16}+\\frac{y^{2}}{9}=1'))['expr'],
   '(x^2)/(16)+(y^2)/(9)=1')

print('\n== 模型输出 ==')
good = expr.interpret_model_output(
    '```json\n{"found": true, "curves": [{"expr": "x^2/9+y^2/4=1", "label": "椭圆"}]}\n```')
eq('围栏里的椭圆', good['ok'] and good['curves'][0]['expr'], True and 'x^2/9+y^2/4=1')
eq('标签留下', good['curves'][0]['label'], '椭圆')
bad_code = expr.interpret_model_output(
    '{"found": true, "curves": [{"expr": "__import__(\'os\').system(\'id\')"}]}')
eq('不执行代码', bad_code['ok'], False)
eq('代码式子没有漏出去', bad_code['curves'], [])
xss = expr.interpret_model_output(
    '{"found": true, "curves": [{"expr": "y=x", "label": "<script>alert(1)</script>", "params": {"a": 1, "evil": "x"}}]}')
eq('能画的式子留下', xss['ok'], True)
eq('脚本标签丢掉', 'label' not in xss['curves'][0], True)
eq('没出现的参数丢掉', xss['curves'][0].get('params'), None)
seeded = expr.interpret_model_output(
    '{"found": true, "curves": [{"expr": "y=a*x+b", "params": {"a": 2, "b": " -1 ", "c": 9}}]}')
eq('参数只留 a、b', seeded['curves'][0]['params'], {'a': 2, 'b': -1})
off = expr.interpret_model_output('好的 {"found": false, "error": "不是函数图像"} 以上')
eq('画不了', off['code'], 'not_plottable')
eq('原因洗过', off['detail'], '不是函数图像')
eq('带尖括号的原因丢掉', expr.sanitize_reason('<script>'), '')
eq('废话不是 JSON', expr.interpret_model_output('我不会')['code'], 'unparseable')
PROBLEM = (
    '3.椭圆 C: frac{x^{2}}{16}+frac{y^{2}}{7}=1 的两个焦点分别为 F_{1}, F_{2}, '
    '椭圆 C 上有一点 P, 则 triangle P F_{1} F_{2} 的周长为'
)
picked = expr.extract_plot_equations(PROBLEM)
eq('大题里捞出一条', len(picked['curves']), 1)
eq('大题标成椭圆', picked['curves'][0].get('label'), '椭圆')
picked_expr = picked['curves'][0]['expr']
check('捞出的是这条椭圆', '16' in picked_expr and '7' in picked_expr and 'x' in picked_expr and 'y' in picked_expr, picked_expr)
eq('天气里没有方程', expr.extract_plot_equations('今天天气怎么样')['curves'], [])
latex = expr.interpret_model_output(json.dumps({
    'found': True,
    'curves': [{'expr': r'\frac{x^{2}}{16}+\frac{y^{2}}{7}=1', 'label': '椭圆'}],
}))
eq('LaTeX 分式也能收', latex['ok'], True)
check('LaTeX 收成画布写法', latex['ok'] and '16' in latex['curves'][0]['expr'] and '^' in latex['curves'][0]['expr'], latex)
bare = expr.interpret_model_output(json.dumps({
    'found': True,
    'curves': [{'expr': 'frac{x^{2}}{16}+frac{y^{2}}{7}=1'}],
}))
eq('没有反斜杠的 frac 也能收', bare['ok'], True)
eq('图片空', expr.classify_image(b'') , 'empty')
eq('图片没有', expr.classify_image(None), 'absent')
eq('svg 不收', expr.classify_image(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'), 'type')
eq('jpeg 文件头', expr.sniff_image(b'\xff\xd8\xff' + b'\x00' * 16), 'jpeg')
eq('png 文件头', expr.sniff_image(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16), 'png')
eq('太大', expr.classify_image(b'\xff\xd8\xff' + b'0' * expr.MAX_IMAGE_BYTES), 'too_big')
many = expr.interpret_model_output(json.dumps({
    'found': True,
    'curves': [{'expr': 'y=%d*x' % i} for i in range(1, 18)],
}))
eq('最多 16 条', len(many['curves']), 16)
eq('多出来的记一笔', many['truncated'], True)
eq('第 16 条还在', many['curves'][-1]['expr'], 'y=16*x')
partial = expr.interpret_model_output(
    '{"found": true, "curves": [{"expr": "y=x"}, {"expr": "???"}]}')
eq('坏的那条略过', partial['ok'] and partial['skipped'] == 1, True)
split = expr.interpret_model_output(
    '{"found": true, "curves": [{"expr": "y=x", "label": "甲"}]}\n'
    '{"found": true, "curves": [{"expr": "x^2+y^2=1", "label": "乙"}]}'
)
check('两个 JSON 都收下', split['ok'] and len(split['curves']) == 2, split)
eq('第二个 JSON 的圆还在', split['curves'][1]['expr'], 'x^2+y^2=1')
mixed = expr.interpret_model_output(
    '{"found": false, "error": "不是函数图像"}\n'
    '{"found": true, "curves": [{"expr": "y=2*x"}]}'
)
check('拒绝旁边仍有方程就画', mixed['ok'] and mixed['curves'][0]['expr'] == 'y=2*x', mixed)
array = expr.interpret_model_output('[{"expr": "y=x"}, {"expr": "y=x^2"}]')
check('曲线数组也收', array['ok'] and len(array['curves']) == 2, array)
overflow = '\n'.join(
    '{"found": true, "curves": [{"expr": "y=%d*x"}]}' % i for i in range(1, 18))
capped = expr.interpret_model_output(overflow)
eq('多个 JSON 合计最多 16 条', len(capped['curves']), 16)
eq('多个 JSON 多出来记一笔', capped['truncated'], True)

print('\n== 密钥文件 ==')
FAKE = 'sk-TESTKEYONLY0001'
eq('掩码不是全文', envfile.mask_secret(FAKE) == '****' + FAKE[-4:] and FAKE not in envfile.mask_secret(FAKE), True)
eq('空密钥', envfile.mask_secret(''), '未配置')
try:
    envfile.normalize_api_key('short')
    check('过短拒绝', False)
except ValueError as exc:
    check('过短拒绝', FAKE not in str(exc))
try:
    envfile.normalize_api_key('sk-has space-000000')
    check('空格拒绝', False)
except ValueError:
    check('空格拒绝', True)

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, '.env')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('# keep\nOTHER=keep-me\nDEEPSEEK_API_KEY=sk-OLDKEY1234567890\n')
    os.chmod(path, 0o644)
    envfile.write_env_key(path, FAKE)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    # Windows 的 chmod 只认「可写 / 只读」，永远报 0666；0600 这件事只有在 Unix（云机）上验得成
    check('权限 0600', mode == 0o600 or os.name == 'nt', '得到 %o' % mode)
    text = open(path, encoding='utf-8').read()
    check('别的键还在', 'OTHER=keep-me' in text and '# keep' in text)
    check('旧钥匙换掉且只留一行', text.count('DEEPSEEK_API_KEY=') == 1 and FAKE in text)
    check('旧钥匙不在了', 'sk-OLDKEY1234567890' not in text)
    values = envfile.read_env_file(path)
    eq('读回来就是新钥匙', values.get('DEEPSEEK_API_KEY'), FAKE)
    sub = os.path.join(tmp, 'sub')
    os.mkdir(sub)
    link = os.path.join(sub, '.env')
    os.symlink(path, link)
    try:
        envfile.write_env_key(link, FAKE)
        check('拒绝符号链接', False)
    except ValueError:
        check('拒绝符号链接', True)
    try:
        envfile.write_env_key(os.path.join(tmp, 'odoo.conf'), FAKE)
        check('拒绝非 .env 文件名', False)
    except ValueError:
        check('拒绝非 .env 文件名', True)

print('\n== 提示词：给出的方程直接画，该解题时先解出再画 ==')
PROMPTS = {
    'system': (ADDON / 'prompts/plot_system.txt').read_text(encoding='utf-8'),
    'user': (ADDON / 'prompts/plot_user.txt').read_text(encoding='utf-8'),
    'image': (ADDON / 'prompts/plot_user_image.txt').read_text(encoding='utf-8'),
}
for name, text in PROMPTS.items():
    check('%s 要求先把题解完' % name, '先把题解完' in text)
    check('%s 不禁止一切所求' % name, '任何所求' not in text)
    check('%s 不丢后面的求解' % name, '不要回答后面的求解问题' not in text)
check('系统提示保留周长例题', 'frac{x^{2}}{16}' in PROMPTS['system'] and '周长' in PROMPTS['system'])
check('系统提示有求出二次函数的例子', 'y=x^2-2*x+1' in PROMPTS['system'])
check('用户提示仍收描述占位', '%%DESCRIPTION%%' in PROMPTS['user'])
check('识图提示仍收描述占位', '%%DESCRIPTION%%' in PROMPTS['image'])

print('\n== 与前端 buildModel 对照 ==')
probe = r'''
import {mkdtemp, readFile, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
const source = process.argv[1];
const cases = JSON.parse(process.argv[2]);
const stubs = `class Interaction { constructor(el){ this.el = el; } registerCleanup(){} }
const registry = { category: () => ({ add(){} }) };`;
const text = await readFile(source, "utf8");
const patched = text
  .replace('import { Interaction } from "@web/public/interaction";', stubs)
  .replace('import { registry } from "@web/core/registry";', "")
  + "\nexport { buildModel };\n";
const dir = await mkdtemp(join(tmpdir(), "zz_plot_ai_"));
const target = join(dir, "function_plot.mjs");
await writeFile(target, patched, "utf8");
const mod = await import(pathToFileURL(target).href);
const out = cases.map((expr) => {
  try {
    const model = mod.buildModel(expr, {});
    return {ok: true, params: model.used};
  } catch (error) {
    return {ok: false};
  }
});
process.stdout.write(JSON.stringify(out));
'''
cases = SAMPLES + REJECTS
js_source = str(ADDON / 'static' / 'src' / 'function_plot.js')
proc = subprocess.run(
    ['node', '--input-type=module', '-e', probe, js_source, json.dumps(cases)],
    check=False, capture_output=True, text=True,
)
if proc.returncode != 0:
    check('node 对照跑起来', False, proc.stderr[-500:])
else:
    got = json.loads(proc.stdout)
    for sample, row in zip(cases, got):
        try:
            info = expr.validate_plot_expression(sample)
            py = {'ok': True, 'params': info['params']}
        except expr.PlotExprError:
            py = {'ok': False}
        check(
            '前后端一致 %r' % sample,
            py['ok'] == row['ok'] and (not py['ok'] or py['params'] == row['params']),
            'py=%s js=%s' % (py, row),
        )

print('\n%d PASS / %d FAIL' % (ok, fail))
sys.exit(1 if fail else 0)
