"""数学文本渲染器的离线断言（不连库、不连模型，纯函数）。

    cd E:\\Odoo && python/python.exe dev/zz_math_text_check.py
"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location('math_text', os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'server', 'addons', 'tutoring_center', 'models', 'math_text.py'))
math_text = importlib.util.module_from_spec(spec)
spec.loader.exec_module(math_text)

# (输入, 结果里必须有的, 结果里不该再有的)
CASES = [
    # 业务库里错题 30 的真实样本（DeepSeek 抄回来的原样）
    ('变式训练3-3 已知函数$f(x)=\\begin{cases}x+6,x<a,\\\\x^2-4x,x\\geq a.\\end{cases}$'
     '若函数$f(x)$的值域为$\\mathbf{R}$,则实数$a$的取值范围是____.',
     ['分段：x+6（x<a）', 'x²-4x（x≥', '值域为R'],
     ['\\begin', '$', '\\end', '\\geq']),
    ('\\frac{1}{2}', ['(1)/(2)'], ['\\frac']),
    ('解不等式 \\frac{x+1}{x-1} > 0', ['(x+1)/(x-1)'], ['\\frac']),
    ('\\frac{\\frac{a}{b}}{c}', ['((a)/(b))/(c)'], ['\\frac']),
    ('\\sqrt{a^2+b^2}', ['√(a²+b²)'], ['\\sqrt']),
    ('\\sqrt[3]{x-1}', ['3√(x-1)'], ['\\sqrt']),
    ('a_{n+1} = 2a_n - 1', ['aₙ₊₁ = 2aₙ - 1'], ['_{', '}']),
    ('x^{10} 与 x_2', ['x¹⁰', 'x₂'], ['^{']),
    ('\\alpha + \\beta = \\pi', ['α + β = π'], ['\\alpha']),
    ('定义域为 \\left(0,+\\infty\\right)', ['(0,+∞)'], ['\\left', '\\right']),
    ('集合 \\{1,2\\} \\subseteq A', ['{1,2}', '⊆'], ['\\{']),
    ('\\log_2 x 在 \\text{单调递增} 上', ['log₂', '单调递增'], ['\\text', '\\log']),
    ("f'(x) = 3x^2 - 12x + 9，令 f'(x)=0", ["f'(x) = 3x² - 12x + 9"], ['^']),
    ('5 \\le x \\le 8 且 x \\neq 6', ['≤', '≠'], ['\\le', '\\neq']),
    ('不认识的记号 \\pmod{5} 要原样留着', ['\\pmod'], []),
    ('第一行 \\\\ 第二行', ['第一行', '第二行'], ['\\\\']),
    ('', [], []),
]

ok = fail = 0
for src, must, must_not in CASES:
    got = math_text.to_plain_math(src) or ''
    missing = [m for m in must if m not in got]
    leftover = [m for m in must_not if m in got]
    good = not missing and not leftover
    ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print('%s  %r' % ('PASS' if good else 'FAIL', (src or '')[:58]))
    if not good:
        print('      得到 %r｜缺 %s｜该清掉还在 %s' % (got, missing, leftover))

print('\n结果: PASS=%d FAIL=%d' % (ok, fail))
sys.exit(1 if fail else 0)
