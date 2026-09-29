# 工作交接（handoff）

> 记录时间：2026-09-29（含上午改造与下午增量改造，均为实测记录）。
> 本文档客观记录本机 Odoo 实例的改造工作与当前状态，供后续接手者查阅。

---

## 一、项目定位

本机 Odoo 19 社区版（业务库 `OdooForDB`）已被改造为**数学辅导数据中台**（一对一个性化数学辅导场景）：

- 教师端（`admin` 登录后台）维护学生、知识点、辅导课次、学校考试成绩、错题记录；
- 学生/家长端（portal 账号）登录门户查看自己的学习数据（上课安排、成绩趋势、错题、知识点掌握），多学生之间按门户联系人硬隔离；
- 辅导模式为**纯讲题 120 分钟/节**：不布置作业、不布置考试（考试成绩仅录入学生在校考试）；作业模型保留但已全面退出界面；
- 网站首页为教育平台门面，不含 ERP/CRM 相关入口。

## 二、环境与基础设施

### 1. 备份（改造前全量，位于 `E:\Odoo\backup\`）

| 文件 | 内容 |
|---|---|
| `OdooForDB_before_cleanup_20260929.dump` | pg_dump 自定义格式全量备份（4.9M） |
| `filestore_OdooForDB_20260929/` | filestore 目录完整副本（25M） |

### 2. 模块卸载（2026-09-29 上午，共 30 个，已装模块 74 → 44）

- 按需求清单卸载 26 个 + 追加 4 个（`im_livechat`、`mail_bot`、`mail_bot_hr`、`spreadsheet_dashboard_im_livechat`），明细见文档末尾"历史记录"。
- 卸载方式：`odoo-bin shell` 中 `button_uninstall()` 标记 + `odoo-bin -u base --stop-after-init` 执行。

### 3. 配置（`E:\Odoo\server\odoo.conf`）

- `addons_path = e:\odoo\server\odoo\addons,E:\Odoo\server\addons`（自定义模块目录）
- `db_template = odoo_template_c`（**不可改回 template0**，见 README 陷阱一）
- 其余未改动。

### 4. 服务与工具

- 服务 `odoo-server-19.0` / `postgresql-x64-18` 正常运行；`svcctl.ps1 check` 六层体检全绿。
- LibreOffice 26.8.0 已装（`C:\Program Files\LibreOffice\program`）。

## 三、自定义模块 `tutoring_center`

位置：`E:\Odoo\server\addons\tutoring_center`（application，依赖 `portal`、`website`）。

### 数据模型（9 个，标签为中文）

| 模型 | 说明 |
|---|---|
| `tutoring.student` | 学生档案：姓名/年级/学校/状态/备注/`session_planned_count`（总课次，手填，tracking）；`partner_id` 关联门户联系人；含统计计算字段与 chatter |
| `tutoring.knowledge.point` | 知识点：名称 + 年级（7/8/9）+ 说明 + active，同年级名称唯一（`models.Constraint`） |
| `tutoring.student.point` | 学生×知识点掌握：mastery 四档（未掌握/学习中/基本掌握/熟练掌握），学生+知识点唯一 |
| `tutoring.session` | 辅导课次：日期/时长/教学内容 m2m/课堂表现/下一步计划 |
| `tutoring.topic` | 教学内容标签（课次标签用，无独立菜单入口） |
| `tutoring.exam` / `tutoring.exam.line` | 学校考试：类型、日期、明细行、得分率自动汇总 |
| `tutoring.homework` | 作业（**已退出所有界面**，模型保留，历史数据在） |
| `tutoring.mistake` | 错题记录：日期/来源（课内练习/考试/其他）/相关教学内容/题目与错误原因/状态（待订正/已订正） |

### 教师后台

- **顶栏菜单只有两项**：数学辅导 → 学生、知识点（作业/辅导课次/考试成绩/教学内容菜单已删，数据仍可从学生档案页签进入）。
- 学生列表：姓名 / 年级 / 学校 / 状态 / 已上课次 / 总课次。
- 学生表单页签：**知识点掌握**（可编辑列表，按学生年级过滤知识点，直接增删与调档）、**学校考试**、**辅导课次**、**错题记录**、备注；右侧信息栏有总课次/已上课次。
- 课次日历视图、作业/考试图表视图仍存在但无菜单入口。
- **应用根菜单（"应用"）已隐藏**：`base.menu_management` 绑定到组 `tutoring_center.group_show_hidden_apps`（组内默认无人）。讨论/项目/邮件营销/调查/员工/仪表板同样被该机制隐藏；把用户加入该组即可全部恢复。实现：`models/ir_ui_menu.py` 的 `MENUS_TO_HIDE` + `views/menus_cleanup.xml`。

