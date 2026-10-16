"""接口层（controllers/api.py）的只读冒烟。

跑法（在 E:\\Odoo 下，注意必须带 PYTHONUTF8=1，脚本有中文）：
    PYTHONUTF8=1 python\\python.exe server\\odoo-bin shell -c server\\odoo.conf -d OdooForDB < dev\\zz_api_smoke.py

验三件事：
1. **"借用门户口径"这条设计真的成立**——`TutoringPortal()` 上的筛选/排序/搜索域
   能被实例化后直接调用（它们只读 request.env，不依赖实例状态）；这是本批最容易
   想当然的地方，所以单独测。
2. 三个序列化函数（`_mistake_item` / `_session_item` / `_exam_item`）能拿真记录跑通，
   且**不吐复习排期字段**（口径：学生看不到"复习"字样）。
3. 我用到的字段与常量在模型上确实存在。

不测的（shell 里没有绑定的 `request`，留给升级后的 HTTP 冒烟）：
`_mistake_filter_counts`、以及所有 `api_*` 路由。
"""

FAILURES = []


def check(name, fn):
    try:
        value = fn()
        print("  OK   %s" % name)
        return value
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本，出错就记下来继续
        FAILURES.append("%s → %r" % (name, exc))
        print("  FAIL %s → %r" % (name, exc))
        return None


print("=== 1. 导入接口模块（顺带验路由装饰器语法） ===")
from odoo.addons.tutoring_center.controllers import api  # noqa: E402
from odoo.addons.tutoring_center.controllers.portal import TutoringPortal  # noqa: E402

print("  CLIENT_HEADER=%s PROTOCOL=%s" % (api.CLIENT_HEADER, api.PROTOCOL))
check("常量不是空的", lambda: (_ for _ in ()).throw(AssertionError("空"))
      if not (api.CLIENT_HEADER and api.PROTOCOL) else True)

print()
print("=== 2. 借用门户的取数口径 ===")


class _EnvHolder:
    """只挂一个真 env 的替身，专门喂给门户那些带 `_()` 的方法。

    **为什么需要它**（踩过一次的坑，值得记住）：Odoo 19 的 `_()` 是**顺着调用栈**
    找语言的——`tools/translate.py` 的 `_get_lang()` 会看每一帧里的 `self.env`、
    `context`、`kwargs`，最后才看 `odoo.http.request`。而 `http.Controller.env`
    在没有绑定请求时是 `None`，于是 `_get_uid()` 在 `None.uid` 上抛
    `AttributeError: 'NoneType' object has no attribute 'uid'`。

    结论：**shell / ir.cron 里不能直接调"self 是 Controller 且方法体里有 `_()`"的方法**。
    真实 HTTP 请求里 request 是绑定的，所以线上不会遇到这个问题
    ——这也是为什么这个替身只存在于本冒烟脚本里。
    """

    def __init__(self, env):
        self.env = env


holder = _EnvHolder(env)
today = env['tutoring.mistake']._fields['date'].context_today(env.user)
month_start = today.replace(day=1)

sorts = check("portal._mistake_sortings()",
              lambda: TutoringPortal._mistake_sortings(holder))
if sorts:
    need = {'review', 'recorded', 'date', 'date_asc', 'hard'}
    check("排序白名单齐全 %s" % sorted(sorts), lambda: need.issubset(set(sorts)) or
          (_ for _ in ()).throw(AssertionError("缺 %s" % (need - set(sorts)))))
    check("默认排序 review 带 order 字符串",
          lambda: bool(sorts['review']['order']))

filters = check("portal._mistake_filters(month_start)",
                lambda: TutoringPortal._mistake_filters(holder, month_start))
if filters:
    need = {'all', 'month', 'hard', 'no_cause', 'no_point', 'archived'}
    check("筛选白名单齐全 %s" % sorted(filters),
          lambda: need == set(filters) or
          (_ for _ in ()).throw(AssertionError("实际 %s" % sorted(filters))))

check("portal._mistake_search_domain('复习')",
      lambda: isinstance(TutoringPortal._mistake_search_domain(holder, '复习'), list))

print()
print("=== 3. 复习到期口径（模型上的 _due_domain） ===")
Mistake = env['tutoring.mistake']
due = check("Mistake._due_domain()", lambda: Mistake._due_domain())
check("该翻出来的条数能算（%s 条）" % Mistake.search_count(due or []),
      lambda: isinstance(Mistake.search_count(due), int))
check("NULL next_review_at 按'该看'处理（判据里有 '=' False）",
      lambda: ('next_review_at', '=', False) in [tuple(x) for x in due if isinstance(x, tuple)])

print()
print("=== 4. 用真记录跑三个序列化函数 ===")
sample = Mistake.search([], limit=1)
if sample:
    item = check("_mistake_item(真实错题)", lambda: api.TutoringApi._mistake_item(sample))
    if item:
        banned = {'next_review_at', 'review_count', 'last_review_at'}
        check("**没有**吐出复习排期字段（学生看不到'复习'字样）",
              lambda: not (banned & set(item)) or
              (_ for _ in ()).throw(AssertionError("漏了 %s" % sorted(banned & set(item)))))
        check("卡片口径齐全（id/difficulty/heat/due/photo_count/workbook）",
              lambda: {'id', 'difficulty', 'difficulty_label', 'heat', 'due',
                       'photo_count', 'summary', 'workbook_id', 'workbook_name'}
              .issubset(set(item)) or
              (_ for _ in ()).throw(AssertionError("缺字段：%s" % (item.keys()))))
else:
    print("  -- 库里没有错题，跳过（不影响结论）")

sess = env['tutoring.session'].search([], limit=1)
if sess:
    check("_session_item(真实课次)", lambda: api.TutoringApi._session_item(sess))
else:
    print("  -- 库里没有课次，跳过")

exam = env['tutoring.exam'].search([], limit=1)
if exam:
    check("_exam_item(真实考试)", lambda: api.TutoringApi._exam_item(exam))
else:
    print("  -- 库里没有考试，跳过")

print()
print("=== 5. 我用到的字段确实存在 ===")
need_fields = [
    ('tutoring.mistake', ['library_photo_count', 'ai_readable_summary', 'ai_readable_text',
                          'ai_state', 'ai_hint', 'portal_heat', 'portal_heat_note',
                          'difficulty', 'cause_id', 'point_id', 'active', 'workbook_id']),
    ('tutoring.student', ['is_self_profile', 'exam_avg', 'grade', 'partner_id', 'school']),
    ('tutoring.session', ['date', 'duration', 'topic_ids', 'performance', 'plan']),
    ('tutoring.exam', ['exam_type', 'percentage', 'total_score', 'total_full', 'name']),
]
for model, names in need_fields:
    model_fields = env[model]._fields
    missing = [n for n in names if n not in model_fields]
    check("%s 字段齐全" % model,
          lambda m=missing: not m or
          (_ for _ in ()).throw(AssertionError("缺 %s" % m)))

check("res.users._is_internal 存在", lambda: callable(env['res.users']._is_internal))
check("core 的 make_json_response 存在",
      lambda: callable(__import__('odoo.http', fromlist=['Request']).Request.make_json_response))

print()
if FAILURES:
    print("失败 %d 项：" % len(FAILURES))
    for line in FAILURES:
        print("  ✗ %s" % line)
else:
    print("全部通过")
