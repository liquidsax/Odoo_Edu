"""一键串跑：契约门禁 + 业务库只读探测。

跑法：
    python dev/zz_api_check_all.py

退出码：0 = 两步都 0；1 = 任一步非 0 或脚本缺失。
**不自动跑** dev/zz_api_40_http.py（它依赖一次性库 zz_watch_40 + 8899 实例）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = (
    ('契约门禁', 'dev/zz_api_contract_gate.py'),
    ('业务库只读探测', 'dev/zz_api_business_probe.py'),
)


def main():
    failed = False
    for name, rel in STEPS:
        print('=== %s: %s ===' % (name, rel))
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print('EXIT -1 (missing)')
            failed = True
            continue
        proc = subprocess.run(
            [sys.executable, path], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip())
        code = proc.returncode
        print('EXIT %d' % code)
        if code != 0:
            failed = True

    print('提示: dev/zz_api_40_http.py 需要一次性库 zz_watch_40 + 8899 实例，本脚本不自动跑。')
    print('RESULT: %s' % ('FAIL' if failed else 'ALL_GREEN'))
    return 1 if failed else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