### 联系人（res.partner）改造

- **全局简化视图**（`views/partner_views.xml`，priority=0，所有打开联系人的路径均生效）：
  - 列表：姓名 / 电话（家长） / 学校；
  - 表单：姓名、电话（家长）、学校、关联学生（只读标签）+ chatter；邮箱、人/公司切换、地址、税号、网站、标签、联系人子表、销售采购、工作职位、"任务"按钮全部消失；新建默认"个人"。
- 新字段 `tutoring_school`（学校）：从关联学生档案计算，**在联系人上改动会同步写回学生档案**。
- 联系人应用动作改为 `view_mode: list,form`，两个视图显式指向简化版。
- **注意**：`base.view_partner_form` 优先级也是 1，简化视图必须保持 priority=0（曾因同为 1、按 id 排序导致老表单仍被选中）。

### 学生门户

- **`/my` 行为**：绑定了学生档案的用户访问 `/my` **直接跳转 `/my/learning`**（`home()` 重载）；`/my` 页面只剩"我的学习"卡（项目/任务卡片经停用 `project.portal_my_home` 移除；"地址"、"连接 & 安全"卡片经 xpath 删除——**按卡片 url 属性匹配，不能按标题匹配**，因为 DB 中 arch 是翻译后的中文）。
- **`/my/learning`（我的学习）布局**（自上而下）：
  1. 统计卡×3：已上课次（含总课次进度条）、考试平均得分率、待订正错题；
  2. **考试成绩趋势折线图**（全宽，Chart.js，`web.chartjs_lib`，无外网依赖）；
  3. **上课时间安排**（近期安排=未来课次优先 + 最近上课列表）｜**最近错题**（状态徽章）；
  4. **最近考试**｜**知识点掌握**（四档彩色徽章）。
- 作业相关内容已全部退出门户；`/my/learning/homework` 路由仍在但无入口。
- 未关联学生档案的账号访问 `/my/learning` 显示提示页（`portal_my_learning_empty`），不再跳回 `/my`。
- 控制器继承 `portal.CustomerPortal`，重写 `home()`、`_prepare_home_portal_values`、`portal_my_learning` 等。

### 网站门面

- 首页"数学辅导 · 学习数据平台"门面 + 导航"学习平台"菜单项（指向 `/my/learning`）。
- 品牌：公司名"数学辅导中心"、网站名"数学辅导学习平台"、SVG logo；页脚教育风格。

## 四、当前数据与账号

| 对象 | 事实 |
|---|---|
| 学生"表弟"（id 2） | 七年级，状态已由用户改为**结课**；5 次课、2 场考试（78%/85%）、3 条知识点掌握、2 条错题（演示） |
| 学生"小明"（id 4，真实数据） | 七年级，总课次 20（用户自录）；门户联系人同名为"小明" |
| 学生"示例学生B"（id 3） | 八年级，隔离验证用，账号可删 |
| portal 账号 | `biaodi`（表弟）；`student02`（示例学生B）；密码见本地密码记录，不入库 |
| 知识点演示数据 | 七年级 5 个（有理数及其运算、整式的加减、一元一次方程、几何图形初步、数据的收集与整理） |

## 五、升级/调试操作要点（本次会话实测总结）

1. **标准升级流程**（Python 代码有变更时必须走）：
   `svcctl.ps1 stop odoo`（UAC）→ `"E:\Odoo\python\python.exe" "E:\Odoo\server\odoo-bin" -c odoo.conf -d OdooForDB -u tutoring_center --stop-after-init` → `start odoo`。
