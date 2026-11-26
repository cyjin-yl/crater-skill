# CLI、认证与账户切换

## 1. CLI 安装、版本与能力边界

Crater CLI 通过 npm 分发对应平台的原生二进制（对外命令为 `crater`）：

```bash
npm install --global @raids-lab/crater-cli
# 或不改动全局安装，临时运行指定/最新版本
npx @raids-lab/crater-cli@latest version --json
```

本地查看二进制身份（不要求登录、不联网）：

```bash
crater -v                    # 单行：<product-version>, build <short-commit>
crater version --json        # 完整构建信息及 api_version / min_supported_backend_api_version
```

不同发行版的能力存在重要分界；执行任务前可用 `<command> --help` 核对当前二进制实际支持的子命令：

| 能力 | 典型要求 | 老版本降级表现与应对 |
| --- | --- | --- |
| `crater job exec` | 后端 API v7+、CLI v1.4+ | 缺失时改用 `crater job ssh` 或在作业启动脚本中向持久卷输出状态 |
| `crater file upload/download/mkdir/mv/rm` | 后端 API v2+、CLI v1.3+ | 如 v1.2.0 仅含 `crater file ls`；优先升级或用 `npx @raids-lab/crater-cli@latest` |
| `crater account current` / `account use` | CLI v1.3+ | 缺失时需升级 CLI 或在 Web 控制台右上角切换账户 |
| `crater job ssh --connect`、自动续期 `refresh_token` | CLI v1.4+ | 旧版 `job ssh` 仅输出 `host:port`，需手动执行 `ssh`；401 时需重新 `auth login` |

**API 兼容性握手**：普通命令不会自动执行兼容性检查。命令失败时**先按结构化错误排查参数、认证、权限与网络**；仅在常见原因无法解释或怀疑契约漂移时再执行：

```bash
crater compatibility --json                    # 使用当前激活平台
crater compatibility --platform <url> --json   # 无激活身份时显式指定
```

若 `compatibility` 提示 `ERR_API_VERSION_MISMATCH`（如旧版 CLI 访问新版后端），但当前所需命令仍能正常工作，只需说明存在潜在风险，不必强行阻断；若实际操作失败且排除其他原因，再升级 CLI 或在临时目录试装与平台匹配的版本：

```bash
trial=$(mktemp -d)
npm install --prefix "$trial" --no-save "@raids-lab/crater-cli@${CRATER_RELEASE:-latest}"
"$trial/node_modules/.bin/crater" compatibility --platform "${PLATFORM:?}" --json
```

## 2. 全局选项与分页契约

- `--json`：强制启用 `--no-interactive`，stdout 输出缩进 JSON 成功信封 `{"status":"OK","data":{...}}`，stderr 输出结构化错误 JSON。`--json` 可放在 `--` 之前的任意位置（`job exec` 中 `--` 之后全部属于容器内命令）。
- `--no-interactive`：彻底禁用交互提示（密码输入、确认框、列表选择），缺参直接报错；删除/登出等危险操作须配合用户明确授权的 `--yes` / `-y`。
- 列表分页：采用公共分页的列表默认 `--page 1 --page-size 15`（常规上限 `200`，`download ls` / `model-download ls` 上限 `100`）。普通分页响应在 `data` 中包含 `pagination: {page, page_size, total}`；按 `total` 决定是否翻页，仅明确需要全量记录时才加 `--all-pages`（使用后省略 `pagination`）。

## 3. 认证上下文（`auth`）与账户／队列切换（`account`）

Crater 用 `(platform_url, username, method)` 三元组标识一个本地已保存登录身份（`method` 默认 `ldap`，另支持 `normal`）。凭据存于本地 `state.json`（含明文 `token` 与 `refresh_token`），**严禁读取、打印或要求用户粘贴 `state.json`**。

```bash
crater auth ls --json                                                 # 查看已保存身份与 active_context（刻意过滤 token）
crater auth login --platform <url> --username <user> --mode ldap      # 让用户在本机终端交互输入密码
crater auth switch --platform <url> --username <user> --mode ldap     # 切换平台或登录用户
crater auth logout                                                    # 登出当前身份（非交互需用户授权加 --yes）
crater auth rm --platform <url> --username <user> --mode ldap         # 删除指定已保存身份
```

**同一用户切换调度账户／队列**（影响后续作业队列、专享节点污点容忍、配额、计费与 `account/` 存储空间）：

```bash
crater account ls --json                # 列出所属账户，取精确 name（勿用昵称或 ID）
crater account current --json           # 查询当前激活账户上下文（不猜测本地缓存）
crater account use <account-name> --json
```

`account current` / `account use` 返回的 `data.context` 语义如下（解释时保留原始字段名与数值，遇未知数值如实报告）：

| 字段 | 含义 | 数值定义 |
| --- | --- | --- |
| `queue` | 当前账户／调度队列名称 | 字符串 |
| `roleQueue` / `rolePlatform` | 账户内角色 / 平台级角色 | `1` = 访客，`2` = 普通用户，`3` = 管理员 |
| `accessQueue` / `accessPublic` | `account/` 与 `public/` 空间访问权限 | `1` = 禁止，`2` = 只读，`3` = 读写，`4` = 仅追加 |

> 区分入口：切换平台或登录用户用 `crater auth switch`；同一用户切换所属账户／队列用 `crater account use <name>`。

## 4. 退出码与结构化错误判读

`--json` 模式下 stderr 错误体格式为 `{"category": "...", "code": "ERR_...", "message": "...", "context": {...}}`。自动化判断只依赖退出码、`category`、`code` 和 `context`，不凭感觉匹配自然语言文案。

| 退出码 | `category` | 常见含义与处理 |
| ---: | --- | --- |
| `2` | `usage_error` | 参数缺失/非法、未知命令或本地身份缺失；若存在 `context.issues`（多字段聚合校验），一次修正全部项 |
| `3` | `cancelled` | 用户主动取消（如 Ctrl+C 或拒绝确认）；禁止自动重试或擅自补 `--yes` |
| `4` | `api_error` | 平台 HTTP 报错（看 `context.http_status` / `crater_code` / `msg`）、网络失败，或 `job exec` 远端非零退出（`ERR_REMOTE_COMMAND_FAILED`，真实退出码在 `context.exit_code`） |
| `5` | `system_error` | 本机配置、文件权限、JSON 编码或 OpenSSH 非零退出等本机错误 |

**两个高频易混错误**：

1. **本地 `ERR_NOT_FOUND` vs 平台 `ERR_NOT_FOUND_404`**：前者退出码为 `2` 且**无 `context.http_status`**，说明请求未发出，属于本机身份状态问题（`no active credentials found` → `auth ls` / `login` / `switch`；`no token saved for these credentials` → 对同一三元组重新 `auth login`）；后者退出码为 `4` 且 `http_status=404`，才是平台资源或接口不存在。
2. **401 vs 403**：v1.4+ CLI 会在 access token 过期时自动用 `refresh_token` 续期；仍返回 `http_status=401`（尤其 `crater_code` 为 `40101`/`40102`）时引导用户重新登录同一三元组。`http_status=403` 表示当前账户权限不足，而非登录状态损坏（勿擅自切到 `crater admin`）。
