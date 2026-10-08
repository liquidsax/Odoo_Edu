# 多 agent 并发协作规范

> 本项目通常有**多个 agent 同时加功能**，但共享同一套本机资源：一个 Odoo 服务、一个业务库
> `OdooForDB`、以及 `E:\Odoo` 这**唯一一份工作树**（它就是仓库主检出，也是服务正在加载的代码，
> 没有第二份"部署副本"）。这份文件规定"谁在什么时候可以动共享资源、什么才算交付完成"。
> 动手前先读 [handoff.md](handoff.md) 的协作规则与陷阱清单，本文件只补并发这一块。

---

## 一、核心原则：谁做的功能谁负责验完，不要攒到最后

**每个 agent 必须把自己这块功能在本机部署 + 真机验证完成后才算交付；不要"先都写完，最后一起测"。**

理由（都是踩过的）：

1. 共享实例只有一个。A 写完不部署就走，B 接手时看到的是**旧界面 + 新文档**，会照着没上线的界面去改，
   白干一轮；
2. 更坏的是**半加载**：工作树上的代码已经比库里的 schema 新（或反过来），跑起来就是
   "字段不存在 / 列不存在"的报错。本轮就撞过一次——新模型的 `_order` 引用了还没建的列，
   结果**别人正在用的列表页直接 500**。这种坏状态对别人是无妄之灾；
3. 出错的时机越晚，能怪的范围越大。刚写完的人知道自己动了什么，隔两天的人只能猜。

**"交付完成"的四件套**：代码进分支 → 本机部署并真机点过 → 文档写清"已验/未验" → 分支已 push。
缺任何一件，就在 handoff/updates 里明确标注它**还没做完**，别让人以为线上已经是那样。

## 二、共享资源的独占规则

| 动作 | 是否独占 | 要求 |
|---|---|---|
| 写代码、跑离线校验（`py_compile`、RelaxNG、一次性新库 `-i`） | 否 | 随时可做，不碰 `OdooForDB` |
| 改本机工作树 `E:\Odoo\server\addons\tutoring_center` 的代码 | 否（写）/ **是**（生效） | 写文件不打扰正在跑的实例；但服务加载的就是这一份，别人一次重启会连你未提交的改动一起加载，所以动手前先 `git status` 看清有没有别人的 WIP |
| `svcctl stop/start/restart odoo` | **是** | 提前打招呼要窗口；会弹 UAC；平台短暂下线 |
| `-u tutoring_center`（停服或就地） | **是** | 同上，事后核对 `latest_version` |
| 改系统参数 / `odoo.conf` | **是** | 属配置变更，先说明改什么、为什么、怎么回退 |

别人在占用期间：**只写不部署**。要验证就用自己的新库，别动共享库。

## 三、部署一次的标准动作（照抄即可）

```bash
# 0) 占用声明（见第六节）+ 确认没人正在部署
powershell -NoProfile -ExecutionPolicy Bypass -File \
  "$USERPROFILE/.qoder-cn/skills/odoo-service-control/scripts/svcctl.ps1" status all

# 1) 看清这一份工作树里有没有别人未提交的改动（服务加载的就是这个目录）
git -C /e/Odoo status --short

# 2) 备份当前模块（务必放 addons_path 之外，否则带 __manifest__.py 的目录会被当模块扫出来）
cp -a /e/Odoo/server/addons/tutoring_center \
      "/e/Odoo/backup/tutoring_center_before_$(date +%Y%m%d-%H%M)"

# 3) 升级（有新增 Python 模型类/控制器必须停服；纯 XML/数据可就地）
#    代码不需要往任何地方"同步"——改的就是服务在读的那份文件
#   停服路线：svcctl stop odoo → 下面这条 → svcctl start odoo
cd /e/Odoo/server && PYTHONUTF8=1 \
  /e/Odoo/python/python.exe odoo-bin -c odoo.conf -d OdooForDB \
  -u tutoring_center --stop-after-init

# 4) 体检 + 核对版本号
powershell -NoProfile -ExecutionPolicy Bypass -File \
  "$USERPROFILE/.qoder-cn/skills/odoo-service-control/scripts/svcctl.ps1" check
```

