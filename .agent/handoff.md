# 工作交接（handoff）

> 记录开始：2026-09-29。本文件只保留**最新且最重要**的信息；
> 完整演进详情按日期记录在 [updates/](updates/) 目录，安装配置见 [ONBOARDING.md](ONBOARDING.md)。

---

## ⚠️ 协作规则（所有协作者 / agent 动手前必读）

1. **开始修改代码之前，先拉取最新代码**：`git checkout main && git pull`；
2. **禁止直接向 `main` 分支推送**：所有修改在**新建分支**上进行——
   - 新功能：`feature/<主题>`（如 `feature/exam-chart`）
   - 问题修复：`fix/<主题>`（如 `fix/portal-403`）
3. 提交信息用中文，说明"改了什么、为什么"；
4. 完成后 push 自己的分支并开 **Pull Request**，由**管理员（liquidsax）审查后合并**；
5. **仓库卫生红线**：不提交真实密码 / 数据库凭据 / `odoo.conf` / 数据库备份 / 学生真实数据 / 截图素材；不硬编码本机绝对路径（用相对路径，文档中用 `%USERPROFILE%` / `%LOCALAPPDATA%` 写法）；
6. 密码类参数一律走环境变量注入（参考 `dev/seed_data.py` 的 `TUTOR_DEMO_PW_A/B`）；
7. **多 agent 并发时先读 [MULTI_AGENT.md](MULTI_AGENT.md)**：核心一条——自己写的功能要自己
   在本机部署 + 真机验完再交出去，不要攒到最后一起测；共享实例（服务、业务库，以及 `E:\Odoo`
   这**唯一一份**工作树——所有 agent 改的是同一个目录，别人一次重启就会带上你未提交的改动）
   同一时刻只允许一个 agent 动，别人占用期间只写不部署。

## 一、项目定位

本机 Odoo 19 社区版（业务库 `OdooForDB`）已改造为 **R3ynA 学习平台**（个人学习数据平台，2026-10-03 由"数学辅导数据中台"改名，`19.0.1.10.0`；**只改显示口径，数据模型未加"科目"维度**，所以 leetcode、科教书这类内容目前仍记在同一套错题/练习册里）：

- 教师端（`admin` 后台）维护学生、知识点、辅导课次、学校考试成绩、错题记录；
- 学生/家长端（portal）在 `/my/learning` 查看学习数据，多学生按门户联系人硬隔离；
- 辅导模式为**纯讲题 120 分钟/节**：不布置作业、不布置在线考试（仅录入在校考试成绩）；作业模型保留但已全面退出界面；
- 网站首页为教育门面，无 ERP/CRM 入口；
- 网站顶栏第三项「函数图像」（`/tools/function-plot`，公开页面）：按曲线类型填题目里的参数自动成图（椭圆/双曲线有「分母式」与「系数式」两种填法），也能自己写方程；预览与图例按数学写法渲染（`prettyEquation()`，上标/π/去括号）；支持缩放平移、悬停读数、画布全屏；纯前端计算、零第三方依赖。**双曲线**弹层里可勾选「画出渐近线（虚线）」，三种写法都从 a、b 反推斜率（实轴在 x 轴是 ±b/a，在 y 轴是 ±a/b，系数式先按 N 的符号归一化出实轴）；**三角函数**弹层可勾选「坐标轴与交点用弧度制（π）表示」：勾上后横竖轴刻度、悬停读数、与两轴的交点都写成 `π/2`、`3π/2`、`−π`（`piStep()` 只在 π 的有理分数里挑步长，横竖轴各按自己跨度取；`drawIntercepts()` 用解析解 `x=(nπ−φ)/ω` 求零点，不是采样近似），不勾就是小数；图例挂一枚 `e = √5/3 ≈ 0.7454` 的标签、弹层预览下方同步显示，数值尽量写成课本根式（`radicalText()`，化不出才退回四位小数）。渐近线是画在主画布上的虚线（`strokeAsymptotes()` + `clipLineToView()` 只画视口内一段，避免斜率大时坐标爆掉），**并附带方程**：虚线旁直接标出方程、图例挂 `渐近线 y = ±(3/2)x` 徽标（悬浮给两条完整方程与斜截式）、弹层预览下方同步显示（`asymptoteLineText()` / `asymptoteSummaryText()` / `asymptoteSlopeIntercept()`）。离心率与渐近线都跟着**曲线对象走**（`addCurve(expr, meta)`）：只有「按类型添加」和预置示例会带上，**自己写方程不带**（未做通用二次曲线识别）。

