# 云服务器部署（腾讯云 CVM · Docker）

> 首次部署实测：2026-09-30；首次版本同步实测：2026-10-01。机器 `119.91.140.197`
> （Ubuntu 22.04.4 / Docker 27.0.3 / Compose v2.28.1）。本文每一步都在该机上跑通过。
> 协作者本机开发仍走 [ONBOARDING.md](ONBOARDING.md)；**本文只管对外提供服务的那台服务器**。

---

## 一、这台机的现状（换机前先核对）

| 项 | 事实 |
|---|---|
| 系统 | Ubuntu 22.04.4 LTS，2 核 / 3.4 GB 内存 / 59 GB 盘（已用 41%） |
| SSH | `~/.ssh/config` 别名 `tx` → `ubuntu@119.91.140.197`，密钥 `~/.ssh/id_ed25519` |
| 账号权限 | `ubuntu` 有**免密 sudo**，但**不在 docker 组** → 一律用 `sudo docker` |
| 已有服务 | 1Panel + openresty（**占用 80/443**）、voiceagent-api（`127.0.0.1:8000`）。本部署只用 8069，不碰它们 |
| 镜像拉取 | 直连 `registry-1.docker.io` 超时；Docker 配了 `mirror.ccs.tencentyun.com` 加速器，可用 |
| 端口 | 5432 不映射宿主机（只在容器网络内）；8069 映射 `0.0.0.0`，是否可达由**腾讯云安全组**决定 |

## 二、目录与文件：什么入库、什么只在机器上

```
/home/ubuntu/odoo-edu/
└── Odoo_Edu/                      # git clone（仓库只含自研内容）
    ├── .env                       # 三个口令，chmod 600 —— .gitignore 已排除
    ├── odoo.conf                  # 挂进容器当 /etc/odoo/odoo.conf —— .gitignore 已排除
    └── docker-compose.override.yml# 生产覆盖 —— .gitignore 已排除
```

`.env` 三个键（口令只在机器上，**不要贴进聊天或提交**）：

```bash
cd ~/odoo-edu/Odoo_Edu
umask 077
{ echo "ODOO_DB_PASSWORD=$(openssl rand -hex 16)"
  echo "ODOO_MASTER_PASSWORD=$(openssl rand -hex 16)"
  echo "ODOO_ADMIN_PASSWORD=$(openssl rand -hex 8)"; } > .env
```

> 口令一律用 `hex`：`$` 等字符会干扰 compose 的 `${VAR}` 插值。
> compose 只自动读取**项目目录**里的 `.env`；放别处只会得到空串且不报错（实测踩过，见第五节 2）。

## 三、首次部署步骤

### 1. 取代码

```bash
mkdir -p ~/odoo-edu && cd ~/odoo-edu
git clone -b main https://github.com/liquidsax/Odoo_Edu.git
```

### 2. `odoo.conf`（挂进容器；主口令只能在这里设）

```ini
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = <ODOO_MASTER_PASSWORD>
list_db = False
db_host = db
db_port = 5432
db_user = odoo
db_password = <ODOO_DB_PASSWORD>
dbfilter = ^edu_prod$
workers = 2
max_cron_threads = 0
limit_time_cpu = 120
limit_time_real = 360
without_demo = ALL
load_language = zh_CN
```

**属主必须是容器里的 odoo 用户**（镜像内是 `uid=100 gid=101`，与宿主机同名用户号段无关）：

```bash
sudo chown 100:101 odoo.conf && sudo chmod 640 odoo.conf
```

### 3. `docker-compose.override.yml`

```yaml
services:
  db:
    volumes: !override
      - edu_db:/var/lib/postgresql        # PG18 必须挂这里，见第五节 1
    environment:
      POSTGRES_PASSWORD: ${ODOO_DB_PASSWORD}
    mem_limit: 384m
    restart: unless-stopped

  odoo:
    environment:
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: ${ODOO_DB_PASSWORD}
    volumes:
      - ./odoo.conf:/etc/odoo/odoo.conf:ro
    command: odoo -d edu_prod
    mem_limit: 1200m
    restart: unless-stopped
```

合并后自检（**必须确认插值不是空串**）：

```bash
set -a; . ./.env; set +a
sudo docker compose config --quiet && echo OK
sudo docker compose config | grep -c -- "POSTGRES_PASSWORD: $ODOO_DB_PASSWORD"   # 应为 2（db 与 odoo 各一次）
```

