# R3ynA 移动端 API 契约（protocol 1）

> 适用版本：`tutoring_center >= 19.0.1.40.0`（40.0 新增 `GET /exams/<id>`、`POST /mistakes/<id>/review` 与 `POST /mistakes/<id>/ai_summary`）。
> 真源是代码：`controllers/api.py`、`controllers/schedule.py`、`controllers/public_api.py`。
> 本文只写**客户端可以依赖**的东西；响应结构做破坏性变更时要同时改这里与 `api.py` 的 `PROTOCOL` 常量。

## 1. 请求约定

### 1.1 地址与认证

全部挂在 `/r3yna/api/` 下，分三类：

| 类别 | `auth=` | 怎么证明身份 | 说明 |
|---|---|---|---|
| 探活 | `none` | 不需要 | `ping` 只用来判断"服务在不在、协议对不对" |
| 业务接口 | `bearer` | `Authorization: Bearer <Odoo API Key>` | 用户在网页端「偏好设置 → 账户安全」自己生成/吊销；本项目不自建 token 表 |
| 门面 | `public` | 不需要（服务端逐字段白名单） | 给还没有 Key 的潜在客户看的两条；仍然过客户端头 |

**所有路由都要求** `X-R3ynA-Client: <任意非空值>`，它与 CSRF 令牌等效：浏览器跨站请求带不上自定义头。
**状态码要看认证顺序**：

- **bearer 路由**：Key 校验发生在进入控制器之前——没有有效 Key 时先回 **401**（哪怕也缺这个头）；
  带有效 Key 但缺头，才回 **400 `missing_client_header`**；
- **`ping`（`auth='none'`）与门面（`auth='public'`）**：没有 Key 这一步，缺头直接 **400**。

（2026-10-20 业务库路由矩阵实测：19 条 bearer 路由无 Key 全 401；`ping`/门面缺头 400。）

### 1.2 响应信封

成功：

```json
{"ok": true, "protocol": 1, "...": "各路由自己的键"}
```

失败：

```json
{"ok": false, "error": "not_found", "message": "这道题找不到，或者你读不到它。"}
```

`message` 是给终端用户看的中文人话，**可以直接展示**；`error` 是给程序判断的稳定键。

### 1.3 错误码

| HTTP | `error` | 含义 |
|---|---|---|
| 400 | `missing_client_header` / `bad_json` / `bad_body` / `bad_date` / `bad_time` / `bad_teacher` / `bad_student` / `too_long` / `no_file` / `incomplete` / `bad_phone` / `rejected` | 入参问题，改参数可重试 |
| 401 | *(无信封)* | Key 缺失/无效/过期。**见 §5 已知代价** |
| 403 | `not_principal` / `cannot_create` | 身份有、但这个口子不给你 |
| 404 | `not_found` / `student_not_found` / `teacher_not_found` / `mistake_not_found` / `page_unavailable` / `no_content` / `bad_content` | 不存在**或**读不到，两者刻意不区分 |
| 409 | `overlaps` | 排课撞车（同一位老师同一时段已有课） |
| 503 | `booking_unavailable` | 门面预约在没装 CRM 的库里不可用 |

**不区分"越权"与"不存在"**：一律 404。客户端不要靠错误码猜"是不是权限问题"。

### 1.4 分页

列表类接口统一回：

```json
{"pager": {"total": 42, "page": 1, "page_size": 20, "page_count": 3}}
```

`page` / `page_size` 传非法值时**退回默认**（不是报错）：`page` 夹在 1~10000，`page_size` 夹在 1~50（排课列表上限 200）。

### 1.5 范围（`student` / `scope`）

`/summary`、`/sessions`、`/exams`、`/mistakes` 共用一套：

