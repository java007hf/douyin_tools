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
