# astrbot_plugin_lark_richpost（飞书富文本气泡插件）

让 AstrBot 的飞书（Feishu/Lark）回复以更“原生”的富文本气泡呈现：将常见 Markdown（粗体/斜体/删除线/链接/标题、@、图片等）转换为飞书 `post` 消息的**原生富文本元素**（`text` / `a` / `at` / `img`），并可通过配置一键开关。

- **不修改 AstrBot 原有代码**：通过插件在运行时对 `LarkMessageEvent.send` 进行 monkey‑patch
- **可配置切换**：`enable_rich_post=false` 时完全走原始发送逻辑
- **支持标题**：可为每条 `post` 设置 `title`

相关文档：
- AstrBot 插件开发指南：[https://docs.astrbot.app/dev/star/plugin-new.html](https://docs.astrbot.app/dev/star/plugin-new.html)
- 飞书 `post` / 富文本消息 JSON 结构：[https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json)

---

## 适用范围

- **平台**：仅飞书（`support_platforms: [lark]`）
- **AstrBot 行为**：仅影响飞书适配器的发送路径（`LarkMessageEvent.send`）

---

## 安装

将本插件目录放到：

`AstrBot/data/plugins/astrbot_plugin_lark_richpost/`

目录至少应包含：

- `main.py`
- `metadata.yaml`
- `_conf_schema.json`

然后在 AstrBot WebUI 的 **插件管理** 中启用插件并配置。

---

## 配置

配置 Schema 在 `_conf_schema.json`，目前提供两个开关：

- **enable_rich_post**（默认 `false`）：是否启用富文本气泡转换
- **rich_post_title**（默认空字符串）：每条富文本消息的标题（留空则不显示标题）

---

## 使用效果（能力说明）

### 支持的 Markdown（当前实现）

本插件会解析 `Plain` 文本组件中的**行内** Markdown，并生成飞书原生富文本元素：

- **粗体**：`**bold**` 或 `__bold__`
- **斜体**：`*italic*` 或 `_italic_`
- **粗斜体**：`***bold italic***`
- **删除线**：`~~strike~~`
- **链接**：`[text](https://example.com)` → `{"tag":"a","text":"text","href":"..." }`
- **标题行**：`# Heading`（当前以 `bold text` 形式输出）

### 支持的消息组件（MessageChain）

- **Plain**：按行转换为 `post.content` 的行元素
- **At**：转换为 `{"tag":"at","user_id": ...}`
- **Image**：复用 AstrBot 原有上传逻辑（`LarkMessageEvent._convert_to_lark`），生成 `img` 行
- **File/Record/Video**：复用 AstrBot 原有发送逻辑（分别调用 `_send_file_message/_send_audio_message/_send_media_message`），作为附件单独发送

---

## 已知限制（很重要）

飞书 `post` 的“原生富文本元素”并不等价于 Markdown 渲染器，本插件也刻意保持**轻量、零依赖**，因此有如下限制：

- **Markdown 表格**：当前不会渲染为表格，会按纯文本显示（例如 `| a | b |` 会原样出现）。  
  说明：表格通常依赖飞书的 `{"tag":"md"}` 渲染能力，而原生元素没有 table 标签。
- **代码块 / 语法高亮**：不支持（飞书原生元素中无 code block 标签；当前实现会把 `` `inline` `` 当普通文本输出）。
- **列表/引用/复杂嵌套**：不做结构化解析（目前按“逐行 + 行内样式”处理）。

如果你希望“表格/代码块也能渲染”，通常需要在检测到这些块时 **回退到 `md` 标签**（混合渲染策略），或改用交互卡片（Card）能力。

---

## 工作原理（面试可讲的点）

### 发送链路

1. 插件 `initialize()` 时安装补丁：将 `astrbot.core.platform.sources.lark.lark_event.LarkMessageEvent.send` 替换为 `patched_send`
2. 当飞书要发送消息时：
   - 若 `enable_rich_post=false`：直接调用原始 `send`（零影响）
   - 若 `enable_rich_post=true`：构造飞书 `post` JSON（`zh_cn.title/content`），并调用 AstrBot 已有的 `_send_im_message(...)` 发送
3. 发送结束后，仍调用 `AstrMessageEvent.send(...)` 保留框架级副作用（如指标上报、发送标记等）
4. 插件卸载 `terminate()` 时还原补丁，保证不会“污染”后续运行

### 为什么选择 monkey‑patch

- **约束条件**：不改动 AstrBot 本体任何代码，只能“新增”
- **最小侵入**：补丁点只在 `LarkMessageEvent.send`，且可配置开关、可卸载还原
- **复用框架能力**：图片上传、文件/音频/视频发送、指标上报完全复用 AstrBot 已实现逻辑

---

## 本地开发与调试建议

- 修改 `main.py` 后，在 WebUI 插件管理中使用 **重载插件** 以快速验证
- 建议用以下内容快速回归：
  - 粗体/斜体/删除线/链接混排
  - 含 `@` 的消息
  - 发送图片与文件附件
  - `enable_rich_post` 开关切换是否影响输出

---

## 卸载 / 关闭

1. 最安全的方式：在插件配置中将 `enable_rich_post=false`
2. 或在 WebUI 停用插件：插件 `terminate()` 会自动还原补丁

---

## License

请根据你在 GitHub 仓库设置的 License 为准。

# astrbot-plugin-helloworld

AstrBot 插件模板 / A template plugin for AstrBot plugin feature

> [!NOTE]
> This repo is just a template of [AstrBot](https://github.com/AstrBotDevs/AstrBot) Plugin.
> 
> [AstrBot](https://github.com/AstrBotDevs/AstrBot) is an agentic assistant for both personal and group conversations. It can be deployed across dozens of mainstream instant messaging platforms, including QQ, Telegram, Feishu, DingTalk, Slack, LINE, Discord, Matrix, etc. In addition, it provides a reliable and extensible conversational AI infrastructure for individuals, developers, and teams. Whether you need a personal AI companion, an intelligent customer support agent, an automation assistant, or an enterprise knowledge base, AstrBot enables you to quickly build AI applications directly within your existing messaging workflows.

# Supports

- [AstrBot Repo](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot Plugin Development Docs (Chinese)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot Plugin Development Docs (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)
