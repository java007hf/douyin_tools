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

视频创作页面按“视频抽帧 / 生图 / 生视频”切换功能。模型下拉选项包含 ComfyUI 当前已安装模型，以及 MiniMax、Seedance 的云端模型；MiniMax 和 Seedance 在后台控制台中分别配置，普通入口不会显示后台控制 Tab。

后台控制台只填写连接所需的 API 地址、API Key 和 Token，MiniMax、Seedance 的 API 地址会预填默认值。配置保存到 `cache/video_creator/provider_configs.json`；再次打开时会回填配置，敏感字段仅显示为 `********`，留空保存不会覆盖已有凭据。模型版本和比例等生成参数在 AI 创作工具中选择。

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
--user-data-dir       浏览器资料目录，建议使用 cache\.douyin-browser
--max-scrolls         抓主页列表时最多滚动次数，默认 500
--idle-rounds         连续多少轮没有新作品后停止，默认 20
--target-count        抓到指定数量后停止
--scroll-pixels       每次滚动距离，默认 3500
--wait                每次滚动后的等待秒数，默认 1.5
--download            下载单个作品地址
--download-dir        下载保存目录，建议使用 cache\downloads
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

所有临时文件、测试结果、下载内容、浏览器 profile、抓取 URL 列表都放到 `cache/` 下，例如：

```text
cache\urls.txt
cache\downloads\
cache\.douyin-browser\
cache\extension_result.json
```

仓库根目录只保留程序、扩展源码和说明文档。
