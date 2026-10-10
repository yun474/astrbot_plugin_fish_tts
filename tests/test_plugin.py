"""使用轻量 AstrBot 接口替身测试插件事件行为，不冒充完整框架联调。"""

import asyncio
import importlib
import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


class Plain:
    def __init__(self, text):
        self.text = text


class Record:
    @staticmethod
    def fromFileSystem(path):
        return Record()


class Result:
    def __init__(self, chain, llm=True):
        self.chain = chain
        self.llm = llm

    def is_llm_result(self):
        return self.llm


class Event:
    def __init__(self, awake=True):
        self.is_at_or_wake_command = awake
        self.extras = {}
        self.result = None
        self.send = AsyncMock()

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_result(self):
        return self.result

    def chain_result(self, chain):
        return Result(chain)


class ToolSet:
    def __init__(self, names):
        self.tools = [SimpleNamespace(name=name) for name in names]

    def get_tool(self, name):
        return next((tool for tool in self.tools if tool.name == name), None)

    def remove_tool(self, name):
        self.tools = [tool for tool in self.tools if tool.name != name]


def identity_decorator(*args, **kwargs):
    return lambda func: func


class Star:
    def __init__(self, context):
        self.context = context


def load_plugin():
    fake_filter = SimpleNamespace(
        CustomFilter=object,
        custom_filter=identity_decorator,
        on_llm_request=identity_decorator,
        on_llm_response=identity_decorator,
        on_decorating_result=identity_decorator,
        llm_tool=identity_decorator,
    )
    modules = {}
    for name, attributes in {
        "astrbot": {},
        "astrbot.api": {
            "AstrBotConfig": dict,
            "logger": logging.getLogger("fish_test"),
        },
        "astrbot.api.event": {"AstrMessageEvent": Event, "filter": fake_filter},
        "astrbot.api.message_components": {"Plain": Plain, "Record": Record},
        "astrbot.api.provider": {
            "LLMResponse": SimpleNamespace,
            "ProviderRequest": SimpleNamespace,
        },
        "astrbot.api.star": {
            "Context": object,
            "Star": Star,
            "StarTools": SimpleNamespace(
                get_data_dir=lambda name: Path(tempfile.gettempdir()) / name
            ),
            "register": identity_decorator,
        },
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        modules[name] = module
    with patch.dict(sys.modules, modules):
        return importlib.import_module(f"{ROOT.name}.main")


plugin_module = load_plugin()
FishError = plugin_module.FishError


class PluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            "api_key": "local-test",
            "reference_id": "voice-test",
            "probability": 1.0,
        }
        self.plugin = plugin_module.FishTTSPlugin(None, self.config)
        self.plugin.client.synthesize = AsyncMock(return_value=Path("test.mp3"))

    async def asyncTearDown(self):
        await self.plugin.terminate()

    def request(self, names=("fish_tts_speak",)):
        return SimpleNamespace(system_prompt="原始人设", func_tool=ToolSet(names))

    def response(self, text, **kwargs):
        return SimpleNamespace(
            completion_text=text,
            result_chain=None,
            role="assistant",
            tools_call_name=[],
            **kwargs,
        )

    async def prepare(self, event=None, text="[angry] 别打断云云！"):
        event = event or Event()
        await self.plugin.on_wake(event)
        response = self.response(text)
        await self.plugin.remember_speech(event, response)
        event.result = Result([Plain(response.completion_text)])
        return event

    async def test_wake_filter_does_not_wake_ordinary_group_messages(self):
        self.assertFalse(plugin_module.Awakened().filter(Event(False), {}))
        self.assertTrue(plugin_module.Awakened().filter(Event(True), {}))

    async def test_probability_draw_once_before_request(self):
        event = Event()
        with patch.object(plugin_module.random, "random", return_value=0.5) as draw:
            await self.plugin.on_wake(event)
            await self.plugin.on_wake(event)
            request = self.request()
            await self.plugin.prepare_request(event, request)
            await self.plugin.prepare_request(event, request)
        draw.assert_called_once()
        self.assertFalse(event.get_extra("enable_streaming"))
        self.assertEqual(request.system_prompt.count("<fish_tts_turn>"), 1)
        self.assertIn("原始人设", request.system_prompt)
        self.assertIn("本轮已决定", request.system_prompt)

    async def test_zero_probability_even_at_zero_random(self):
        self.config.update(probability=0, enable_tool=False)
        event = Event()
        with patch.object(plugin_module.random, "random", return_value=0):
            await self.plugin.on_wake(event)
        request = self.request()
        await self.plugin.prepare_request(event, request)
        self.assertFalse(event.get_extra(plugin_module.STATE_KEY).selected)
        self.assertIsNone(event.get_extra("enable_streaming"))
        self.assertEqual(request.system_prompt, "原始人设")
        self.assertIsNone(request.func_tool.get_tool("fish_tts_speak"))

    async def test_probability_is_per_event_not_session(self):
        self.config["probability"] = 0.5
        a, b = Event(), Event()
        with patch.object(plugin_module.random, "random", side_effect=[0.1, 0.9]):
            await asyncio.gather(self.plugin.on_wake(a), self.plugin.on_wake(b))
        self.assertTrue(a.get_extra(plugin_module.STATE_KEY).selected)
        self.assertFalse(b.get_extra(plugin_module.STATE_KEY).selected)

    async def test_custom_prompt_and_tags_not_replaced(self):
        self.config["voice_prompt"] = "自定义 [very excited]，不要喵喵叫。"
        event = Event()
        await self.plugin.on_wake(event)
        request = self.request()
        await self.plugin.prepare_request(event, request)
        self.assertIn(self.config["voice_prompt"], request.system_prompt)
        self.assertNotIn("常用情绪", request.system_prompt)

    async def test_tool_only_prompt_does_not_force_spoken_final_reply(self):
        self.config["probability"] = 0
        event = Event()
        await self.plugin.on_wake(event)
        request = self.request()
        await self.plugin.prepare_request(event, request)
        self.assertIn("本轮未命中", request.system_prompt)
        self.assertFalse(event.get_extra("enable_streaming"))
        self.assertIsNotNone(request.func_tool.get_tool("fish_tts_speak"))

    async def test_missing_tool_not_advertised(self):
        self.config["probability"] = 0
        event = Event()
        await self.plugin.on_wake(event)
        request = SimpleNamespace(system_prompt="人设", func_tool=None)
        await self.plugin.prepare_request(event, request)
        self.assertEqual(request.system_prompt, "人设")

    async def test_disable_tool_does_not_mutate_shared_toolset(self):
        self.config["enable_tool"] = False
        event = Event()
        await self.plugin.on_wake(event)
        request = self.request(("fish_tts_speak", "search"))
        shared = request.func_tool
        await self.plugin.prepare_request(event, request)
        self.assertIsNotNone(shared.get_tool("fish_tts_speak"))
        self.assertIsNone(request.func_tool.get_tool("fish_tts_speak"))
        self.assertIsNotNone(request.func_tool.get_tool("search"))

    async def test_unprepared_requests_do_not_draw_late(self):
        request = self.request()
        with patch.object(plugin_module.random, "random") as draw:
            await self.plugin.prepare_request(Event(), request)
        draw.assert_not_called()
        self.assertEqual(request.system_prompt, "原始人设")
        self.assertIsNone(request.func_tool.get_tool("fish_tts_speak"))

    async def test_missing_credentials_and_disabled_are_inert(self):
        for change in ({"api_key": ""}, {"enabled": False}):
            with self.subTest(change=change):
                self.config.update(api_key="test", enabled=True)
                self.config.update(change)
                event = Event()
                await self.plugin.on_wake(event)
                request = self.request()
                await self.plugin.prepare_request(event, request)
                self.assertEqual(request.system_prompt, "原始人设")
                self.assertIsNone(event.get_extra("enable_streaming"))
                self.assertIsNone(request.func_tool.get_tool("fish_tts_speak"))

    async def test_tags_reach_fish_but_not_visible_text(self):
        event = await self.prepare()
        self.assertEqual(event.result.chain[0].text, "别打断云云！")
        image = object()
        event.result.chain.extend([image, Plain("补充")])
        await self.plugin.render_voice(event)
        self.plugin.client.synthesize.assert_awaited_once_with("[angry] 别打断云云！")
        self.assertEqual(len(event.result.chain), 2)
        self.assertIsInstance(event.result.chain[0], Record)
        self.assertIs(event.result.chain[1], image)

    async def test_intermediate_tool_response_does_not_synthesize(self):
        event = Event()
        await self.plugin.on_wake(event)
        response = self.response("我先查一下")
        response.tools_call_name = ["search"]
        await self.plugin.remember_speech(event, response)
        event.result = Result([Plain("我先查一下")])
        await self.plugin.render_voice(event)
        self.plugin.client.synthesize.assert_not_called()

    async def test_failure_retains_clean_text_and_no_retry(self):
        event = await self.prepare()
        self.plugin.client.synthesize.side_effect = FishError("HTTP 503")
        with self.assertLogs("fish_test", "WARNING"):
            await self.plugin.render_voice(event)
        await self.plugin.render_voice(event)
        self.assertEqual(event.result.chain[0].text, "别打断云云！")
        self.plugin.client.synthesize.assert_awaited_once()

    async def test_response_cleanup_preserves_attachment_order(self):
        event = Event()
        await self.plugin.on_wake(event)
        image = object()
        response = self.response("[happy] 主人好！")
        response.result_chain = Result([image, Plain(response.completion_text)])
        await self.plugin.remember_speech(event, response)
        self.assertIs(response.result_chain.chain[0], image)
        self.assertEqual(response.result_chain.chain[1].text, "主人好！")
        self.assertEqual(
            event.get_extra(plugin_module.STATE_KEY).speech, "[happy] 主人好！"
        )

    async def test_command_reply_not_converted(self):
        event = await self.prepare()
        event.result.llm = False
        await self.plugin.render_voice(event)
        self.plugin.client.synthesize.assert_not_called()

    async def test_existing_audio_not_replaced(self):
        event = await self.prepare()
        event.result.chain.append(Record())
        await self.plugin.render_voice(event)
        self.plugin.client.synthesize.assert_not_called()

    async def test_tool_concurrent_calls_send_one_audio(self):
        event = Event()
        await self.plugin.on_wake(event)
        await asyncio.gather(
            self.plugin.fish_tts_speak(event, "[happy] 主人好！"),
            self.plugin.fish_tts_speak(event, "重复调用"),
        )
        event.send.assert_awaited_once()
        self.plugin.client.synthesize.assert_awaited_once()
        event.result = Result([Plain("语音已经发了"), object()])
        await self.plugin.render_voice(event)
        self.assertEqual(len(event.result.chain), 1)
        self.assertNotIsInstance(event.result.chain[0], Plain)

    async def test_tool_failure_allows_text_and_skips_auto_retry(self):
        event = Event()
        await self.plugin.on_wake(event)
        self.plugin.client.synthesize.side_effect = FishError("请求超时")
        result = await self.plugin.fish_tts_speak(event, "[happy] 台词")
        self.assertIn("文字回复", result)
        self.assertFalse(event.get_extra(plugin_module.STATE_KEY).tool_sent)
        await self.prepare(event, "[sad] 改用文字")
        await self.plugin.render_voice(event)
        self.assertEqual(event.result.chain[0].text, "改用文字")
        event.send.assert_not_called()
        self.plugin.client.synthesize.assert_awaited_once()

    async def test_platform_send_failure_does_not_claim_success(self):
        event = Event()
        await self.plugin.on_wake(event)
        event.send.side_effect = RuntimeError("platform error")
        with self.assertLogs("fish_test", "WARNING"):
            result = await self.plugin.fish_tts_speak(event, "台词")
        self.assertIn("发送失败", result)
        self.assertFalse(event.get_extra(plugin_module.STATE_KEY).tool_sent)

    async def test_plain_text_cleanup_preserves_links_and_non_cues(self):
        text = (
            "[very excited]好耶！[chuckling] [链接] [1, 2] [guide](https://example.com)"
        )
        self.assertEqual(
            plugin_module.plain_text(text),
            "好耶！ [链接] [1, 2] [guide](https://example.com)",
        )

    async def test_schema_and_runtime_prompt_agree(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            schema["voice_prompt"]["default"], plugin_module.DEFAULT_PROMPT
        )
        self.assertEqual(schema["voice_prompt"]["type"], "text")
        self.assertEqual(schema["api_key"]["default"], "")


if __name__ == "__main__":
    unittest.main()