- `?student=<学生档案 id>`：只看这一份；读不到 → `404 student_not_found`；
- `?scope=all`：全部可读范围（老师＝全校学生，但同事的「本人档案」除外；门户账号通常只有自己那份）；
- 都不传：有本人档案就只看本人，否则退回"全部可读"；
- 响应里的 `scope` 回显最终生效的那一档（数字 id / `all` / `mine`）。

### 1.6 日期与时区

- 日期：`YYYY-MM-DD`；没有值一律 `false`（不是 `null`、不是空串）；
- 时间戳：`YYYY-MM-DD HH:MM:SS`，**UTC、无时区后缀**（Odoo `Datetime` 的存储口径）；
- 排课接口额外收 `?tz=Asia/Shanghai`：它决定"哪天"和显示用的时分，响应会把**最终生效的 tz** 与
  `window {"from","to"}` 一起回显。客户端不要自己算本周。

### 1.7 身份

`GET /me` 的 `role` 是全项目**唯一**身份出口：

| `role` | 判据 | 能力 |
|---|---|---|
| `principal` | `base.group_system` | 看全校课表、老师名单、排课 |
| `teacher` | `tutoring_center.group_teacher`；其余内部账号也按这档走 | 只看自己参与的课 |
| `student` | 门户账号 | 只看自己（孩子）参与的课；看不到老师名单 |

客户端**不要**根据学生档案数量或 `is_internal` 自己推断身份。

## 2. 路由总表（23 条）

| # | 方法 | 路径 | 认证 | 用途 |
|---|---|---|---|---|
| 1 | GET | `/r3yna/api/ping` | none | 探活 |
| 2 | GET | `/r3yna/api/me` | bearer | 我是谁 + 我的学生档案 |
| 3 | GET | `/r3yna/api/meta` | bearer | 常量表（难度/错因/筛选/排序） |
| 4 | GET | `/r3yna/api/summary` | bearer | 学习看板四张卡 |
| 5 | GET | `/r3yna/api/sessions` | bearer | 课次列表 |
| 6 | GET | `/r3yna/api/sessions/<id>` | bearer | 课次详情 |
| 7 | GET | `/r3yna/api/exams` | bearer | 考试列表 |
| 8 | GET | `/r3yna/api/exams/<id>` | bearer | 考试详情（**40.0**） |
| 9 | GET | `/r3yna/api/mistakes` | bearer | 错题列表 |
| 10 | GET | `/r3yna/api/mistakes/<id>` | bearer | 错题详情 |
| 11 | POST | `/r3yna/api/mistakes` | bearer | 记一道题 |
| 12 | GET | `/r3yna/api/mistakes/<id>/page.pdf` | bearer | 出处那一页（PDF） |
| 13 | POST | `/r3yna/api/mistakes/<id>/review` | bearer | 看过这道，复习排期前移（**40.0**） |
| 14 | POST | `/r3yna/api/mistakes/<id>/ai_summary` | bearer | 排队一次 AI 摘要 |
| 15 | GET | `/r3yna/api/library` | bearer | 知识库列表 |
| 16 | GET | `/r3yna/api/library/<id>` | bearer | 条目元数据 |
| 17 | GET | `/r3yna/api/library/<id>/raw` | bearer | 条目正文 |
| 18 | POST | `/r3yna/api/library/upload` | bearer | 上传（可带 `mistake_id` 绑图） |
| 19 | GET | `/r3yna/api/schedule` | bearer | 课表 |
| 20 | POST | `/r3yna/api/schedule` | bearer | 排一节课（仅校长） |
| 21 | GET | `/r3yna/api/teachers` | bearer | 老师名单（仅校长） |
| 22 | GET | `/r3yna/api/public/institution` | public | 机构门面整屏 |
| 23 | POST | `/r3yna/api/public/trial` | public | 预约试听留资 |

## 3. 逐条

### 3.1 `GET /ping`
回 `{service: "r3yna-edu", server_time, has_key}`。**不**回库名、版本、账号数。

