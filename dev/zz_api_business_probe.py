"""业务库只读探测（默认 8069）：只发 GET，不造 Key、不写任何数据。

跑法：
    python dev/zz_api_business_probe.py
    R3YNA_BASE=http://127.0.0.1:8069 python dev/zz_api_business_probe.py

可选（只是使用已有的 Key，不创建）：
    R3YNA_PROBE_KEY=<已有 API Key> python dev/zz_api_business_probe.py

硬断言：ping+Client 200；institution+Client 200 且 ok==true（字段空只 WARN）；
        缺 Client 400；exams/1、schedule、me 无 Authorization 均 401（且不是 404）。
有 R3YNA_PROBE_KEY 时额外：/me 与 /exams 期望 200；带 Key 缺 Client 期望 400。
退出码：0 = 无 FAIL；1 = 有 FAIL 或网络错误。
"""
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

BASE = (os.environ.get('R3YNA_BASE') or 'http://127.0.0.1:8069').rstrip('/')
HDR = 'X-R3ynA-Client'
PROBE_KEY = (os.environ.get('R3YNA_PROBE_KEY') or '').strip()

passed = 0
warned = 0
failed = []

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def log(msg):
    print(msg)


def check(name, cond, detail=''):
    global passed
    if cond:
        passed += 1
        log('PASS %-38s %s' % (name, detail))
    else:
        failed.append(name)
        log('FAIL %-38s %s' % (name, detail))


def warn(name, detail):
    global warned
    warned += 1
    log('WARN %-38s %s' % (name, detail))


def call(method, path, client=True, key=None):
    if method != 'GET':
        raise ValueError('只允许 GET：探测脚本禁止写操作')
    headers = {}
    if client:
        headers[HDR] = 'probe-readonly'
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(BASE + path, headers=headers, method='GET')
    try:
        with opener.open(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def as_json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None


def main():
    log('BASE=%s (read-only)' % BASE)
    try:
        # 多库没绑会话时自定义路由一律 404
        opener.open(BASE + '/web?db=OdooForDB', timeout=20).read()
    except Exception as exc:  # noqa: BLE001
        log('FATAL 绑库会话失败: %r' % (exc,))
        return 1

    status, _ = call('GET', '/r3yna/api/ping', client=True)
    check('ping + Client -> 200', status == 200, '-> %s' % status)

    status, raw = call('GET', '/r3yna/api/public/institution', client=True)
    body = as_json(raw) or {}
    check('institution + Client -> 200', status == 200, '-> %s' % status)
    check('institution ok == true', body.get('ok') is True, '-> %r' % body.get('ok'))
    inst = body.get('institution') or {}
    for field in ('intro', 'phone', 'email', 'address', 'lat', 'lng'):
        if not inst.get(field):
            warn('institution.%s' % field, '空（只 WARN）')
    for section in ('services', 'team', 'subjects'):
        if not body.get(section):
            warn('institution.%s' % section, '空（只 WARN）')

    status, _ = call('GET', '/r3yna/api/ping', client=False)
    check('ping 缺 Client -> 400', status == 400, '-> %s' % status)

    for path in ('/r3yna/api/exams/1', '/r3yna/api/schedule', '/r3yna/api/me'):
        status, _ = call('GET', path, client=True, key=None)
        check('%s 无 Key -> 401' % path, status == 401, '-> %s' % status)
        check('%s 不是 404（路由已注册）' % path, status != 404, '-> %s' % status)

    if PROBE_KEY:
        status, raw = call('GET', '/r3yna/api/me', client=True, key=PROBE_KEY)
        body = as_json(raw) or {}
        check('me + 已有 Key -> 200', status == 200, '-> %s' % status)
        if status == 200:
            log('     role=%r user=%r' % (body.get('role'), (body.get('user') or {}).get('login')))
        status, raw = call('GET', '/r3yna/api/exams', client=True, key=PROBE_KEY)
        body = as_json(raw) or {}
        check('exams + 已有 Key -> 200', status == 200, '-> %s' % status)
        if status == 200:
            log('     exams pager=%r' % (body.get('pager'),))
        status, _ = call('GET', '/r3yna/api/me', client=False, key=PROBE_KEY)
        check('me + Key 但缺 Client -> 400', status == 400, '-> %s' % status)
    else:
        log('SKIP R3YNA_PROBE_KEY 未设置（脚本不创建 Key）')

    log('RESULT passed=%d failed=%d warnings=%d %s' % (
        passed, len(failed), warned, ('FAILED:' + ','.join(failed)) if failed else 'ALL_GREEN'))
    return 1 if failed else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log('FATAL %r' % (exc,))
        sys.exit(1)
