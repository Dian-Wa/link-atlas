# 拾链 · Link Atlas

[打开浏览器版](https://dian-wa.github.io/link-atlas/) · [部署无数据库抓取服务](https://render.com/deploy?repo=https://github.com/Dian-Wa/link-atlas)

独立于 Windows 本机版的公网版本。React / TypeScript / Vite + IndexedDB；Python FastAPI 只提供无状态元信息抓取，**不连接数据库、不保存收藏、不下载源码或附件**。

## 使用

1. 打开 GitHub Pages 页面，创建当前浏览器的本地账号。
2. 在“抓取设置”填写 HTTPS 抓取服务根地址，例如 `https://你的服务.onrender.com`。没有配置时资料先入库，任务保留排队。
3. 添加网址或 GitHub 公共仓库，页面打开时最多同时抓取 3 条。关闭页面后不保证持续抓取；重新打开并登录后继续。多标签页通过 Web Locks 保证同一空间只有一个抓取执行器。
4. 定期导出 JSON，下载后确认备份文件确实存在。备份含链接、分类、规则、标签、备注、抓取任务和回收区；不含本地账号密码和头像。支持导入本机版 JSON。重复地址跳过，保留已有人工内容；导入失败整体回滚。

浏览器账号仅用于本地解锁和区分空间，不是云端账号，IndexedDB 中的资料未加密。关闭整个页面后需要重新登录；刷新不丢失登录。换浏览器、设备或网站域名请使用 JSON 备份迁移。清理站点数据会丢失资料，浏览器持久存储申请也不代替备份。当前 JSON 单文件上限 32 MiB / 100000 条；超限时保留资料并提示，不生成无法原样恢复的备份。

保留资源库/文件夹增改、层级折叠、同级排序、快捷入口、图标、收藏、归档、搜索和每页 50 条。删除链接或任务先确认，再移入浏览器回收区；可恢复且随 JSON 备份导出。不销毁实际文件。

## 抓取边界

仅发送待抓取的 URL 和网页读取上限，不发送笔记、密码、标签或整个资料库。URL 会被抓取服务器和目标网站接收。读取静态元信息，不运行网页脚本。公网 URL 及每次重定向重新校验，阻止本机/内网/保留地址并固定已验证 IP。网页解压后上限默认 2 MiB，可配置 1–10 MiB；README 最多 256 KiB、保存 2000 字。超大仓库只收录项目索引。

15 秒单次远端请求超时、最多 3 次重定向，网络失败最多重试两次，429 按 Retry-After 保存下次时间。GitHub 无密钥公共额度可能耗尽，许可证缺失显示“许可证待核实”。不克隆仓库，不获取 ZIP、Release、LFS 或依赖。

## 发布

前端：GitHub Actions 构建并发布 GitHub Pages。仓库变量 `VITE_FETCH_SERVICE_URL` 可设置默认抓取服务根地址；不设置时用户在界面填写。域名属于浏览器存储边界，同一 GitHub Pages 主域下的页面属于同源，不应把本地账号当作强隔离安全边界。

后端：仓库包含 Render Blueprint `render.yaml`，仅创建一个 Free Docker Web Service，无数据库、无磁盘。点击仓库 README 的 Deploy to Render 后登录自己的 Render 账号，确认 Free 方案再部署。`ATLAS_ALLOWED_ORIGINS` 填前端来源，示例 `https://dian-wa.github.io`，多个用逗号分隔，不含路径。首次部署后把生成的 HTTPS 根地址填写到前端抓取设置。来源限制不等于身份认证，公开服务另有每客户端每分钟 30 次和总并发 3 的限额，勿公开配置宽泛来源。

Render 免费实例空闲后会休眠，唤醒可能较慢；达到平台配额时可能暂停。浏览器资料不受后端休眠或重启影响。自动抓取依赖服务可达及目标网站允许访问，不能保证所有网页都能提取。

## 本地开发

前端：`npm ci` 后执行 `npm run dev`（127.0.0.1:5180）。后端：安装 requirements.txt 后执行 `python -m uvicorn server.service:app --host 127.0.0.1 --port 8787 --no-access-log`。抓取设置填写 http://127.0.0.1:8787。

构建：`npm run build`。后端测试：`python -m pytest tests/test_service.py -q`（需先安装 pytest）。浏览器验收：`node tests/browser.cjs`，先设置 `PLAYWRIGHT_MODULE` 为已有 Playwright 安装路径，仅使用 cache 内全新隔离档案；不读取本机正式资料。

源代码中的 backend 模块仅复用元信息抓取与校验逻辑；服务入口 server/service.py 不创建 Store 或任何 SQLite 数据库。没有上传开发电脑的账号、收藏、日志或缓存。
