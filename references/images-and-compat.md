# 镜像构建、Harbor 管理与老架构 GPU 兼容

## 1. 在 Crater 获取可用镜像的 5 条路径

按可复现性与运维成本从低到高选择：

### 路径 A：复用已有可用镜像与平台 CUDA 基础镜像

```bash
crater image ls --available --arch linux/amd64 --search pytorch --page-size 15 --json --no-interactive
crater image cuda ls --json --no-interactive   # 查看平台内网 Harbor 缓存的 CUDA 基础镜像
```

优先复用平台已登记、架构匹配（`linux/amd64` / `linux/arm64`）且尽量固定 digest 的镜像；不要等到 GPU 作业启动后再在容器内临时装大包（既拖慢启动又可能因容器层磁盘满或 PEP 668 失败）。

### 路径 B：平台原生低代码构建（`pip-apt`）

适合在已有基础镜像上追加少量系统包和 Python 依赖：

```bash
crater image build pip-apt \
  --name my-env --tag v1 \
  --image "<base-image-link>" \
  --packages "git vim curl" \
  --requirements "numpy==2.1.0" \
  --archs linux/amd64 --tags CUDA,PyTorch \
  --json --no-interactive
```

### 路径 C：平台原生 Dockerfile / Envd 构建

```bash
crater image build dockerfile --name my-app --tag v1 --file ./Dockerfile --archs linux/amd64 --json --no-interactive
crater image build envd       --name my-env --tag v1 --file ./build.envd --archs linux/amd64 --json --no-interactive
```

**关键限制**：平台原生 Dockerfile 构建（Kaniko）只接收 `--file` 读取的 Dockerfile **文本内容**，**不会上传本地构建上下文目录**。若配方需要 `COPY` 本地文件或 wheel，须二选一：
1. 改为在 Dockerfile 内直接下载固定公开制品并在构建层内校验 `sha256sum`；
2. 改走路径 D，在有构建上下文的机器用 Docker 构建并推送至平台 Harbor。

### 路径 D：本机构建推送 Harbor + 平台登记

```bash
crater image harbor info --json --no-interactive       # 查询 Harbor 地址与项目名（通常为 user-<username>）
crater image quota get --json --no-interactive         # 查询 Harbor 存储配额
crater image harbor credential --yes --json            # 仅用户明确要求时调用！会重置密码且仅显示一次
```

推送至个人 Harbor 后，**必须登记**才可在作业列表中选择：

```bash
docker tag local:tag "<harbor>/user-<username>/<repo>:<new-tag>"
docker push "<harbor>/user-<username>/<repo>:<new-tag>"
crater image upload --image "<harbor>/user-<username>/<repo>:<new-tag>" --type custom --archs linux/amd64 --json --no-interactive
```

**Crater Harbor 标签铁律**：**切勿覆盖已推送过的非 `latest` 标签**！哪怕改动很小，也必须推送新 tag（或按 digest 引用）；快速迭代时请统一使用 `latest`，否则计算节点可能继续使用旧缓存层。

### 路径 E：运行中容器快照（`crater job snapshot`）

`crater job snapshot <jobName> --json` 可把运行中 Jupyter/Custom 容器改动打包成新镜像，但大镜像快照成功率受网络影响且计入 Harbor 配额与数量限制；正式环境优先用 Dockerfile 或 `pip-apt`。

## 2. 异步构建追踪与镜像维护

- `image build` 是后台异步任务，提交返回 `OK` 时列表里可能尚未立即出现记录。通过 `crater image build ls --json` 按目标 `imageLink`、所有者与时间窗定位唯一记录。
- **区分两种标识**：`crater image build get <imagepackName> --json` 传字符串构建名，`crater image build pod <buildId> --json` 传数字 ID。
- **清理构建记录须谨慎**：`crater image build remove --ids <id1,id2>` 可能连带删除已生成镜像，操作前确认无活跃作业依赖。
- 常用元信息维护：`crater image valid --links <img1,img2>`（校验可用性）、`crater image type|tags|arch|description <id> ...`、`crater image share ls|add|remove <id> ...`。

## 3. 老架构 GPU 兼容指南（V100 / SM70 与 A100 / SM80）

Crater 集群常混布多代 GPU（如 V100 SM70、T4 SM75、A100 SM80 及更新型号）。构建镜像或选型前，先通过 `crater resource ls --with-vendor-domain --json` 确认实际可申请卡型，再按目标架构匹配工具链：

### V100（Volta, Compute Capability 7.0 / `sm_70`）