### 4. 建库装模块（一次性，跑完退出）

```bash
sudo docker compose up -d db            # 先让 db 健康
sudo docker inspect --format '{{.State.Health.Status}}' odoo_edu-db-1   # healthy
sudo docker compose run --rm odoo odoo -d edu_prod -i tutoring_center --stop-after-init < /dev/null
```

判据：日志出现 `Modules loaded`、`Module tutoring_center loaded`，
`grep -icE "CRITICAL|ParseError|password authentication"` 为 0；
`psql -At -c "SELECT name,state FROM ir_module_module WHERE name='tutoring_center'"` → `installed`。

### 5. 改 admin 口令（建库时它是写死的 `admin`）

`base/data/res_users_data.xml:16` 把 admin 用户口令初始化为 `admin`，公网机器上必须立刻改掉：

```bash
set -a; . ./.env; set +a
cat > /tmp/setpw.py <<'PY'
import os
env.ref('base.user_admin').password = os.environ['ADMINPW']
env.cr.commit()
print('ADMIN_PASSWORD_SET')
PY
chmod 600 /tmp/setpw.py
sudo docker compose run --rm -T -e ADMINPW="$ODOO_ADMIN_PASSWORD" odoo odoo shell -d edu_prod --no-database-list < /tmp/setpw.py
rm -f /tmp/setpw.py
```

### 6. 起服务与验收

```bash
sudo docker compose up -d
B=http://127.0.0.1:8069
curl -s -o /tmp/h.html -w 'home=%{http_code}\n' $B/            # 200
grep -c '数学辅导 · 学习数据平台' /tmp/h.html                     # 1
curl -s -o /tmp/p.html -w 'plot=%{http_code}\n' $B/tools/function-plot   # 200
grep -c 'data-plot-type' /tmp/p.html                            # 8（曲线类型入口）
curl -s $B/web/database/manager | grep -c edu_prod             # 0（list_db 已挡住）
```

外网访问前，去**腾讯云控制台 → 安全组**放行 TCP `8069`，源填使用者当前出口 IP。
本机出口 IP 是动态的（实测 `117.162.x.x` 段会变），打不开时先确认出口 IP 再怀疑服务。

## 四、同步版本（把服务器跟上 main，2026-10-01 实测流程）

```bash
cd ~/odoo-edu/Odoo_Edu
git fetch origin
git checkout main && git merge --ff-only origin/main   # 未入库的 .env / odoo.conf / override 不受影响

sudo docker compose up -d db
sudo docker inspect --format '{{.State.Health.Status}}' odoo_edu-db-1    # healthy 再继续
sudo docker compose run --rm odoo odoo -d edu_prod -u tutoring_center --stop-after-init < /dev/null

sudo docker compose up -d          # 起来验收
sudo docker compose stop           # 维护者要求下线时
```

要点：

- **必查版本号**：升级前后各跑一次
  `psql -At -c "SELECT latest_version,state FROM ir_module_module WHERE name='tutoring_center'"`，
  确认库里真的越过了 `migrations/` 目录（[MULTI_AGENT.md](MULTI_AGENT.md) 陷阱 13 的服务器版）。
  2026-10-01 实测：`19.0.1.0.0 → 19.0.1.7.0`，日志出现
  `module tutoring_center: Running upgrade [>19.0.1.2.0] pre-migrate`。
- **有新增 Python 模型/字段时 `run` 一次性升级就够**，不需要停服（容器里没跑着的同库进程）；
  若 `up -d` 已在跑，先 `stop` 再升级，避免两个进程同时写 registry。
- **模块的 `data/*.xml` 会在升级时重放**：例如 `data/knowledge_data.xml` 首次升级后服务器多出 98 条知识点，
  这是预期行为，不是脏数据。
- 版本礼仪、独占规则见 [MULTI_AGENT.md](MULTI_AGENT.md)；服务器与本机是**两套独立环境**，
  升级服务器不影响 `OdooForDB`，反之亦然。

## 五、与开发环境（ONBOARDING 路径 B）的差别

