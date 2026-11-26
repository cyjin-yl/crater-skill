# 作业与生命周期管理

## 1. 提交前：发现可申请的资源与配额

提交前先确认当前账户（`crater account current --json`），再查询可用资源名、个人配额与空闲节点：

```bash
crater resource ls --with-vendor-domain --json --no-interactive
crater context quota --json --no-interactive
crater context resources --json --no-interactive
crater node ls --gpu <keyword> --gpu-available --json --no-interactive
```

- **GPU 资源名必须精确**：`--gpu-resource` 必须传入 `resource ls` 中的完整资源名（例如 `nvidia.com/v100`、`nvidia.com/a100`、`nvidia.com/t4`），不要写简称；同时留意每项的 `amountSingleMax`（单作业可申请上限）。
- **勿混淆个人配额与集群余量**：`context resources` 返回的是当前账号的已用/排队/限额，不代表集群物理空闲量；物理空闲参考 `node ls --gpu <type> --gpu-available`。
- **按需选卡与 CPU 作业**：数据预处理、校验、打包或轻量 CPU 推理直接省略 `--gpu` / `--gpu-resource` 提交纯 CPU 作业，避免无谓排队。

## 2. 防重复提交与回执绑定

为每轮作业设定唯一显示名 `RUN`，先查重再提交：

```bash
crater job ls --search "$RUN" --days -1 --all-pages --json --no-interactive
```

`--search` 为模糊匹配，须逐条核对完整 `name`、所有者与创建时间。若本轮作业已存在，直接接管观测；无法区分时停止提交。

提交输出应写入本地私有临时回执目录（`umask 077`）。无论提交返回成功、超时还是空响应，都必须通过上面的 `job ls` 回读核实，取出平台唯一标识 `jobName` 并用 `crater job get "$JOB" --json --no-interactive` 确认绑定。若短暂查不到，每 30 秒重查一次，最多 3 次；仍无法确认则报告“提交结果未知”并保留回执，**禁止盲目重提**。

## 3. 提交各类作业

### 单机自定义批处理（`custom`）

```bash
crater job create custom \
  --name "$RUN" \
  --image "$IMAGE" \
  --arch linux/amd64 \
  --cpu 4 --memory 16Gi \
  --gpu 1 --gpu-resource nvidia.com/v100 \
  --volume "user/runs/$RUN:/work" \
  --dataset "123:/data" \
  --env "PYTHONUNBUFFERED=1" \
  --working-dir /work \
  --shell bash \
  --command 'set -euo pipefail; exec bash ./run.sh' \
  --json --no-interactive
```

关键说明：
- 纯 CPU 作业省略 `--gpu` 与 `--gpu-resource`。
- `--volume` 格式为 `<subPath>:<mountPath>`（`subPath` 必须以 `user`、`account` 或 `public` 开头）；`--dataset` 格式为 `<datasetID>:<mountPath>`（正整数 ID）。容器自动挂载内存型 `/dev/shm`。
- **零挂载跳过配额检查**：若作业完全不依赖共享存储，可省略全部 `--volume` 与 `--dataset`，平台会跳过存储配额检查（但容器临时文件系统退出即丢失，须另行输出产物）。
- 其他常用参数：`--schedule normal|backfill`（按部署支持选用）、`--cpu-pinning`、`--selector key=Operator:value1,value2`（节点亲和/排除）、`--forward name:port`（创建时配置 Ingress 端口转发）、`--alert`（邮件告警）、`--template <name-or-json>`、`--file <request.json>`（提供 `--file` 后忽略其他创建 flags，且 CLI 会拒绝未知字段）。

### 交互式作业（`jupyter` / `webide`）

```bash
crater job create jupyter --name "$RUN" --image "$IMAGE" --cpu 4 --memory 16Gi --json --no-interactive
crater job create webide  --name "$RUN" --image "$IMAGE" --cpu 4 --memory 16Gi --json --no-interactive
```

运行后获取访问信息（输出含敏感 token/密码，仅按需读取，勿写入公开日志或工单）：

