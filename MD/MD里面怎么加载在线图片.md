2025/12/17
---
在 Markdown（.md）文件中加载在线图片，语法非常简单，但能否正常显示，取决于你使用的渲染环境（如 VS Code、GitHub、Typora、Obsidian 等）。下面从语法规范和常见问题解决两方面说明：

✅ 一、标准语法（通用）

markdown
![图片描述（可选）](https://example.com/path/to/image.jpg)
![] 表示插入图片；
括号内是图片的完整 URL（必须以 http:// 或 https:// 开头）；
方括号内是替代文本（alt text），用于无障碍访问或图片加载失败时显示。
示例：
markdown
![NASA 宇宙照片](https://images-assets.nasa.gov/image/PIA24925/PIA24925~orig.jpg)
✅ 只要网络可访问该链接，且平台允许加载外部资源，就能显示。

⚠️ 二、为什么有些地方不显示？——常见原因与解决方案
1. VS Code 预览不显示在线图片
   原因：出于安全考虑，VS Code 默认禁用远程图片预览。
   解决方法：
   打开 VS Code 设置（Ctrl + ,）；
   搜索 markdown.preview.security；
   将 “Markdown: Preview Security” 设为 allow insecure content；
   或在预览窗口点击右上角盾牌图标 → 选择 “Allow insecure content”。
   🔒 注意：仅对可信来源开启，避免恶意图片。

2. GitHub / GitLab 不显示某些图片
   原因：
   图片链接是 http://（非加密），而 GitHub 强制 HTTPS；
   目标服务器设置了 防盗链（Referer 限制）；
   图片被墙（如部分境外图床在中国无法访问）。
   解决方法：
   使用 HTTPS 链接；
   优先使用 GitHub 仓库内图片（相对路径）或 支持 CORS 的图床（如 Imgur、SM.MS、阿里云 OSS）；
   自建图床并配置 Access-Control-Allow-Origin: *。

✅ 推荐图床（2025年可用）：
[SM.MS](https://sm.ms)（免费，支持 HTTPS）
[PicGo + 阿里云 OSS](https://picgo.github.io)（稳定，适合长期使用）
GitHub 仓库 raw 链接（如 https://raw.githubusercontent.com/user/repo/main/image.png）

3. Obsidian / Typora 显示正常，但导出 PDF 失败
   原因：导出时网络中断，或目标服务拒绝爬虫请求。
   解决方法：
   导出前先在编辑器中确保图片已缓存；
   或将图片下载到本地，用相对路径引用（更可靠）。

💡 三、最佳实践建议

场景 推荐做法
------ --------
写博客 / GitHub README 用 HTTPS 在线图床（如 SM.MS）或 仓库内图片
个人笔记（Obsidian/Typora） 用 PicGo + 阿里云 OSS 自动上传，生成永久链接
分享给他人 避免使用微信/QQ截图链接（会失效），改用专业图床
追求稳定性 优先本地存储 + 相对路径（如 ./images/photo.jpg）

🛠️ 四、附：自动上传图片到图床的工具（推荐）

1. PicGo（开源）
   支持阿里云 OSS、腾讯云、GitHub、SM.MS 等；
   安装后，截图自动上传并复制 Markdown 链接。

2. VS Code 插件：Paste Image
   在 .md 文件中按 Ctrl+Alt+V，自动保存截图到指定文件夹并插入相对路径。

✅ 总结
语法没问题：![alt](https://xxx.jpg) 是标准写法；
显示不出来？ 90% 是环境限制或链接不可靠；
终极方案：用 PicGo + 阿里云 OSS 实现“截图→自动上传→插入 Markdown”，一劳永逸。
如果你告诉我你用的是哪个平台（VS Code？GitHub？Obsidian？），我可以给你定制具体设置步骤。
