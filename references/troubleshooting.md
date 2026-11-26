# 故障排查与分阶段断点恢复

## 1. 第一步：先区分“观测失败”与“作业故障”

在下任何作业结论前，先核实观测链路本身正常：
- CLI 返回非零、stderr 出现结构化错误 JSON、stdout 为空或非法 JSON，均属于**查询失败**，**绝对不能当成“作业不存在”或“空列表”**。
- 只有退出码为 `0` 且成功信封中数组为空，才构成有效的空结果。
- 遇到本地 `ERR_NOT_FOUND`（无 `http_status`）或 HTTP `401`：按 [CLI 与认证](cli-and-auth.md) 恢复同一身份后，对原 `jobName` 重读一次。
- 遇到瞬时超时或网络波动：退避 30–60 秒重查同一 `jobName`，连续失败 3 次后报告“可见性丢失”，勿盲目重提作业。
- 仅在排除常见参数、认证、权限和网络原因后，再运行 `crater compatibility --json` 排查 API 版本漂移。

## 2. 一次性取证命令组合

单条只读命令建议加 `timeout 30s`，防止网络卡死。`POD` 与真实 `NAMESPACE` 从 `job pods` 响应中读取（多 Pod 作业逐个检查）：

```bash
timeout 30s crater job get "$JOB" --json --no-interactive
timeout 30s crater job pods "$JOB" --json --no-interactive
timeout 30s crater job events "$JOB" --json --no-interactive
timeout 30s crater job logs "$JOB" --tail 200 --timestamps --no-interactive
# 若容器崩溃重启过，查看上一个已终止容器实例的日志：
timeout 30s crater job logs "$JOB" --previous --tail 200 --timestamps --no-interactive
# 需要细粒度 Pod 事件时，传入从 job pods 读出的真实 namespace：
timeout 30s crater pod events "$POD" --namespace "$NAMESPACE" --json --no-interactive
```

## 3. Crater 常见故障速查表

| 现象 / 证据 | 根因判读 | 下一步动作 |
| --- | --- | --- |
| `status=Pending` 且 `podGroupPhase=Pending` | Volcano 队列尚未准入（账户配额满或队列容量不足） | 查 `crater context resources` / `quota` 与当前账户（`account current`）；等待配额释放、切到有配额账户或按授权缩小规格 |
| `status=Pending` 且 `podGroupPhase=Inqueue` | 已准入队列，等待匹配物理节点（`job events` 常见 `FailedScheduling`） | 查 `crater node ls --gpu <type> --gpu-available`；单节点多卡或节点选择器过严需评估排队预算；保留原作业直至截止，更换资源规格会产生新作业 |
| `status=Pending` 且 `podGroupPhase=Running` / `Completed` | 已分配节点，容器正在拉镜或初始化 | 查 `pod events` 与容器状态，勿误判为排队 |
| `Pulling` 耗时久或 `ErrImagePull` | 冷节点拉取 10+ GiB 镜像常需数分钟；报错需看具体消息细分 | 鉴权失败 → 核对是否已 `crater image upload` 及拉取权限；`blob unknown` → 检查 Harbor 对应 tag/digest；节点磁盘空间不足 → 换已缓存镜像或记录节点报管理员 |
| `FailedCreatePodSandBox` | 节点容器运行时/网络异常，应用未启动 | 保留绑定节点名与事件，反馈平台管理员，必要时重提并使用节点选择器避开该节点 |
| 容器启动数秒即退出 | 常见原因：镜像缺 venv / PEP 668（`externally-managed-environment`）、`GLIBC_2.38` 缺失、Jupyter 历史 Slurm 迁移残留 `.jupyter` 硬编码证书路径 | 先看 `job logs --previous`；依赖/ABI 问题见 [镜像与兼容](images-and-compat.md)；Jupyter 证书路径报错可清理或修复 `user/.jupyter` |
| `no kernel image` 或 `uncorrectable ECC` | 镜像缺少目标卡计算能力码（如 V100 缺 `sm_70`），或物理卡硬件故障 | 架构不匹配见 [镜像与老架构兼容](images-and-compat.md)；ECC 故障记录 `nvidia-smi -L` 的设备 UUID、节点名与时间，停止在故障卡重跑并报管理员 |
| 终态变为 `Freed` | 被 Crater 超长运行或低 GPU 利用率清理器自动释放 | 检查作业时长与 GPU 利用率；从持久卷检查点恢复；长跑作业提前按 [作业与生命周期](jobs-and-lifecycle.md) 提交 `order submit` 并回读锁 |
| 创建作业报存储配额查询失败或个人空间满 | 个人目录配额达上限，或配额服务短暂异常 | 清理 `user/` 空间或稍后重试；无共享存储依赖的作业可移除全部 `--volume`/`--dataset` 挂载以跳过配额检查 |
| 训练日志长时间沉默 | 处于大 batch、数据加载或保存检查点，或真正死锁/挂起 | 间隔记录两个带时间戳的步数/样本数/最新落盘时间；超过单步与存盘预算且全部计数静止时，通过 `crater job exec` 或日志保留最后调用栈与 I/O 错误再决定恢复 |
| 原生下载报 HTTP 429 或版本/来源不符 | 达到并发/滚动窗口下载额度，或命中公共 `name+category` 复用 | 查 `crater download ls` 等待额度释放；发生公共复用且来源/版本不符时如实汇报，勿删除或重试他人下载 |
| `image build` 返回 OK 但 `build ls` 查不到 | Kaniko 构建记录异步创建，或观测器在 `Running` 到期后构建已 `Failed` | 在时间窗内按 `imageLink` 与所有者重查；观察到期与构建终态分开记录，窗口耗尽仍无记录时报告“受理结果未知” |

## 4. 分阶段断点恢复原则

中断或失败后，**永远只重做失败环节，从最后一个通过验收的阶段继续推进**：

1. **找回原记录**：从私有回执取出唯一显示名、`jobName` / 构建名 / 下载 ID、输入版本、镜像引用与输出目录；先查原对象是否仍活跃，避免并发双写同一输出目录。
2. **镜像阶段**：核对 `image build ls` / `build get <imagepackName>` / `build pod <buildId>`；`Finished` 后检查平台可用列表与目标架构，并在目标资源上完成一次最小拉取与实算验收。
3. **模型/数据下载阶段**：读回原下载 ID 的 `status`、`source`、`revision`、`path` 与 `download logs <id>`；暂停任务用 `resume` 续传，本人失败任务按需 `retry`；`Ready` 后核对挂载资源 ID 与关键分片。
4. **训练与计算阶段**：
   - 先确认旧作业已进入终态，防止旧进程继续写入同一持久目录。
   - 以训练器持久卷检查点文件内的权威 `step`（以及优化器、调度器、数据游标）为准，**不要轻信可能缺 `step` 字段的外部状态摘要 JSON**（把缺失当 `0` 会从头重训）。
   - 保留原检查点，启动恢复作业后必须核实**载入的旧 `step` 与首个新落盘 `step` 确实递增**；若旧检查点已达目标步数，直接只重做导出与验收。
5. **交付阶段**：若产物已完整生成，仅导出打包漏文件或下载传输中断，直接补齐打包或重拉文件，并按 [存储、下载与验收](storage-and-models.md) 校验 SHA-256 与干净目录试载。