2. **纯 XML/数据变更可免重启**：`odoo-bin shell -c odoo.conf -d OdooForDB < E:\Odoo\dev\upgrade_via_rpc.py`，脚本内调 `button_immediate_upgrade()`（等价应用页点升级），运行中的服务经数据库 signaling 自动重载。
3. **进程内升级的硬限制**：运行中的服务**无法加载新增的 Python 模型类/控制器**（sys.modules 缓存），必须重启服务；纯字段/视图变更无此限制。
4. **`_sql_constraints` 在 Odoo 19 已弃用**，用 `models.Constraint('unique(...)', '消息')` 类属性。
5. **Odoo 19 chatter 写法**：表单内直接 `<chatter/>`；旧式 `<div class="oe_chatter">` 塞字段会被当成普通子列表渲染（本次"CRM 页面"问题的根因）。
6. **视图优先级**：Odoo 19 中 `base.view_partner_form` 等核心视图 priority=1，自定义默认视图需 priority=0 才能稳定胜出（平级按 id 排序，老视图 id 小）。
7. **服务会话文件**：`%LOCALAPPDATA%\OpenERP S.A\Odoo\sessions\`。删除已测试账号后其残留会话会导致浏览器 403（"不允许访问 Website 记录"）；全量删除该目录下文件即可（所有人需重新登录）。测试时可用不同主机名（127.0.0.1 / localhost / 127.0.0.2）隔离 cookie。
8. **验收用临时教师账号**：`make_qa_user.py` / `del_qa_user.py`（qa_check，密码经环境变量 `QA_PASSWORD` 注入或运行时随机生成），用完即删。
9. `svcctl.ps1`（`%USERPROFILE%\.qoder-cn\skills\odoo-service-control\scripts\`）：stop/start/restart 触发 UAC；`check` 六层体检；日志 UTC（本地 UTC+8）。

## 六、已知注意事项

1. **project 模块若单独升级**，`project.portal_my_home`（门户"项目/任务"卡片）会被重新激活——重跑一次 `tutoring_center` 升级即恢复隐藏。
2. 若未来升级 `contacts`/`portal`/`base` 模块：联系人动作的视图指回、portal 首页两张卡、应用菜单绑定均可能被复位，重跑 `tutoring_center` 升级即可。
3. 作业模型与历史作业数据仍在（表弟有 5 份演示作业），如需彻底移除需另行处理。
4. `menus_cleanup.xml` 的隐藏逻辑对缺失 xmlid 自动跳过（`env.ref(..., raise_if_not_found=False)`）。
5. 门户账号无邮件邀请可用（未配置 SMTP），初始密码需在用户表单直接设置。
6. 学生"表弟"的门户联系人名叫"小明"（历史数据），如需可改名。

## 七、交付物清单

| 路径 | 内容 |
|---|---|
| `E:\Odoo\docs\数学辅导数据中台使用说明.md` | 使用说明（部分内容已被本次改造超越，以本文档为准） |
| `E:\Odoo\docs\数学辅导数据中台-初创展示.pptx` + `ppt_assets/` | 展示 PPT 及构建脚本、截图素材 |
| `E:\Odoo\dev\upgrade_via_rpc.py` | 进程内升级脚本（shell 中执行） |
| `E:\Odoo\dev\seed_knowledge.py` / `seed_data.py` / `branding*.py` / `contact_cleanup.py` | 演示数据与品牌变更脚本 |
| `E:\Odoo\dev\make_qa_user.py` / `del_qa_user.py` | 临时验收账号脚本 |
| `E:\Odoo\dev\*.html / cookies_*.txt / *.py` 其余 | 历次调试过程产物，可清理 |

## 八、验证记录（本次会话实测通过）

1. 学生列表六列显示、总课次录入与展示（浏览器实测）。
2. 学生表单：知识点掌握增删调档（徽章着色）、学校考试/辅导课次/错题/备注页签、chatter 正常渲染（浏览器实测）。
3. 联系人：列表三列、表单精简、从学生档案"门户账号"按钮进入同样生效、学校字段双向联动、"任务"按钮消失（浏览器实测）。
4. 知识点页：按年级分组、即改即存（浏览器实测）。
5. 门户：biaodi 登录 `/my` 直达 `/my/learning`，新布局各区块渲染正常、折线图真实绘制（浏览器实测）。
6. `/my` 卡片清理、教师账号访问学习页显示提示页（浏览器实测）。
7. 应用切换器仅剩 数学辅导/联系人/网站（浏览器实测）。
8. 每次升级后 `svcctl.ps1 check` 六层体检全绿；无新增 ERROR 日志。

## 九、历史记录（2026-09-29 上午，供追溯）

- 改造前全量备份于 `E:\Odoo\backup\`；卸载 30 个模块（auth_passkey_portal、auth_totp_mail、auth_totp_portal、google_gmail、microsoft_outlook、partner_autocomplete、privacy_lookup、snailmail、mass_mailing_themes、web_unsplash、hr_gamification、hr_homeworking、hr_org_chart、hr_skills_survey、project_todo、project_hr_skills、project_sms、hr_livechat、website_links、website_mail、website_project、website_sms、website_mass_mailing、website_livechat、theme_bewise、api_doc、im_livechat、mail_bot、mail_bot_hr、spreadsheet_dashboard_im_livechat）；品牌数据变更；PPT 制作与 LibreOffice 逐页质检；门户数据隔离双向验证（跨学生 404）。
