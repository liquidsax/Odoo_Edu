"""40.0 带 Key 的硬验收（一次性库 zz_watch_40 / 8899）。

跑法：
    PYTHONUTF8=1 python\\python.exe dev\\zz_api_40_http.py
前置：一次性库已 seed（dev/zz_watch_40_seed.py），8899 实例在跑。
输出：.agent/local/overnight/zz_api_40_http.log（完整 stdout）
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_PATH = os.path.join(ROOT, '.agent', 'local', 'overnight', 'zz_watch_40_keys.json')
LOG_PATH = os.path.join(ROOT, '.agent', 'local', 'overnight', 'zz_api_40_http.log')
BASE = os.environ.get('R3YNA_BASE', 'http://127.0.0.1:8899')
HDR = 'X-R3ynA-Client'

lines = []
passed = 0
failed = []


def log(msg):
    print(msg)
    lines.append(msg)


def call(method, path, key=None, client=True, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if client:
        headers[HDR] = 'zz-api-40'
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def as_json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None


def check(name, cond, detail=''):
    global passed
    if cond:
        passed += 1
        log('PASS %-46s %s' % (name, detail))
    else:
        failed.append(name)
        log('FAIL %-46s %s' % (name, detail))


def main():
    if not os.path.exists(KEYS_PATH):
        log('FATAL missing keys file: %s' % KEYS_PATH)
        return 1
    data = json.load(open(KEYS_PATH, encoding='utf-8'))
    keys = data['keys']
    adm, a, b = keys['admin'], keys['a'], keys['b']
    exam_id, mist_id = data['exam_id'], data['mistake_id']
    student_a = data['student_a']
    exam_path = '/r3yna/api/exams/%d' % exam_id
    mist_path = '/r3yna/api/mistakes/%d' % mist_id

    log('BASE=%s exam=%s mistake=%s' % (BASE, exam_id, mist_id))

    # --- 1. 考试详情 ---
    status, raw = call('GET', exam_path, key=adm)
    body = as_json(raw) or {}
    item = body.get('item') or {}
    check('GET /exams/<id> 200', status == 200, '-> %s' % status)
    check('exams.lines >= 1', len(item.get('lines') or []) >= 1,
          '-> %d' % len(item.get('lines') or []))
    check('exams.student_name', bool(item.get('student_name')), '-> %r' % item.get('student_name'))
    check('exams.total_full > 0', (item.get('total_full') or 0) > 0,
          '-> %s/%s' % (item.get('total_score'), item.get('total_full')))

    # --- 2. 越权 / 乱 id -> 404 ---
    status, _ = call('GET', exam_path, key=b)
    check('exams: other student 404', status == 404, '-> %s' % status)
    status, _ = call('GET', '/r3yna/api/exams/999999', key=adm)
    check('exams: bad id 404', status == 404, '-> %s' % status)
    status, _ = call('POST', mist_path + '/review', key=b)
    check('review: other student 404', status == 404, '-> %s' % status)

    # --- 3. 认证顺序 ---
    status, _ = call('GET', exam_path, key=None)
    check('exams: no key 401', status == 401, '-> %s' % status)
    status, _ = call('GET', exam_path, key=adm, client=False)
    check('exams: valid key + no client header 400', status == 400, '-> %s' % status)

    # --- 4. 复习写口 ---
    status, raw = call('GET', mist_path, key=a)
    due_before = (as_json(raw) or {}).get('item', {}).get('due')
    status, raw = call('POST', mist_path + '/review', key=a)
    body = as_json(raw) or {}
    item = body.get('item') or {}
    check('POST /review 200', status == 200, '-> %s' % status)
    check('review: due/heat present', 'due' in item and 'heat' in item,
          '-> due=%r heat=%r' % (item.get('due'), item.get('heat')))
    check('review: no schedule fields',
          not any(k in item for k in ('next_review_at', 'review_count', 'last_review_at')))
    status, raw = call('GET', mist_path, key=a)
    due_after = (as_json(raw) or {}).get('item', {}).get('due')
    check('review: due changed True -> False', due_before is True and due_after is False,
          '-> before=%r after=%r' % (due_before, due_after))

    # --- 5. 回归 ---
    status, raw = call('GET', '/r3yna/api/schedule', key=a)
    body = as_json(raw) or {}
    check('GET /schedule as student 200', status == 200, '-> %s' % status)
    check('schedule: role=student', body.get('role') == 'student', '-> %r' % body.get('role'))
    status, _ = call('GET', '/r3yna/api/teachers', key=a)
    check('GET /teachers as student 403', status == 403, '-> %s' % status)
    status, raw = call('GET', '/r3yna/api/teachers', key=adm)
    body = as_json(raw) or {}
    teachers = body.get('items') or []
    check('GET /teachers as principal 200', status == 200, '-> %s' % status)
    check('teachers non-empty', len(teachers) >= 1, '-> %d' % len(teachers))

    # --- 6. SHOULD: 排课写入口 ---
    if teachers:
        teacher_id = teachers[0]['id']
        day = (date.today() + timedelta(days=1)).isoformat()
        base_vals = {
            'teacher_id': teacher_id, 'student_id': student_a,
            'date': day, 'start_time': '10:00', 'end_time': '12:00',
            'tz': 'Asia/Shanghai', 'name': 'zz-watch 40 验收课',
        }
        status, raw = call('POST', '/r3yna/api/schedule', key=adm, body=base_vals)
        body = as_json(raw) or {}
        check('POST /schedule as principal 200', status == 200,
              '-> %s %s' % (status, body.get('error') or ''))
        check('POST /schedule returns item id', bool((body.get('item') or {}).get('id')),
              '-> %s' % (body.get('item') or {}).get('id'))
        status, raw = call('POST', '/r3yna/api/schedule', key=a, body=base_vals)
        body = as_json(raw) or {}
        check('POST /schedule as student 403 not_principal',
              status == 403 and body.get('error') == 'not_principal',
              '-> %s %s' % (status, body.get('error')))
        overlap = dict(base_vals, start_time='10:30', end_time='11:30')
        status, raw = call('POST', '/r3yna/api/schedule', key=adm, body=overlap)
        body = as_json(raw) or {}
        check('POST /schedule overlap 409 overlaps',
              status == 409 and body.get('error') == 'overlaps',
              '-> %s %s' % (status, body.get('error')))
    else:
        log('SKIP POST /schedule: no teacher in /teachers')

    log('RESULT passed=%d failed=%d %s' % (
        passed, len(failed), ('FAILED:' + ','.join(failed)) if failed else 'ALL_GREEN'))
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001
        log('FATAL %r' % (exc,))
        code = 1
    with open(LOG_PATH, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    sys.exit(code)
