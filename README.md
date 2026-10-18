# Douyin Tools

## 第三方依赖记录

| 依赖 | 用途 | 安装方式 | 验证 |
| --- | --- | --- | --- |
| Python `opencv-python-headless` | 视频读取、抽帧和图片写入 | `pip install -r requirements.txt` | `python -c "import cv2; print(cv2.__version__)"` |
| FFmpeg | 视频裁剪、音视频封装、保留参考视频音频 | Windows 使用 `winget install --id Gyan.FFmpeg.Shared --exact` | `ffmpeg -version` |
| Playwright Chromium | 抖音页面采集和下载相关浏览器能力 | `python -m playwright install chromium` | `python -m playwright --version` |

FFmpeg 安装后如果当前终端找不到 `ffmpeg`，请重新打开 PowerShell，使系统 PATH 生效。当前开发机安装位置由包管理器维护，不提交到仓库。

这个项目提供一个 Python 命令行工具，用来处理抖音 Web 页面上的作品数据：

- 输入博主主页地址，获取当前博主自己的作品地址列表。
- 输入单个作品地址，下载作品里的视频或图片到本地。
- 对指定作品执行评论、点赞、收藏。

主页作品抓取会用主页 URL 里的 `sec_uid` 匹配接口返回的 `author.sec_uid`，避免把推荐流、导航入口或其他博主的作品混进结果。

## 环境安装

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## 抓取博主主页作品列表

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
python services/douyin/service.py "主页地址" --headful --user-data-dir cache\.douyin-browser -o cache\urls.txt
```

## 下载单个作品

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

## 推荐的互动方式：Chrome 扩展桥接

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

## 其他互动方式

页面自动化模式会用 Playwright 打开浏览器并点击页面按钮：

```powershell
python services/douyin/service.py --interact "作品地址" --comment "评论内容" --like --favorite --headful --user-data-dir cache\.douyin-browser
```

直接接口模式会复用浏览器 cookie 组装 Web API 请求，但容易缺少抖音页面运行时生成的签名参数：

```powershell
python services/douyin/service.py --api-interact "作品地址" --comment "评论内容" --like --favorite --user-data-dir cache\.douyin-browser
```

一般优先使用 `--extension-interact`。

## 网站部署

### ComfyUI 生图/生视频

视频创作 Tab 默认连接本机 `http://127.0.0.1:8188`，可通过环境变量配置 ComfyUI 和视频工作流：

```powershell
$env:COMFYUI_URL="http://127.0.0.1:8188"
$env:COMFYUI_T2V_WORKFLOW="C:\workflows\t2v_api.json"
$env:COMFYUI_I2V_WORKFLOW="C:\workflows\i2v_api.json"
$env:COMFYUI_R2V_WORKFLOW="C:\workflows\r2v_api.json"
python web_app.py --host 0.0.0.0 --port 8003 --service-host 0.0.0.0
```

工作流文件应使用 ComfyUI API 格式，并包含 `LoadImage`/`LoadVideo` 节点。图片无参考图时走文生图，有参考图时走图生图；视频按参考素材自动选择 T2V、I2V 或 R2V。每次提交立即进入生成资产 Feed，卡片会展示 prompt、参考文件、参数及排队/执行/完成/失败状态。

启动统一前端和全部 Tab 服务：

```powershell
python web_app.py --host 0.0.0.0 --port 8003 --service-host 0.0.0.0
```

Windows 也可以直接双击项目根目录的 `run.bat` 启动全部服务。

访问方打开：

```text
http://服务器IP:8003
```

后台控制台（仅管理员使用）访问：

```text
http://服务器IP:8003/?admin=1
```

视频创作页面按“视频抽帧 / 生图 / 生视频 / AI视频”切换功能。模型下拉选项包含 ComfyUI 当前已安装模型，以及 MiniMax、Seedance 的云端模型；MiniMax 和 Seedance 在后台控制台中分别配置，普通入口不会显示后台控制 Tab。

“生视频”直接提交一次模型生成任务；“AI视频”前台只填写创作要求、可选参考图/参考视频和总时长，并运行固定、可观测的四阶段 Workflow：理解诉求并生成故事板、逐镜头调用 T2V/I2V/R2V、AI 审片、合成最终视频。镜头数由故事板 LLM 自行决定；若用户在创作要求中明确指定镜头数，则由故事板遵循该约束。故事板与审片 JSON、镜头文件和成片均保存在 `store/video_creator/ai_video_jobs/<task-id>/`。

后台控制包含相互隔离的“生图&视频 LLM”和“AI视频”配置。“生图&视频 LLM”只供普通生图/生视频页面改善提示词；“AI视频”独立配置 Agent API 地址、API Key、Agent 模型、默认生图 Provider/模型，以及分别独立的 T2V、I2V、R2V Provider/模型和故事板规划、审片 System Prompt。AI 视频不会读取“生图&视频 LLM”的凭据或模型。故事板规划节点同时完成意图理解，输出 `creative_intent` 和 `shots`。每个镜头包含序号、起止时间、共时长、镜头与转场、美学与光影、画面与动作、声音与台词、生成 prompt 和参考策略。Workflow 会根据 `generation_plan.mode` 自动选择 T2V、I2V 或 R2V 路由，并把各镜头时长及时间轴归一化到用户指定的总时长。