- **CUDA / PyTorch 版本边界**：Linux x86-64 下 CUDA 12.x 的官方 PyTorch wheel（如 `cu126`、`cu128`）仍包含 `sm_70`；**CUDA 13.0+ 官方 PyTorch wheel 从 `sm_75` 起步**，原生不再包含 SM70，直接运行会报 `no kernel image is available for execution on the device`。常规场景优先锁定 CUDA 12.x（如 `cu126` / `cu128`）。
- **在 V100 上运行 CUDA 13 应用（Volta Forever）**：若目标程序仅提供 CUDA 13 构建，可使用兼容层 [**Volta Forever**](https://github.com/nbald/volta-forever)（`vf` CLI，要求宿主机 NVIDIA R580+ 驱动与 Linux x86-64，将支持的 PTX/cubin 翻译或将部分库调用转发至 CUDA 12.9.2 运行）。接入原则：
  1. 先在分配到的 V100 容器中运行 `vf doctor`，确认识别到 R580 驱动与 CUDA 12.9.2 转发库；
  2. 用目标核心算子与原生 CUDA 12.x 在**同一张 V100** 上做数值正确性对照（不要只看 `import torch` 或设备名）；
  3. 遇到 kernel 拒绝、设备端 trap 或 CUDA Graph 失败时即停，回退原生 CUDA 12.x 栈。
- **V100 大模型推理（1Cat-vLLM）**：上游新版 vLLM 多已停止支持 SM70；在 V100 上部署 vLLM 服务可选用专门维护 SM70 支持的 [**1Cat-vLLM**](https://github.com/1CatAI/1Cat-vLLM)（如 `cu128` / `cp312` 发行 wheel）：
  - 计算精度使用 FP16（`--dtype half`），KV cache 可按模型与显存预算开启 FP8 E4M3（注意权重量化与 `--kv-cache-dtype` 相互独立）；
  - 镜像内保留 `nvcc` 与 CUDA 头文件（选用 `devel` 基础镜像），供部分内核在首次真实请求时 JIT 编译；
  - 某些 GPU 后端只能在分配到真实 GPU 后才能完整响应 `--help`；启动服务后从日志中的 `GPU KV cache size` 核实实际可容纳的上下文与并发，再发真实生成请求验收。

### A100（Ampere, Compute Capability 8.0 / `sm_80`）

- 原生支持 BF16、TF32 与 FlashAttention-2，常规 CUDA 12.x / 13.x 栈均可顺畅运行。
- **无原生 FP8 Tensor Core**（原生 FP8 计算需 SM89/SM90+，如 L40S/H100）：加载 FP8 量化权重时需依赖推理/训练框架的反量化或 W8A16 路径，部署前务必核对模型 `config.json` 中的 `quantization_config` 与所用后端对 SM80 的实际支持。

### 通用基础镜像与 glibc / Python 环境避坑

- **Ubuntu 22.04 vs 24.04 的 glibc 边界**：`crater image cuda ls` 提供的平台缓存镜像多基于 **Ubuntu 22.04（glibc 2.35）**。若所用 wheel（如较新的 `1Cat-vLLM` 或高版本 C++ 扩展）链接依赖 **`GLIBC_2.38+`**，会在 import 时直接报 `version 'GLIBC_2.38' not found`——此时须改用 **Ubuntu 24.04（glibc 2.39）** 的 CUDA 基础镜像（如 `nvidia/cuda:12.8.1-devel-ubuntu24.04`）。
- **固化 venv，规避 PEP 668**：Ubuntu 24.04 系统 Python 启用 PEP 668（`externally-managed-environment`），直接 `pip install` 会报错退出；在镜像构建阶段创建独立 venv（如 `/opt/venv`）并将 `PATH=/opt/venv/bin:$PATH` 写入镜像 `ENV`。

### 新镜像入卡最小实算验收

切勿只凭 `nvidia-smi` 或 `torch.cuda.get_arch_list()` 宣布环境可用。分配到目标 GPU 后，在工作负载实际使用的 Python 解释器中执行一次同步实算，同时筛查 ABI 缺失、架构码不匹配和静默不可纠正 ECC 错误：

```bash
getconf GNU_LIBC_VERSION
nvidia-smi --query-gpu=uuid,name,compute_cap,driver_version,memory.total --format=csv,noheader
python - <<'PY'
import torch
assert torch.cuda.device_count() > 0
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i), torch.cuda.get_device_capability(i), torch.__version__, torch.version.cuda)
    x = torch.ones((256, 256), dtype=torch.float16, device=f"cuda:{i}")
    y = x @ x
    torch.cuda.synchronize(i)
    assert torch.all(y == 256).item()
print("GPU compute preflight passed")
PY
```

随后再用同一解释器 `import` 实际要用的核心扩展（如 `vllm._C`、自定义算子或训练库）并处理一条代表性输入；通过后再提交长作业。