要点：

- **合并到 main ≠ 生效**。代码就在服务加载的那一份目录里，不需要"同步"，但没跑 `-u`（Python 变更还要重启）
  就进不了库、也不会重建资产包；反过来别人一次重启会连你**未提交的改动**一起加载——所以占用声明里要写清工作树是否干净。
- `odoo-bin shell < dev/upgrade_via_rpc.py` 这类带中文注释的脚本在 Windows 上**必须 `PYTHONUTF8=1`**，
  否则 stdin 按控制台代码页读进来会 `UnicodeEncodeError: surrogates not allowed`（在编译阶段就炸，
  不会留下半个写入）。
- 服务进程已经加载了新代码但库还没升级时，**不用停服**：用第二个进程跑一次 `-u --stop-after-init`
  补上 schema 即可（本轮就是这么从坏状态里出来的）。
- 事后必查 `ir_module_module.latest_version` 有没有越过别人挂在中间版本号上的迁移目录
  （handoff 陷阱 13）。

## 四、版本号礼仪

manifest 版本会撞车，而且撞车会**静默吃掉别人的迁移**。改版本号前：

```bash
git fetch origin
for r in $(git for-each-ref --format='%(refname:short)' refs/remotes); do
  printf '%-45s %s\n' "$r" "$(git show "$r:server/addons/tutoring_center/__manifest__.py" | grep -m1 "'version'")"
done
ls server/addons/tutoring_center/migrations/
```

取**比所有分支和 main 都大**的号；自己没迁移就别建 `migrations/<版本>/` 目录。

## 五、验收要求

1. **交互控件必须真机点击**。本项目有过"脚本合成 click 把 `preventDefault` 吞事件掩盖掉"、
   "组件没注册但默认渲染看起来完全正常"两次教训（handoff 陷阱 8、14）。
2. 前端崩服务端可能全是 200：定位顺序是 `svcctl check` → `odoo.log`（UTC，本地 +8）→
   **浏览器 console**。本轮的 `invalid portal target` 只在 console 里看得见。
3. 改完前端资产（`static/src/**`）要确认资产包真的重建了；就地升级不触发失效信号。
4. 门户端验证**别用维护者的浏览器会话**：登录 portal 账号会顶掉当前 admin 会话，而 agent 拿不到
   维护者密码，换不回来。用独立会话打真实路由：
   `POST /web/session/authenticate`（带 `db`/`login`/`password`）拿到自己的 cookie，再 GET
   `/my/learning/...` 与 `/web/content/...`。临时账号验完删干净。
5. 大文件上传：单个文件 ≈96MB 就到顶（handoff 陷阱 15），且**多份不能攒在一次保存里提交**，
   否则请求体是几份 base64 之和，必然 413。

## 六、占用声明（轻量，够用就行）

在本文件末尾"占用记录"追加一行，部署完再改状态。它是一行文本，冲突了随手合一下即可。
不想动文件也可以：在 PR 标题前挂 `[部署中]`，合并后去掉。

## 七、给 agent 的三条硬约束（来自维护者）

1. 不 force-push，不改写已推送的历史；PR 的开与合归维护者，agent 只提交并 push 自己的分支；
2. 生产/共享库的破坏性 SQL 由维护者自己跑；agent 需要跑就写清楚语句并等确认；
3. 真实凭据、`odoo.conf`、数据库备份、学生真实数据一律不入库；密码走环境变量。

---

## 占用记录