```bash
crater job token <jobName> --json --no-interactive    # Jupyter URL 与 token
crater job secret <jobName> --json --no-interactive   # WebIDE URL 与密码
```

### 分布式作业（`pytorch` / `tensorflow`）与模板

分布式作业因含嵌套 `tasks[]`，须通过 `--file` 传入与后端 DTO 对齐的完整 JSON（CLI 会校验 `name`、非空 `tasks`、正整数 `replicas`、非负资源并拒绝未知字段）：

```bash
crater template ls --json --no-interactive            # 查看平台内置/保存模板
crater template get <template-id> --json --no-interactive
crater job template <existing-jobName> --json --no-interactive
crater job create pytorch --file pytorch-job.json --json --no-interactive
```

## 4. 连接运行中作业：`job exec`、`job ssh` 与外部访问

### 容器内执行命令（`crater job exec`，推荐，需 API v7+）

通过平台 WebSocket 直连容器，**不依赖 `sshd`、GPU 或本机 `kubectl`**，适用于任意 CPU/加速卡节点：

```bash
# 自动化/脚本执行（-- 之后原样保留 argv，不经本地 shell 解释）
crater job exec <jobName> --json --no-interactive -- python -V
crater job exec <jobName> --pod <pod> -c <container> --json --no-interactive -- sh -c 'nvidia-smi -L'

# 进入任务用户交互式登录 shell（需本地终端，不可与 --json/--no-interactive 同用）
crater job exec <jobName>

# 若用户 shell 启动脚本耗时或阻塞，跳过配置探测但仍保留任务用户与 HOME
crater job exec <jobName> --env-mode container -- env
```

要点：
- `data.exec` 返回 `namespace`、`pod`、`container`、`stdout`、`stderr`、`exit_code`。`--json` 捕获上限 16 MiB，大文件或二进制请用普通模式重定向。
- 远端命令非零退出时 CLI 返回退出码 `4`（`ERR_REMOTE_COMMAND_FAILED`），真实退出码在 `context.exit_code`。
- 在 Jupyter/WebIDE 作业中，`job exec` 启动的是独立新进程，不会附着到已有 Notebook kernel 或读取 IDE 选中的解释器；需要指定环境时显式传入解释器路径或 `conda run -n <env> ...`。
- 多 Pod 或多容器必须显式指定 `--pod` 与 `-c/--container`（默认忽略 init container）。

### SSH 连接（`crater job ssh`）

适用于容器已运行 `sshd` 且需要原生 SSH / VSCode Remote-SSH 的场景：

```bash
crater job ssh <jobName> --json --no-interactive                        # 获取 host:port
crater job ssh <jobName> --connect [--user <user>] [--identity-file <key>]
```

若镜像允许密码认证但既无密钥也无容器密码，可先 `crater job exec <jobName>` 进入容器执行 `sudo passwd "$(id -un)"`（或 root 直接 `passwd`）设置容器内密码，该密码独立于平台 LDAP 密码。

### 端口转发与外部访问（Ingress / NodePort）

- 创建作业时用 `--forward <name>:<port>` 配置 HTTP/HTTPS Ingress（`name` 限 1–20 个小写字母，平台映射路径形如 `/ingress/<user>-<uuid>/`；TensorBoard 等应用需配 `--path_prefix`）。
- 运行后从 `crater job pods <jobName> --json` 读出 `pod` 与**后端返回的真实 `namespace`**（绝不编造 namespace），再查入口：

```bash
crater pod ingresses <pod> --namespace <ns> --json --no-interactive
crater pod nodeports <pod> --namespace <ns> --json --no-interactive
```

部署推理或 Web 服务时，优先在容器内向 `127.0.0.1:<port>` 做一次健康检查和真实请求验收，确认就绪后再对外暴露或经 Ingress 访问。

## 5. 接管、轮询与监控作业

接管已有作业时，优先使用本技能自带的只读轮询脚本 [`scripts/watch.py`](../scripts/watch.py)（单次 `job get` 设 30s 超时，核对 `jobName` 与所有者，识别 401、契约变化与 `Freed` 终态）：

