import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

# 确保可以导入 AstrBot 本体以及同目录下的 main.py 作为模块
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# 显式指定 AstrBot 根目录，避免相对路径推断错误
ASTRBOT_ROOT = os.path.abspath(r"C:\Software\Astrbot_latest\AstrBot")
for p in (ASTRBOT_ROOT, PLUGIN_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import main as plugin  # type: ignore[import]


class FakeLarkClient:
    """用来挂在 event_self.bot 上的假 client。"""

    pass


class DummyLarkEventAPI:
    """模拟 LarkMessageEvent 的静态方法，避免依赖真实 SDK。"""

    post_called = False
    file_called = False

    @staticmethod
    async def _send_im_message(*args, **kwargs):
        DummyLarkEventAPI.post_called = True

    @staticmethod
    async def _send_file_message(*args, **kwargs):
        DummyLarkEventAPI.file_called = True

    @staticmethod
    async def _send_audio_message(*args, **kwargs):
        return

    @staticmethod
    async def _send_media_message(*args, **kwargs):
        return

    @staticmethod
    async def _convert_to_lark(message, client):
        # 直接返回一行包含图片的行，验证图片路径不会报错即可
        return [[{"tag": "img", "image_key": "fake"}]]


@pytest.mark.asyncio
async def test_markdown_to_post_rows_basic_inline():
    """验证 Markdown 行内样式解析为预期的 Feishu 元素结构。"""
    text = "Hello **bold** *italic* ~~gone~~ [link](https://example.com)"
    rows = plugin._markdown_to_post_rows(text)
    assert len(rows) == 1
    elements = rows[0]
    # 至少包含粗体、斜体和链接三种元素
    assert any(e.get("style") == ["bold"] for e in elements)
    assert any(e.get("style") == ["italic"] for e in elements)
    assert any(e.get("tag") == "a" and e.get("href") == "https://example.com" for e in elements)


@pytest.mark.asyncio
async def test_markdown_to_post_rows_heading_and_blank_lines():
    text = "# Title\n\nParagraph"
    rows = plugin._markdown_to_post_rows(text)
    assert len(rows) == 3
    assert rows[0][0]["text"] == "Title"
    assert rows[0][0]["style"] == ["bold"]
    assert rows[1][0]["text"] == ""


@pytest.mark.asyncio
async def test_send_rich_post_success_and_attachments():
    """正常情况下，应发送 post 且尝试发送附件。"""
    # 准备 fake LarkMessageEvent 静态方法
    from astrbot.core.platform.sources.lark import lark_event as lark_event_mod  # type: ignore[import]
    from astrbot.api.message_components import Plain, At, File  # type: ignore[import]
    backup_send_im = lark_event_mod.LarkMessageEvent._send_im_message
    backup_send_file = lark_event_mod.LarkMessageEvent._send_file_message
    backup_send_audio = lark_event_mod.LarkMessageEvent._send_audio_message
    backup_send_media = lark_event_mod.LarkMessageEvent._send_media_message
    backup_convert = lark_event_mod.LarkMessageEvent._convert_to_lark

    lark_event_mod.LarkMessageEvent._send_im_message = DummyLarkEventAPI._send_im_message
    lark_event_mod.LarkMessageEvent._send_file_message = DummyLarkEventAPI._send_file_message
    lark_event_mod.LarkMessageEvent._send_audio_message = DummyLarkEventAPI._send_audio_message
    lark_event_mod.LarkMessageEvent._send_media_message = DummyLarkEventAPI._send_media_message
    lark_event_mod.LarkMessageEvent._convert_to_lark = DummyLarkEventAPI._convert_to_lark

    try:
        DummyLarkEventAPI.post_called = False
        DummyLarkEventAPI.file_called = False

        event_self = SimpleNamespace()
        event_self.bot = FakeLarkClient()
        event_self.message_obj = SimpleNamespace(message_id="mid")

        # 使用 AstrBot 自带的组件类型，便于命中 isinstance 分支
        message = SimpleNamespace(
            chain=[
                Plain("hello **world**"),
                At(qq="user_open_id"),
                File(name="dummy", file="dummy"),
            ]
        )

        await plugin._send_rich_post(event_self, message)

        assert DummyLarkEventAPI.post_called is True
        assert DummyLarkEventAPI.file_called is True
    finally:
        # 还原静态方法，避免污染其他测试 / 运行环境
        lark_event_mod.LarkMessageEvent._send_im_message = backup_send_im
        lark_event_mod.LarkMessageEvent._send_file_message = backup_send_file
        lark_event_mod.LarkMessageEvent._send_audio_message = backup_send_audio
        lark_event_mod.LarkMessageEvent._send_media_message = backup_send_media
        lark_event_mod.LarkMessageEvent._convert_to_lark = backup_convert


@pytest.mark.asyncio
async def test_patched_send_fallback_on_richpost_error(monkeypatch):
    """当富文本发送失败时，应自动回退到原始 send。"""

    from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
    from astrbot.core.platform import MessageType  # type: ignore[import]

    # 安装最小测试环境：原始 send 只记录一次调用
    called = {"count": 0}

    async def original_send(self, *args, **kwargs):
        called["count"] += 1

    monkeypatch.setattr(plugin, "_original_lark_send", original_send, raising=False)
    monkeypatch.setattr(
        plugin,
        "_plugin_config_getter",
        lambda: {"enable_rich_post": True},
        raising=False,
    )

    async def broken_send_rich(*a, **k):
        raise plugin.RichPostSendError("boom")

    monkeypatch.setattr(plugin, "_send_rich_post", broken_send_rich, raising=False)

    # 安装补丁
    plugin._install_patch()

    # 构造一个假的 event_self，message_obj 需要有合法的 type 字段
    message_obj = SimpleNamespace(
        message_id="mid",
        type=MessageType.FRIEND_MESSAGE,
    )
    event_self = LarkMessageEvent(
        message_str="",
        message_obj=message_obj,
        platform_meta=SimpleNamespace(name="lark", id="lark"),
        session_id="sid",
        bot=FakeLarkClient(),
    )

    # 调用 patched_send，应在富文本失败后回退到 original_send
    await event_self.send(SimpleNamespace(chain=[]))  # type: ignore[arg-type]

    assert called["count"] == 1


@pytest.mark.asyncio
async def test_patched_send_fallback_on_richpost_error(monkeypatch):
    """当富文本发送失败时，应自动回退到原始 send。"""

    from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
    from astrbot.core.platform import MessageType  # type: ignore[import]

    # 安装最小测试环境：原始 send 只记录一次调用
    called = {"count": 0}

    async def original_send(self, *args, **kwargs):
        called["count"] += 1

    monkeypatch.setattr(plugin, "_original_lark_send", original_send, raising=False)
    monkeypatch.setattr(
        plugin,
        "_plugin_config_getter",
        lambda: {"enable_rich_post": True},
        raising=False,
    )

    async def broken_send_rich(*a, **k):
        raise plugin.RichPostSendError("boom")

    monkeypatch.setattr(plugin, "_send_rich_post", broken_send_rich, raising=False)

    # 安装补丁
    plugin._install_patch()

    # 构造一个假的 event_self，message_obj 需要有合法的 type 字段
    message_obj = SimpleNamespace(
        message_id="mid",
        type=MessageType.FRIEND_MESSAGE,
    )
    event_self = LarkMessageEvent(
        message_str="",
        message_obj=message_obj,
        platform_meta=SimpleNamespace(name="lark", id="lark"),
        session_id="sid",
        bot=FakeLarkClient(),
    )

    # 调用 patched_send，应在富文本失败后回退到 original_send
    await event_self.send(SimpleNamespace(chain=[]))  # type: ignore[arg-type]

    assert called["count"] == 1

