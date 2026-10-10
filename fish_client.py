"""Fish HTTP TTS：异步请求，生成 MP3/WAV，定期清理过期音频。"""

import asyncio
import io
import time
import wave
from pathlib import Path
from uuid import uuid4

import aiohttp


class FishError(Exception):
    """可向调用方展示的错误，不携带密钥或服务端响应正文。"""


def has_mp3_header(audio: bytes) -> bool:
    """检查可选 ID3v2 标签之后的 MPEG Layer III 帧头，不代替完整解码。"""
    offset = 0
    if audio.startswith(b"ID3"):
        if len(audio) < 10 or any(byte & 128 for byte in audio[6:10]):
            return False
        tag_size = 0
        for byte in audio[6:10]:
            tag_size = (tag_size << 7) | byte
        offset = 10 + tag_size
        if audio[3] == 4 and audio[5] & 16:
            offset += 10  # ID3v2.4 可选 footer。
    header = audio[offset : offset + 4]
    return (
        len(header) == 4
        and header[0] == 255
        and header[1] & 224 == 224
        and (header[1] >> 3) & 3 != 1  # 非保留 MPEG 版本。
        and (header[1] >> 1) & 3 == 1  # Layer III，排除 ADTS AAC 和 Layer I/II。
        and header[2] >> 4 not in (0, 15)
        and (header[2] >> 2) & 3 != 3
    )


def has_wav_audio(audio: bytes) -> bool:
    """检查 PCM WAV 容器和首个采样帧，兼容流式 WAV 的未定长头。"""
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            frame_size = source.getnchannels() * source.getsampwidth()
            return source.getnframes() > 0 and len(source.readframes(1)) == frame_size
    except (wave.Error, EOFError):
        return False


class FishClient:
    def __init__(self, config: dict, audio_dir: Path):
        self.config = config
        self.audio_dir = audio_dir
        self.session: aiohttp.ClientSession | None = None
        self.last_cleanup = 0.0

    def ready(self) -> bool:
        return bool(
            str(self.config.get("api_key", "")).strip()
            and str(self.config.get("reference_id", "")).strip()
        )

    async def synthesize(self, text: str) -> Path:
        if not self.ready():
            raise FishError("请先配置 Fish API Key 和音色 reference_id。")
        if not text.strip():
            raise FishError("语音内容不能为空。")
        if len(text) > int(self.config.get("max_text_length", 1000)):
            raise FishError("语音内容超过配置的字数上限。")
        audio_format = str(self.config.get("audio_format", "mp3")).strip().lower()
        if audio_format not in ("mp3", "wav"):
            raise FishError("音频格式仅支持 mp3 或 wav，请检查配置。")

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        headers = {
            "Authorization": f"Bearer {str(self.config['api_key']).strip()}",
            "model": str(self.config.get("model", "s2-pro")),
        }
        payload = {
            "text": text,
            "reference_id": str(self.config["reference_id"]).strip(),
            "format": audio_format,
            "normalize": True,
            "latency": "normal",
            "prosody": {
                "speed": float(self.config.get("speed", 1.1)),
                "volume": float(self.config.get("volume", 0)),
            },
        }
        if audio_format == "mp3":
            payload["mp3_bitrate"] = 128
        endpoint = str(
            self.config.get("api_url", "https://api.fish.audio/v1/tts")
        ).strip()
        timeout = aiohttp.ClientTimeout(total=float(self.config.get("timeout", 60)))
        try:
            async with self.session.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise FishError(f"Fish 请求失败（HTTP {response.status}）。")
                if "json" in response.headers.get("Content-Type", "").lower():
                    raise FishError("Fish 返回了错误数据，未收到音频。")
                audio = await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise FishError("Fish 网络请求失败或超时。") from exc
        valid_audio = (
            has_mp3_header(audio) if audio_format == "mp3" else has_wav_audio(audio)
        )
        if not valid_audio:
            raise FishError(f"Fish 返回的数据不符合 {audio_format.upper()} 音频格式。")

        return await asyncio.to_thread(self._save_audio, audio, audio_format)

    def _save_audio(self, audio: bytes, audio_format: str) -> Path:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        if now - self.last_cleanup > 3600:
            self.last_cleanup = now
            for path in self.audio_dir.glob("fish_*.*"):
                if path.suffix not in (".mp3", ".wav"):
                    continue
                try:
                    if now - path.stat().st_mtime > 86400:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        path = self.audio_dir / f"fish_{uuid4().hex}.{audio_format}"
        path.write_bytes(audio)
        return path.resolve()

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