```bash
python3 scripts/watch.py --job "$JOB" --owner "$OWNER" --minutes 60 --interval 60
```

| 退出码 | 含义 | 下一步 |
| ---: | --- | --- |
| `0` | 平台成功终态（`Completed` / `Succeeded`） | 立即进入 [存储、下载与验收](storage-and-models.md) |
| `1` | 作业失败、被停止或被清理（`Failed` / `Aborted` / `Terminated` / `Cancelled` / `Evicted` / `Deleted` / `Freed`） | 保存终态、事件与首个解释原因的日志，进入 [故障排查](troubleshooting.md) |
| `2` | 观察截止到期（作业可能仍在排队或运行） | 汇报最后状态与是否仍占资源；勿擅自停止，除非已获授权 |
| `3` | 认证失效（401 / 缺 token） | 恢复同一账号登录后重读原 `jobName` 继续跟踪 |
| `4` | CLI 缺失/不兼容、JSON 结构变化、身份不匹配或未知状态 | 用 `crater job get "$JOB" --json` 核对实际结构，必要时通过 `--record-path`/`--job-key`/`--owner-key`/`--status-key` 适配 |

**按阶段观测与汇报节奏**：
- `Pending`：默认每 60s 查一次，同时查看 `podGroupPhase`（脚本会自动输出）与 `crater job events "$JOB" --json`。
- 已调度、容器未就绪：每 30s 查一次 `job pods` 与 `pod events`，拉镜耗时久时区分 `Pulling` 与 `ErrImagePull`。
- `Running`：每 30–60s 查一次，关注业务日志（`crater job logs "$JOB" --tail 100 --timestamps`）与持久卷进度；长任务每 15 分钟给一次简短带时区进度汇报。避免长时间无截止地 `-f` 跟随日志而漏查平台状态。
- 作业进入终态后立即保存关键日志与退出状态（Pod 结束后可能很快被回收）。

## 6. 运行时限、自动清理与延期审批（`order`）

Crater 清理器会定期回收两类作业（被清理后终态常为 `Freed`）：
- **超长运行作业**：常见默认策略为运行 3 天提醒、4 天回收（按开始运行时刻计算，重连 SSH 或保持进程在线不重置）。
- **低 GPU 利用率作业**：常见默认策略为连续 90 分钟低利用率提醒、120 分钟回收（按窗口内每张卡的最大利用率判定）。

> 以上为常见初始策略，实际阈值与是否启用以当前部署公告为准；普通账户无法确认时记“当前阈值未知”，并在最早可能中断点前留足检查点写入与恢复余量。长训练务必原子保存完整检查点（含 `step`、模型、优化器、调度器与数据游标）到 `user/` 持久卷。

**申请延期**：仅对活跃作业生效，且 `backfill` 调度作业通常不可走此延期流程：

```bash
crater order submit --type job --name "$JOB" --hours "$HOURS" --reason "$REASON" --json --no-interactive
```

- 在 v1.4.4 规则下，**1–12 小时**延长在满足近期频次条件时可触发系统自动审批并自动加锁；超过 12 小时需管理员审核。
- **必须回读确认锁生效**：不能仅凭 `Approved` 或通知判定安全，须回读确认：

```bash
crater order by-name "$JOB" --json --no-interactive
crater job get "$JOB" --json --no-interactive   # 核对 locked / lockedTimestamp
```

- 管理待审批工单：`crater order ls --json`、`crater order edit <id> ...`、`crater order cancel <id> --yes --json`（仅在授权时）。

## 7. 停止作业与确认资源释放

1. 核对 `jobName`、所有者与授权范围；若仍需产物，先完成 [存储、下载与验收](storage-and-models.md)。
2. 对仍在运行的交互式/服务型/需取消作业，经授权后执行：
   ```bash
   crater job delete "$JOB" --yes --json --no-interactive
   ```
3. 通过 `crater job get "$JOB" --json`、`crater job pods "$JOB" --json` 与 `crater context resources --json` 核实 Pod 退出且资源计数释放。停止作业不要求删除持久卷数据、已构建镜像或共享下载。