### 3.2 `GET /me`
`{role, user:{id,login,name,is_internal}, own_student_id, students:[学生简报]}`。
学生简报 = `{id,name,grade,grade_label,school,is_self_profile,partner_id}`。

### 3.3 `GET /meta`
`{difficulties:[{value,label}], causes:[{id,name,category}], causes_readable, filters:[{key,label}], sortings:[{key,label}]}`。
客户端**不要硬编码**这些常量。

### 3.4 `GET /summary`
收 `student`/`scope`；回
`{scope, student, counts:{sessions,exams,mistakes,mistakes_due}, exam_avg, upcoming_sessions:[课次简报], recent_exams:[考试简报]}`。
课次简报 = `{id,student_id,date,duration,topics:[名],has_performance,has_plan}`；
考试简报 = `{id,student_id,name,date,exam_type,exam_type_label,total_score,total_full,percentage}`。

### 3.5 `GET /sessions` / `GET /sessions/<id>`
列表：`{scope, items:[课次简报], pager}`。
详情在简报之上加 `student_name, performance, plan`（HTML 原文）。

### 3.6 `GET /exams` / `GET /exams/<id>`
列表：`{scope, items:[考试简报], pager}`。
详情（40.0）在简报之上加：

```json
{"student_name": "…", "remark": "<p>HTML</p>",
 "lines": [{"topic_id": 1, "topic_name": "…", "score": 80.0, "full_score": 100.0, "percentage": 80.0}]}
```

`lines` 顺序即 `exam.line_ids`；没有明细时是空数组。

### 3.7 `GET /mistakes`
收 `student/scope/filterby/sortby/search/point_id/cause_id/page/page_size`。
`filterby` 与 `sortby` 的合法值由 `/meta` 给出，非法值退回 `all` / `review`。
回 `{scope, filterby, sortby, search, counts:{药丸: 数量}, items:[错题卡片], pager}`。

错题卡片**刻意不含** `next_review_at` / `review_count` / `last_review_at`；
只给派生的 `due`（该不该翻出来）与 `heat`（配色档）。

### 3.8 `GET /mistakes/<id>`
卡片 + `{student_name, question_text, ai_state, ai_hint, recorded_at, page_pdf_ready, library_items:[知识库条目]}`。
归档的题（`archived=true`）仍可按 id 读。

### 3.9 `POST /mistakes`
JSON 体；出处（练习册/页码/题号）可空；题号写 `1-5` 会拆成多条。
成功回 `{created: n, items:[卡片]}`。照片不走这里，见 3.13。

### 3.10 `GET /mistakes/<id>/page.pdf`
回 `application/pdf`（内联，`nosniff`）。抽不出来回 `404 page_unavailable`。

### 3.11 `POST /mistakes/<id>/review`（40.0）
无请求体。调用模型的 `touch_review()`：`review_count` +1、`last_review_at` = 现在、
`next_review_at` 按 1/3/7/15/30/60 天推进。回 `{item: 卡片}`（同样不吐排期三字段）。
需要 `write` 权限；归档的题取不到（404，与门户 snooze 一致）。

### 3.12 `POST /mistakes/<id>/ai_summary`
无请求体。给这道题排一次 AI 摘要任务（`tutoring.mistake.ai.job`）：只建任务，真正调用交给服务端 cron。
需要能读这道题；没有可分析素材回 `400 no_source`，已生成/生成中回 `400 ai_done` / `400 ai_pending`，
当日额度用完等回 `400 ai_not_queued`（message 是人话）。
成功回 `{queued: true, job_id, ai_state: "pending"}`。
小程序在照片全部上传完之后调用，确保视觉模型拿到完整的一组图。

### 3.13 `POST /library/upload`
`multipart/form-data`：`file`（一个或多个）、`category`、`folder_id`、`mistake_id`、`title`、`tags`。
带 `mistake_id` 时**先校验那道题读得到**，否则 404，不会静默存成一张不绑图的条目。
回 `{uploaded:[{id,name,size,size_text}], failed:[{name,error}], quota}`；
**一个文件失败不带走整批**，逐个提交。
配额 1GB、单文件 ≤64MB。