- **错题记录**（学生不会/做错的题）：来源关联**练习册**（可填页码/题号）、**辣椒难度 2~5 🌶**、系统自动的**记录时刻**＋可手填「发生日期」、可选「错因/备注」——**不记题目内容**（不通过平台做题，只记错了哪道题）；**不设订正状态**（这页只用于记录出处，没人会做完一道题再回网站改状态）。**错题带错因与知识点**（`19.0.1.10.0`）：`cause_id` 指向新模型 `tutoring.mistake.cause`（概念/审题/运算/策略/习惯/其它六类、预置 13 条、`noupdate=1` 可自由增改，后台"错因"菜单维护）；`point_id` 指向知识点树，挑选域按学生年级放开（`student_id.knowledge_grades`），门户 POST 里服务端再校一次年级。`note` 降为"补充说明"。另有三个**不进任何视图**的字段 `last_review_at`/`review_count`/`next_review_at`：打开一次详情＝复习过一次，按 1→3→7→15→30→60 天往后推到期日，门户错题页默认顺序就是"到期最早的排最前"——**学生看不到任何"复习"字样，也不需要维护状态**。**后台错题页已改造为教师友好形态（`19.0.1.8.0`，PR #20）**：默认视图是**按学生分栏的卡片看板**（栏头带难度分布进度条，整卡点击开只读详情弹窗，拖拽/改组全禁）；列表和看板顶部有**统计概览条**（共 N 条/本月新增/高难度/未填错因，除总数外可点击直接切换筛选，`summary_stats()` 取数、自定义 `js_class` 控制器挂载）；视图切换器里还有**图表页签**（柱状按月）；列表 4~5🌶 行标红、搜索加了原生发生日期筛选和基础难度过滤器。要改内容（含难度辣椒）仍走详情页「修改」进编辑弹窗；新建走控制栏「快速记录」（题号可写 `1-5`、`1,3,7` 自动拆多条，「保存并继续」沿用学生/练习册）或「新建错题」；**Excel 式逐行连填仍在学生表单的「错题记录」页签**（那里仍是 `editable="bottom"` 网格）。门户 `/my/mistakes` 已重做为卡片页（`19.0.1.10.0`）：卡片网格 + 搜索 + 带计数的筛选药丸 + **按知识点/错因/月份分组**（点分组标题下钻，条件以胶囊可摘）+ 每页 10/20/50；取数改成服务端 `domain`+`order`+`limit/offset`、统计走 `read_group`（原来是全量 `search()` 后 Python 排序 + 4 次 `search_count`，300 条就废了）；详情页可就地补一句补充说明。**学生可自助添加/编辑自己的错题**（记录规则强制只能本人、不可删）。kanban 卡片模板必须 `t-name="card"`、进度条是 `<progressbar>` 子元素、卡片模板默认拿不到分组字段（要自定义 KanbanRecord 塞 `groupByField`）——细节与新陷阱 18~21 见 [updates/2026-10-03.md](updates/2026-10-03.md)。

- **展示"某一页"而不是整本**（已在本机库升级生效 `19.0.1.6.0` 并完成真机验收；实测数据与细节见 [updates/2026-10-01.md](updates/2026-10-01.md) 末节）：练习册有两个新字段——`page_mode`（`direct`＝填的就是 PDF 页号／`offset`＝填书印刷页码）与 `page_offset`（**53 资料实测：印刷页 + 8 ＝ PDF 页号**，故该书设 `offset` / `8`）。`tutoring.workbook._locate_page()` 把页码翻译成"哪份分册的第几页"，`tutoring.workbook.page` 用 `odoo.tools.pdf.PdfReader/PdfWriter` 只抽出那一页存成小 PDF（**同页多题共用一份缓存**；重传正文或改页码范围即作废该文件的缓存）。为什么要抽：核心 `pdf_viewer` 走 `/web/content?model=&field=&id=`，而该路由**不支持 Range 请求**（全库无 `Accept-Ranges`），直接指整本文件等于把几十 MB 全拉进浏览器才显示一页。抽页失败/越界/没传教材一律只显示一句提示，**不抛异常**（它在计算字段里跑，抛错＝弹窗 500）。

