"""API 路由 ↔ docs/api-contract.md 对拍门禁。

跑法：
    python dev/zz_api_contract_gate.py               # 读工作树 docs/api-contract.md
    python dev/zz_api_contract_gate.py --docs X.md   # 读指定文档（用于故意改坏测试）

当前分支没有 docs/api-contract.md 时，回退到 `git show docs/api-contract:docs/api-contract.md`。
退出码：0 = 完全一致且三条 40.0 路由都在；1 = 有缺失/多余/必需路由缺席。
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLERS = ('api.py', 'schedule.py', 'public_api.py')
DOC_DEFAULT = os.path.join(ROOT, 'docs', 'api-contract.md')
DOC_BRANCH = 'docs/api-contract'

# 40.0 / 39.2 必做主线：代码与文档都必须有
REQUIRED = {
    ('GET', '/r3yna/api/exams/<id>'),
    ('POST', '/r3yna/api/mistakes/<id>/review'),
    ('POST', '/r3yna/api/schedule'),
}

ROUTE_RE = re.compile(r"@http\.route\(\s*(.*?)\)\s*\n\s*def\s+(\w+)", re.S)
PATH_RE = re.compile(r"['\"](/[^'\"]*)['\"]")
METHODS_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")
DOC_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*(GET|POST)\s*\|\s*`([^`]+)`\s*\|", re.I)


def norm(path):
    """`<int:exam_id>` 与 `<id>` 归一成同一个占位符，只比形状不比变量名。"""
    return re.sub(r"<[^>]+>", "<id>", path.strip())


def parse_code():
    routes = set()
    per_file = {}
    for name in CONTROLLERS:
        path = os.path.join(ROOT, 'server', 'addons', 'tutoring_center', 'controllers', name)
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        found = []
        for match in ROUTE_RE.finditer(text):
            args = match.group(1)
            path_match = PATH_RE.search(args)
            if not path_match:
                continue
            route_path = norm(path_match.group(1))
            methods_match = METHODS_RE.search(args)
            methods = ([q.upper() for q in QUOTED_RE.findall(methods_match.group(1))]
                       if methods_match else ['GET'])
            for method in methods:
                routes.add((method, route_path))
                found.append((method, route_path))
        per_file[name] = found
    return routes, per_file


def parse_docs(text):
    routes = set()
    for line in text.splitlines():
        match = DOC_ROW_RE.match(line.strip())
        if match:
            routes.add((match.group(1).upper(), norm(match.group(2))))
    return routes


def load_docs(path):
    if path:
        with open(path, encoding='utf-8') as fh:
            return fh.read(), path
    if os.path.exists(DOC_DEFAULT):
        with open(DOC_DEFAULT, encoding='utf-8') as fh:
            return fh.read(), DOC_DEFAULT
    try:
        out = subprocess.run(
            ['git', '-C', ROOT, 'show', DOC_BRANCH + ':docs/api-contract.md'],
            capture_output=True, text=True, encoding='utf-8', check=True)
        return out.stdout, 'git:' + DOC_BRANCH
    except Exception as exc:  # noqa: BLE001
        print('FATAL 找不到 docs/api-contract.md（工作树与 %s 分支都没有）: %r' % (DOC_BRANCH, exc))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='API 路由与契约文档对拍')
    parser.add_argument('--docs', help='契约文档路径（默认工作树，缺失时回退 git 分支）')
    args = parser.parse_args()

    code, per_file = parse_code()
    text, source = load_docs(args.docs)
    docs = parse_docs(text)

    missing_in_docs = sorted(code - docs)
    missing_in_code = sorted(docs - code)
    required_missing = sorted(item for item in REQUIRED if item not in code or item not in docs)

    print('代码路由数: %d' % len(code))
    print('文档路由数: %d' % len(docs))
    print('文档来源: %s' % source)
    print('按文件: %s' % ', '.join('%s=%d' % (name, len(items))
                                for name, items in per_file.items()))
    print('缺失（代码有、文档没有）: %s' % (missing_in_docs or '[]'))
    print('多余（文档有、代码没有）: %s' % (missing_in_code or '[]'))
    print('40.0 必需路由: %s' % ('OK' if not required_missing
                              else 'MISSING %r' % required_missing))

    ok = not missing_in_docs and not missing_in_code and not required_missing
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
