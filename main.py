"""唤醒时决定语音，LLM 写台词与标签，Fish 负责合成。"""

import asyncio
import copy
import random
from dataclasses import dataclass, field

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

from .fish_client import FishClient, FishError
from .prompts import DEFAULT_PROMPT, plain_text

STATE_KEY = "fish_tts.turn"
PROMPT_MARK = "<fish_tts_turn>"
TOOL_NAME = "fish_tts_speak"


@dataclass
class VoiceTurn:
    selected: bool = False
    speech: str | None = None
    attempted: bool = False
    tool_sent: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Awakened(filter.CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        # 不把群内普通聊天变成唤醒事件。
        return bool(event.is_at_or_wake_command)


@register(
    "astrbot_plugin_fish_tts", "yun474", "Fish 语音：唤醒预选概率与 LLM 工具", "0.1.0"
)
class FishTTSPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = FishClient(
            config, StarTools.get_data_dir("astrbot_plugin_fish_tts") / "audio"
        )

    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True)) and self.client.ready()

    def tool_enabled(self) -> bool:
        return self.enabled() and bool(self.config.get("enable_tool", True))

    @filter.custom_filter(Awakened, priority=100)
    async def on_wake(self, event: AstrMessageEvent):
        if event.get_extra(STATE_KEY) is not None:
            return
        probability = max(0.0, min(1.0, float(self.config.get("probability", 0.3))))
        selected = self.enabled() and random.random() < probability
        event.set_extra(STATE_KEY, VoiceTurn(selected=selected))
        # 必须在核心读取 enable_streaming 之前执行。工具也可能发语音，统一整轮输出。
        if selected or self.tool_enabled():
            event.set_extra("enable_streaming", False)

    @filter.on_llm_request()
    async def prepare_request(self, event: AstrMessageEvent, req: ProviderRequest):
        state = event.get_extra(STATE_KEY)
        # 未经唤醒处理的主动请求不做迟到的概率抽签，也不提供依赖非流式输出的工具。
        has_tool = (
            self.tool_enabled() and state is not None and req.func_tool is not None
        )
        if req.func_tool is not None:
            req.func_tool = copy.copy(req.func_tool)
            tool = req.func_tool.get_tool(TOOL_NAME)
            has_tool = has_tool and tool is not None
            if not has_tool:
                req.func_tool.remove_tool(TOOL_NAME)

        if state is None or (not state.selected and not has_tool):
            return
        if PROMPT_MARK in (req.system_prompt or ""):
            return
        guidance = str(self.config.get("voice_prompt", DEFAULT_PROMPT)).strip()
        if state.selected:
            mode = (
                "本轮已决定使用语音回复。请把最终回复写成待朗读的台词，插件会自动合成并发送。"
                "不需要调用 fish_tts_speak；可以正常调用其他工具获取信息，最后再写完整台词。"
            )
        else:
            mode = (
                "本轮未命中概率语音，默认正常文字回复，正文不要带声音标签。"
                "用户要求语音或确有语音表达需要时，可以调用 fish_tts_speak。"
                "以下台词要求仅用于该工具的 text 参数，不用于普通文字正文。"
            )
        req.system_prompt = (
            req.system_prompt or ""
        ) + f"\n\n{PROMPT_MARK}\n{mode}\n{guidance}\n</fish_tts_turn>"

    @filter.on_llm_response()
    async def remember_speech(self, event: AstrMessageEvent, response: LLMResponse):
        state = event.get_extra(STATE_KEY)
        if not state or not state.selected or state.tool_sent or response is None:
            return
        if response.role != "assistant" or response.tools_call_name:
            return
        state.speech = response.completion_text
        # API 接收原始标签，文字回退与最终 response 使用可读台词。
        if state.speech:
            if response.result_chain:
                for part in response.result_chain.chain:
                    if isinstance(part, Plain):
                        part.text = plain_text(part.text)
            else:
                response.completion_text = plain_text(state.speech)

    @filter.on_decorating_result(priority=100)
    async def render_voice(self, event: AstrMessageEvent):
        state = event.get_extra(STATE_KEY)
        result = event.get_result()
        if state is None or result is None or not result.is_llm_result():
            return
        if state.tool_sent:
            result.chain = [
                part for part in result.chain if not isinstance(part, Plain)
            ]
            return
        if not state.selected or state.attempted or not state.speech:
            return
        if any(isinstance(part, Record) for part in result.chain):
            return
        if not any(isinstance(part, Plain) for part in result.chain):
            return
        async with state.lock:
            if state.attempted or state.tool_sent:
                return
            state.attempted = True
            # 先清理标签，失败时直接交回 AstrBot 发送文字。
            for part in result.chain:
                if isinstance(part, Plain):
                    part.text = plain_text(part.text)
            try:
                audio = await self.client.synthesize(state.speech)
            except (FishError, OSError) as exc:
                logger.warning(
                    "Fish 概率语音未完成，保留文字回复：%s", self._error_text(exc)
                )
                return
            chain = []
            inserted = False
            for part in result.chain:
                if isinstance(part, Plain):
                    if not inserted:
                        chain.append(Record.fromFileSystem(str(audio)))
                        inserted = True
                else:
                    chain.append(part)
            result.chain = chain

    @filter.llm_tool(name=TOOL_NAME)
    async def fish_tts_speak(self, event: AstrMessageEvent, text: str) -> str:
        """用当前 Fish 音色发送一条语音。仅在用户要求或适合语音时调用，每轮最多一条。
        text 是完整口语台词，可使用 S2 方括号标签，如 [happy]、[angry]、[chuckling]。
        已选中自动语音的轮次无需调用本工具。成功后不要再重复台词或发送确认文字。

        Args:
            text(string): 要朗读的完整台词，可含 Fish S2 声音标签，不要 Markdown 或动作旁白。
        """
        if not self.tool_enabled():
            return "Fish 语音工具未开启或尚未配置音色和密钥，请直接用文字回复。"
        state = event.get_extra(STATE_KEY)
        if state is None:
            return "本轮未经过语音准备，请使用普通文字回复。"
        async with state.lock:
            if state.tool_sent:
                return "本轮语音已经发送，不要再次发送或重复台词。"
            if state.attempted:
                return "本轮已经尝试语音，请使用文字回复，不要重复调用。"
            state.attempted = True
            try:
                audio = await self.client.synthesize(text)
                await event.send(
                    event.chain_result([Record.fromFileSystem(str(audio))])
                )
            except (FishError, OSError) as exc:
                return (
                    f"{self._error_text(exc)} 请直接用文字回复，不要继续调用语音工具。"
                )
            except Exception:
                logger.warning("Fish 音频已生成，但平台发送失败。")
                return "语音发送失败，请改用文字回复，不要重复调用。"
            state.tool_sent = True
            return "语音已发送。请结束本轮，不要重复台词或输出确认文字。"

    @staticmethod
    def _error_text(exc: Exception) -> str:
        return str(exc) if isinstance(exc, FishError) else "音频文件读写失败。"

    async def terminate(self):
        await self.client.close()
