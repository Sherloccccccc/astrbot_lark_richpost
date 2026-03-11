"""飞书富文本气泡插件 (astrbot_lark_richpost)

将 LLM 回复中的 Markdown 格式转换为飞书 post 消息的原生富文本元素
（text/bold/italic/link/at/img 等标签），替代默认的 md 标签渲染方式，
并支持通过 rich_post_title 配置项为每条消息设置标题。

通过插件配置中的 enable_rich_post 开关控制是否启用（默认关闭），
不启用时对原有行为零影响。
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.star import Context, Star

if TYPE_CHECKING:
    from astrbot.api.event import MessageChain

# --------------------------------------------------------------------------- #
#  模块级状态（保证跨热重载只 patch 一次，terminate 时能还原）                #
# --------------------------------------------------------------------------- #
_original_lark_send = None
_plugin_config: dict = {}


# --------------------------------------------------------------------------- #
#  Markdown → 飞书原生富文本元素的转换工具                                     #
# --------------------------------------------------------------------------- #

_INLINE_PATTERN = re.compile(
    r"\*\*\*(.*?)\*\*\*"             # group 1: bold + italic  ***text***
    r"|\*\*(.*?)\*\*"                # group 2: bold           **text**
    r"|\*(.*?)\*"                    # group 3: italic         *text*
    r"|__(.*?)__"                    # group 4: bold (alt)     __text__
    r"|_(.*?)_"                      # group 5: italic (alt)   _text_
    r"|~~(.*?)~~"                    # group 6: strikethrough  ~~text~~
    r"|\[([^\]]+)\]\(([^)]+)\)"      # group 7,8: link         [text](url)
    r"|(`[^`\n]+`)"                  # group 9: inline code    `code`
    r"|([^*_~\[`]+|[*_~\[`])",       # group 10: plain text
    re.DOTALL,
)

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


def _parse_inline(text: str) -> list[dict]:
    """将单行文本中的行内 Markdown 解析为飞书富文本元素列表。"""
    elements: list[dict] = []
    for m in _INLINE_PATTERN.finditer(text):
        g1, g2, g3, g4, g5, g6, g7, g8, g9, g10 = m.groups()
        if g1 is not None:
            elements.append({"tag": "text", "text": g1, "style": ["bold", "italic"]})
        elif g2 is not None:
            elements.append({"tag": "text", "text": g2, "style": ["bold"]})
        elif g3 is not None:
            elements.append({"tag": "text", "text": g3, "style": ["italic"]})
        elif g4 is not None:
            elements.append({"tag": "text", "text": g4, "style": ["bold"]})
        elif g5 is not None:
            elements.append({"tag": "text", "text": g5, "style": ["italic"]})
        elif g6 is not None:
            elements.append({"tag": "text", "text": g6, "style": ["lineThrough"]})
        elif g7 is not None:
            elements.append({"tag": "a", "text": g7, "href": g8 or ""})
        elif g9:
            # 行内代码：飞书 post 无 code 标签，保留原始格式作为普通文本
            elements.append({"tag": "text", "text": g9})
        elif g10:
            elements.append({"tag": "text", "text": g10})
    return elements or [{"tag": "text", "text": text}]


def _markdown_to_post_rows(text: str) -> list[list[dict]]:
    """将多行 Markdown 文本转换为飞书 post content 数组（行列表）。

    每个换行符产生一行（row），每行内的行内 Markdown 解析为元素列表。
    """
    rows: list[list[dict]] = []
    for line in text.split("\n"):
        heading = _HEADING_PATTERN.match(line)
        if heading:
            rows.append([{"tag": "text", "text": heading.group(2), "style": ["bold"]}])
        elif line.strip():
            rows.append(_parse_inline(line))
        else:
            rows.append([{"tag": "text", "text": ""}])
    return rows or [[{"tag": "text", "text": text}]]


# --------------------------------------------------------------------------- #
#  核心发送逻辑                                                                #
# --------------------------------------------------------------------------- #

async def _send_rich_post(event_self, message: "MessageChain") -> None:
    """构造并发送飞书原生富文本 post 消息，替代默认的 md 标签方式。

    文本/At 组件直接转换为 post 行；图片委托原有静态方法上传；
    文件/音频/视频通过原有静态方法单独发送。
    """
    from astrbot.api.message_components import At, File, Plain, Record, Video
    from astrbot.api.message_components import Image as AstrBotImage
    from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent

    file_components: list[File] = []
    audio_components: list[Record] = []
    media_components: list[Video] = []
    post_rows: list[list[dict]] = []

    for comp in message.chain:
        if isinstance(comp, File):
            file_components.append(comp)
        elif isinstance(comp, Record):
            audio_components.append(comp)
        elif isinstance(comp, Video):
            media_components.append(comp)
        elif isinstance(comp, Plain):
            post_rows.extend(_markdown_to_post_rows(comp.text))
        elif isinstance(comp, At):
            mention = {"tag": "at", "user_id": comp.qq, "style": []}
            if post_rows:
                post_rows[-1].append(mention)
            else:
                post_rows.append([mention])
        elif isinstance(comp, AstrBotImage):
            # 图片上传委托给原有静态方法，避免重复实现
            from astrbot.api.event import MessageChain as MC
            img_chain = MC()
            img_chain.chain = [comp]
            img_rows = await LarkMessageEvent._convert_to_lark(img_chain, event_self.bot)
            post_rows.extend(img_rows)

    title = _plugin_config.get("rich_post_title", "")

    if post_rows:
        wrapped = {
            "zh_cn": {
                "title": title,
                "content": post_rows,
            }
        }
        await LarkMessageEvent._send_im_message(
            event_self.bot,
            content=json.dumps(wrapped, ensure_ascii=False),
            msg_type="post",
            reply_message_id=event_self.message_obj.message_id,
        )

    for fc in file_components:
        await LarkMessageEvent._send_file_message(
            fc, event_self.bot,
            reply_message_id=event_self.message_obj.message_id,
        )
    for ac in audio_components:
        await LarkMessageEvent._send_audio_message(
            ac, event_self.bot,
            reply_message_id=event_self.message_obj.message_id,
        )
    for vc in media_components:
        await LarkMessageEvent._send_media_message(
            vc, event_self.bot,
            reply_message_id=event_self.message_obj.message_id,
        )


# --------------------------------------------------------------------------- #
#  Monkey-patch 安装                                                           #
# --------------------------------------------------------------------------- #

def _install_patch() -> None:
    """给 LarkMessageEvent.send 打上富文本补丁（幂等）。"""
    global _original_lark_send

    try:
        from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
    except ImportError as e:
        logger.warning(f"[lark_richpost] 无法导入 LarkMessageEvent，跳过补丁: {e}")
        return

    if _original_lark_send is not None:
        logger.debug("[lark_richpost] 补丁已安装，跳过重复安装")
        return

    _original_lark_send = LarkMessageEvent.send

    async def patched_send(event_self, message: "MessageChain") -> None:
        from astrbot.core.platform.astr_message_event import AstrMessageEvent

        if not _plugin_config.get("enable_rich_post", False):
            return await _original_lark_send(event_self, message)

        await _send_rich_post(event_self, message)
        # 触发框架级副作用（Metric 上报、_has_send_oper 标记等）
        await AstrMessageEvent.send(event_self, message)

    LarkMessageEvent.send = patched_send
    logger.info("[lark_richpost] 富文本补丁已安装")


def _remove_patch() -> None:
    """还原 LarkMessageEvent.send 至原始实现。"""
    global _original_lark_send

    if _original_lark_send is None:
        return

    try:
        from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
        LarkMessageEvent.send = _original_lark_send
        _original_lark_send = None
        logger.info("[lark_richpost] 富文本补丁已还原")
    except ImportError:
        pass


# --------------------------------------------------------------------------- #
#  插件入口                                                                    #
# --------------------------------------------------------------------------- #

class Main(Star):
    """飞书富文本气泡插件。

    启用后将 LLM 回复的 Markdown 转换为飞书 post 原生富文本元素；
    通过插件配置 enable_rich_post 开关控制，默认关闭，不影响原有行为。
    """

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        # 立即同步到模块级配置引用，使 initialize() 中可见
        _plugin_config.clear()
        _plugin_config.update(self.config)

    async def initialize(self) -> None:
        """插件初始化：安装 monkey-patch。"""
        _install_patch()
        status = "已启用" if _plugin_config.get("enable_rich_post", False) else "未启用（enable_rich_post=false）"
        logger.info(f"[lark_richpost] 插件初始化完成，富文本转换：{status}")

    async def terminate(self) -> None:
        """插件卸载：还原 monkey-patch。"""
        _remove_patch()