### 3.14 `GET /library` / `<id>` / `<id>/raw`
列表回 `items/pager/filterby/sortby/search/folder/shared_scope/filters/counts/sortings/categories/folders/quota/page_sizes`；
条目 = `{id,name,filename,category,kind,ext,mimetype,size,size_text,upload_date,folder_id,folder_name,tags,mistake_id,mistake_label,is_own,raw_path}`；
详情另加 `from_workbook, share_user_names`。
`raw` 回原始字节；SVG 一律 `attachment` + `nosniff`。

### 3.15 `GET /schedule`
收 `date` / `date_from`+`date_to`（默认本周）/ `teacher`（仅校长）/ `tz` / `page` / `page_size`。
回：

```json
{"role":"principal","scope":"all","tz":"Asia/Shanghai",
 "window":{"from":"2026-10-19","to":"2026-10-25"},
 "items":[{"id":1,"name":"…","allday":false,"start":"2026-10-21 02:00:00","stop":"2026-10-21 04:00:00",
           "date":"2026-10-21","weekday":"周三","start_text":"10:00","stop_text":"12:00",
           "duration_minutes":120,"duration_text":"2 小时 0 分钟",
           "teacher":{"id":2,"name":"…"},"students":["…"],"recurrency":false,
           "is_mine":true,"has_description":false,"location":""}],
 "pager":{...}}
```

非校长传 `?teacher=` → **403**（不静默忽略）。周期事件只回第一次出现的那一节，不展开实例。

### 3.16 `POST /schedule`（仅校长）
JSON：`{teacher_id, student_id, date, start_time, end_time, name?, tz}`。
成功回 `{item: 与 GET 同形的卡片, tz}`。
撞车 409、非校长 403、时段非法 400、单节 >8 小时 400。
建事件时带 `no_mail_to_attendees=True`，**不给参与人发邀请邮件**。

### 3.17 `GET /teachers`（仅校长）
`{items:[{id,name}], count}`。口径是 `group_teacher` 的**显式**成员，不是门面「师资展示」标签。

## 4. 公共门面（`public`）

### 4.1 `GET /public/institution`
一个响应喂整屏：`{institution:{name,intro,phone,email,address,lat,lng,logo},
services:[{id,name,intro,price,currency,category,image}], subjects:[类目名], team:[{name,title,intro,subjects,photo}],
grades:[{value,label}]}`。
真源分别是 `res.company` 的联系人、`type='service'` 的产品模板、「师资展示」标签下的联系人。
**库里这三处为空时，对应数组就是空的**——接口不编内容。

### 4.2 `POST /public/trial`
JSON：`{name*, phone*, grade?, when?, note?, service_id?}`（`*` 必填）。
落 `crm.lead`，不另建咨询表。手机号至少 7 位数字；`service_id` 认不到就当没选。
回 `{ok:true, received:true}`。**没有防刷**（已知代价，见 §5）。

## 5. 已知代价（客户端必须知道）

1. **401 的响应体是核心自带的 HTML，不是我们的 JSON 信封**。Key 缺失/无效时，核心在进入
   我们的控制器之前就抛了 `Unauthorized`。客户端**只能看状态码**，不要尝试解析 body。
2. 401 不会 302 到登录页（`auth='bearer'` 的保证）——这是选 bearer 的理由之一。
3. 公开门面的 `POST /trial` 没有验证码/限流。
4. 门户账号的 API Key 有效期受组的 `api_key_duration` 限制，当前只有 1 Day 一档。

## 6. 变更纪律

- 响应结构破坏性变更 → `PROTOCOL` +1，并同步本文；
- 新增字段（向后兼容） → 只改本文，不动 `PROTOCOL`；
- 新路由 → 先在这一份里写清认证、权限、错误码，再写代码。