| 时间（本地） | 分支 / agent | 动作 | 状态 |
|---|---|---|---|
| 2026-10-01 13:49–17:35 | `feature/workbook-file-reader` | 同步副本 + 两次 `-u`（19.0.1.4.0 → 19.0.1.5.0）+ 真机验收 | 已完成并释放 |
| 2026-10-01 19:32–19:55 | `feature/mistake-page-detail` | 同步副本 + 停服 `-u`（19.0.1.5.0 → 19.0.1.6.0，新增模型 `tutoring.workbook.page`）+ 真机验收 | 已完成并释放 |
| 2026-10-01 22:35–22:52 | 云服务器部署线（`fix/docker-pg18-mount-and-cloud-deploy`） | **只动云机，不碰本机 `OdooForDB`**：clone 切 main、`-u tutoring_center`（19.0.1.0.0 → 19.0.1.7.0，跑 `19.0.1.2.0` pre-migrate）、容器内验收后 stop 下线 | 已完成并释放 |
| 2026-10-01 23:19–23:26 | 部署线（`fix/docker-pg18-mount-and-deploy-notes`） | **共享 `OdooForDB`**：本地 main 快进到 `cdca6cd` 后磁盘代码领先库，走方式一 `-u tutoring_center`（19.0.1.6.0 → 19.0.1.7.0，无迁移区间）、`check` 六层全绿 | 已完成并释放；PR #17 的勾选框**未真机点击验收**（浏览器面板 hidden） |
| 2026-10-05 00:44–01:25 | `feature/knowledge-library`（知识库，19.0.1.12.0） | 同步到 `E:/Odoo` 主工作树的 `server/addons/tutoring_center/`（原内容已备份到 `E:\Odoo\backup\tutoring_center_deployed_20261005-0114`）→ 不停服跑 `-u tutoring_center --stop-after-init`（19.0.1.10.0 → 19.0.1.12.0，执行 post-migrate 把 3 份教材搬进条目表）；业务库已 dump 备份 198MB | 升级已落库，**服务未重启**（UAC 提权被安全策略拦截，需维护者手动 `Restart-Service`），真机验收未做，**不算交付完成** |
| — | 同上 | ⚠️ `E:/Odoo` 主工作树当前 checkout 在 `feature/r3yna-brand-and-mistake-review` 且原本有未提交改动，现在它的 `server/addons/tutoring_center/` 已被换成知识库分支的代码（原状在上述备份里）。该分支的 agent 接手前先 `git status` 确认 | 待维护者处置 |
| 2026-10-05 11:20–14:05 | `feature/library-folders-and-nav`（知识库第二轮：文件夹 + 隐私收口 + 用户端页 + 顶栏入口，`19.0.1.13.0`） | 先只在一次性库上验（安装 + 模型层 + HTTP 56/57）；13:08 拿到窗口后按标准动作部署 `OdooForDB`：备份模块 + 198MB dump → 停服 `-u`（post-migrate 跑过）→ 起服 → `check` 六层全绿 → `latest_version` 核对 = `19.0.1.13.0`；因 SVG 加固再 `restart odoo` 一次；部署后又补删了 6 个历次验收留下的一次性库（先 dump 到 `backup/db_graveyard_2026-10-05/`）。业务库上跑过门户 HTTP 21/21、后台 RPC 14/14 | **业务库已生效**；浏览器里的视觉/真机点击仍挂着，临时账号已删，工作树干净 |
| 2026-10-05 15:00–15:35 | `feature/library-folders-and-nav`（第三轮：Markdown 渲染 + 纯文本就地编辑 + 错题固有类型，`19.0.1.14.0`） | 一次性库 `zz_md_check` 上验完（安装 + 渲染器 20 项 + 模型 6 组 + HTTP 35 项）→ 业务库：模块备份 + 198MB dump → 停服 `-u`（post-migrate 重算 1 条 `.json` 的 kind）→ 起服 → `check` 全绿；分类默认值那一条 XML 走 `dev/upgrade_via_rpc.py` 就地升级免重启；`zz_md_check` 已删，`qa_check` 已删 | **业务库已生效**（14.0）；浏览器视觉截图仍欠（面板几次都 `visibilityState=hidden`，结构快照可用且已核对布局与默认值） |
| 2026-10-05 16:05 起（`49a6e07` 提交后随即部署） | `feature/library-folders-and-nav`（第三轮补丁：错题入口，`19.0.1.14.1`） | 业务库上纯 XML/Python 小改：`dev/upgrade_via_rpc.py` 就地升级免重启 + 一次 `restart odoo`（计数器口径改了要重建门户资产）；`qa_check`（教师组、无学生档案）与 `biaodi` 各跑一遍 HTTP 对照，验完即删 | **业务库已生效**（14.1）；截图那张"点错题只剩知识库卡"的现场已按维护者定位修掉 |
| 2026-10-05 18:40–18:51 | `feature/library-folders-and-nav`（第四轮：老师也是学习者，`19.0.1.15.0`） | 一次性库 `zz_self_check` 验完（安装 + 档案补齐）后删除 → 业务库：模块备份 → `svcctl stop odoo`（第一次 UAC 被取消，不静默重试；维护者给窗口后重跑）→ `-u tutoring_center`（0 ERROR/CRITICAL，`data/self_profile_data.xml` 给存量老师补「我自己」）→ 起服 → `check` 全绿。业务库上直接跑 HTTP：范围切换/速记条/记到谁/题目照片入库/越权与匿名 5 类共 32 项。⚠️ `odoo_template_c` 是 `db_template`，**不是残留库**（陷阱 38） | **业务库已生效**（15.0），测试数据与 `qa_check` 已清；浏览器四条 JS 项仍欠（面板此刻 `visibilityState=hidden`），工作树留给文档提交 |
| 2026-10-05 20:03–20:09 | `fix/drop-library-folder-menu`（删后台「知识库文件夹」页 + 别人的本人档案及其错题收口，`19.0.1.15.2`，顺带补上没部署的 `15.1`） | 一次性库 `zz_selfprofile_check` 安装 0 ERROR + 19 项断言 → 业务库：模块备份 `tutoring_center_before_20261005-2005` → `stop odoo` → `-u`（exit 0、0 ERROR）→ `start odoo` → `check`；两次 UAC 都正常通过。业务库真发 HTTP 17 项（`qa_teacher2` 与门户 `biaodi` 各一会话） | **业务库已生效**（15.2）；`qa_teacher2` 与档案 #11、一次性库、口令文件全清，工作树干净；**只剩浏览器里那一眼**（顶栏少一项、学生列表只剩一条「我自己」）等维护者刷新确认 |
| 2026-10-05 21:10–21:40 | `feature/ai-mistake-summary`（错题 AI 摘要，`19.0.1.16.0`，新模型 + cron + DeepSeek） | 模块备份 `tutoring_center_before_20261005-2110` → `stop odoo` → `-u`（0 ERROR）→ **起服前**把密钥写进 `ir.config_parameter`（运行中的服务缓存系统参数，起了再改它看不见）→ `start odoo` → `restart odoo` 一次加载修好的 Python。一次性库 `zz_ai_check` 安装 0 ERROR + 40 项断言；业务库真调用：门户 22 项、后台与 `_abort` 10 项。⚠️ 期间挖出既有 bug：门户学生读不到教材（陷阱 46），本轮只 sudo 绕过 | **业务库已生效**（16.0）；一次性库已删；错题 30 有真实摘要、31 是真实失败样本（保留着看效果）；**浏览器里那颗按钮没人点过**；教材可见性修根留给下一条分支 |
| 2026-10-05 22:16–22:20 | `feature/ai-mistake-summary`（同一分支续做：AI 抄回来的 LaTeX 渲染成纯文本可读数学） | 模块备份 `tutoring_center_before_20261005-2216` → `stop odoo` → `-u`（exit 0、0 ERROR）→ `start odoo` → `check` 六层全绿。渲染器 17 项离线断言 + 业务库 16 项（含真发 HTTP 看门户页面），**全程没再花额度**（拿已有的错题 29/30 当样本） | **业务库已生效**；`prompts/` 两份文案 + `models/math_text.py` 上线；仍只剩浏览器那一眼；教材可见性修根（陷阱 46）没做 |
| 2026-10-07 00:10–01:10 | `feature/do1ng-time-sync`（时间账本批次①，最终 `19.0.1.19.0`：云端五张表 + 三条机器接口 + 门户 `/my/time` + Do1ng 客户端） | **全程没碰共享服务与 `OdooForDB`，`E:\Odoo` 一行没动**（服务仍读它）。另起独立进程 `--http-port=8899 --db-filter=^zz_do1ng_time$ --max-cron-threads=0`，在自己的 PG 上反复 drop/create 一次性库 `zz_do1ng_time` 装模块跑验收；`filestore\zz_do1ng_time` 随库一起清掉。验收：全新库 `-i` 0 ERROR、HTTP 套件 100/100、真实 `tasks.json` 协议预检 15/15、Java 端到端 36/36 | **只到本机一次性库**：共享库未升级、云机未部署、代码未同步到 `E:\Odoo`；门户页两个 Bootstrap 下拉与折叠、以及截图仍欠——浏览器面板 0×0 `hidden`，指针动作被系统拒绝（陷阱 29 的同款现场）；状态药丸是纯 `<a href>` GET 链接，已按真实链接验过 |
| 2026-10-07 01:30 | 同上（PR #? 合 main 冲突） | 版本号撞车：本分支与 `feature/drop-mistake-topic-field` 都取了 `19.0.1.18.0`，且新陷阱号也被占（50）。merge main 后本分支改 **19.0.1.19.0**、陷阱改 **51~58**，并在一次性库上重装重跑 HTTP 套件复验 | 已解决并 push；**提醒下一个人**：push 前重新核对 `git for-each-ref` 的版本号，别按开工时看到的值定 |
| 2026-10-08 17:00–17:53 | `feature/library-workbook-link`（知识库「新建资料」＋「练习册/教辅」真的成为一本练习册，`19.0.1.20.0`） | **没碰共享服务与 `OdooForDB`**（服务没重启也没 `-u`，内存里仍是 `19.0.1.18.0` 那份代码）。一次性库 `zz_library_link`：全新库 `-i tutoring_center` 0 ERROR → ORM 37 项（跑完整体 rollback，可反复跑）→ 独立进程 `--http-port=8899 --db-filter=^zz_library_link$` 上 HTTP 20 项 → **真机点击走完**：点「新建资料」→ 填名选分类 → 跳详情页 → 错题页「哪本练习册」下拉里出现这本没附件的书 → 选它记一条 → 页面回「已记录 1 道错题」。⚠️ 工作树已从 `4fcc27b` 切到这个分支（＝`main` ＋本轮改动），**下次谁重启就会连带加载 `main` 上那份从未部署的时间账本批次①**（陷阱 59~60 是这轮挖的） | **只到本机一次性库**：共享库未升级、云机未部署；`zz_library_link` 和它的 filestore 还在，按规矩验完要删（删库等维护者点头）；**未 push、PR 未开** |
| 2026-10-08 21:28–21:40 | 同上（部署：维护者问"为什么 `localhost:8069` 看不到时间账本"→ 当场答清"批次①从没上过共享库"→ 他给窗口） | 模块备份 `backup/tutoring_center_before_20261008-2132` → `svcctl stop odoo`（未弹 UAC）→ `-u tutoring_center --stop-after-init`（exit 0、**0 ERROR/CRITICAL**）→ `start odoo` → `check` 六层全绿。落库核对 `19.0.1.18.0`→**`19.0.1.20.0`**、`tutoring_time%` 5 张表、`/my/time` 菜单 2 行、练习册 3→4 本、错题 15 条没动；本轮迁移在真库上"5 条已核对／新增教材行 1 条／无权 0 条"，孤儿归 0。**这一升连带把批次①（时间账本）一起落了共享库**——切分支时即已知并接受 | **本机业务库已生效**（20.0），云机仍未部署；`/my/time` 与本轮效果由**维护者本人点验通过**；⚠️ 那次没删的一次性库把 `localhost:8069/` 顶成了 `/web/database/selector`（`db_name` 为空＋两个库），他跑 `DROP DATABASE` 后恢复——**删库这步别拖**（细节与"匿名 404 不算路由没注册"的判据纠正见 `updates/2026-10-08.md` 第四节） |
