# FaMAS

FaMAS（figure-aware multi-agent system，图像感知多智能体系统）从教材 PDF 构建知识图谱，并把教材原生图片作为可追溯证据保留下来。

![FaMAS 流程](assets/famas-pipeline.jpg)

## 先说明系统范围

- **Windows PowerShell**：完整支持 Web 启动、依赖安装和一键本地运行。
- **Linux / macOS**：适合跑 `code_implement/` 流水线和静态可视化；Web 一键脚本目前是 PowerShell 版。

## 交付前提和联网下载

把项目交给其他用户前，请确认对方机器具备这些基础环境：

- Windows PowerShell
- Python 3.11 - 3.13
- Node.js 和 npm
- 可访问 PyPI，用于安装后端和流水线 Python 依赖
- 可访问 npm registry，用于安装前端依赖
- 可访问 ModelScope，用于下载 MinerU pipeline 模型
- 如需 GPU 版 PyTorch，还需要可访问 PyTorch wheel 下载源 `https://download.pytorch.org/`
- 如需临时公网访问，还需要可访问 GitHub release 下载 `cloudflared`
- 真实构图和问答需要用户自己的 DashScope / DeepSeek API Key

如果这些公网下载源在目标网络中不可访问，需要先准备代理、镜像源或离线依赖包；当前仓库不包含 Python wheel、npm 包、MinerU 模型权重、`cloudflared` 可执行文件或真实 API Key。

## 目录职责

- `web/`：前后端 Web 应用
- `code_implement/`：FaMAS 流水线
- `textbook/`：默认教材输入
- `visualization/chemistry/`：化学图谱静态查看器

历史过程文档和本地笔记不纳入最终转交包。

## Windows PowerShell

以下命令默认都在**仓库根目录**执行，除非步骤中明确写了 `cd`。

### 1. 后端环境

```powershell
.\web\scripts\setup-backend-env.ps1
```

### 2. 流水线环境

```powershell
.\web\scripts\setup-pipeline-env.ps1
```

如需 GPU 版 PyTorch：

```powershell
.\web\scripts\setup-pipeline-env.ps1 -GpuTorch
```

GPU 参数会从 PyTorch 官方下载 CUDA wheel。目标机器的显卡、驱动和 CUDA runtime 不一致时，可能需要按 PyTorch 官网选择器给出的命令重新安装匹配版本。

### 3. 前端依赖

```powershell
cd web\frontend
npm install
```

### 4. MinerU 模型下载

请在**仓库根目录**执行这一步，并先激活流水线环境，否则 `mineru-models-download` 可能找不到。

```powershell
.\code_implement\.venv\Scripts\Activate.ps1
$env:MODELSCOPE_CACHE = "$PWD\code_implement\.models\modelscope"
mineru-models-download --source modelscope --model_type pipeline
$env:MINERU_MODEL_SOURCE = "local"
```

如果不想先激活，也可以直接用完整路径：

```powershell
$env:MODELSCOPE_CACHE = "$PWD\code_implement\.models\modelscope"
.\code_implement\.venv\Scripts\mineru-models-download.exe --source modelscope --model_type pipeline
```

下载完成后，后续启动服务的同一个 PowerShell 会话中也应保持：

```powershell
$env:MINERU_MODEL_SOURCE = "local"
```

### 5. 可选：下载 Cloudflare Quick Tunnel

只有需要临时公网访问时才需要这一步。本项目提供的脚本会把 Windows 64 位 `cloudflared.exe` 下载到 `tools\cloudflared\cloudflared.exe`。

```powershell
.\web\scripts\setup-cloudflared.ps1
```

如果目标机器已经通过其他方式安装了 `cloudflared`，且命令在 `PATH` 中，可以跳过这一步。

### 6. 启动前检查

```powershell
.\web\scripts\check-deployment-readiness.ps1 -RunDatabaseCheck
```

如果这里出现 `FAIL`，先按提示补齐环境再启动。前端构建产物缺失在首次启动前可以是 `WARN`，因为后面的启动脚本会自动执行 `npm run build`。

### 7. 首次启动与一键运行

```powershell
.\web\scripts\start-single-port-local.ps1
```

这个脚本会：

- 自动检查后端、流水线、前端依赖
- 缺环境时提示具体安装命令
- 自动执行 `npm run build`
- 构建失败直接退出
- 首次运行交互输入并保存 `FAMAS_SECRET_KEY` 和 `FAMAS_ADMIN_PASSWORD`
- 下次自动读取当前用户目录下的 `~/.famas/famas/local-config.json`

默认访问地址：

```text
http://127.0.0.1:8000
```

首次启动后会自动准备两个系统知识库：

- `小初高知识全集`：来自 `默认知识库/` 的全量预置图谱。
- `化学`：只包含 `普通高中教科书·化学必修第一册` 的知识图谱，方便单独演示化学必修一。