- **知识点是树**：`tutoring.knowledge.point.parent_id` 自关联挂上级（年级 → 专题 → 考点），列表页用「完整路径」列读成 `高中 / 集合、常用逻辑用语与不等式 / 不等式的解法`；社区版列表没有树形折叠控件，所以是平铺 + 路径列。**模块自带一套高中知识点**（`data/knowledge_data.xml`，11 专题 / 87 考点，取自 53A 精讲册目录，`noupdate=1` 所以老师改动不会被升级还原），新装的库开箱就有；年级键值多一个 `'13'` 高中（跨高一~高三的一层），高一/高二/高三学生的挑选域连 `'13'` 一起放开。

- **练习册 / 教材**：列表**不再是可编辑网格**——单击整行打开**只读页中页**（原生 `<list type="object" action="…">`
  把行点击交给 Python 方法），改数值或加行只能走「新建练习册」/「修改」两个明确按钮；一本书可挂**多份 PDF**，
  `tutoring.workbook.file.content` 用 `Binary(attachment=False)` → **正文本机就是 PostgreSQL 的 bytea 列**。
  阅读用核心 `widget="pdf_viewer"`（pdf.js 滚轮翻页，自带上传/换文件/清除），门户学生在
  `/my/learning/workbooks` 只读阅读自己用过的教材。**已在本机库升级生效（`19.0.1.5.0`）并完成真机验收。**
- **大 PDF 要"物理拆、逻辑不拆"**：Odoo 的上传上限实际卡在 **128MiB 请求体**（见陷阱 15），
  base64 换算后**单个文件约 96MB** 就到顶。所以一本厚书按页切成几份挂进同一本书，
  `page_from`/`page_to` 记全书连续页号，阅读台头部「按页码定位」输一个页号 → 自动挑出那份分册
  并跳到它的局部页号（靠 `content_page` 这个核心钩子字段，见 `updates/2026-10-01.md`）。
  《五年高考三年模拟》已按 1–55 / 56–110 / 111–164 页存成 3 份，是这套流程的样板。

- **知识库**（2026-10-05 新增，`19.0.1.12.0`）：每位用户自己的顶层内容空间，**1GB 配额、单文件 ≤64MB**，
  分类（`workbook` 练习册 / `leetcode` / `note` / `doc` / `other`）只是条目上的一个字段，不限制内容类型。
  **练习册是它的一个分类**：`tutoring.workbook.file` 改为委托继承 `tutoring.library.item`
  （`_inherits`，正文与文件名归条目表），所以教材同样占同一份配额、可被搜索打标签、删除即释放。
  后台页面是卡片看板 + 容量条/拖拽上传区（多选、逐条进度）；门户 `/my/library` 用同一个模型。
  配额统计走 `used_bytes()`（SQL 求和 + 先 flush，见陷阱 23），并发靠 `res_users` 行锁串行化同一用户。
  细节与迁移见 [updates/2026-10-05.md](updates/2026-10-05.md)。

核心自定义模块：`server/addons/tutoring_center`（15 个模型，含练习册 `tutoring.workbook`、教材文件
`tutoring.workbook.file`、单页缓存 `tutoring.workbook.page` 与速记向导 `tutoring.mistake.quickadd`，详见根 README）。

## 二、环境与使用方式

| 角色 | 环境 | 说明 |
|---|---|---|
| **协作者** | 原生 Windows 安装（**优先**） | PostgreSQL 18 + Python 3.12 + Odoo 19 源码，完整步骤见 [ONBOARDING.md](ONBOARDING.md) 路径 A |
| **协作者（备选）** | Docker（`docker compose up -d`） | ONBOARDING.md 路径 B，容器内 `edu_dev` 库，数据一次性 |
| **维护者** | 原生 Windows 服务 | Odoo 19 社区版 + PostgreSQL 18（服务 `odoo-server-19.0` / `postgresql-x64-18`），**本机不装 Docker** |
| **使用端（公网）** | 云服务器 + Docker | 与本机完全独立的一套环境。它的地址、目录、口令位置、加固清单与变更史都记在**那台机自己的运维档案** `~/odoo-edu/ops/`（`state.md` / `runbook.md` / `updates/`，权限 700/600，不在仓库内）；本仓库只留可复用的技术结论（陷阱 18、`updates/2026-10-01.md`） |