AI 视频故事板还包含 `continuity_bible`、镜头 `depends_on`、`continuity.must_preserve` 与 `generation_plan`。MVP 支持先生成镜头首帧再执行 I2V，以及提取上一镜头尾帧供下一镜头 I2V 使用；生成的连续性参考图和首尾帧都保存在任务目录并通过 Workflow artifact ID 传递。后台可分别选择默认生图和视频 Provider/模型。`reference_pack_i2v` 会把原始身份参考与上一镜头尾帧同时绑定到 H3 ref2va；真正的多模态视频审片仍属于后续能力。

AI 视频默认采用质量优先档：H3 768p 使用约 1MP 的原生画布、16:9 和 24 个完整采样步骤，不启用 8-step Turbo。后台“AI视频”可调整清晰度、画幅和采样步数；在 12GB 显存约束下，768p 每镜头最多 5 秒，1080p 每镜头最多 3 秒。

后台控制台只填写连接所需的 API 地址、API Key 和 Token，MiniMax、Seedance 的 API 地址会预填默认值。配置保存到 `store/video_creator/provider_configs.json`；再次打开时会回填配置，敏感字段仅显示为 `********`，留空保存不会覆盖已有凭据。模型版本和比例等生成参数在 AI 创作工具中选择。

网站由一个统一前端和多个独立 Tab 服务组成：

- `web_app.py`：统一前端和 Tab 注册入口，默认端口 `8003`。
- `services/douyin/service.py`：抖音工具服务，默认端口 `8101`。
- `services/video_creator/service.py`：视频创作服务，默认端口 `8102`，当前提供输入和任务契约占位页面。
- `services/admin/service.py`：后台控制服务，默认端口 `8103`，独立管理 MiniMax、Seedance 和 ComfyUI 模型配置。

每个 Tab 都有独立端口，可以单独启动、替换或部署；统一前端通过 `services/core/registry.py` 读取 Tab 配置。服务器部署时：

- 服务器需要安装 Chrome。
- 服务器 Chrome 需要加载本项目的 `services/douyin/chrome_extension/` 扩展，并保持 manifest 中的版本与服务一致。
- 服务器 Chrome 需要保持可用的抖音登录态；如果遇到验证码或风控，需要在服务器 Chrome 上处理。
- 用户侧只需要打开 `http://服务器IP:8003`，不需要安装 Chrome 扩展。

网页端采集只需要填写“目标数量”。滚动次数和等待时间由服务端自动控制，达到目标数量后立即停止；不填写目标数量时使用默认滚动上限继续采集。命令行模式仍保留 `--max-scrolls`、`--wait` 等参数供高级场景使用。

如果希望每个用户使用自己的抖音账号和自己的浏览器上下文，则扩展需要安装在用户自己的 Chrome 里。

也可以分别启动 Tab 服务：

```powershell
python services/douyin/service.py --web --web-host 0.0.0.0 --web-port 8101 --cache-dir cache\douyin
python services/video_creator/service.py --host 0.0.0.0 --port 8102
python web_app.py --host 0.0.0.0 --port 8003 --no-start-services
```

## 常用参数

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

## 文件约定

临时文件、测试结果和测试用媒体/浏览器 profile/URL 列表放到 `cache/`；需要保留的用户数据放到 `store/`。测试示例：

```text
cache\urls.txt
cache\downloads\
cache\.douyin-browser\
cache\extension_result.json
```

仓库根目录只保留程序、扩展源码和说明文档。
## Cloudinary 参考素材上传

云端 MiniMax 的参考图片/视频必须能被公网访问。项目支持使用 Cloudinary 的 unsigned upload preset：用户在 AI 创作工具中选择本地参考素材后，服务会先上传到 Cloudinary，再把返回的 `secure_url` 提交给云端模型。

在启动项目的同一个 PowerShell 窗口中配置：

```powershell
$env:CLOUDINARY_CLOUD_NAME="你的 cloud name"
$env:CLOUDINARY_UPLOAD_PRESET="你的 unsigned upload preset"
.\run.bat
```

`CLOUDINARY_UPLOAD_PRESET` 需要在 Cloudinary 控制台中创建为 unsigned 类型。只把 Cloud Name 和 Upload Preset 暴露给浏览器，不要把 API Secret 放入前端或提交到代码库。

### 抖音视频理解

### @我视频分析与自动回复

抖音工具新增“@我自动回复”：监听登录页面的提及通知，下载对应视频，复用独立的“视频理解 LLM”完成音频转写及画面分析，再生成 300 字以内的回复并绑定原评论 ID。支持自动发送或仅生成草稿；图文、下载/分析失败、缺少作品/评论 ID、账号不匹配均不发送。

@回复由主 Agent 识别评论意图：单纯 @、test、问候或未明确提出视频问题时仅回复视频摘要；明确的视频问题结合视频证据回答，证据不足时说明无法确认。评论文字仅供意图识别，视频理解 MCP 不接收评论；问答 MCP 仅接收提取的问题。主 Agent 与 MCP 内部 LLM 目前使用独立于其他业务的“视频理解 LLM”配置。