### 8. 本地开发

```powershell
.\web\scripts\start-backend-dev.ps1
.\web\scripts\start-frontend-dev.ps1
```

### 9. 临时公网评审

当前推荐使用 Cloudflare Quick Tunnel。公网评审需要两个 PowerShell 窗口：

```text
窗口 1：启动 FaMAS，监听 http://127.0.0.1:8000
窗口 2：启动 cloudflared，把公网 HTTPS URL 转发到本机 8000
```

公网评审模式会启用注册审核，并要求稳定的强 `FAMAS_SECRET_KEY`。建议至少 32 个字符，且后续不要随意更换，否则已保存的会话和 API Key 可能失效。

公网启动前先在当前 PowerShell 会话中设置密钥并做检查。下面的示例值要替换成你自己的长随机字符串；后面两次 `start-public-review.ps1` 都必须使用这个同一个值。

```powershell
$env:FAMAS_SECRET_KEY = "replace-with-a-long-random-secret-at-least-32-chars"
$env:FAMAS_ENABLE_DIAGNOSTICS = "0"
.\web\scripts\check-deployment-readiness.ps1 -RuntimeMode public -RunDatabaseCheck
```

窗口 1 先启动 FaMAS：

```powershell
.\web\scripts\start-public-review.ps1 `
  -SecretKey $env:FAMAS_SECRET_KEY `
  -AdminPassword "replace-with-initial-admin-password"
```

窗口 2 再启动 Cloudflare Quick Tunnel：

```powershell
.\web\scripts\start-cloudflared-tunnel.ps1
```

终端会生成类似这样的临时地址：

```text
https://xxxxxx.trycloudflare.com
```

复制这个地址后，回到窗口 1，按 `Ctrl + C` 停止 FaMAS，再用同一个密钥和公网地址重启：

```powershell
.\web\scripts\start-public-review.ps1 `
  -SecretKey $env:FAMAS_SECRET_KEY `
  -AdminPassword "replace-with-initial-admin-password" `
  -PublicUrl "https://xxxxxx.trycloudflare.com"
```

启动成功后，本机可先打开：

```text
http://127.0.0.1:8000/api/health/ready
```

再用外部网络打开 Cloudflare 生成的公网地址。如果没有传 `-PublicUrl`，公网转发仍可访问页面，但 `Settings` 页面会提示公网地址未配置。

Cloudflare Quick Tunnel 是临时地址：每次重新启动 `cloudflared` 通常会生成新的 `trycloudflare.com` URL；关闭 `cloudflared` 后，旧 URL 可能失效。

## Linux / macOS

这部分适合只跑流水线、示例数据和静态图谱查看器。

### 1. 创建 Python 环境

```bash
python3.11 -m venv code_implement/.venv
source code_implement/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. 配置模型 Key

```bash
export DASHSCOPE_API_KEY="<your-dashscope-key>"
export DEEPSEEK_API_KEY="<your-deepseek-key>"
```

### 3. 下载 MinerU 模型

请在**仓库根目录**执行这一步，且先 `source code_implement/.venv/bin/activate`。

```bash
export MODELSCOPE_CACHE="$PWD/code_implement/.models/modelscope"
mineru-models-download --source modelscope --model_type pipeline
export MINERU_MODEL_SOURCE="local"
```

### 4. 运行流水线

```bash
python -m mas.pipelines.full_pipeline.main \
  --pdf "textbook/普通高中教科书·化学必修 第一册.pdf" \
  --subject 化学 \
  --grade high_school \
  --publisher sujiao \
  --run-id chemistry_full_famas
```

### 5. 运行静态可视化

```bash
cd visualization/chemistry
python -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/`。

## 密钥和页面配置

- `FAMAS_SECRET_KEY` 负责登录签名和后端保存的 API Key 加密。
- `FAMAS_ADMIN_PASSWORD` 只在首次创建管理员时需要。
- DashScope / DeepSeek API Key 进入前端 `API` 页面后由后端加密保存。
- 如果以后更换 `FAMAS_SECRET_KEY`，历史 API Key 需要重新保存。

## 默认保留的数据

以下内容是默认要保留的，不应当当成一次性测试产物删掉：

- `默认知识库/`
- `web/storage/`
- `code_implement/data/examples/chemistry/`
- `visualization/chemistry/data/`
- `visualization/chemistry/assets/images/`

其它运行缓存、中间产物、构建输出、测试残留和本地笔记都不应放进最终转交包。

其中 `默认知识库/02_high_school_化学_passed_普通高中教科书·化学必修第一册/` 会同时用于初始化单独的 `化学` 系统知识库。

## 回退

我已经先做了一次检查点提交：

```text
925f7c6 整理启动脚本本地配置
```

需要回退时，可以直接按提交号切换，或者基于它再开一个分支。
