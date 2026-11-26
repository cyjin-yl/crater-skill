# 存储、模型下载与产物验收

## 1. Crater 三类逻辑存储空间与挂载规则

Crater 对普通用户暴露三个逻辑根路径（严禁传入本机路径或含 `.` / `..` 的路径段）：

| 逻辑空间 | 典型用途与访问权限 |
| --- | --- |
| `user/` | 个人读写空间；Jupyter/WebIDE 作业通常自动挂载到 `/home/<username>` |
| `account/` | 当前激活账户／队列的共享空间；权限取决于 `crater account current` 返回的 `accessQueue` |
| `public/` | 平台公共空间（含原生下载落盘目录 `public/Models/<owner>/<repo>`、`public/Datasets/<owner>/<repo>`）；权限取决于 `accessPublic` |

作业提交时的两种挂载方式：
- **目录挂载 `--volume <subPath>:<mountPath>`**：`subPath` 必须以 `user`、`account` 或 `public` 开头（例如 `user/projects/exp1:/work`）。
- **平台数据挂载 `--dataset <id>:<mountPath>`**：`<id>` 来自 `crater dataset ls --json` 的正整数 ID。普通数据集与模型以**只读（ROX）**挂载；在平台“共享文件”中创建的条目以**可读写（RWX）**挂载。
- **跳过存储配额检查**：若作业不需要任何共享存储，删除全部 `--volume` 与 `--dataset` 参数即可跳过个人存储配额检查（容器内临时盘不持久化）。

## 2. 远端文件操作（`crater file`）

```bash
# 只读列举（所有 CLI 版本均支持）
crater file ls --json --no-interactive
crater file ls user/projects --json --no-interactive

# 完整读写操作（需后端 API v2+ 与 CLI v1.3+）
crater file mkdir user/runs/exp1 --json --no-interactive                       # 父目录须已存在
crater file upload ./train.py user/runs/exp1/train.py --json --no-interactive  # 仅单常规文件；服务端原子发布
crater file download user/runs/exp1/out.tar.gz ./out.tar.gz --json --no-interactive
crater file mv user/runs/exp1/a.bin user/runs/exp1/b.bin --json --no-interactive
crater file rm user/runs/exp1/old.bin --yes --json --no-interactive
```

关键边界：
- `file upload` 与 `file download` 均只处理**单个常规文件**，不支持目录递归、通配符或断点续传；传目录须先归档压缩。Web 端单文件上传通常限 1 GiB，大文件优先用 CLI、`job exec` / `scp` 或交互式作业传输。
- 默认拒绝覆盖已存在目标；**仅在用户明确要求覆盖该精确目标时**才传 `--overwrite`。
- `file mv` 无覆盖模式，目标不可已存在。
- `file rm` 删除任何目录（含空目录）必须显式传 `--recursive`（须单独获得用户授权，且删除失败可能处于部分完成状态）；逻辑根（`user`/`account`/`public`）不可删除。
- 若本机 CLI 较旧（如 v1.2.0 仅列出 `file ls`），先用 `npx @raids-lab/crater-cli@latest file ...` 或升级 CLI；平台若返回 `404` 表示后端存储服务未启用该契约，改走已授权的 `job exec` / `scp` 等通道。

## 3. 原生模型与数据集下载（`crater download` & `crater dataset`）

Crater 支持在平台侧异步从 ModelScope（`modelscope` / `ms`，默认）或 Hugging Face（`huggingface` / `hf`）拉取公开或私有仓库到公共存储。

### 步骤一：先查现有资源与下载记录

```bash
crater dataset ls --json --no-interactive
crater download ls --category model --search "<owner/repo>" --page-size 15 --json --no-interactive
```

### 步骤二：按需创建下载任务

```bash
# 公开仓库（简写命令 model / dataset 或通用 create）
crater download model Qwen/Qwen2.5-7B-Instruct --source hf --revision "<rev>" --json --no-interactive
crater download dataset AI-ModelScope/alpaca-gpt4-data-zh --source ms --json --no-interactive

# 私有 / gated 仓库：只用 --token-env 或 --token-stdin，禁止 --token 明文入历史或聊天
crater download model <owner/repo> --source hf --token-env HF_TOKEN --json --no-interactive
```

### 步骤三：追踪与管理

```bash
crater download get <id> --json --no-interactive
crater download logs <id>                      # 持续跟踪可用 --follow（不可与 --json 同用）
crater download pause <id> --json              # 暂停并保留已下载部分，后续可 resume 断点续传
crater download resume <id> --json
crater download retry <id> --json              # 重试失败任务（会先清空不完整公共目录）
crater download rm <id> --yes --json           # 仅解除当前用户关联，不删除已存文件
```

也可以在创建时加 `--wait --json` 等待进入 `Ready` / `Failed` / `Paused` 终态。

### 必须牢记的三个平台机制

1. **公共资源复用陷阱**：平台按 **`name + category`** 全局共享唯一一份公共资源（默认落盘于 `public/Models/<owner>/<repo>` 或 `public/Datasets/<owner>/<repo>`）。如果平台已有 `Ready`、`Pending`、`Downloading` 或 `Paused` 记录，创建请求会**直接复用既有记录**，可能忽略你本次指定的 `--source` 或 `--revision`！
   - 创建后**必须检查**返回 JSON 中的 `data.download.source`、`revision`、`status`、`path`。
   - 仅当 `status == "Ready"` 且实际来源与版本满足用户要求时才报告就绪；若发生复用且与用户明确要求的版本/来源不一致，**如实报告复用限制，禁止擅自删除、重试或干扰他人共享记录**。
2. **下载额度（HTTP 429）**：平台可能对每个用户限制同时活跃（`Pending`/`Downloading`）下载数及滚动时间窗口内成功次数。复用已有公共记录不占额度；遇到 429 时先查 `crater download ls` 等待已有任务完成，勿循环重试。
3. **下载任务 ID ≠ 作业挂载 ID**：`crater download` 返回的是下载任务 ID；提交作业传 `--dataset <id>:<mountPath>` 时，应从 `crater dataset ls --json` 查找对应的资源数字 ID（或挂载对应的 `public/...` 逻辑路径）。`Ready` 后仍建议在作业容器内抽查索引引用的权重分片是否完整。

## 4. 产物拉取与业务验收

平台状态变为 `Completed` 或日志打印 `DONE` **只能触发验收，不能直接宣称成功**：

1. **生产端清单**：让作业把结果写入专属输出目录（如 `user/runs/$RUN/out/`），在全部文件关闭后生成包含文件名、大小与 SHA-256 的清单文件（或独立归档包）。
2. **先验后改名（原子落地）**：下载到本地临时文件，校验 SHA-256 通过后再在同文件系统原子重命名：
   ```bash
   crater file download "user/runs/$RUN/out/$ARTIFACT" "$PART" --json --no-interactive
   printf '%s  %s\n' "$EXPECTED_SHA256" "$PART" | sha256sum -c - && mv -- "$PART" "$FINAL"
   ```
3. **干净目录真实试载**：用目标消费者在全新空目录中实际加载并执行一次最小消费（例如解包归档并加载模型/读取第一条样本/跑一次短推理），防备“压缩包能解压但漏打相对路径引用的权重文件”这类隐蔽缺陷。
4. **验收汇报**：只给出脱敏后的文件名、大小、SHA-256、消费动作及结果；校验失败时保留诊断信息，不发布为成功。