架构采用官方 Python MCP SDK 的 stdio 客户端和两个独立 Server：`understanding` 暴露 `understand_video`，`reply` 暴露 `summarize_video` 和 `answer_video_question`。主 Agent 通过 `tools/list` 发现工具并通过 `tools/call` 调用，意图结果经过固定白名单校验。每条任务的 `agent_trace.json` 记录意图、工具调用及错误；相同视频及模型/上下文配置复用已完成分析缓存。任务状态、目录、串行队列与评论发送仍由程序管理，MCP 不提供直接发布工具。

独立启动示例：`python -m services.douyin.mention_mcp --kind understanding --task-dir cache/mcp-test --config-path store/video_creator/provider_configs.json --profile store/douyin/.douyin-browser-download`；回复 Server 将 `--kind` 改为 `reply`，并使用已有 `summary.json` 的任务目录。运行前安装 `requirements.txt`，协议实现参考 [MCP Python SDK v1 文档](https://py.sdk.modelcontextprotocol.io/v1/)。

1. 在 Chrome 扩展管理页重载 `services/douyin/chrome_extension`（版本 `0.4.8`），刷新已打开的抖音页面，确保该 Chrome 用户已登录抖音。
2. 在后台配置并启用“视频理解 LLM”，确认单条“视频理解”可以下载并分析作品。
3. 启动 `run.bat`。默认设置 `DOUYIN_MENTION_AUTOSTART=1`，启动 Chrome 并自动开启每 60 秒检查一次的新 @通知分析与回复。扩展打开或复用个人主页，自动打开通知及 @我筛选来发现真实读取请求，无需手动打开面板或点击“开始监听”。
4. 在 Admin 控制台 → @我自动回复中管理开始/停止监听、检查间隔和自动回复/草稿模式；抖音工具 → @我自动回复保留状态及处理记录。缺少视频理解配置时每 30 秒自动重试，停止可取消等待；登录失效需用户登录，页面结构变化会显示错误。首次使用账号时登记已有通知为基线；已有账号重启后根据持久化读取时间接收停机期间的新提及。

服务默认自动监听，包括直接运行 Python 服务。要关闭启动时的自动监听，可设置环境变量 `DOUYIN_MENTION_AUTOSTART=0`。自动启动不会安装扩展、填写凭据或绕过验证码；Chrome 需使用安装扩展且已经登录抖音的用户配置。

扩展优先使用真实网络请求：`mention_requests.js` 在页面的 MAIN 环境、`document_start` 阶段捕获 fetch/Request/XHR 请求及 JSON 响应，避免较晚注入漏掉个人资料和首批通知。[Chrome 内容脚本文档](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts)说明了这两个设置。通知采集已移除 DOM 和 React 属性扫描，个人主页的 `showTab=favorite_collection` 只是页面入口，真正的通知读取地址来自该页面的网络请求。

扩展首次自动打开“通知 → @我的”用于发现实际读取请求。之后每轮先请求个人资料确认账号，再按原始读取请求的 URL、方法、请求头、请求体和 fetch/XHR 通道轮询；通知面板无需一直展开，个人主页关闭后扩展会在下一次读取时重新打开。GET 请求按完整过滤参数分开保存模板；POST 只有在实际响应被识别为通知列表时才允许重放，修改、删除、标记已读等请求不重放。请求模板只保存在浏览器内存，完整 URL、Cookie、Token、签名和请求体不进入后端任务记录。页面“通知请求状态”展示接口路径、HTTP/业务状态、字段名称、脱敏结构及解析数量，便于真实抓包适配。读取失效时自动重新打开通知，并最多每五分钟刷新个人主页一次；发送回复不会通过刷新或重开页面重试。

当前支持真实通知响应 `notice_list_v2[].at`，从评论对象或 `schema_url` 提取作品、原评论及父评论 ID；也支持明确的 `at_list`/`mention_list` 等字段，以及带“在评论中提到了你”标识的结构化响应；不猜测数值通知类型。缺少作品 ID 或原评论 ID 的通知跳过，64 位数字 ID 在解析前保留为字符串。首次读取已有通知作为基线，随后发现带时间戳的历史通知也按启动时间跳过。每轮请求失败、签名过期或响应结构未知时，不将旧缓存当作有效轮询，也不推进基线或创建分析任务。原请求中的临时参数不能保证永久有效，代码不实现通用的抖音签名算法；失败时需刷新页面重新捕获，实际签名刷新方式仍需登录环境验证。

单条历史通知验收可向 `/api/mentions/process-existing` POST `{"id":"列表中的完整通知 ID"}`，只允许当前账号尚未处理的基线记录进入队列；已处理或发送结果未知的记录不会重新发送。

@评论处理完成后，成功的视频分析会保存到“视频解析”的同一历史列表，标记为“@评论回复 · 用户名”；手动记录显示“手动解析”。详情和报告包含回复对象、正文及处理状态（包括草稿或发送失败），服务启动会补入已有的 @分析结果，已删除的历史不会重新出现。

收到新 @并入队时即创建解析历史，不必等到完成。历史显示排队位置、进行中阶段、发送中及最终状态，打开后每5秒自动刷新；分析未完成的详情显示进度和原视频入口，报告完成后再开放。

@消息采用 SQLite 持久化 FIFO 队列，模型处理和回复发送保持单条执行；独立下载准备通道在当前任务分析时提前下载后续视频，历史显示“视频已下载，等待 LLM 处理”，模型轮到该任务时复用文件。提前下载使用独立持久浏览器目录，下载失败由正式处理重试。采集仍定时运行，失败任务不阻塞后续任务。页面显示等待总数、处理中数量和每条排队位置。服务重启保留未开始的任务，并按账号保存成功读取时间，验证登录账号后接收停机期间的新通知；首次使用的账号仍建立基线。已开始或发送中的中断任务不自动重试，避免重复回复。点击“停止监听”会取消等待任务。

监听桥接只绑定 `127.0.0.1:18766`，与手动操作的 `18765` 分开。通知按账号、作品、评论 ID 在 SQLite 中持久去重；缓存位于 `<抖音 store-dir>/web_downloads/mentions/`，包含逐任务视频理解报告和 `mentions.sqlite3`。页面显示分析进度、草稿、发送结果和错误。停止后取消等待任务并禁止尚未提交的回复，已提交的网络请求不能撤回；服务重启会标记遗留任务中断，run.bat 标准启动会重新监听并建立基线。发送采用单次 POST，无普通评论回退；失败或结果未知不会自动重发，需核对原评论。仅草稿模式可在页面复制正文。

本地验证：`python -m unittest services.douyin.tests.test_mention_monitor`、`node services/douyin/tests/test_mention_requests.js` 和 `node services/douyin/tests/test_mentions_extension.js`。覆盖页面早期请求、fetch/Request/XHR 请求头与请求体、账号切换、64 位 ID、失效缓存、过滤条件、基线及单次发送。2026-10-11 已使用 Jessica 的单条顶层 @评论完成真实通知、视频分析与回复验收：原评论 `7695373081279611691`，接口返回回复评论 `7695381560526324517`，回复目标一致；嵌套评论参数仍需真实验收。

### 视频理解配置与历史

最终分析在同一次 LLM 请求中生成完整 `summary` 和口语化 `comment_reply`，并保存回复风格版本。@摘要回复直接使用校验通过的 `comment_reply`，不再发起独立回复模型请求；合并文案不合格时最多额外改写一次。旧分析没有合并文案时保留补生成路径；明确的视频问答仍使用独立问答工具。两条路径共用 `services/douyin/reply_style.py` 的写作规则与字符限制。

本机 ASR 对比后选择 `large-v3-turbo`，通过控制台“本地语音转写模型”保存，不在代码中写死选中的模型。该模型启用词级时间对齐和静音幻觉抑制；这能降低静音段的错误输出，但不能保证消除同音词、英文术语或截断语音的识别错误。模型缓存保存在 `store/models/whisper`。

每次完成后自动生成 `report.md`，包含摘要、核心观点、时间线、阶段耗时、完整原始转写、画面观察、音频分段归纳及采样图片。网页展示完整报告并提供下载、缓存视频播放和“理解历史”入口。SQLite 数据库 `store/douyin/understanding_history.sqlite3` 的每条记录分别保存来源链接、报告正文及文件路径、视频缓存路径和结构化结果；历史在刷新或服务重启后保留，启动时自动补录以前已完成的任务。视频文件保留在任务持久目录中，不将视频二进制写入数据库；不要手动清理仍需要回看的持久文件。

抖音工具的“视频理解”支持单个作品链接或分享文案，下载视频后以完整音轨转写和均匀采样画面生成内容分类、摘要、核心观点和时间线。总结优先以完整音频转写为准，画面和字幕只作辅助；冲突时以音频为准并标注，未识别到语音时注明仅基于采样画面。报告的 `summary_basis` 字段记录 `audio_primary` 或 `visual_only`。时间线可跳转原视频，展开后可查看全部语音转写，支持下载摘要 JSON。当前支持两小时以内的视频，不支持图文作品；画面为采样观察，不能保证覆盖每个动作，转写及归纳可能有误，摘要不会将作者观点当作已核实事实。

执行 `python -m pip install -r requirements.txt` 安装语音转写组件。后台控制新增独立的“视频理解 LLM”配置，与提示词辅助和 AI视频配置隔离。必须在控制台选择接口类型、填写 API 地址及视觉模型并保存；代码没有默认地址、模型或 Key，也不回退到其他 LLM 配置。本机 Ollama 示例：接口类型选 Ollama，API 地址填写 `http://127.0.0.1:11434/v1`，模型填写实际安装的 `qwen3.8:latest`，本地 Key 可留空。也可选择 OpenAI 兼容接口并填写对应服务地址、模型及 Key。接口类型决定请求格式，与端口号无关：Ollama 使用 `/api/chat`，按控制台“上下文窗口（tokens）”设置上下文（4096–262144，旧配置按 16384 兼容）并关闭思考输出；增大窗口会增加内存/显存消耗，不保证提速；OpenAI 兼容服务使用 `/chat/completions`。

音频在本机通过 faster-whisper 的 CPU/int8 模式转写，默认 `small`，可在后台选择 `tiny/base/small/medium/large-v3`。首次使用自动下载模型到 `store/models/whisper/`，需要网络；音轨通过 ffprobe 检查（随 FFmpeg 安装）。模型不可达、音频转写失败或模型返回格式错误时会明确报错，不会用无声画面冒充口播摘要。

任务串行处理，页面持续轮询直至完成或失败，刷新后恢复跟踪。服务重启会将遗留运行任务标记中断，需重新提交。任务视频、采样画面、转写、画面观察、分段语音归纳、最终摘要及节点状态均保存于 `<抖音 store-dir>/web_downloads/understanding/<任务ID>/`，页面任务记录在 `<抖音 store-dir>/web_jobs/`。云端视觉模型会接收采样图片和音频转写文本；默认 Ollama 在本地分析。


### 持久数据与临时缓存

`store/` 保存控制台配置、数据库、素材库、任务历史、报告、用户媒体和浏览器登录状态，`cache/` 仅保存可清理的测试、日志和临时文件。完整目录结构及规则见 `AGENTS.md` 的 Persistent Store。两个目录均不提交 Git；迁移部署时应备份整个 `store/`，其中包含敏感配置。

默认持久目录为项目根目录下的 `store/`。网关可用 `--store-dir` 或环境变量 `DOUYIN_STORE_DIR` 指定根目录；单独启动 Tab 时，其 `--store-dir` 指向对应服务子目录。ASR 模型默认在 `store/models/whisper/`，可通过 `DOUYIN_ASR_MODEL_DIR` 单独覆盖。原 `--cache-dir` 仅用于临时数据，不再决定配置/数据库位置。

标准网关启动会在启动子服务前迁移旧 `cache/douyin`、`cache/video_creator` 中已知的持久数据，保持媒体 URL、数据库关系和历史记录。迁移前须停止所有服务；已有同名目标时会明确报错，不覆盖已有数据。诊断及测试目录不会迁入 `store/`。

### 豆包网页请求生图

生图模型列表新增 `豆包网页 / mock_doubao_seedream`，使用独立基础工具
`services/video_creator/tools/ai/mock_doubao.py`，通过现有 `/api/generate-image`
任务接口执行，完成后将图片下载到 `store/video_creator/generation_jobs/<task-id>/`。
任务沿用现有进度、错误和资产 Feed。此名称表示请求通道，不代表可任意指定
Seedream 版本；实际模型由捕获的豆包请求决定。

私有配置位于 `service_store("video_creator") / "mock_doubao.json"`，遵循
`DOUYIN_STORE_DIR` / 服务 `--store-dir`。配置包含 `base_url`、`endpoint`、
`headers`、`query`、`body` 和 `timeout`（秒，默认 180，最高 600）。
`body` 当前支持实验脚本的 Android `uplink_body.send_message_body` 协议，
其中 `content` 是包含 `text` 的 JSON 字符串。网页协议若不同，需要新增对应适配，
不能直接替换 body。请从自己已登录的有效请求更新完整模板与凭据，保留设备字段和
签名的原始对应关系；工具仅更新消息 UUID、时间与提示词，不伪造或刷新认证签名。
配置不会通过公开 Provider API 返回，不能提交到 Git。

当前仅支持文生图，不支持本地参考图上传。表单数量设为 1；这代表一次请求，
豆包可能返回多张图片。比例、分辨率及实际出图数量由请求模板/豆包端决定，
不保证服从表单参数。网络失败、登录失效、空结果均终止任务；生成 POST 不会
自动重试，避免重复生成。更新配置后新任务立即读取，无需重启。

独立验证只提交一次并保存图片：

```powershell
python -B -m services.video_creator.tools.ai.mock_doubao "生成一只可爱的小猫咪"
# 本机原实验入口也保留为兼容脚本：
python -B cache/test.py "生成一只可爱的小猫咪"
python -B -m unittest services.video_creator.tests.test_mock_doubao services.video_creator.tests.test_providers
```

2026-10-15：解析及 Provider 回归测试通过；用迁移的旧请求模板进行一次真实请求，
豆包返回业务错误，未取得图片。仍需有效的登录请求模板完成在线验收。

后台控制的「豆包网页登录」提供凭据更新入口：可单独更新 Token、Cookie，
或粘贴请求头 JSON / 完整配置 JSON。设置页回填已有凭据，Token / Cookie 支持显示与隐藏，留空保留已有值；
完整模板中提供的部分会替换对应配置，因此更新签名和设备参数时应成套粘贴。
保存会校验模板并原子写入持久配置，下次生成立即使用，不会自动提交测试生图。
“已配置”仅代表存在配置，不代表登录仍有效。


### 豆包多模型与网页视频协议调查（2026-10-15）

登录后的豆包图像生成菜单实查：Seedream 5.0 Flash（专业快速）、Seedream 5.0 Pro
（专业出图，4 倍消耗）、Seedream 4.5（日常生成）、Seedream 4.0（基础生图）。
生图列表展示对应 mock 模型；尚未配置真实请求差异的选项标记“待绑定请求”并禁用。
原来的 `mock_doubao_seedream` 仅表示旧模板默认通道，不能确定其具体 Seedream 版本。

后台控制 → 豆包网页登录 → 生图模型路由：保存 `model_routes` 对象，每个键为
`mock_doubao_` 开头的小写英文/数字/下划线标识；值包含 `enabled`（可选）和
`request`。`request` 中的 `body`、`query`、`headers`、`base_url`、`endpoint`
递归覆盖原模板；列表整体替换，JSON 字符串不做猜测解析。新增路由必须实际改变请求，
不能只增加别名。模型目录动态读取配置，重新打开/刷新生图页即可加载。
例如真实抓包确认某个模型的 `ext.input_skill` 后，可在其路由的
`request.body.uplink_body.send_message_body.ext.input_skill` 保存完整字符串。
这里不提供未经抓包证实的模型参数值。当前执行器仍只支持 Android send_message_body
协议，网页 Samantha 协议需要另外适配，不能直接把网页请求粘成该 body。

公开前端源码已确认的生视频线索（不是端到端验收）：

- `/samantha/skill/pack`：POST，接收 `skill_type` 与 `condition`；前端视频技能值为 17，
  图像技能值为 3。视频配置从 `data.video_generation.meta.option_list` 读取，另有
  `model_capability` / `model_input_rule` 相关配置，不能用图像模型列表代替。
- 视频输入组件构造 `ext.input_skill` JSON，包含 `skill_id`、`skill_type` 和
  `variables`；旧输入组件能看到 `ratio`、`camera_movement`。具体模型键和现代输入
  协议仍需有效网络请求确认；展示名称及埋点字段不能直接视为执行参数。
- `/samantha/video/query_video_gen_info`：前端 API 声明的 POST 无请求体。尚未确认它
  返回账号额度、队列还是任务状态，不能将它当作按任务 ID 查询的接口实现。
- `/samantha/video/get_play_info`：POST 接收 `vid`，用于获取播放信息；实际下载字段、
  URL 有效期、是否需鉴权仍待响应确认。
- 网页协议存在 `messageToSamanthaChatMessage` 转换，当前 Android
  `/im/sse/send/message` 适配器不能仅改模型名就用于网页视频。

可行接入需要先捕获有效网页会话中的模型配置、单次生成提交、流式/轮询状态和
播放信息响应；明确任务 ID/会话 ID/消息 ID、队列进度、终态、失败和取消协议后，
再实现独立 VideoProvider，持续监控并下载到 generation_jobs，验证视频可解码。
图生视频还需要真实上传协议与素材 key 绑定。生成提交保持单次，未知结果不自动重发。
本次没有提交任何视频生成，也没有把尚未验证的 mock 视频选项开放为可用模型。
未携带网页会话的 skill/pack 探测返回 code 710012001（login invalid）；
内置浏览器能读取登录后的模型菜单，但当前提供的浏览器接口不支持网络抓包。

源码证据来自 https://www.doubao.com/chat/ 当日引用的官方静态资源，研究快照仅放在
`cache/doubao_research/`：`im.js`（API 定义）、`e3.js`（视频配置解析）、
`po.js`（图像输入）、`t0d.js`（视频输入）、`74.js`（Samantha 转换）。


2026-10-17 原始脚本兼容性复核：保留用户恢复的 cache/test.py，另备份至
cache/doubao_baseline/test.original.20261017.py。固定时间、随机数和 UUID 后，
新请求构造器与原脚本的 URL、全部请求头及请求体逐项相等；恢复 9 个动态请求头、
四位随机后缀 _rticket、随机 iid、原始查询拼接和秒级 create_time_ms 规则。
签名的固定片段仍取自私有模板，此逻辑不代表更新认证签名或续期登录。
原始脚本当前单次线上基线返回 HTTP 200，但 ACK status_code=710022002
（当前服务访问频繁，请稍后重试），图片数为 0；原脚本仅依据 HTTP 状态报告 success。
服务现在识别 status_code/status_desc，不把 HTTP 200 当成生成成功；遇到限流停止提交。
请求一致性报告在 cache/doubao_baseline/parity.json，基线响应保存在
store/video_creator/generation_jobs/doubao_baseline_1792199295/。


豆包功能采用分阶段验收，禁止只凭单元测试或 HTTP 200 宣布出图完成：

```powershell
python -B -m services.video_creator.tools.ai.verify_doubao --prompt "生成一只可爱的小狗的图片"
```

诊断器直接调用原始 `cache/test.py` 一次，不调用会重复发送的批量 main。
先检查业务状态、原脚本提取的图片地址，并实际下载/解码图片；脚本阶段失败即停止，
不提交工程生成。脚本通过后才比较原脚本和工程模板，并用相同提示词通过工程 HTTP API
提交一次任务、监控终态并下载/验证工程产物。`--baseline-only` 可只验原脚本。
报告和真实图片保存在 `store/video_creator/generation_jobs/test_py_verify_<id>/`，
不记录凭据和完整请求。参数扩展必须先在脚本阶段用真实已确认字段验证，再迁入工程；
没有确认的参数保持跳过。若原脚本可出图而工程失败，应首先判为工程集成问题进行对照排查。
2026-10-17 本次基线仍收到业务码 710022002，图片数 0，工程阶段跳过。


### 豆包网页生图：真实 HAR/cURL 验收（2026-10-17）

网页实际使用 `POST https://www.doubao.com/chat/completion`，与原 Android
`/im/sse/send/message` 协议不同。`DoubaoWebImageProvider` 仅在私有配置存在
`web_request` 时启用，错误时不会回退或重复提交旧协议。原始 cache/test.py 保持不动。

真实请求参数位置：外层 `chat_ability.ability_type=3`；
`chat_ability.ability_param` 是 JSON 字符串，内含 `ability_type=1` 和
`ability_param.model/style/ratio/input_box_content`。风格使用真实元数据的 key，
例如 `skill_image_styles_3d`、`skill_image_styles_watercolor`；可选项保存在
`services/video_creator/tools/ai/doubao_web_options.json`，不含账号或签名缩略图。
消息文本与 input_box_content 同步更新。新生成必须更新消息/本地会话/unique_key，
重放旧 ID 可能只收到结束事件。保留空的可选 ID，不凭空填充未知参数。

用户提供的 cURL 包含完整 Cookie，但中文已丢失为空格。初次验证仅用同条 HAR 的
原始中文恢复这些文本字段，保留 cURL 的实际 Cookie、URL 和其他请求头。
原始 cURL 不作为 shell 执行，凭据写入 store，普通任务记录不保存凭据。
Admin 的 Cookie 字段用于更新网页会话；「已验证的网页生图请求」可编辑完整
`web_request`，包含 url、headers、body。旧 Android 模板仍保留。

按用户要求先独立脚本再工程验证：

- 独立 `cache/test_har.py` 新请求：Flash + 3D + 9:16，生成并下载 1520×2720 图片。
- 独立脚本比例改为 1:1：生成并下载 2048×2048 图片。
- 独立脚本改为水彩画：生成并下载新的 2048×2048 图片。
- 固定时间与 UUID 后，工程与独立脚本的 URL、请求头、完整 body 逐项相等。
- 工程 HTTP 接口同输入任务 `180b4c26ad4f4371afbd41196b7b1091` 到达 done，
  SSE_REPLY_END 完整，已下载并解码 2048×2048 水彩小狗。

工程报告：`store/video_creator/generation_jobs/180b4c26ad4f4371afbd41196b7b1091/verification.json`。
其他模型名称按 HAR 元数据和实际捕获字段映射，尚未逐个进行在线出图验收。
生图页面增加真实风格选项，比例送入结构化参数；清晰度显示为豆包自动（模板），
生成数量 1 表示一次请求。参考图上传尚未捕获；视频协议接入见下节。

### 豆包网页视频：真实 HAR 验证（2026-10-17）

根据 `cache/video.har` 接入独立的 `doubao_web_video.py`。视频提交仍是
`/chat/completion`，但 `chat_ability.ability_type=17`，`ability_param` 直接包含
`model`、`ratio`、`duration`、`input_box_content`，与生图的嵌套结构不同。
提交流返回 `SSE_ACK` 的会话 ID 后，通过捕获的 `/im/chain/single` 请求每 10 秒
查询该会话，只从已完成的 `creation_block.creations[type=2].video` 读取下载地址。
`SSE_REPLY_END` 只表示提交回复结束，不表示视频已生成。

生视频菜单增加：

| 网页模型 | 工程模型 | 时长 |
| --- | --- | --- |
| Seedance 2.0 Mini | `mock_doubao_seedance_2_0_mini` | 4–15 秒 |
| Seedance 2.0 Fast | `mock_doubao_seedance_2_0_fast` | 4–15 秒 |
| Seedance 2.0 | `mock_doubao_seedance_2_0` | 4–15 秒 |
| Seedance 2.5 | `mock_doubao_seedance_2_5` | 4–30 秒 |

模型标识、比例与时长范围均取自 HAR 的网页菜单配置，只有 Mini 做了在线生成验证。
清晰度由豆包控制。现已支持文生视频和单张参考图 I2V；参考视频与多图参考包仍明确拒绝。
后台「豆包网页登录」的 `web_video_request` 分别保存 submit/poll、i2v_submit/confirm 模板，
共用 Cookie 更新入口并支持凭据回显。完整请求仅保存在私有 store 配置，任务记录
保存会话 ID、查询次数和状态，不保存 Cookie 或签名 URL。

先运行独立 `cache/test_video_har.py`，再进行工程 HTTP 验证。独立 Mini 测试
`video_har_test_917555ec0bd4428babc431ba482a3a13` 已下载并解码 1280×720、
24 fps、241 帧视频，记录在对应 `store/video_creator/generation_jobs/` 目录。
首次独立测试收到“确认参数”回复，未开始渲染；使用明确直接生成的提示词后成功。
工程会识别该回复并结束等待、说明原因，不会把确认回复或 HTTP 200 当成成片。
生成提交不自动重试；查询最多等待 30 分钟，重启时将未完成任务标为中断并保留会话 ID。

工程 `/api/generate-video` 验收任务 `266337c2e7784579b3ace26243a88861` 已到达
done，经 17 次会话查询取得 1280×720、24 fps、约 10 秒成片；网关媒体地址返回
HTTP 200、video/mp4，已解码并查看中间帧。验收记录及视频保存在对应任务目录。


### 两参考图 i2i 独立验收（2026-10-18）

`cache/test_i2i_har.py` 按 `cache/i2i_v2.har` 的实际附件结构，使用两张已上传的
参考图 URI 提交一次新的 Seedream 5.0 Flash 请求。任务
`i2i_har_test_63d8520f36c14db1b3671b475ddc1868` 成功返回 1344×1792 图片，
158 个事件、完整 SSE_REPLY_END、无业务错误，下载文件可解码并已人工查看。
结果及 verification.json 保存在对应 store/video_creator/generation_jobs 目录。
这只验证已上传 URI 的两参考图生成；插件新图片上传尚未通过在线验收，不代表网页
参考图上传入口已接入完成。上传桥接支持重复 --image 参数，逐张提交并等前一张
commit 成功后才发送下一张。


两张新图片上传与 i2i 续验（2026-10-18）：上传桥接记录
`1af9c1d448b344c1a784921dbb896581` 的两个本地参考图均取得新 URI 并 commit 成功。
仅一张具有明确 Python 上传 HTTP 200 记录，另一张上传传输未被 Python 记录，
因此不能称为两张均由 Python 传输。使用这两个新 URI 的独立生成任务
`i2i_har_test_46a524321fa54344862239b59dc33924` 已成功，74 个事件、完整流结束、
无业务错误，下载并解码 1536×1536 结果。工程网页表单尚未接入这个诊断桥接。


0.1.7 双图完整链路验收通过（2026-10-18）：
上传报告 `dcf99fa80ea54573bf6dc441db1e58fd` 记录两次 Python 上传 HTTP 200，
两个不同图片 URI commit 成功，state=done；不存在原生上传回退。
使用这两个新 URI 的独立 i2i 任务 `i2i_har_test_afceb39ec2514fec8f1727f90ebba762`
已成功生成并下载 1536×1536 图片，SSE_REPLY_END 完整，无业务错误，已解码查看。
这是浏览器申请/提交 + Python 传输 + Python i2i 的独立脚本验收，工程网页参考图表单
仍未接入该诊断桥接，不得将其描述为网页工程端到端验收完成。


### 网页表单与 AI视频的豆包 Mock Provider

控制台新增「豆包 Mock Provider」，仅保存配置 ID、名称、默认模型和启用状态；
网页登录 Cookie 与签名请求模板仍由「豆包网页登录」统一维护，不复制到任务或
Provider 普通响应中。控制台 AI视频 → 默认生图 Provider 可选择该配置及对应
`mock_doubao_seedream_*` 模型，不会借用普通提示词辅助 LLM 的凭据。

生图表单选择豆包模型后，可用原参考图和「第二张参考图」上传 1–2 张图，也可选资产；
本地上传与资产合计最多 2 张。上传使用已登录 Chrome 的豆包上传插件，页面自动连接，
不需要手选图片或点击启动。多次上传串行执行，完整记录 Python 传输和 commit；
失败时不提交生成请求。图片与任务结果仍保存在持久 store。

工程集成插件需 0.1.10：自动复用/打开图像创作标签，在每次派发前注入当前脚本，
等待上传组件，并优先选择图片专用或更明确的附件输入框。请求仍完全使用实际抓包
确认的 attachment_block 和独立文本 message；全部 message/block ID 都重新生成。

AI视频资产生图路由已用实际 Provider 配置 ID 实测任务
`b0d406ed21a348fba8af7fc92e9b6197`，生成并解码 2720×1520 道具参考图。
这验证资产生图工具的配置路由，不代表运行了一次完整故事板、视频生成和合成。


网页表单的工程 HTTP 双参考图验收已通过：任务
`73f8d9f55a5d425f867885158683276b` 使用豆包 Mock Provider 配置 ID，两个文件字段
reference_image/reference_image_2 经实际插件上传，各有 Python HTTP 200 和 commit。
Provider 返回完整 SSE_REPLY_END，任务 done，网关图片 HTTP 200 并成功解码。
验收记录保存在该任务目录的 verification.json。图像创作页同时具有多图参考入口与
单图编辑入口，插件优先选择 multiple 的参考图入口；相同优先级才报告歧义。

### 豆包 Mock T2V / I2V（2026-10-18）

生视频选择豆包 Mock 模型，不传图片走 T2V，上传一张图片或选择一个图片资产走 I2V。
I2V 自动通过已登录 Chrome 的上传插件申请凭据，由 Python 传输图片，再提交豆包视频请求。
控制台 Mock Provider 可设置默认视频模型；AI视频的 T2V、I2V 路由可分别选用该 Provider。
凭据继续使用独立网页登录配置，不复制进任务。参考视频和多图参考包暂不支持。

请求来自真实 video.har / i2v.har，确认消息使用已捕获的 confirm 模板，核对模型、时长、比例及消息游标后最多发送一次。
只读轮询每 10 秒进行，最长 30 分钟；生成 POST 不自动重试。完成后下载并验证视频可解码。
Mini、Fast、标准 2.0 和 2.5 的模型选择来自实际网页配置；此次在线验收使用 Mini，其余模型尚未逐一生成验收。

独立 I2V 脚本任务 `video_har_test_b3134f1943a144c68ee6282db4bcfae5` 已完成 10 秒视频。
工程 HTTP 验收 T2V `11467faa9bd040bf80d51bbf42ae7fb1` 和 I2V `598b4b07b17b44cf82e597de998ae770`
均完成 4 秒、24 fps 视频；后者上传报告记录 uploaded=1、committed=1。
成片和验收 JSON 保存在各自 `store/video_creator/generation_jobs/<任务ID>/`。
T2V 本次提交 1:1 但实际返回 1280×720；I2V 返回 720×720。豆包可能调整比例，实际输出尺寸为准。
