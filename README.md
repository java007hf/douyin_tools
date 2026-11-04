# Douyin Tools / AI 创作工作台

一个可在本机或局域网使用的 Python + Web 工具，集成抖音素材采集、下载、视频理解、@我通知处理，以及图片和视频生成。生成端支持本地 ComfyUI、云端 Provider 和豆包网页登录 Mock 请求。

## 目录

- [功能一览](#功能一览)
- [安装与首次启动](#安装与首次启动)
- [主机管理员：日常启动清单](#主机管理员日常启动清单)
- [网页访问者：使用指南](#网页访问者使用指南)
- [网页使用方法](#网页使用方法)
- [豆包 Mock 配置与使用](#豆包-mock-配置与使用)
- [本地模型与云端配置](#本地模型与云端配置)
- [命令行使用方法](#命令行使用方法)
- [数据保存与备份](#数据保存与备份)
- [部署与服务结构](#部署与服务结构)
- [常见问题](#常见问题)
- [开发验证](#开发验证)

## 功能一览

| 模块 | 功能 | 使用前需要 |
| --- | --- | --- |
| 抖音素材 | 采集指定博主作品列表；下载视频、图文图片；预览和保存结果 | 可用的抖音页面，部分操作需要登录 |
| 抖音互动 | 对指定作品评论、点赞、收藏 | 已登录 Chrome 和抖音扩展 |
| 视频理解 | 下载作品、完整音轨转写、采样画面分析、摘要、时间线、完整报告和历史 | FFmpeg、ASR 模型、独立视觉 LLM 配置 |
| @我自动回复 | 接收新提及、串行分析、摘要或视频问答、原评论回复或草稿 | 抖音扩展、登录态、视频理解配置 |
| 视频抽帧 | 上传视频，按间隔或总张数抽帧，预览及 ZIP 下载 | OpenCV |
| 生图 | 文生图、参考图生图，模型/比例/风格等参数，生成记录 | 对应模型 Provider |
| 生视频 | 文生视频 T2V、图生视频 I2V、参考视频 R2V | 对应 Provider，能力因模型而异 |
| AI视频 | 从创作要求生成故事板、准备资产、逐镜头生成、连续性检查和合成 | 独立 Agent LLM 及生图/视频路由 |
| 资产库 | 保存和复用角色、场景、道具、风格参考，查看及编辑描述，选择资产参与生成 | 可用参考素材；重新生成需要生图 Provider |
| 后台控制 | Provider、LLM、ASR、素材存储、豆包凭据和 @通知设置 | 管理员可访问服务 |

**能力边界：**模型出现在列表中不表示本机已安装或账号已开通。ComfyUI 需要匹配的模型和 API 工作流；云端需要有效凭据；豆包需要真实网页请求模板和登录态。AI视频当前的结构化/元数据审片不能替代实际视频内容审查。

## 安装与首次启动

以下示例在 Windows PowerShell 中执行，工作目录为仓库根目录。建议使用 Python 3.10 或更新版本，并在虚拟环境安装依赖。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

安装 FFmpeg，并确认两个命令均可用：

```powershell
winget install --id Gyan.FFmpeg.Shared --exact
ffmpeg -version
ffprobe -version
```

主要依赖：Playwright 用于抖音页面采集与下载；OpenCV 用于抽帧与媒体解码；faster-whisper 用于本地转写；requests 用于 Provider HTTP 请求；MCP SDK 用于 @处理工具调用。Chrome、ComfyUI、Ollama 和模型权重按所用功能另行准备。

安装后若 PATH 未生效，重新打开终端并激活虚拟环境。只使用采集、下载或抽帧时，不必先配置全部生成模型。

启动整个工作台：

```powershell
.\run.bat
```

也可直接启动：

```powershell
python web_app.py --host 0.0.0.0 --port 8003 --service-host 0.0.0.0
```

打开 `http://127.0.0.1:8003/`，局域网其他设备使用 `http://服务器IP:8003/`。后台入口为 `http://127.0.0.1:8003/?admin=1`，也可通过工作台的“后台控制”进入。

`run.bat` 会停止占用 8003、8101、8102、8103 的旧工作台进程，再启动服务。生成任务进行中请等待完成后再重启。启动窗口需要保持打开。

> 默认会自动开启新 @通知的分析与回复，并尝试启动 Chrome。初次配置时建议先关闭自动启动，再在控制台用草稿模式验证：
>
> ```powershell
> $env:DOUYIN_MENTION_AUTOSTART="0"
> .\run.bat
> ```

首次使用按需完成配置：

1. 抖音互动或 @通知：安装抖音扩展，在相同 Chrome 用户中登录抖音。
2. 视频理解：后台配置“视频理解 LLM”和本地语音转写模型。
3. 生图/生视频：配置一个 Provider；本地 ComfyUI 与豆包 Mock 的步骤见下文。
4. AI视频：单独配置“AI视频”的 Agent 和各生成路由。

## 主机管理员：日常启动清单

“主机”指运行本项目 Python 服务的电脑；“网页访问者”指用浏览器访问工作台的人，两者可以是同一个人。以下步骤在主机执行，首次安装依赖请先完成[安装与首次启动](#安装与首次启动)。

### 哪些服务需要启动

| 组件 | 何时需要 | 如何启动／由谁启动 |
| --- | --- | --- |
| 工作台网关及功能服务 | 使用本工具时 | 主机运行 `run.bat`，默认启动 8003 网关和 8101／8102／8103 三个功能服务，无需逐个再启动 |
| Ollama | 视频理解或 Agent 配置选择本地 Ollama 时 | 主机另行运行 Ollama 应用或 `ollama serve`；`run.bat` 不负责启动 Ollama |
| ComfyUI | 生图／生视频路由选择本地 ComfyUI 时 | 主机另行启动自己的 ComfyUI，确认配置地址可访问；`run.bat` 不负责启动 ComfyUI |
| 主机 Chrome＋抖音扩展 | 使用扩展采集、评论／点赞／收藏、@通知监听时 | 在主机 Chrome 加载抖音扩展并登录抖音；`run.bat` 默认只会尝试打开 Chrome，不会替你安装扩展或登录 |
| 主机 Chrome＋豆包上传扩展 | 使用豆包 Mock，尤其上传参考素材时 | 按[豆包 Mock 配置与使用](#豆包-mock-配置与使用)准备登录态、请求模板和上传扩展 |
| FFmpeg／ffprobe、OpenCV、Whisper | 对应的媒体处理、抽帧、语音转写功能 | 是主机安装的工具／库，不需要另外启动一个服务；Whisper 在任务运行时加载，首次使用下载权重 |
| 云端 Provider | 选择对应云端生成或 LLM 服务时 | 在后台配置并启用，由工作台发起请求，不要求网页访问者安装本地模型 |

Ollama、ComfyUI 也可以部署在另一台机器，此时后台／环境变量要填写**工作台主机能够访问的地址**。只使用云端 Provider 时，不必为了打开工作台额外启动 Ollama 或 ComfyUI；只做采集、下载或抽帧，也不要求启动 LLM。

### 1. 检查 Ollama 和模型（按需）

首次安装使用 [Ollama 官方 Windows 安装说明](https://docs.ollama.com/windows)。先在 PowerShell 检查服务是否已运行：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

能返回版本信息即可，不要再重复启动第二个实例。如果连接失败，先从开始菜单打开 Ollama 应用；也可在一个独立终端中执行下列命令，并保持该终端运行：

```powershell
ollama serve
```

确认后台填写的模型名称确实已安装，而不是仅出现在本工具的下拉选项中：

```powershell
ollama list
ollama ps
```

`ollama list` 查看已安装模型；`ollama ps` 查看当前驻留模型，没有任务时后者为空是正常的。缺少模型时，按实际可用的名称执行 `ollama pull "模型名称:标签"`（先替换占位名称）；本地自定义／导入的模型需按其来源准备，不能假定所有名称都能从公共仓库下载。命令说明见 [Ollama 官方 CLI 文档](https://docs.ollama.com/cli)。

视频理解需要支持图像输入的模型。在后台“视频理解 LLM”选择 Ollama 接口、填写 `http://127.0.0.1:11434/v1` 和准确的模型名称，再保存并启用。本地 ASR 模型单独选择，不能用 Ollama 模型代替。AI视频使用自己的 Agent 配置；普通表单的“生图&视频 LLM”也需分别配置，三者不会自动共用设置。

API 返回版本、模型已安装只代表服务准备好，不能证明显存／内存足够或视觉推理正常；首次配置后用一条短视频验证完整流程。模型应按主机硬件选用，避免同时运行多个高负载模型任务。

### 2. 启动可选生成服务和工作台

使用本地生成时，先启动已配置工作流与权重的 ComfyUI，并在主机浏览器检查 `http://127.0.0.1:8188/`；非默认地址通过 `COMFYUI_URL` 配置，详见[本地模型与云端配置](#本地模型与云端配置)。豆包 Mock 或其他云端路线不依赖 ComfyUI，但仍需准备各自的凭据和所选 LLM。

然后在本项目根目录执行；如安装在虚拟环境中，先激活它：

```powershell
.\.venv\Scripts\Activate.ps1
.\run.bat
```

工作台窗口需要保持运行。`run.bat` 会重启已有工作台服务，因此有分析或生成任务时，不要把再次运行它当作刷新网页。模型／云端暂不可用时仍可能正常打开首页，具体功能是否可用需检查对应后台配置和任务状态。

### 3. 确认登录、访问与监听状态

1. 主机打开 `http://127.0.0.1:8003/`。需要共享时，其他设备打开 `http://主机局域网IP:8003/`；当前主机的访问示例为 `http://192.168.3.104:8003/`，更换网络后以实际 IP 为准。
2. 使用抖音扩展功能时，确认主机 Chrome 中扩展已启用、同一 Chrome 用户已登录抖音，并打开个人主页；需要时打开“通知 → @我的”完成请求采集。使用豆包 Mock 时，另外确认豆包登录与上传扩展。
3. 使用 @自动处理时，检查后台监听为“已启动”、通知读取正常，并确认草稿／自动回复模式。默认启动可能自动发布新 @评论回复，首次使用建议先按前文关闭自动启动并用草稿模式验证。
4. 临时排查问题而停止监听后，排查结束须明确恢复并核对状态；网页首页可访问不代表 @监听仍开启。停止监听期间不会处理新提及，恢复后的补采范围取决于抖音接口返回的通知，不保证无限历史回溯。

管理员也可在主机用只读请求核对当前监听与队列：

```powershell
Invoke-RestMethod http://127.0.0.1:8003/tabs/douyin/api/mentions |
    Select-Object enabled, auto_reply, queue, error
```

局域网访问只需让访问者能到达网关端口 8003；Ollama 11434、ComfyUI 8188 和扩展桥接端口通常不需要对访问者开放。共享部署的认证与管理入口保护见[部署与服务结构](#部署与服务结构)。

## 网页访问者：使用指南

### 访问者需要准备什么

普通使用只需要浏览器和可访问主机的网络，打开管理员提供的工作台网址，例如 `http://192.168.3.104:8003/`。**无需在访问者电脑安装 Python、FFmpeg、Whisper、Ollama、ComfyUI 或服务端扩展，也不需要运行 `run.bat`。**

| 操作 | 网页访问者操作 | 主机负责 |
| --- | --- | --- |
| 下载／理解抖音作品 | 粘贴作品链接，提交并查看任务 | 下载、登录资料、模型调用、语音转写和报告保存 |
| 上传视频抽帧 | 选择自己电脑上的视频并上传 | 解码、抽帧、打包和结果保存 |
| 生图／生视频／AI视频 | 填写要求，选择已配置模型，按需上传参考素材 | Provider 凭据、模型服务、生成与合成 |
| 查看／下载结果 | 打开历史或生成记录，预览并点击下载 | 提供保存在主机 `store/` 中的媒体和报告 |
| @我监听与原评论回复 | 按管理员约定查看队列和结果 | 使用主机已登录的抖音账号接收通知、分析和回复 |

访问者上传的文件会传到主机，任务历史、报告和生成结果也保存在主机；点击下载后才会保存一份到访问者自己的电脑。提交后可从历史／任务记录继续查看，关闭访问者的网页不会代替主机停止任务；主机服务、所需模型及 Chrome 登录态应保持可用。

### 账号、地址和故障反馈

- 页面使用的是主机配置的 Provider 和登录账号，不会因为访问者在自己的浏览器登录了抖音或豆包就自动切换账号。当前部署没有自动多用户账号隔离；需要个人账号时应由管理员准备独立配置与浏览器环境。
- `127.0.0.1` 始终指执行请求的那台机器：主机后台配置中的 `127.0.0.1:11434` 指主机 Ollama；访问者在自己浏览器输入 `127.0.0.1:8003` 则会访问自己的电脑，不能用于连接远程主机。
- 网站打不开：先确认主机地址／网络以及管理员是否已启动工作台。首页能打开但某项任务失败：提供任务链接和页面错误给管理员检查对应服务，无需在访问者电脑补装模型。
- @消息不处理：先核对主机监听是否开启、Chrome／扩展及登录态是否正常，再看队列、通知读取状态与模型错误；不要通过重复发评论来测试恢复。

各功能的具体表单步骤见下面的[网页使用方法](#网页使用方法)。

## 网页使用方法

### 抖音工具：采集与下载

**采集作品列表：**输入博主主页 URL，可填写目标数量，开始后查看进度并保存结果。服务会按主页 `sec_uid` 匹配作品作者，避免混入推荐内容。未填写目标数量时仍受默认滚动和空闲停止条件限制，不保证取得全部历史作品。

**下载作品：**输入单条作品 URL 或支持的分享内容，下载并预览媒体。支持 `/video/`、`/note/`，以及含 `modal_id` 或 `vid` 的主页弹窗链接。图文下载会提取原图；视频使用接口返回的媒体地址。登录、验证码、临时地址失效可能导致下载失败。

网页任务与下载结果保存在 `store/douyin/`。命令行可通过 `--download-dir` 指定其他目录。

### 视频理解与历史

1. 后台“视频理解 LLM”选择 Ollama 或 OpenAI 兼容接口，填写实际 API 地址、视觉模型及所需 Key，保存并启用。
2. 选择本地 ASR 模型，并预先准备完整的 CTranslate2 模型文件；仅从本地加载，不访问 Hugging Face。支持 `store/models/whisper/<模型名>/`、已有完整模型缓存，或通过 `DOUYIN_ASR_MODEL_DIR` 指定目录。确认 FFmpeg/ffprobe 可用。
3. 在抖音工具的“视频理解”输入单条视频作品链接或分享文案，提交后等待下载、转写、画面分析和总结完成。
4. 查看分类、摘要、关键点、可跳转时间线和完整转写；在“理解历史”重新打开记录，下载完整 `report.md`。

摘要采用作者直接讲述的成稿口吻：标题、正文、核心观点和章节内容直接展开主题、例子与结论，避免“视频中提到”“作者认为”等分析报告式开场；不虚构个人经历，不添加资料外的事实，不把推测改成确定结论。来源、转写误差及采样限制保留在报告的“理解范围”等独立部分，不混入正文。最终成稿的 System Prompt 集中在 [understanding_prompts.py](services/douyin/understanding_prompts.py) 的 `AUTHOR_SYSTEM_PROMPT`；画面识别、口播证据提取仍使用独立的分析提示词。新任务及重新分析采用新文风；旧历史不会自动改写，成稿文风版本参与分析缓存校验，避免直接复用旧口吻结果。

音频优先用于理解口播内容，画面用于补充视觉证据；无语音时只根据采样画面分析。当前视频时长上限为两小时。抽帧可能遗漏动作，ASR 和模型归纳也可能有误，报告不把创作者观点视为已证实事实。

视频理解下载优先选择约 480p、短边 360–720 的适中尺寸视频源，保留其他尺寸作为失败回退；普通素材下载仍使用原有画质策略。视频理解的下载阶段累计最多等待 20 分钟，候选源共用剩余时限。获取媒体地址后关闭采集浏览器，沿用系统代理流式写入文件，避免大视频堆积在浏览器驱动内存中。视频画面按全时长均匀采样，最多 20 张，长视频自动增大采样间隔；图文作品仍分析全部原图。完整语音转写先将密集时间戳合并为不超过 30 秒的语音段落，再按约 4000 字符分段归纳，每完成一段即保存中间结果，模型单次请求最多等待 20 分钟。@队列可在当前任务分析期间预下载下一条，模型分析仍串行执行。

视频理解会检查候选源的音轨，避免把仅含画面的低清版本误当作完整输入；只有所有候选均无法提供音轨时才回退到纯画面分析。使用本地 Ollama 时，语音转写前释放当前理解模型的驻留内存，随后按需重新加载；画面批次最多使用 16K、口播片段与证据压缩最多使用 8K、最终汇总最多使用 16K 上下文，均不超过后台配置的窗口；长视频证据先分层压缩再汇总。视频解码限制为两个线程，降低 HEVC 抽帧时的缓冲内存峰值。失败的 @任务重试会创建独立任务目录、保留旧错误轨迹并重置预下载状态，完成后仅生成草稿，不自动发送评论。

简单的纯 @、固定摘要或测试评论直接按摘要处理，不加载意图识别模型；明确问题仍使用模型识别，限制为4K上下文、256输出tokens。资源错误（GPU、内存分配失败、模型进程退出）会让 @队列进入持久化等待：30/120/300秒冷却后，以真实的小型推理验证模型恢复；探测未通过时不消费后续任务或分析重试次数。单条分析最多自动恢复两次，恢复任务仅生成草稿，发送结果未知时仍禁止自动重发。恢复状态保存于 `store/douyin/web_downloads/mentions/inference_health.json`，每条任务保留 `inference_recovery.json`（含错误分类、时间和系统内存快照）。该机制不会自动重启外部Ollama服务或修改显卡驱动；持续的硬件/驱动故障会保持等待。

分析断点保存在任务目录中，按来源、模型配置和媒体 SHA-256 校验后复用完整转写、已完成的画面分析，以及逐段保存的口播归纳；输入或模型配置改变时重新分析。Ollama 明确返回模型进程意外退出时，同一请求最多自动重载重试一次，其他 HTTP 错误保留原始错误正文。服务启动时先将中断的 @任务标为失败，再回填解析历史，避免旧任务一直显示运行中。

视频理解配置独立于生图提示词辅助和 AI视频 Agent，不会自动借用其他 LLM 的地址或 Key。本地 Ollama 地址示例为 `http://127.0.0.1:11434/v1`，模型必须填写本机实际安装且支持视觉输入的模型。接口类型决定请求协议，不能只凭端口选择。

#### 当前视频理解 Workflow

抖音手动理解、@通知理解和 YouTube 理解复用同一个确定性处理链路，核心入口为 [video_understanding.py](services/douyin/video_understanding.py) 的 `understand_work`。@入口先做意图路由，再通过 MCP 调用理解工具；模型负责识别与归纳，代码控制节点顺序、状态、文件和恢复。

```mermaid
flowchart TD
    A[抖音手动提交] --> Q
    B[YouTube 提交 / 本地持久 FIFO] --> Q
    C[抖音 @通知 / 去重与持久 FIFO] --> I[意图路由：摘要或视频问答]
    I --> M[MCP understand_video]
    M --> Q
    Q[跨进程共享 FIFO 准入：整体并发 1] --> V[校验独立的视频理解配置]
    V --> D[download：解析链接并下载 / 复用已准备媒体]
    D --> K[校验断点：来源、配置、媒体 SHA-256]
    K --> T{媒体类型}
    T -->|视频| F[extract_frames：检查时长 / 均匀抽帧，最多 20 张]
    T -->|图文| P[prepare_images：按原顺序准备全部图片]
    F --> H{有音轨或配音？}
    P --> H
    H -->|有| W[transcribe：复用完整转写或离线 Whisper 转写]
    H -->|无| N[空转写并记录限制]
    W --> O[visual_understanding：每批最多 4 张，调用视觉 LLM]
    N --> O
    O --> S[summarize：转写分段归纳，逐段保存断点]
    S --> E{合并证据超过 8000 字符？}
    E -->|是| R[分批压缩全部证据，保留时间点与不确定性]
    R --> E
    E -->|否| G[最终成稿：标题、分类、正文、观点、时间线、评论正文]
    G --> J{结构和时间范围校验通过？}
    J -->|首次未通过| U[自动修正一次]
    U --> J
    J -->|通过| Z[保存 summary.json、report.md / 更新历史与任务 done]
    J -->|修正后仍失败| X[任务 error：保存节点错误与已有产物]
    W -. 本地模型缺失或转写异常 .-> X
    R -. 压缩不收敛 .-> X
    Z --> OUT[手动 / YouTube：展示结果与历史]
    Z --> AT[@入口：复用评论正文或调用摘要 / 问答 MCP]
    AT --> REPLY[按任务模式保存草稿或确定性发送原评论回复]
```

- **执行顺序**：抽帧、转写、画面理解、口播归纳和最终成稿顺序执行；图中的各入口共用处理能力。@队列允许预下载下一条，但不并行运行理解模型。@工具命中有效分析缓存时可直接复用已有结果。
- **语音识别**：当前保存配置为 `large-v3-turbo`，由 `faster-whisper` 在 CPU 上以 INT8 执行；开启 VAD、词级时间戳和静音幻觉抑制。加载前释放当前 Ollama 理解模型，后续视觉/文本请求按需加载。仅使用本地权重；不自动下载，也不切换其他 ASR 引擎。无音轨或未识别到语音时带警告继续；转写异常则失败。
- **证据与模型**：视频以语音为主、画面为补充；图文综合全部原图与可选配音。转写先合并不超过 30 秒的段落，再按约 4000 字符分块；画面、口播归纳/压缩、最终成稿的上下文分别最多为 16K、8K、16K，且不超过后台配置。最终成稿使用独立的 `AUTHOR_SYSTEM_PROMPT`。
- **持久化与恢复**：任务目录保存 `task.json` 的节点状态/耗时/错误，以及媒体、图片、`transcript.json`、`observations.json`、口播归纳断点、`summary.json` 和 `report.md`；SQLite 保存历史。断点匹配时复用已完成的转写、画面分析和口播归纳。任一节点异常都会记录失败；图中只展开了部分失败边。摘要结构最多修正一次，不是无限重试。
- **入口差异**：@任务额外保留 Agent/MCP 轨迹并处理回复；失败重试仅生成草稿。@资源故障冷却和恢复探测属于通知队列层，不代表所有错误都自动重试。YouTube 队列重启恢复未开始任务，已开始任务标记中断；共享准入回收退出进程的占用。

### @我通知与自动回复

1. Chrome 加载 `services/douyin/chrome_extension/`，保持同一用户已登录抖音；扩展版本以 `manifest.json` 为准。
2. 先验证普通“视频理解”可以完成，再在后台“@我自动回复”设置检查间隔、草稿或自动回复模式，启动监听。
3. 扩展会复用或打开个人主页、发现真实通知读取请求。首次使用账号时已有通知登记为基线，随后处理新提及。
4. 在抖音工具查看队列、当前阶段、通知请求状态和历史；在控制台停止监听或修改模式。

处理采用持久化 FIFO 队列。单纯 @、问候或没有明确视频问题时回复摘要；明确视频问题由问答工具依据视频证据回答。草稿模式只生成回复供查看，自动模式会发布到原评论。缺少作品/评论 ID、账号不符、下载或分析失败时不会发送。

请求签名或登录失效时，在 Chrome 中重新登录并刷新抖音页。不要为了重试未知发送结果而重复提交评论。嵌套评论回复尚需更多真实验收。

### 视频抽帧

进入 AI创作工具 → 视频抽帧，上传视频，选择按时间间隔或总张数抽取、填写参数并选择图片格式。完成后可预览每张图片及时间点，下载全部 ZIP。

### 生图与生视频

1. 在对应视图选择模型；列表中的模型关联其 Provider。
2. 填写描述，选择比例、时长、风格等当前模型支持的参数。
3. 按需上传参考素材或选择资产库素材。无参考图的图片请求为文生图；视频根据参考素材选择 T2V、I2V 或 R2V。
4. 提交后在生成记录中持续查看状态，完成后预览/下载；失败时查看具体错误再重试。

参考能力和参数由 Provider 决定，不能跨模型通用。云端需要公网素材地址时，先配置素材存储；豆包 Mock 参考图使用专用上传桥接，步骤见下节。资产可多选，支持稳定的 `<asset:ID>` 提示词引用，最终参考图数量仍受 Provider 限制。

“生图&视频 LLM”用于普通表单的提示词改善，不负责 AI视频的故事板规划。

### AI视频与资产库

1. 后台“AI视频”选择 OpenAI 兼容或 Ollama 原生接口，配置独立 Agent API 地址、Key、模型、上下文窗口、故事板与审片提示词。本地 Ollama 可留空 Key，地址可填 `http://127.0.0.1:11434/v1` 或 `http://127.0.0.1:11434/api/chat`；原生接口使用指定上下文窗口，可通过“Ollama 思考模式”选择关闭、模型默认强度或低强度；低强度会先核对模型是否声明支持 `low`。可选择采用模型自身默认采样参数，避免工程固定温度覆盖模型设置。旧配置默认关闭思考并保留原采样行为。思考内容不保存到任务或日志，仅统计进度，结构化结果只解析最终回答。“Ollama 输出预算”默认 6000 tokens，可独立调整；思考与最终回答共享输出预算，达到上限时会明确报错，不接受截断的 JSON。旧配置未设置接口类型时继续使用 OpenAI 兼容协议。
2. 分别设置默认生图、T2V、I2V、R2V Provider/模型。先验证这些路由的普通生成任务可用。
3. 在 AI视频填写创作要求、总时长及可选参考素材；可在要求中明确镜头数、角色、剧情和声音要求。
4. 工作流生成故事板和连续性设定，准备独立角色/场景/道具资产，再按镜头依赖生成片段并合成。包含“搞笑、喜剧、幽默、comedy”的新任务会先执行 `develop_story`：由 AI视频配置中的 LLM 生成三个四拍剧情候选，再独立调用同一 LLM 检查规则、动机、因果和笑点；未通过时最多重写一轮。程序验证评审覆盖、原文引用及通过条件，按分数选择通过的候选，再交给分镜规划。两个轮次均未通过会停止任务，不生成素材；可调整创作要求或 AI视频模型后重新提交。评分是模型的主观筛选，不是实际观众效果的保证。
5. 候选原稿、每轮评审、提示词、状态和最终选择保存在任务目录的 `story_development/` 中；Trace 的 `develop_story` 节点显示选择结果或错误。剧情全部由配置的模型生成和重写，无人工代写步骤。普通非喜剧任务及复用已有故事板的失败重试沿用原流程。
6. 若开启资产确认，先为缺失资产选择已有素材或重新生成，再继续。任务 Trace 可查看故事板、资产绑定、节点耗时、子任务、错误和输出。
7. 完成后播放成片；不需要的排队、运行或待确认任务可取消并移除。

可用策略包括先生成关键帧再 I2V、使用前一镜头尾帧续拍，以及 Provider 支持时的多参考图。豆包 Mock 只接受单张 I2V，不支持 H3 的多参考图模式或 R2V。完整多模态审片和自动定向修复仍在完善，成片需要人工检查。

资产库用于长期复用独立主体，可查看/编辑名称、类型、描述及生成提示词，并基于现图或上传参考图生成改进版本。镜头首尾帧用于任务连续性，不应当作独立角色资产保存。

## 豆包 Mock 配置与使用

豆包 Mock 复用登录网页的实际请求模板，与火山云 API 的 Seedream/Seedance Provider 分开配置。新机器不会自带登录凭据或已捕获模板；仅安装依赖不能直接生成。

### 1. 准备网页登录请求

1. 在 Chrome 登录豆包，打开 `https://www.doubao.com/chat/create-image`。
2. 打开开发者工具 → Network，实际执行一次希望接入的生图或生视频请求；保留请求及响应，可以导出 HAR 或复制为 cURL。参考图模式需要额外捕获带图请求。
3. 按实际捕获结果整理下表中的配置，写入后台“豆包网页登录”的对应 JSON 字段。**cURL/HAR 是原始抓包材料，不能直接当作 JSON 粘贴，也不要在终端执行来历不明的命令。**

| 配置项 | 作用 | 填写位置 |
| --- | --- | --- |
| `headers.Cookie` | 当前网页完整 Cookie 请求头 | Cookie 输入框，或完整请求模板 |
| `web_request` | 文生图 `url`、`headers`、`body` | 已验证的网页生图请求 |
| `web_reference_request` | 带附件的参考图生图请求 | 完整请求模板中的同名键 |
| `web_video_request.submit` | 文生视频提交 | 网页视频请求 JSON |
| `web_video_request.i2v_submit` | 单图视频提交 | 网页视频请求 JSON |
| `web_video_request.poll` | 查询视频会话结果 | 网页视频请求 JSON |
| `web_video_request.confirm` | 同一会话内确认参数 | 网页视频请求 JSON |

每个请求模板使用 `{ "url": "实际 URL", "headers": {…}, "body": {…} }` 结构；省略号仅说明结构，不能作为有效 JSON 保存。模板必须保留实际协议字段，不要手造签名或把网页视频参数套进生图结构。项目测试 fixtures 为脱敏单元测试数据，不能直接用于在线请求。

当前网页协议使用 `/chat/completion`；生图与视频的 `chat_ability` 结构不同。视频通过捕获的 `/im/chain/single` 查询。旧 Android 请求兼容代码仍保留，新接入优先使用已验证的网页模板。

### 2. 注册 Provider 与更新凭据

1. 后台“豆包网页登录”保存 Cookie 和请求模板。Token 用于需要它的旧协议，网页模式主要使用实际 Cookie 与捕获请求。
2. 后台“豆包 Mock Provider”填写名称、默认生图/视频模型并启用保存。
3. 刷新 AI创作页面，在生图或生视频模型列表选择 `mock_doubao_*` 模型。
4. 如需用于 AI视频，在独立 AI视频配置中将默认生图、T2V、I2V 分别设为这个 Provider 配置及对应模型。

凭据过期后，在同一入口更新 Cookie，必要时重新捕获请求模板。管理页支持回填并显示/隐藏 Token 和 Cookie；“已配置”只代表保存成功，不表示会话有效。凭据保存在 `store/video_creator/mock_doubao.json`，不要提交或共享该文件。

### 3. 参考图上传插件

1. Chrome → `chrome://extensions/` → 开启开发者模式 → 加载已解压的扩展程序。
2. 选择 `services/video_creator/chrome_extension/`，这是 **Doubao Upload Bridge**，与抖音扩展是两个不同扩展。
3. 保持该 Chrome 用户已登录豆包，刷新豆包页。当前工程集成版本为 0.1.10，实际版本以 manifest 为准。
4. 在我们的网页选择本地参考图或资产后提交。不需要在豆包页手选图片，也不需要点击“启动”。

插件自动复用/打开图像创作页，在每个上传批次开始前清理带专用标记的自身临时草稿附件（保留用户附件），避免达到网页 10 张上限；刷新可能恢复草稿，不能代替清理。用页面运行环境申请上传；图片内容由 Python 上传，再由页面提交获得 URI。只有预期数量的 Python 上传和 commit 均完成才会继续生成，失败不会回退到原生上传绕过校验。

上传桥接监听服务机器的 `127.0.0.1:18767`，因此 Chrome/插件与 Python 应运行在同一台机器。远程访问网页时，参考图仍交给服务端这套已登录 Chrome 处理。修改后台/manifest 等扩展代码后，在扩展管理页重新加载并刷新豆包页。上传诊断详见 [插件说明](services/video_creator/chrome_extension/README.md)。

### 4. 模型与支持范围

| 类型 | 模型选项 | 当前范围 |
| --- | --- | --- |
| 生图 | `mock_doubao_seedream_5_0_flash`、`5_0_pro`、`5_0_lite`、`4_5`、`4_0`（均带相同前缀） | 文生图、1–2 张参考图、捕获菜单中的风格与比例 |
| 视频 | `mock_doubao_seedance_2_0_mini`、`2_0_fast`、`2_0`（相同前缀） | T2V、单图 I2V，4–15 秒整数时长 |
| 视频 | `mock_doubao_seedance_2_5` | T2V、单图 I2V，4–30 秒整数时长 |

本地上传与资产选择合计计入参考图数量。视频暂不支持多图参考包或参考视频。清晰度由豆包控制；模型列表及范围来自实际网页配置，账号是否可用仍以真实响应为准。在线完整验收主要使用 Seedream 5.0 Flash 和 Seedance 2.0 Mini，其余选项未逐一完成生成验收。

视频只提交一次生成请求，每 10 秒查询，最长等待 30 分钟。若要求确认，仅在捕获模板、会话游标及模型/时长/比例核对通过时最多自动确认一次。HTTP 200 或 `SSE_REPLY_END` 不代表成片完成，下载结果还必须能解码。网络中断不自动重发生成 POST，避免重复扣额。

已完成两参考图生图、T2V 和新图片 I2V 的工程 HTTP 端到端测试。Mini 验收得到 4 秒、24 fps 成片；I2V 为 720×720，T2V 提交 1:1 但返回 1280×720，说明网页端可能调整比例。请以生成记录中的实际尺寸为准。报告与视频位于相应 `store/video_creator/generation_jobs/<任务ID>/`。

## 本地模型与云端配置

### ComfyUI

先启动 ComfyUI，再在同一终端设置地址和已准备好的 API 格式视频工作流：

```powershell
$env:COMFYUI_URL="http://127.0.0.1:8188"
$env:COMFYUI_T2V_WORKFLOW="C:\workflows\t2v_api.json"
$env:COMFYUI_I2V_WORKFLOW="C:\workflows\i2v_api.json"
$env:COMFYUI_R2V_WORKFLOW="C:\workflows\r2v_api.json"
.\run.bat
```

图片使用已安装的 Flux 等对应工作流；Qwen、SD 等模型需实际安装权重和匹配工作流后使用。视频工作流需要正确绑定提示词、尺寸、帧数、种子及参考素材输入。不要把普通 ComfyUI 编辑器 JSON 当作 API 格式工作流。

AI视频的清晰度、比例、采样步数在独立配置中设置。默认质量档为 768p/约 1MP、16:9、24 步；实际显存和镜头时长上限取决于已安装模型与硬件。

### 云端与素材存储

后台分别配置 MiniMax、Seedance 的 API 地址、Key/Token 并启用，再在生成表单选择模型和生成参数。不同厂商/模型的参考素材、时长和清晰度范围不同，错误会保留在任务状态中。

需要公网参考图/视频 URL 的 Provider，可在“素材存储”选择阿里云 OSS 或 Cloudinary，填写对应连接参数和公网访问地址；Cloudinary 单独面板配置 Cloud Name 与 unsigned preset。也支持启动前配置：

```powershell
$env:CLOUDINARY_CLOUD_NAME="你的 cloud name"
$env:CLOUDINARY_UPLOAD_PRESET="你的 unsigned upload preset"
.\run.bat
```

本地 ComfyUI 与豆包上传桥接不要求先转换成公网素材 URL。普通 Provider 凭据在公共响应中脱敏，空值保存保留已有值；豆包专用管理凭据入口支持回显，需限制管理访问。

## 命令行使用方法

以下采集、下载与互动示例可独立于 Web 运行。`cache/` 用于测试产物；需要长期保留的媒体请输出到 `store/` 下。

### 抓取博主主页作品列表

基础用法：

```powershell
python services/douyin/service.py "主页地址" -o cache\urls.txt
```

示例：

```powershell
python services/douyin/service.py "https://www.douyin.com/user/MS4wLjABAAAApzZePR1kYLd7RXrQvyj5kKJvuK7XvEw-oeNe-ahH5PI?from_tab_name=main&relation=0&vid=7652265576731359337" -o cache\urls.txt
```

作品很多时，加大分页滚动次数和等待时间：

```powershell
python services/douyin/service.py "https://www.douyin.com/user/MS4wLjABAAAAWtdddV646SZLHVCxRm6DZjHbMX2dgAiyqVhiAYMDUm8?from_tab_name=main&vid=7677547779459179242" --max-scrolls 1000 --idle-rounds 30 --wait 2 -o cache\urls.txt
```

如果知道大概作品数，可以用 `--target-count` 达到数量后自动停止：

```powershell
python services/douyin/service.py "主页地址" --target-count 300 -o cache\urls.txt
```

遇到登录、验证码或空结果，用可见浏览器模式：

```powershell
python services/douyin/service.py "主页地址" --headful --user-data-dir store\douyin\.douyin-browser -o cache\urls.txt
```

### 下载单个作品

下载标准视频地址：

```powershell
python services/douyin/service.py --download "https://www.douyin.com/video/7577345577656035574" --download-dir cache\downloads
```

下载标准图文或 note 地址：

```powershell
python services/douyin/service.py --download "https://www.douyin.com/note/7657685355588900179" --download-dir cache\downloads
```

下载主页弹窗地址也支持，会优先读取 URL 里的 `modal_id`，没有 `modal_id` 时读取 `vid`：

```powershell
python services/douyin/service.py --download "https://www.douyin.com/user/MS4wLjABAAAAWtdddV646SZLHVCxRm6DZjHbMX2dgAiyqVhiAYMDUm8?from_tab_name=main&modal_id=7577345577656035574&vid=7677547779459179242" --download-dir cache\downloads
```

如果主页弹窗链接下载不稳定，可以把 `modal_id` 改成标准作品地址再下载：

```powershell
python services/douyin/service.py --download "https://www.douyin.com/video/7577345577656035574" --download-dir cache\downloads
```

下载全部候选媒体：

```powershell
python services/douyin/service.py --download "作品地址" --download-dir cache\downloads --all-media
```

下载实现原理：脚本先通过 Playwright 打开页面并监听抖音 Web 接口，从接口返回的作品结构里提取 `video.play_addr`、`play_addr_h264`、`images` 等媒体 URL，然后再用 HTTP 把这些播放流或图片地址保存到本地。它不是调用“下载按钮”，所以作品是否允许前端下载按钮可用，不一定等同于脚本能否拿到播放流；但如果抖音风控、登录状态、签名或临时播放地址失效，下载仍然会失败。

### 推荐的互动方式：Chrome 扩展桥接

`--extension-interact` 是当前最稳定的互动方式。Python 不启动也不操控浏览器，只启动本地桥接服务；已安装的 Chrome 扩展在抖音页面上下文里接收任务并执行请求。

安装扩展：

1. 打开 Chrome。
2. 进入 `chrome://extensions/`。
3. 打开“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择本项目的 `services/douyin/chrome_extension` 目录。
6. 确认扩展版本与 `services/douyin/chrome_extension/manifest.json` 中的 `version` 一致；代码更新后需要在扩展页点击“重新加载”。

执行评论、点赞、收藏：

```powershell
python services/douyin/service.py --extension-interact "作品地址" --comment "我也来一台" --like --favorite
```

支持带 `modal_id` 的主页弹窗地址：

```powershell
python services/douyin/service.py --extension-interact "https://www.douyin.com/user/MS4wLjABAAAAe1U5r2VogLrabUBs8ebistBpRd4naDk_4GuPbE1ozgOLt6obzQ8lgTOn4hvs6ZUH?modal_id=7208412974606798138" --comment "xuedaole" --like --favorite
```

导出结果到日志文件：

```powershell
python services/douyin/service.py --extension-interact "作品地址" --comment "xuedaole" --like --favorite > cache\extension_result.json
```

PowerShell 重定向出来的 JSON 可能是 UTF-16，使用项目里的分析脚本查看结果：

```powershell
python analyze_extension_result.py cache\extension_result.json
```

成功结果应重点看这些字段：

```text
version: 以 `services/douyin/chrome_extension/manifest.json` 为准
readiness.reason: captured-comment-list
ACTION like     success: true
ACTION favorite success: true
ACTION comment  success: true，并且 comment_id 不为空
```

扩展桥接的等待逻辑：

- Python 从输入 URL 提取 `modal_id` 或作品 ID。
- Python 把任务交给本地桥接服务 `http://127.0.0.1:18765`。
- 扩展收到任务后打开标准作品页，例如 `https://www.douyin.com/video/<作品ID>`。
- 扩展等待页面加载完成，再等待抖音页面捕获到目标作品的 `comment/list` 接口。
- 捕获到目标作品接口后，再在页面上下文调用互动接口。

当前使用的互动接口：

```text
点赞: /aweme/v1/web/commit/item/digg/
收藏: /aweme/v1/web/aweme/collect/
评论: /aweme/v1/web/comment/publish/
```

注意：旧的 `/aweme/v1/web/aweme/favorite/` 在当前页面里可能返回收藏列表，不是可靠的收藏动作接口；扩展版本以 manifest 为准，已改用 `collect`。

### 其他互动方式

页面自动化模式会用 Playwright 打开浏览器并点击页面按钮：

```powershell
python services/douyin/service.py --interact "作品地址" --comment "评论内容" --like --favorite --headful --user-data-dir store\douyin\.douyin-browser
```

直接接口模式会复用浏览器 cookie 组装 Web API 请求，但容易缺少抖音页面运行时生成的签名参数：

```powershell
python services/douyin/service.py --api-interact "作品地址" --comment "评论内容" --like --favorite --user-data-dir store\douyin\.douyin-browser
```

一般优先使用 `--extension-interact`。


### 常用参数

```text
-o, --output          抓主页列表时的输出文件；.json 输出 JSON，否则一行一个 URL
--headful             显示浏览器窗口，适合手动登录或处理验证码
--user-data-dir       持久浏览器资料目录，默认 store\douyin\.douyin-browser
--max-scrolls         抓主页列表时最多滚动次数，默认 500
--idle-rounds         连续多少轮没有新作品后停止，默认 20
--target-count        抓到指定数量后停止
--scroll-pixels       每次滚动距离，默认 3500
--wait                每次滚动后的等待秒数，默认 1.5
--download            下载单个作品地址
--download-dir        下载保存目录，默认 store\douyin\downloads
--all-media           下载接口里的全部候选媒体
--interact            通过页面自动化执行互动
--api-interact        通过直接 Web API 执行互动
--extension-interact  通过已安装 Chrome 扩展桥接执行互动
--extension-collect   通过已安装 Chrome 扩展桥接拉取博主主页作品列表
--comment             互动时发布的评论文本
--like                互动时点赞作品
--favorite            互动时收藏作品
--bridge-port         Chrome 扩展桥接服务端口，默认 18765
--bridge-timeout      等待扩展回传结果的秒数，默认 60
```


## 数据保存与备份

`store/` 保存持久数据，`cache/` 只存放可丢弃的测试、诊断和临时文件。两者都不提交到 Git。

```text
store/
  models/whisper/                     # ASR 权重
  douyin/
    understanding_history.sqlite3     # 理解历史
    web_jobs/                         # 网页任务状态
    web_downloads/                    # 下载媒体、报告、转写、@消息处理记录
    web_url_lists/                    # 保存的作品列表
    .douyin-browser*/                 # 可复用登录资料
  video_creator/
    provider_configs.json             # Provider、LLM、ASR 等配置
    mock_doubao.json                   # 豆包私有凭据与请求模板
    storage.json                      # 素材存储配置
    assets.db                         # 生成任务记录
    reference_library/                # 长期参考素材库
    frame_jobs/                       # 抽帧任务
    generation_jobs/                  # 直接生图/生视频输入与结果
    ai_video_jobs/                    # AI视频故事板、Trace、镜头及成片
    doubao_web/upload_verification/   # 上传验证报告
cache/                                # 临时测试、抓包、调试日志等
```

自定义全局持久目录：

```powershell
python web_app.py --store-dir D:\douyin-store
```

也可设置 `DOUYIN_STORE_DIR`。网关参数表示整个 store 根目录；单独启动 Tab 服务时，其 `--store-dir` 表示该服务自己的子目录。ASR 模型可通过 `DOUYIN_ASR_MODEL_DIR` 单独指定。

备份时先停止写入服务，再完整备份 `store/`，包括数据库、媒体和登录资料。不要只备份数据库后删除它引用的文件。旧版已知持久数据会在网关启动子服务前从 cache 迁移；若目标已存在会报错，不能直接覆盖。抓包 HAR/cURL 可能含登录凭据，放在 cache 并避免分享。

## 部署与服务结构

| 入口 | 默认端口 | 作用 |
| --- | --- | --- |
| `web_app.py` | 8003 | 统一网页与 API 代理 |
| `services/douyin/service.py` | 8101 | 抖音采集、下载、互动与理解 |
| `services/video_creator/service.py` | 8102 | 抽帧、生图、生视频、AI视频与资产库 |
| `services/admin/service.py` | 8103 | Provider、模型和凭据配置 |
| 抖音扩展桥接 | 18765 | 抖音页面任务桥接 |
| @通知监听桥接 | 18766 | 主机 Chrome 与 @监听的本机通信，启动监听时建立 |
| 豆包上传桥接 | 18767 | 按需启动的参考图上传桥接 |
| Ollama（可选） | 11434 | 单独启动的本地模型 API，工作台不会代为启动 |
| ComfyUI（可选） | 8188 | 单独启动的本地生成服务，工作台不会代为启动 |

`services/core/registry.py` 注册 Tab，前端通过同源 `/tabs/<id>/` 访问各服务，通常只需从网关访问。功能服务可独立启动和替换。

局域网默认监听 `0.0.0.0`，需要服务器防火墙允许相应访问。后台保存并可回显部分敏感配置，`?admin=1` 只是显示入口，不是身份认证；不要将默认部署直接暴露到不受信任的公网。需要共享访问时自行配置反向代理认证和访问控制。

隐藏工作台的后台 Tab（不会停止后台子服务，也不构成访问隔离）：

```powershell
python web_app.py --host 0.0.0.0 --port 8003 --no-admin
```

分别启动服务的例子（每条命令使用独立终端）：

```powershell
python services/douyin/service.py --web --web-host 127.0.0.1 --web-port 8101 --cache-dir cache\douyin --store-dir store\douyin
python services/video_creator/service.py --host 127.0.0.1 --port 8102 --cache-dir cache\video_creator --store-dir store\video_creator
python services/admin/service.py --host 127.0.0.1 --port 8103 --store-dir store\video_creator
python web_app.py --host 0.0.0.0 --port 8003 --no-start-services
```

服务器上的 Chrome 应安装所需扩展并保持登录；远程网页用户无需安装服务端扩展。每位用户使用自己账号的场景需要相应独立浏览器和服务配置，当前部署不会自动实现多用户账号隔离。

代码组织：跨 Tab 基础设施在 `services/core/`；AI视频工作流在 `services/video_creator/workflow/` 与 `workflows/`；单一媒体/AI 能力在 `tools/`；HTTP 服务负责输入和任务状态，工作流负责依赖、节点和中间产物。抖音 @处理另有 MCP 工具边界；AI视频工具的完整可发现 MCP 服务仍在建设中。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 页面打不开或启动报端口占用 | 检查启动终端输出；标准启动使用 run.bat；修改端口时同步网关与服务配置 |
| 采集为空、下载失败或要求验证 | 使用已登录 Chrome，或命令行 `--headful` 手动完成登录/验证码；确认作品链接有效 |
| 抖音互动一直等待扩展 | 确认加载的是抖音扩展、版本与源码一致，并在同一 Chrome 用户中打开已登录抖音页 |
| @通知没有新任务 | 检查监听状态、当前账号、真实通知请求状态及基线；首次已有通知不自动回复 |
| 视频理解失败 | 检查 ffprobe、本地 ASR 模型完整性及独立视觉 LLM 配置；查看任务节点错误和报告目录 |
| ComfyUI 模型可选但生成失败 | 确认模型权重、工作流和自定义节点真实存在，检查 ComfyUI 返回的验证错误 |
| 豆包模型不显示 | 后台启用豆包 Mock Provider，保存默认模型，刷新生成页面；仅保存 Cookie 不会完成 Provider 注册 |
| 豆包显示已配置但生成失败 | 状态只验证配置存在；更新 Cookie，检查模板、账号额度、模型权限和真实业务错误 |
| 豆包参考图上传超时/脚本失联 | 检查 Doubao Upload Bridge、登录页及 18767；重载扩展并刷新豆包页；无需手动选图或点启动 |
| 豆包收到确认提示后失败 | 检查是否提供真实 confirm 模板，模型/时长/比例是否与返回一致；不匹配时不会自动确认 |
| 视频提交成功但还没有成片 | 查看轮询进度和会话 ID；SSE 回复结束不是生成结束，避免重复提交 |
| 豆包画幅/清晰度与期望不同 | 网页服务可能调整参数，以下载文件实际尺寸为准；当前不保证精确画幅或分辨率 |
| 云端参考素材不可访问 | 检查 OSS/Cloudinary 的公网 URL、上传配置及 Provider 的素材要求 |
| 服务重启后任务中断 | 查看保留的任务状态、会话 ID/子任务，再决定是否重试；网页任务不会把未知远端状态当作成功 |

## 开发验证

Python 语法检查可将字节码放在 cache，避免仓库内出现 `__pycache__`：

```powershell
$env:PYTHONPYCACHEPREFIX="$PWD\cache\pycache"
python -m py_compile web_app.py services/douyin/service.py services/video_creator/service.py services/admin/service.py analyze_extension_result.py
python -m unittest discover -s services/video_creator/tests -p "test_*doubao*.py"
python -m unittest discover -s services/video_creator/tests -p "test_generation_routes.py"
node --test services/video_creator/tests/test_doubao_upload_background.cjs services/video_creator/tests/test_doubao_upload_content.cjs services/video_creator/tests/test_doubao_upload_page.cjs
```

在线生成验收应先验证原始抓包/独立脚本，再通过工程 HTTP 接口测试同样输入，并持续观察至成功、失败或取消。成功需检查下载媒体可解码及访问地址有效，不能只判断 HTTP 200。

互动验收使用用户指定的单条作品，避免批量评论、点赞或收藏。测试资料和日志放 cache，持久结果放 store；不把 Cookie、Token、签名地址或原始抓包加入提交。待办及能力规划见 [todo.md](todo.md)，工程约定见 [AGENTS.md](AGENTS.md)。
