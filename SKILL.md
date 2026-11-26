---
name: crater-skill
description: 在 RAIDS-Lab Crater（Kubernetes + Volcano）集群上通过 crater CLI 完成认证与账户队列切换、资源与配额发现、交互式/批处理/分布式作业提交、容器执行（job exec/ssh）、Ingress 端口转发、作业轮询与延期审批、远端文件与模型数据集下载、镜像构建（含 V100/A100 老架构兼容参考）以及故障排查。用户操作 Crater 平台、调用 crater 命令或处理集群作业、排队（Pending/Inqueue）、自动释放（Freed）、镜像与模型存储时使用。
license: Apache-2.0
---

# Crater 平台操作技能

Crater 是构建在 Kubernetes + Volcano 之上的云原生 AI 训练与推理平台，通过 `crater` CLI 与平台 HTTP/WebSocket API 交互，无需本机 `kubectl` 或 `kubeconfig`。

## 核心心智模型

- **登录身份与账户／队列分离**：`crater auth` 管理 `(platform_url, username, method)` 登录上下文；`crater account` 管理同一身份下激活的**调度账户／队列**。当前账户决定调度队列、专享节点污点容忍、资源配额、计费归属和 `account/` 存储空间。
- **平台唯一标识 `jobName`**：`name` 是人类显示名，`jobName`（如 `sg-<user>-...`）才是平台唯一标识。几乎所有详情、日志、执行、连接、删除和延期命令都必须传 `jobName`。
- **三类逻辑存储空间**：`user/`（个人空间，读写）、`account/`（当前账户空间）、`public/`（公共空间，含 `public/Models/` 与 `public/Datasets/`）。挂载文件目录用 `--volume <subPath>:<mountPath>`（`subPath` 以空间名开头）；挂载平台登记的数据集/模型/共享文件用 `--dataset <id>:<mountPath>`。
- **Volcano 排队与自动释放**：`Pending` 作业需看 `--json` 中的 `podGroupPhase` 区分“未过队列配额（`Pending`）”与“已入队等节点（`Inqueue`）”。超长运行或持续低 GPU 利用率作业会被平台清理器自动回收，终态为 `Freed`。

## 启动自检（Bootstrap）

执行任意 Crater 任务前先做两步轻量检查：

```bash
crater -v && crater auth ls --json --no-interactive
```

1. **未安装或版本过旧**：缺少 `crater` 时用 `npm install -g @raids-lab/crater-cli` 安装，或用 `npx @raids-lab/crater-cli@latest ...` 临时执行。不同 CLI 版本能力有差异（例如 `job exec` 需 API v7 / CLI v1.4+，`file upload/download/mkdir/mv/rm` 需 API v2 / CLI v1.3+，`account current/use` 需 CLI v1.3+）；不确定子命令或参数时先跑 `<command> --help`。
2. **未登录或凭据失效**：无 `active_context` 时引导用户在本机终端执行 `crater auth login --platform <url> --username <user> --mode ldap`（或 `normal`）。普通命令失败先按错误码排查，仅在排除常见原因或怀疑契约漂移时再运行 `crater compatibility --json`。

## 安全与操作红线

- **凭据不落地、不进聊天**：绝不要求用户把密码、token、cookie 或本地 `state.json` 发到聊天；禁止把密码/token 放进 `--password`、`--token` 命令行参数、日志、回执或代码仓库。私有/gated 模型下载只用 `--token-env` 或 `--token-stdin`。
- **先确认授权，不静默跳过确认**：提交作业、删除作业/镜像/下载/文件、切换身份或账户、签发 Harbor 凭据等写操作必须符合用户明确授权；未经明确同意，禁止自动追加 `--yes` / `-y` 或 `--overwrite`。
- **严守权限边界**：普通用户任务不得调用 `crater admin ...`；不得擅自删除或重试公共/他人的共享下载记录。
- **去重与回读**：创建作业、镜像构建或下载前先查是否已有同轮记录；请求超时或返回异常时必须先回读核实，禁止盲目重提造成重复扣费或并发冲突。
- **终态不等于交付**：平台 `Completed` 仅代表容器退出，批处理作业须校验产物摘要并用真实消费者试载；交互式或服务型作业验收后按授权及时释放计算资源。

## 按任务读取参考（按需加载，一跳直达）

每次只读取当前步骤所需的参考文档，不预先加载无关文档：

| 任务场景 | 参考文档 / 脚本 | 核心内容 |
| --- | --- | --- |
| 登录、多账户／队列切换、CLI 升级、分页与错误码 | [CLI、认证与账户](references/cli-and-auth.md) | `auth`、`account use`、CLI 版本能力边界、退出码与结构化错误 |
| 查资源配额、提交作业、`job exec`/`ssh`、端口转发、盯作业、延期与释放 | [作业与生命周期](references/jobs-and-lifecycle.md) | 5 类作业提交、Ingress/NodePort、清理策略与 `order submit`、资源释放 |
| 远端文件读写、卷与数据集挂载、原生下载模型/数据集、产物验收 | [存储、下载与验收](references/storage-and-models.md) | `user/account/public`、`crater file`、公共下载复用陷阱、SHA-256 与试载 |
| 选镜像、平台原生构建、Harbor 推送、快照、V100/A100 兼容 | [镜像与老架构兼容](references/images-and-compat.md) | `pip-apt`/`dockerfile`/`envd`、Harbor 标签铁律、Volta Forever、1Cat-vLLM、glibc/ABI |
| 作业卡 `Pending`、镜像拉取/沙箱/ECC/OOM/401 排查与续跑 | [故障排查与断点恢复](references/troubleshooting.md) | `podGroupPhase` 分流、事件/日志取证、阶段性恢复 |
| 确定性只读轮询单个作业直到终态或观察截止 | [作业轮询脚本](scripts/watch.py) | `python3 scripts/watch.py --job <jobName> --owner <user> --minutes <M>` |

## 高频只读命令速查

```bash
# 当前账户上下文、配额与已用资源
crater account current --json --no-interactive
crater context quota --json --no-interactive
crater context resources --json --no-interactive

# 可申请 GPU 资源名与空闲节点
crater resource ls --with-vendor-domain --json --no-interactive
crater node ls --gpu v100 --gpu-available --json --no-interactive

# 作业查询与诊断（<jobName> 为平台唯一作业名）
crater job ls --page 1 --page-size 15 --json --no-interactive
crater job get <jobName> --json --no-interactive
crater job pods <jobName> --json --no-interactive
crater job events <jobName> --json --no-interactive
crater job logs <jobName> --tail 100 --timestamps --no-interactive
```

脚本化读取优先加 `--json --no-interactive`，成功数据在 stdout 的 `data` 字段，结构化错误在 stderr。交接或对外汇报时仅保留 `jobName`、带时区观测时间、状态、已验证结果与下一步，去除凭据、完整日志与私有地址。
