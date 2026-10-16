# FaMAS

FaMAS（figure-aware multi-agent system，图像感知多智能体系统）从教材 PDF 构建知识图谱，并把教材原生图片作为可追溯证据保留下来。

![FaMAS 流程](assets/famas-pipeline.jpg)

## 先说明系统范围

- **Windows PowerShell**：完整支持 Web 启动、依赖安装和一键本地运行。
- **Linux / macOS**：适合跑 `code_implement/` 流水线和静态可视化；Web 一键脚本目前是 PowerShell 版。

## 目录职责

- `web/`：前后端 Web 应用
- `code_implement/`：FaMAS 流水线
- `textbook/`：默认教材输入
- `visualization/chemistry/`：化学图谱静态查看器

历史过程文档和本地笔记不纳入最终转交包。

## Windows PowerShell

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

### 5. 首次启动与一键运行

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

### 6. 本地开发

```powershell
.\web\scripts\start-backend-dev.ps1
.\web\scripts\start-frontend-dev.ps1
```

### 7. 临时公网评审

```powershell
.\web\scripts\start-public-review.ps1
```

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

## 回退

我已经先做了一次检查点提交：

```text
925f7c6 整理启动脚本本地配置
```

需要回退时，可以直接按提交号切换，或者基于它再开一个分支。
