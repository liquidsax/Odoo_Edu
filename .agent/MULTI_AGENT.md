# 多 agent 并发协作规范

> 本项目通常有**多个 agent 同时加功能**，但共享同一套本机资源：一个 Odoo 服务、一个业务库
> `OdooForDB`、以及 `E:\Odoo` 这**唯一一份工作树**（它就是仓库主检出，也是服务正在加载的代码，
> 没有第二份"部署副本"）。这份文件规定"谁在什么时候可以动共享资源、什么才算交付完成"。
> 动手前先读 [ONBOARDING.md](ONBOARDING.md) 的「开发工作流」一节与本文件；交接档案怎么写见 [handoff.md](handoff.md)。

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
缺任何一件，就在你的交接档案（`.agent/local/handoff.md`，不入库）里明确标注它**还没做完**，别让人以为线上已经是那样。

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
  （详见 [updates/2026-10-01.md](updates/2026-10-01.md)）。

## 四、版本号礼仪

**默认往最后一位加，别轻易占新号。** manifest 形如 `19.0.1.<批次>.<小步>`：

- 一批功能**第一次上本机业务库**才进第三位（例：`34.0`）；
- 这批之后接着改、补做、调口径、修 bug，**一律只加第四位**：`34.0 → 34.1 → 34.2 → 34.3`；
- **只有来了新需求 / 换了新主题**才进第三位（`34.x → 35.0`）；
- 纯文档、注释、脚本改动**不占号**（`__manifest__.py` 不动）。

第三位是**占号**，不是记日志：每占一个新第三位，别人那条线的号就被往后挤一格。
本项目吃过一次——`32.0`/`33.0` 连着把"函数图像·不等式着色"那批的号挤掉了。

撞号更糟：manifest 版本会撞，而撞车会**静默吃掉别人的迁移**。改版本号前：

```bash
git fetch origin
for r in $(git for-each-ref --format='%(refname:short)' refs/remotes); do
  printf '%-45s %s\n' "$r" "$(git show "$r:server/addons/tutoring_center/__manifest__.py" | grep -m1 "'version'")"
done
ls server/addons/tutoring_center/migrations/
```

取**比所有分支和 main 都大**的号；自己没迁移就别建 `migrations/<版本>/` 目录。
push 前再核一次——别按开工时看到的值定。

## 五、验收要求

1. **交互控件必须真机点击**。本项目有过"脚本合成 click 把 `preventDefault` 吞事件掩盖掉"、
   "组件没注册但默认渲染看起来完全正常"两次教训（见 [updates/2026-10-01.md](updates/2026-10-01.md)）。
2. 前端崩服务端可能全是 200：定位顺序是 `svcctl check` → `odoo.log`（UTC，本地 +8）→
   **浏览器 console**。本轮的 `invalid portal target` 只在 console 里看得见。
3. 改完前端资产（`static/src/**`）要确认资产包真的重建了；就地升级不触发失效信号。
4. 门户端验证**别用维护者的浏览器会话**：登录 portal 账号会顶掉当前 admin 会话，而 agent 拿不到
   维护者密码，换不回来。用独立会话打真实路由：
   `POST /web/session/authenticate`（带 `db`/`login`/`password`）拿到自己的 cookie，再 GET
   `/my/learning/...` 与 `/web/content/...`。临时账号验完删干净。
5. 大文件上传：单个文件 ≈96MB 就到顶（算法与实测见 [updates/2026-10-01.md](updates/2026-10-01.md)），且**多份不能攒在一次保存里提交**，
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

**只留最近三条**（2026-10-16 起，维护者定的）。更早的在 `git log -p .agent/MULTI_AGENT.md` 里，
按日的完整过程在 `.agent/updates/`（已冻结，只当历史读）。

| 时间（本地） | 分支 / agent | 动作 | 状态 |
|---|---|---|---|
| 2026-10-08 22:40–次日 00:40 | `feature/plot-param-sliders`（参数滑块 `19.0.1.21.0`） | 一次性库 `zz_plot_sliders` 全新装 0 ERROR + 离线 101 项（`dev/zz_plot_slider_check.mjs` 直接跑线上那份 `function_plot.js`）+ 8899 独立进程真机点击；同晚按维护者要求把参数改成"每条曲线私有 + 点图例行选中才摆它的旋钮"并复验 | **已解决**：`21.0` 已随 10-09 那次 `-u` 上本机库、分支已并入 main；当时欠的截图就是 `docs/screenshots/plot-param-sliders.png`；`zz_plot_sliders` 与 `zz_library_link` 两个残留库现在都不在 `pg_database` 里了。**但数库时新发现一条没记过的残留**：`zz_wxapi_wb` |
| 2026-10-09 13:33–13:45 / 15:45–15:50 / 17:46–17:50 | 部署线（`main` `4e72112`→`ffad8be`，再 `fix/plot-ai-quota-25`） | 三次标准部署共享库：每次模块备份 + `pg_dump -Fc` 191MB → `stop odoo` → `-u` → `start odoo` → `check` 六层全绿、0 ERROR/CRITICAL；版本 `20.0`→`22.0`→`26.0`→**`28.0`**；逐格核对过每段区间都没有 `migrations/` 目录（不会静默吃掉别人的迁移），错题 16／练习册 4／学生 4 行数未动 | **已解决**：`28.0` 已被后续批次覆盖（现库 `36.0`）；当时说已 `DROP` 的 `zz_library_share`／`zz_quota25` 今天数过 `pg_database` 确认真不在了；函数图像两轮由维护者本人点验通过；那句"云机一次都没部署"已过时——云机现 `35.0` |
| 2026-10-16 12:17–12:19 | 本会话（移动端接口层部署） | 停服 `-u`：库 `19.0.1.35.0`→**`19.0.1.36.0`**，exit 0、日志 0 ERROR/CRITICAL；起服后 `check` 六层全绿；真发 HTTP 验接口层：`ping` 200、缺 `X-R3ynA-Client` 400、无 key 401 且**不 302**；`/`、`/tools/function-plot`、`/web/login` 全 200 | **未完全解决**：① 带真 API Key 的 8 个端点仍未验（要往业务库写一行 `res.users.apikeys`，等维护者点头）；② **`zz_wxapi_wb`（52MB）还在**，名字像小程序接口层那批留下的、无人记过，filestore 在 `%LOCALAPPDATA%\OpenERP S.A\Odoo\filestore\`，删它要维护者本人跑；③ 云机仍停在 `35.0`，36.0 没上 |