| 项 | 开发（仓库 compose） | 服务器（本文 override） |
|---|---|---|
| 启动方式 | `--dev=xml,qweb,reload` 单进程 werkzeug，页面带堆栈 | 去掉 dev，`workers=2` 多进程 |
| 改前端资产 | `--dev=assets` 直接读源文件 | 必须进容器 `-u tutoring_center --stop-after-init` 后重启才生效 |
| 库 | `edu_dev`，可 `down -v` 重来 | `edu_prod`，`restart: unless-stopped`，**别手抖 `down -v`**（会删数据卷） |
| 库列表 | 默认可用 | `list_db = False` + 非默认 `admin_passwd` |
| cron | 默认 | `max_cron_threads = 0`（无业务 cron，省内存） |
| 内存 | 不限 | odoo 1200m / db 384m（与 1Panel 共机，必须设上限；实测稳态 odoo 274MiB） |

> 常驻 command 里带 `-i tutoring_center` 对**已安装**模块是安全空操作
> （`loading.py` 只搜 `state='uninstalled'`），所以开发 compose 每次重启都带 `-i` 不会出问题。

## 六、实测踩到的坑（都能让人以为服务坏了）

1. **PG18 挂载点**：`postgres:18-alpine` 要求数据卷挂在 `/var/lib/postgresql`；挂成
   `/var/lib/postgresql/data` 会被判定"卷里已有数据"而无限重启。仓库 `docker-compose.yml` 已修正，
   本文的 override 也写了 `!override`（双保险）。
2. **`.env` 位置**：compose 只自动读项目目录的 `.env`。放子目录 → `${VAR}` 静默变空串，
   症状是"密码明明是对的却连不上库"。
3. **entrypoint 追加参数**：`/entrypoint.sh` 用 `POSTGRES_USER/POSTGRES_PASSWORD`（或 `PG*`）拼出
   `--db_*` 并**追加在命令行之后**，optparse 后者覆盖前者 → 在 command 里手写 `--db_password` 会被 env 盖掉。
   口令统一走 env，或让 `odoo.conf` 与 env 一致。
4. **`admin_passwd` 是 `FileOnlyOption`**（`config.py:207`）：没有对应命令行开关，只能靠配置文件；
   官方镜像也**不**认 `ADMIN_PASSWD` 环境变量。
5. **挂载 conf 的属主**：写成宿主机用户或 101 都会让 entrypoint 报
   `grep: /etc/odoo/odoo.conf: Permission denied`，随后 `wait-for-psql.py` 抛
   `NoSectionError: No section: 'options'`——错误信息完全指不到权限问题。容器内 odoo 是 **uid=100 gid=101**。
6. **`docker compose run` 吃 stdin**：在 heredoc 脚本里跑 `compose run` 会把后面的脚本内容当 stdin 吞掉，
   表现是"命令没执行却没报错"。必须加 `< /dev/null`。
7. **引号层级**：`ssh host 'bash -c "... $VAR ..."'` 里 `\$VAR` 不展开，会把字面量 `$ODOO_DB_PASSWORD`
   当口令传下去，症状是 `password authentication failed`（其实密码是对的）。统一用
   `ssh host 'bash -s' <<'REMOTE'` 传整段脚本。
8. **SSH 偶发 `Connection closed by ... port 22`**：这台机高频建连会被断，重试即可
   （`-o ConnectionAttempts=2 -o ServerAliveInterval=15`），不是密钥或服务问题。
9. **`list_db=False` 的表现**（容易误判成没生效）：`/web/database/manager` 仍返回 200，但页面里
   **列不出任何库**；`/web/database/list` 抛 `odoo.exceptions.AccessDenied`；`/web/database/select` 404。
   验收要看这三条，不是看 manager 的状态码。

## 七、当前状态（2026-10-01）

- 代码：`main @ cdca6cd`（含 PR #15/#16/#17），库 `edu_prod`，模块 `19.0.1.7.0`，`installed`。
- 容器：`odoo_edu-db-1` / `odoo_edu-odoo-1`，**当前处于停止状态**（维护者要求下线），
  `docker compose start` 即可恢复；数据卷与口令文件都在。
- 内容：空库（本次确认不迁移本机真实数据），但模块 `data/` 自带的知识点目录已在（98 条）。
- 安全组：从本机出口实测 8069 仍超时（规则未加，或本机出口 IP 与放行 IP 不一致）。
- 口令：`~/odoo-edu/Odoo_Edu/.env` 的 `ODOO_ADMIN_PASSWORD`（后台账号 `admin`），权限 600，
  不在仓库、不在聊天记录里。
- 若要 HTTPS/域名：80/443 已由 1Panel 的 openresty 占着，应在其上加反向代理指向 `127.0.0.1:8069`，
  并把 compose 端口映射收回 `127.0.0.1:8069:8069`；届时 Odoo 侧需加 `proxy_mode = True`。
