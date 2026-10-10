import asyncio
import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
client_module = importlib.import_module(f"{ROOT.name}.fish_client")
FishClient, FishError = client_module.FishClient, client_module.FishError


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.calls = []
        self.status = 200
        self.body = (ROOT / "tests/fixtures/tone_id3.mp3").read_bytes()
        self.content_type = "audio/mpeg"
        self.delay = 0
        self.chunked = False

        async def handle(request):
            self.calls.append((dict(request.headers), await request.json()))
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.chunked:
                response = web.StreamResponse(
                    headers={"Content-Type": self.content_type}
                )
                response.enable_chunked_encoding()
                await response.prepare(request)
                for start in range(0, len(self.body), 97):
                    await response.write(self.body[start : start + 97])
                await response.write_eof()
                return response
            return web.Response(
                status=self.status, body=self.body, content_type=self.content_type
            )

        app = web.Application()
        app.router.add_post("/v1/tts", handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.config = {
            "api_key": "local-test-secret",
            "reference_id": "test-voice",
            "api_url": f"http://127.0.0.1:{port}/v1/tts",
            "model": "s2-pro",
            "speed": 1.1,
            "volume": 2,
        }
        self.client = FishClient(self.config, self.path)

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()
        self.temp.cleanup()

    async def test_real_http_request_and_audio_file(self):
        path = await self.client.synthesize("[angry] 不许欺负云云！")
        self.assertEqual(path.read_bytes(), self.body)
        headers, body = self.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer local-test-secret")
        self.assertEqual(headers["model"], "s2-pro")
        self.assertEqual(body["reference_id"], "test-voice")
        self.assertEqual(body["text"], "[angry] 不许欺负云云！")
        self.assertEqual(body["prosody"], {"speed": 1.1, "volume": 2})
        self.assertEqual(body["format"], "mp3")
        await self.client.close()
        self.assertTrue(self.client.session.closed)

    async def test_http_error_not_saved_and_sensitive_body_not_echoed(self):
        self.status = 401
        self.body = b"local-test-secret"
        with self.assertRaisesRegex(FishError, "HTTP 401") as error:
            await self.client.synthesize("hello")
        self.assertNotIn("local-test-secret", str(error.exception))
        self.assertEqual(list(self.path.iterdir()), [])
        self.assertEqual(len(self.calls), 1)

    async def test_chunked_audio_is_reassembled_without_changes(self):
        self.chunked = True
        path = await self.client.synthesize("分块音频")
        self.assertEqual(path.read_bytes(), self.body)

    async def test_mp3_without_id3_and_generic_content_type(self):
        self.body = (ROOT / "tests/fixtures/tone_frames.mp3").read_bytes()
        self.content_type = "application/octet-stream"
        path = await self.client.synthesize("没有 ID3 的 MP3")
        self.assertEqual(path.read_bytes(), self.body)

    async def test_other_formats_and_id3_only_are_rejected(self):
        for body in (
            b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 64,
            b"OggS" + b"\0" * 64,
            b"\xff\xf1\x50\x80" + b"\0" * 64,
            b"ID3\x04\x00\x00\x00\x00\x00\x00",
            b"\xff\xfb",
        ):
            with self.subTest(header=body[:10]):
                self.body = body
                with self.assertRaises(FishError):
                    await self.client.synthesize("格式不符")
        self.assertEqual(list(self.path.iterdir()), [])

    async def test_bad_audio_empty_body_and_json_response(self):
        for content_type, body in [
            ("audio/mpeg", b""),
            ("text/html", b"<html>oops</html>"),
            ("application/json", b"{}"),
        ]:
            with self.subTest(content_type=content_type, body=body):
                self.content_type, self.body = content_type, body
                with self.assertRaises(FishError):
                    await self.client.synthesize("hello")
        self.assertEqual(list(self.path.iterdir()), [])

    async def test_timeout(self):
        self.config["timeout"] = 0.02
        self.delay = 0.05
        with self.assertRaisesRegex(FishError, "超时"):
            await self.client.synthesize("hello")
        self.assertEqual(list(self.path.iterdir()), [])

    async def test_length_limit_rejects_without_charging_request(self):
        self.config["max_text_length"] = 5
        with self.assertRaisesRegex(FishError, "字数上限"):
            await self.client.synthesize("123456")
        self.assertEqual(self.calls, [])

    async def test_missing_credentials_do_not_request(self):
        self.config["api_key"] = ""
        with self.assertRaisesRegex(FishError, "配置"):
            await self.client.synthesize("hello")
        self.assertEqual(self.calls, [])

    async def test_parallel_synthesis_writes_distinct_files(self):
        paths = await asyncio.gather(
            self.client.synthesize("a"), self.client.synthesize("b")
        )
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(path.read_bytes() == self.body for path in paths))

    async def test_cleanup_keeps_recent_and_unrelated_files(self):
        old = self.path / "fish_old.mp3"
        old.write_bytes(b"old")
        stale_time = time.time() - 90000
        os.utime(old, (stale_time, stale_time))
        recent = self.path / "fish_recent.mp3"
        recent.write_bytes(b"recent")
        unrelated = self.path / "other.mp3"
        unrelated.write_bytes(b"unrelated")
        await self.client.synthesize("hello")
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
