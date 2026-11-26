# crater-skill

面向 [RAIDS-Lab Crater](https://github.com/raids-lab/crater) 平台的中文 Agent Skill，深度适配 `crater` CLI 与 Crater（Kubernetes + Volcano）平台机制，覆盖从认证与账户切换、资源发现、作业提交与容器执行、轮询与延期审批、存储与模型下载、镜像构建（含 V100/A100 老架构兼容参考）到故障排查的完整运维工作流。

遵循 [Agent Skills 规范](https://agentskills.io/specification) 与渐进式披露（Progressive Disclosure）设计：仅暴露单个入口技能 [`SKILL.md`](SKILL.md)，所有专题手册通过一跳链接按需加载，避免上下文膨胀与跨技能断链。

## 安装

### 通过 skills CLI 安装到项目

```bash
npx skills add cyjin-yl/crater-skill
```

例如直接安装到当前 Codex 项目：

```bash
npx skills add cyjin-yl/crater-skill --skill crater-skill --agent codex -y
```

### 安装到 OMP 或本地技能目录

```bash
git clone https://github.com/cyjin-yl/crater-skill.git ~/.omp/agent/skills/crater-skill
cd ~/.omp/agent/skills/crater-skill
python3 scripts/install.py
```

可传 `--dest DIRECTORY` 指定其他支持 `SKILL.md` 的目录；更新时执行 `git pull --ff-only` 后重新运行 `python3 scripts/install.py`（会自动清理旧版拆分遗留的失效子技能软链）。

### 前置依赖

操作平台需要本机可用的 `crater` CLI（推荐最新正式版，支持 `job exec`、`file upload/download`、`account use` 等完整能力）：

```bash
npm install --global @raids-lab/crater-cli
```

## 结构一览

| 路径 | 职责 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | 入口技能：Crater 心智模型、启动自检、安全红线、高频命令与一跳导航 |
| [`references/cli-and-auth.md`](references/cli-and-auth.md) | CLI 版本与能力矩阵、认证三元组、账户／队列切换、分页与结构化错误码 |
| [`references/jobs-and-lifecycle.md`](references/jobs-and-lifecycle.md) | 资源发现、5 类作业提交、`job exec`/`ssh`、Ingress/NodePort、监控、延期与释放 |
| [`references/storage-and-models.md`](references/storage-and-models.md) | `user`/`account`/`public` 空间、`crater file`、原生下载复用陷阱与产物验收 |
| [`references/images-and-compat.md`](references/images-and-compat.md) | 平台构建与 Harbor 推送、标签铁律、V100（Volta Forever / 1Cat-vLLM）与 A100 兼容指南 |
| [`references/troubleshooting.md`](references/troubleshooting.md) | Volcano `podGroupPhase`、镜像/沙箱/ECC/OOM/401 排查与分阶段恢复 |
| [`scripts/watch.py`](scripts/watch.py) | 确定性只读作业轮询脚本（支持 `Freed`、`podGroupPhase` 与 401/契约检测） |

## 离线校验与测试

无需 Crater 账号、网络或 GPU 即可运行全套校验：

```bash
python3 scripts/check.py
python3 -m unittest discover -s tests
```

仓库默认拒绝跟踪未列入白名单的文件（见 [`.gitignore`](.gitignore)）。严禁将账号凭据、token、私有地址、作业回执或完整日志提交到仓库。

本仓库采用 [Apache License 2.0](LICENSE)。

[上游 Crater 仓库](https://github.com/raids-lab/crater) · [Crater 用户文档](https://raids-lab.github.io/crater/zh/docs/user/) · [CLI 命令契约](https://github.com/raids-lab/crater/blob/main/cli/docs/COMMANDS.md) · [Agent Skills 规范](https://agentskills.io/specification)
