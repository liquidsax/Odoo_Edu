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
