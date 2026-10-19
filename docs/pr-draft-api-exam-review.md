# PR 草稿：40.0 考试详情 + 错题复习写口（含 39.2 排课写入口）

> 本文件是给维护者直接粘贴用的 PR 草稿，不是要合并的代码文件。
> 未开 GitHub PR（`gh` 令牌 invalid、浏览器无 GitHub 会话）；合并与 PR 归维护者。

## 分支与版本

- **base**：`main` @ `d30d21c`（`19.0.1.39.1`）
- **head**：`feature/api-exam-review` @ **`bb1c3f1`**
- **版本**：`19.0.1.39.1` → **`19.0.1.40.0`**（其中 `86db033` 先把 39.2 的排课写入口带上来）
- 相对 main 的提交：

```
bb1c3f1 docs: 契约并入 api-exam-review，门禁不再依赖旁支
a2b62d9 test(api): 新增路由契约门禁 dev/zz_api_contract_gate.py
b562339 test(api): 40.0 带 Key 的硬验收脚本（一次性库 22/22 全绿）
ae95f72 feat(api): 考试详情与错题复习写口（19.0.1.40.0）
86db033 feat(schedule): 校长排一节课的写入口 POST /schedule（19.0.1.39.2）
```

合并顺序：先合 `feature/miniapp-schedule-read`（39.2），本 PR 的 base 改回 `main`；
若直接以 main 为 base，diff 会带上 `86db033`。

## 做了什么

1. **`GET /r3yna/api/exams/<id>`**（40.0）
   - `_guard → search → has_access('read')`，取不到（含读不到）统一 404；
   - 主体复用 `_exam_item`，另加 `student_name / remark / lines[]`
     （每条 line：`topic_id / topic_name / score / full_score / percentage`）。
2. **`POST /r3yna/api/mistakes/<id>/review`**（40.0）
   - 调模型已有的 `touch_review()`（与门户整屏流 snooze 同一个方法），不另造状态字段；
   - 需要 `write` 权限；归档题取不到（404，与门户一致）；
   - 响应只回 `due` / `heat`，**不吐** `next_review_at / review_count / last_review_at`。
3. **`POST /r3yna/api/schedule`**（39.2，随本分支带入）
   - 仅校长；`calendar.event` 为真源；建事件时 `no_mail_to_attendees=True`（不发邀请邮件）；
   - 结束必须晚于开始、单节 ≤8 小时、同老师同时段撞车 409。
4. **测试三件套**（按维护者指令例外入库，其余 `dev/zz_*` 仍不入库）：
   - `dev/zz_api_contract_gate.py`：代码路由 ↔ 契约文档对拍门禁；
   - `dev/zz_watch_40_seed.py`：一次性库 fixture（校长/两个门户学生/考试 2 行/错题/3 把 Key）；
   - `dev/zz_api_40_http.py`：带 Key 的真 HTTP 硬验收（22 条断言）。
5. **契约文档已并入**：`docs/api-contract.md`（取自 `origin/docs/api-contract` @ `872ca9b`），
   门禁直接读工作树，不再依赖旁支。

不加字段、不加迁移、不改 XML。

## 怎么验

### 1) 路由契约门禁（不需要数据库）

```bash
python dev/zz_api_contract_gate.py
# 期望：代码路由数 22 / 文档路由数 22、缺失 []、多余 []、40.0 必需路由 OK、exit 0
```

### 2) 一次性库 + 带 Key 的真 HTTP（不碰业务库）

```bash
# 建库（只用自己建的 zz_*）
createdb -h localhost -U openpg -T odoo_template_c zz_watch_40

# 安装 40.0
python/python.exe server/odoo-bin -c server/odoo.conf -d zz_watch_40 -i tutoring_center --stop-after-init --http-port 8899 --db-filter '^zz_watch_40$'

# 造 fixture（校长/两学生/考试/错题/3 把 Key）
PYTHONUTF8=1 python/python.exe server/odoo-bin shell -c server/odoo.conf -d zz_watch_40 --db-filter '^zz_watch_40$' < dev/zz_watch_40_seed.py

# 起 8899 实例
python/python.exe server/odoo-bin -c server/odoo.conf -d zz_watch_40 --http-port 8899 --db-filter '^zz_watch_40$'

# 跑验收
PYTHONUTF8=1 python/python.exe dev/zz_api_40_http.py
# 期望：RESULT passed=22 failed=0 ALL_GREEN，exit 0
```

最近一次结果：**22/22 全绿、exit 0**（2026-10-20 07:06）。
验收后删除自己建的 `zz_watch_40` 与 filestore；**不要动业务库 `OdooForDB`**。

## 未做

- **未开 GitHub PR**（`gh` 令牌 invalid；浏览器打开 compare 页只有 Sign in）；
- **未在业务库验 200**：业务库 `res_users_apikeys` 仍 0、`calendar_event` 仍 0，
  8069 上只验证了"新路由已注册（401）"，没有用真实 Key 打 200；
- **云机未升**：仍 `36.0`；
- 小程序渲染仍未真机验收。
