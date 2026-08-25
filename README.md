# Douyin Work URL Collector

这个项目提供一个 Python 脚本：

- 输入抖音博主主页地址，抓取当前博主自己的作品地址列表。
- 输入单个作品地址，下载作品里的视频或图片到本地。

脚本基于 Playwright 打开抖音网页并监听接口响应。抓主页列表时会用主页 URL 里的 `sec_uid` 匹配接口里的 `author.sec_uid`，避免把推荐流、导航入口、其他博主作品误抓进来。

## 环境安装

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

依赖文件：

```text
requirements.txt
```

## 抓取博主主页作品列表

基础用法：

```powershell
python douyin_work_urls.py "主页地址" -o cache\urls.txt
```

示例：

```powershell
python douyin_work_urls.py "https://www.douyin.com/user/MS4wLjABAAAApzZePR1kYLd7RXrQvyj5kKJvuK7XvEw-oeNe-ahH5PI?from_tab_name=main&relation=0&vid=7652265576731359337" -o cache\urls.txt
```

输出到 JSON：

```powershell
python douyin_work_urls.py "主页地址" -o urls.json
```

作品很多时，加大分页滚动次数和等待时间：

```powershell
python douyin_work_urls.py "https://www.douyin.com/user/MS4wLjABAAAAWtdddV646SZLHVCxRm6DZjHbMX2dgAiyqVhiAYMDUm8?from_tab_name=main&vid=7677547779459179242" --max-scrolls 1000 --idle-rounds 30 --wait 2 -o cache\urls.txt
```

如果知道大概作品数，可以用 `--target-count` 达到数量后自动停止：

```powershell
python douyin_work_urls.py "主页地址" --target-count 300 -o cache\urls.txt
```

遇到登录、验证码或空结果，用可见浏览器模式：

```powershell
python douyin_work_urls.py "主页地址" --headful --user-data-dir cache\.douyin-browser -o cache\urls.txt
```

## 下载单个作品

下载标准视频地址：

```powershell
python douyin_work_urls.py --download "https://www.douyin.com/video/7577345577656035574" --download-dir cache\downloads
```

下载标准图文或 note 地址：

```powershell
python douyin_work_urls.py --download "https://www.douyin.com/note/7657685355588900179" --download-dir cache\downloads
```

下载主页弹窗地址也支持，会优先读取 URL 里的 `modal_id`，没有 `modal_id` 时读取 `vid`：

```powershell
python douyin_work_urls.py --download "https://www.douyin.com/user/MS4wLjABAAAAWtdddV646SZLHVCxRm6DZjHbMX2dgAiyqVhiAYMDUm8?from_tab_name=main&modal_id=7577345577656035574&vid=7677547779459179242" --download-dir cache\downloads
```

如果主页弹窗链接下载不稳定，可以把 `modal_id` 改成标准作品地址再下载：

```powershell
python douyin_work_urls.py --download "https://www.douyin.com/video/7577345577656035574" --download-dir cache\downloads
```

下载时遇到登录、验证码或拿不到媒体地址：

```powershell
python douyin_work_urls.py --download "作品地址" --download-dir cache\downloads --user-data-dir cache\.douyin-browser --headful
```

默认下载策略：

- `/video/` 作品默认下载 1 个视频文件；如果接口返回多个候选视频源，会默认选择文件大小最大的源。
- `/note/` 如果接口返回视频，会优先下载视频。
- `/note/` 如果是纯图文，会下载图片文件。
- 如果想把接口里的所有候选视频源、图片都下载下来，加 `--all-media`。

下载所有候选媒体：

```powershell
python douyin_work_urls.py --download "作品地址" --download-dir cache\downloads --all-media
```

## 常用参数

```text
-o, --output          抓主页列表时的输出文件；.json 输出 JSON，否则一行一个 URL
--headful             显示浏览器窗口，适合手动登录或处理验证码
--max-scrolls         抓主页列表时最多滚动次数，默认 500
--idle-rounds         连续多少次没有新作品后停止，默认 20
--target-count        抓到指定数量后停止
--scroll-pixels       每次滚动距离，默认 3500
--wait                每次滚动后的等待秒数，默认 1.5
--user-data-dir       浏览器资料目录；建议测试时使用 cache\.douyin-browser
--download            下载单个作品地址
--download-dir        下载保存目录；建议使用 cache\downloads
--all-media           下载接口里的全部候选媒体
```

## 登录状态

脚本默认复用 `.douyin-browser` 目录作为浏览器资料目录。你可以先运行一次 `--headful`，在打开的浏览器里完成登录，后续再次运行通常会复用登录状态。

示例：

```powershell
python douyin_work_urls.py "主页地址" --headful --user-data-dir cache\.douyin-browser -o cache\urls.txt
```

或：

```powershell
python douyin_work_urls.py --download "作品地址" --headful --user-data-dir cache\.douyin-browser --download-dir cache\downloads
```

## 输出文件

抓列表输出示例：

```text
https://www.douyin.com/video/7677547779459179242
https://www.douyin.com/note/7657685355588900179
```

下载文件命名示例：

```text
cache\downloads\7577345577656035574_video_01.mp4
cache\downloads\7657685355588900179_image_01.webp
```

## 注意事项

- 抖音接口和网页结构可能变化，脚本依赖 Playwright 模拟真实浏览器访问。
- 部分作品或主页需要登录、验证码、风控校验，建议用 `--headful` 先登录。
- 大量作品主页分页可能较慢，可以提高 `--max-scrolls`、`--idle-rounds` 和 `--wait`。
- 主页弹窗链接不如标准 `/video/<id>` 或 `/note/<id>` 稳定；如果下载失败，优先改成标准作品地址。