两套环境数据完全隔离。维护者环境的详细安装/陷阱见根 README 与 `updates/2026-09-29.md`。

> **本机形态（2026-10-03 逐项实测校准）——`E:\Odoo` 就是唯一真源，一切从这里开始**：
> 这个目录既是本仓库的主工作树（`git worktree list` 第一项），也是正在运行的 Odoo 安装目录，
> **不存在第二份需要"同步"的部署副本**。实测：服务 `odoo-server-19.0`（nssm 拉起
> `E:\Odoo\python\python.exe E:\Odoo\server\odoo-bin -c E:\Odoo\server\odoo.conf`）与
> `postgresql-x64-18`（数据 `D:\PostSQL\data`，`psql` 在 `D:\PostSQL\bin`）均在 Running，业务库 **`OdooForDB`**，
> `addons_path` 第二项 `E:\Odoo\server\addons` 就落在仓库工作树里 → 改 `server/addons/tutoring_center`
> 的文件，服务读的就是这一份；`svcctl.ps1`（skill `odoo-service-control`）**在本机可用**。
> 但**改文件 ≠ 生效**：Python 变更必须重启服务，XML/QWeb/JS 变更必须 `-u` 重建资产包（见第四节）。
>
> **（2026-10-05 补充）别的 worktree 不算数**：`git worktree list` 里除 `E:/Odoo` 外还有几个
> 工作树（含 WorkBuddy 的 `C:\Users\lenovo\WorkBuddy\Worktrees\Odoo\main-*`）。
> 服务只认 `E:/Odoo/server/addons/tutoring_center` 这一份，所以**在别的 worktree 里改完代码，
> 必须把 `server/addons/tutoring_center/` 同步到 `E:/Odoo` 下才会被加载**（`--addons-path` 另指
> 只对本进程有效，服务进程不受影响）。同步前先把 `E:/Odoo` 的当前内容备份到 `E:\Odoo\backup\` 下，
> 并注意 `E:/Odoo` 自己可能正 checkout 在别人的分支上且有未提交改动。
> 另：本机业务库确为 `OdooForDB`（`edu_native` 在本机不存在，是云机/别处的库）。
>
> 2026-10-01 曾在这里记过一套"开发模式"形态（`E:\Odoo\odoo19` + venv + `edu_native` + `start-odoo.bat`
> 前台跑 `--dev`、无 Windows 服务、`addons_path` 指向 `E:/workspace/Odoo_Edu`），**本机复核不成立**——
> 磁盘上没有 `odoo19/`、`E:\Odoo\odoo.conf`、`pgsql/`、`pgdata/`、`start-odoo.bat`。那描述的是别处的另一份副本；
> 协作者照 [ONBOARDING.md](ONBOARDING.md) 自装的机器可能是那种形态，动手前先按上面几行判自己在哪台机器上。

## 三、当前数据与账号（维护者本机）

| 对象 | 事实 |
|---|---|
| 学生"表弟"（id 2） | 初一，已**结课**；5 次课、2 场考试（78%/85%）、3 条掌握、7 条错题（演示） |
| 学生"小明"（id 4） | 初一，**真实数据**，总课次 20 |
| 学生"示例学生B"（id 3） | 初二，隔离验证用，可删 |
| portal 账号 | `biaodi`（表弟）、`student02`（示例学生B）；密码见本地密码记录，**不入库** |
| 知识点 | 初一 5 个演示数据；模块另自带高中库 98 条（11 专题 / 87 考点）——**业务库尚未升级，升级后才落库** |
| 练习册 | 「53」「一数」「课内/其他」3 本（错题数 7/7/1，按 表弟/小明 计）；教材文件 3 份（《53》按 1–55 / 56–110 / 111–164 页拆的三份） |

容器演示环境的账号由 `dev/seed_data.py` 创建（`biaodi` / `student02`，密码环境变量注入）。

## 四、维护者高频操作要点

> 服务启停与体检**统一走 Qoder skill `odoo-service-control` 的 `svcctl.ps1`**（命令、UAC 规则、六层 `check`、失败判读见 [service-control.md](service-control.md)），不要手搓 `Start-Service` / `Stop-Service`。

1. **没有"部署副本"要同步**：`addons_path = E:\Odoo\server\odoo\addons,E:\Odoo\server\addons`，第二项所在的 `E:\Odoo` **就是仓库主工作树**，服务加载的正是你手里在编辑的这份文件。合并到 main 之后只需 `git pull`；**不要用 `cp -a` 往哪儿盖**——历史上那套"备份副本 → `diff --strip-trailing-cr` → 整份覆盖"已作废，真去覆盖只会把 `git status` 弄脏，让下一个人分不清哪些是真改动。动手前先 `git status`：这一份目录所有 agent 共用，别人未提交的 WIP 会被你一次重启一起加载进内存。要留底就把模块整份复制到 `E:\Odoo\backup\` 下（**别放进 addons_path 目录**，带 `__manifest__.py` 的目录会被当模块扫出来）。
2. **标准升级**（Python 变更必须走）：`svcctl.ps1 stop odoo`（UAC）→ `"E:\Odoo\python\python.exe" "E:\Odoo\server\odoo-bin" -c odoo.conf -d OdooForDB -u tutoring_center --stop-after-init` → `start odoo`。
3. **纯 XML/数据变更免重启**：`PYTHONUTF8=1 odoo-bin shell -c odoo.conf -d OdooForDB < E:\Odoo\dev\upgrade_via_rpc.py`，脚本内 `button_immediate_upgrade()`，运行中服务经 signaling 自动重载。**必须带 `PYTHONUTF8=1`**：脚本有中文注释，默认按控制台代码页读 stdin 会 `UnicodeEncodeError: surrogates not allowed`。
4. **硬限制**：运行中的服务无法加载新增 Python 模型类/控制器，必须重启；纯字段/视图变更无此限制。
5. **前端资产（`static/src` 的 JS/CSS）改动也走标准升级**：资产包只在模块升级时重建，改完刷新页面看不到变化（实证见 `updates/2026-09-30.md`）。
6. 服务体检：`svcctl.ps1 check` 六层；日志 UTC（本地 UTC+8）。

## 五、最重要陷阱（正文 19 条；20~22 见 updates/2026-10-03.md，23~25 见 updates/2026-10-05.md）

> 编号在几份文档里有过错位，以"见哪份 updates"为准：知识库那次新增的三条写在
> [updates/2026-10-05.md](updates/2026-10-05.md) 第六节（委托继承的字段搬运、
> stored compute 要 flush 才能 SQL 统计、`@api.model` 方法不能用记录调用）。

1. `db_template = odoo_template_c` **不可改回 template0**（Windows 上 collate≠ctype 库无法连接，已存在库只能删库重建）；
2. `_sql_constraints` 在 Odoo 19 已弃用，用 `models.Constraint('unique(...)', '消息')`；
3. chatter 写法：表单内直接 `<chatter/>`，旧式 `oe_chatter` div 会被当普通子列表渲染；
4. 视图优先级：核心视图 `base.view_partner_form` 为 priority=1，自定义默认视图需 **priority=0** 才能稳定胜出；
5. 若单独升级 `project`/`contacts`/`portal`/`base`，门户卡片/联系人视图指回/菜单隐藏可能复位，**重跑 `tutoring_center` 升级即恢复**；
6. 删除账号后残留会话会导致浏览器 403，全量清 `%LOCALAPPDATA%\OpenERP S.A\Odoo\sessions\` 即可；
7. git：`.gitignore` 的 `*` 不匹配点开头文件；且本地 Odoo 源码树 `server/.gitignore` 的否定行已移除（详见 updates，重装 Odoo 源码需重做）；
8. **画布/交互容器上对 `pointerdown` 调 `preventDefault()` 会抑制浏览器合成的 `mousedown`/`click`/`dblclick`**——容器内按钮会彻底点不动（本项目「函数图像」页的全屏/重置按钮就栽在这）。前端交互控件必须**真实点击**验收，脚本里的 `element.click()` 合成事件会掩盖此问题（细节见 `updates/2026-09-30.md`）。
9. **用了别人模块的记录就必须声明依赖，否则只有维护者的库能装**——`<record id="contacts.action_contacts">`、`inherit_id="project.*"` 这类写法在**全新库**上直接报 `The ID "…" refers to an uninstalled module` 并中断安装；维护者的库因为从完整 ERP 演示库改造而来，那些模块本来就装着，所以永远发现不了。纯清理/装饰性的跨模块引用不要写死 XML，用容错函数（`env.ref(..., raise_if_not_found=False)`，见 `models/ir_ui_menu.py`、`models/ir_ui_view.py`）。**每次改模块后要用一次性新库跑一次 `-i tutoring_center` 才算验收**（细节见 `updates/2026-09-30.md`）。
10. **门户 QWeb 表单/分页两个坑**：① 表单取 CSRF 令牌要用 `request.csrf_token()`，裸 `csrf_token()` 未注入上下文会 `KeyError` 直接 500；② 列表分页器写 `<t t-call="portal.pager"/>`（`pager` 走上下文），误用 `<t t-out="pager"/>` 会把 `{'page_count':…}` 字典原样打印到页面底部（错题/课次/作业/考试四处已统一修正）。给已有行的表加**必填**字段时，Odoo 升级只会延迟并降级 NOT NULL 约束（不中断），但要用数据阶段 `<function>` 先回填存量行，收尾约束才干净生效（见 `data/mistake_data.xml`）。
11. **Selection 键值按字符串排序，选项定义顺序不算数**——`_order` 与 `read_group` 分组都按**值**比较，`'10' < '7'`，所以两位数键值会把「高一」排在「初一」之前（知识点页默认按年级分组，正是用户天天看的那一屏）。年级键值已统一**补零**为 `07~13`（`13`=高中，跨高一~高三的知识点层）（见 `models/tutoring_knowledge.py` 的 `GRADE_SELECTION`，学生与知识点共用一份定义）；改键值必须配 `migrations/<版本>/pre-migrate.py` 把存量行一起补零，`19.0.1.2.0` 已处理 `tutoring_student`、`tutoring_knowledge_point`（细节与实测见 `updates/2026-10-01.md`）。
12. **列表控制栏按钮的两个死法**：① 按钮方法上加 `@api.model` 必报 `TypeError: takes 1 positional argument but 2 were given`——`call_kw` **只对带 `@api.model` 的方法跳过 ids**，而 `/web/dataset/call_button` 恒以 `[ids]` 为首个位置参数（空选区是 `[[]]`），于是实际调用成 `method(recs, [])`；② `icon` 只认 `fa-`/`oi-` 前缀（`ViewButton.iconFromString` 把其余一律当图片 `src`），写 `icon="fa fa-magic"` 就是一个破图，正确写法 `icon="fa-magic"`。想在列表页放**常驻**按钮，用 `<header><button name="..." type="object" display="always"/>`（19 原生渲染进 `control-panel-always-buttons` 插槽），不必 patch `web.ListView.Buttons`。
13. **并发时对共享业务库跑 `-u` 会吃掉别人的迁移**：Odoo 执行迁移脚本的区间是 `(ir_module_module.latest_version, 新 manifest 版本]`。两路同时把版本写成 `19.0.1.2.0`、而年级补零迁移挂在 `migrations/19.0.1.2.0/`，本方为验收先升级了 `OdooForDB`，`latest_version` 就越过了那个目录，合并后那次统一升级会**静默跳过**对方的迁移（存量 `'7'/'8'` 不补零 → 新键值 `'07'/'08'` 显示为空、分组乱序）。规则：别人有未合并改动时**不要升级业务库**；必须升级则事后核对 `latest_version`，必要时 `UPDATE` 回退一格（详见 `updates/2026-10-01.md`）。

14. **自定义字段组件的 import 必须写绝对别名**——照抄核心文件里的相对路径（如 `from "../standard_field_props"`）会被 `js_transpiler` 按**你自己的模块**解析成 `@tutoring_center/standard_field_props`，该模块不存在 → 整个组件文件加载失败，页面只留一行 `Missing widget: chili for field of type selection` 的 console 警告并**静默回退成默认 widget**（难度列照样显示 🌶🌶🌶，肉眼看不出差别）。跨模块一律写 `@web/views/fields/standard_field_props`；验收要确认自定义类名（如 `.o_tutoring_chili`）真的出现在 DOM 里，而不是"看起来正常"。另：编译后的资产包是 `ir.attachment` 里的 `web.assets_backend.min.js/.css` 两条缓存，只在收到 assets 失效信号时重建——就地升级 `button_immediate_upgrade()` 会重载 registry 但**不**触发该信号，删掉这两条 attachment 即可让下次请求按磁盘新代码重新生成（纯派生缓存，不用停服）。
15. **Binary 默认不在库里、进库也是 base64、上传天花板是 96MB 而不是 128MB**：19 里 `fields.Binary` 的 `attachment` 默认 `True` → 正文进 `ir.attachment`，而 `ir.attachment.location` 默认 `file` → **字节在磁盘 filestore，库里只有元数据**；要"文件就在 PostgreSQL"必须写 `attachment=False`（列变 `bytea`），但 bytea 里存的是 **base64 文本**，实测 7497 字节的 PDF 占 `octet_length=9996`，**库体积 ≈ 文件的 4/3**。更坑的是上传上限：`odoo/http.py` 给每个请求硬设 `max_content_length = 128MiB`，而请求体是在 `_serve_db` 判定只读性时就被读掉的（`web/controllers/dataset.py` → `request.get_json_data()`），**早于** `base/ir_http._pre_dispatch` 里用 `web.max_file_upload_size` 覆盖上限的那句——所以**这个系统参数对 `/web/dataset/*` 的写无效**，只抬得动浏览器第一道检查。结论：单个文件超过 **≈96MB**（128MiB ÷ 4/3）就必须拆，且几份不能攒在一次保存里一起提交。反面代价另记：`bin_size` 对非 attachment 列是**先全量读再算体积**，任何"按 content 过滤 / 显示大小"都会把整本 PDF 拉进内存；Binary 默认 `prefetch=False`，列表页只显示行数据是安全的。
16. **后台弹窗的四个原生机制**（省掉一整层自定义 JS，细节见 `updates/2026-10-01.md`）：① 列表整行点击可直接交给 Python 方法——`<list type="object" action="方法名">`（19 原生，`base/rng/list_view.rng` 已声明这两个属性），方法返回 `target='new'` 即"页中页"，且列表在弹窗关闭后会自动 `root.load()`（实测上传完计数列自己变了）；但**弹窗叠几层不可依赖**：点文件行是叠在下层之上、点「上传教材」是替换掉下层，按"关掉可能回下层也可能回列表"来测；② 弹窗尺寸走 context 键 `dialog_size`（`extra-large|large|medium|small`），**但 context 的 `footer: False` 只能配 client action**——给表单弹窗用它，Dialog 连 `<footer>` 节点都不生成，表单按钮插槽的 portal 找不到目标，直接 `OwlError: invalid portal target`，而且服务端全是 200、只能看浏览器 console；想让表单弹窗不出"保存/放弃"，就在 arch 里写显式 `<footer>`（`form_compiler.compileFooter` 只有在 `footer@replace` 为假值时才追加 `DefaultButtonsSlot`）；③ `target='new'` 的表单弹窗里**已存在记录默认按只读渲染**（上传键与保存都不出现），改脏后才出现保存/放弃——"打开就是看、要动就动手"是天然分层的；④ 上传组件的配套 `filename` 字段**必须 `invisible="1"`（列表里 `column_invisible="1"`）**，写成 `readonly="1"` 就不进保存载荷、落库 NULL（核心 `hr_skills`/`l10n_in` 同款写法）。另外：可编辑网格里单击单元格是"进编辑态"，`<list action=… type=…>` 的行点击在那儿**不触发**，要开弹窗必须放显式 `<button>`。

17. **SQL 判重约束：换定义可以，换属性名会留幽灵**——Odoo 19 的 `Constraint.apply_to_database` 拿库里的定义与代码比对，不同就 `DROP` 再 `ADD`（知识点判重从 `unique(name, grade)` 换成含 `parent_id` 已实测生效）；但它只遍历模型**当前声明**的表对象，属性名一改旧约束就没人认领、永久留在库里继续拦数据，所以改定义时保持 `_name_grade_uniq` 这个名字别动。另注意 `unique(..., parent_id)` 里 NULL 互相视为不同——**枝干层（无上级）重名数据库不管**。

18. **Odoo 不能挂在子路径下（`domain/edu` 这种一律不通）**——它生成的资源与表单 URL 全是根相对路径（实测登录页里 `href="/web/static/src/…"`、`action="/website/search"`），套前缀后这些请求会打到同域名的别的应用上；JS 运行时拼出的 `/jsonrpc`、`/web/dataset/*` 连 `sub_filter` 都改不动。`proxy_mode` / `web.base.url` 只处理主机名，**公网部署必须用独立主机名（子域名）**。反代三件套必须齐：`X-Forwarded-For` + `X-Forwarded-Proto` + `X-Forwarded-Host`，且 `proxy_mode = True`——否则登录防爆破按来源 IP 计数（`res_users.py:1283-1303`，默认 5 次失败 / 60 秒冷却）会把所有访客当成同一个人，一人连错全员被关；Odoo 用 `ProxyFix(x_for=1, x_proto=1, x_host=1)`（`http.py:189-190`）。另两条：没配 SMTP 就把 `auth_signup.reset_password` 设 `False`（否则那页面 200 却永远发不出信，实测 `mail_mail.state=exception`）；`ports` 收回 `127.0.0.1:8069:8069` 才是真不泄露端口（compose 里 `ports` 默认合并，要 `!override` 才替换得掉基础文件的写法）。

19. **升级时 `<record id="别的模块.x">` 会被静默跳过**——想改 `website.default_website`、`base.main_company` 这类**由别人模块创建**的记录，在 XML 里写 `<record>` 既不报错也不生效：Odoo 加载升级数据时，凡目标 xmlid 自身带 `noupdate=1`（网站名与公司名恰好都是）就直接跳过。改名实测无效，最后用 `<function model="website" name="_apply_tutoring_branding"/>` 在 Python 里 write 才落库（见 `data/branding_data.xml`）。副作用要知道：**这样每次升级都会盖回模块里这一份**，网站设置里手填的同名项目留不住。两条附带结论：`website.logo`/`favicon` 都是 attachment 型 Binary（库里**没有列**，正文在 filestore），XML 里 `<field type="base64" file="..."/>` 可以写；但 favicon 在 `website._handle_favicon` 里会被 `image_process(..., output_format='ICO')` 过一遍，**源图必须是位图**，给 SVG 会在那一步崩。

## 六、文档索引

| 文档 | 内容 |
|---|---|
| [ONBOARDING.md](ONBOARDING.md) | 协作者安装配置指南（原生 Windows 完整步骤 + Docker 备选 + 自检清单 + 工作流） |
| [MULTI_AGENT.md](MULTI_AGENT.md) | 多 agent 并发协作规范：谁负责部署、独占规则、部署标准动作、版本号礼仪、验收要求、占用声明 |
| [service-control.md](service-control.md) | 服务启停与体检 skill（`svcctl.ps1`）：action/target、UAC 规则、六层 `check`、失败判读、红线 |
| [updates/](updates/) | 按日期的完整更新记录（含维护者原生环境详情、验证记录、陷阱全表） |
| 根 [README.md](../README.md) | 面向人的项目总览、模块概览、快速开始 |
| `docs/R3ynA学习平台使用说明.md` | 面向使用者的操作说明 |

## 七、备份与交付物

- 改造前全量备份：`E:\Odoo\backup\`（数据库 dump + filestore，**不入库**）；
- `dev/`：演示数据、品牌、进程内升级、临时验收账号等脚本（密码均环境变量注入）；
- `docs/`：使用说明 `R3ynA学习平台使用说明.md`（PPT 及截图素材不入库，仅本地保存）；
- `odoo.conf.example`：脱敏配置模板，复制成 `odoo.conf` 再填密码（真配置含密码，不入库）。

> **仓库只跟踪自研内容**（模块 + 文档 + 运维脚本，共 50 余个文件），Odoo 本体源码不入库、由协作者
> clone 上游 19.0 获取。这不是缺陷：已核实维护者本机源码树自安装后**零改动**，换机不会缺项目代码。
