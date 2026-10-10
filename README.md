# Fish 语音

主人，云云把 Fish 语音做成了一个独立的 AstrBot 插件。唤醒时决定这一轮是否语音回复，LLM 直接写口语台词和声音标签，插件交给 Fish 合成。

## 使用

1. 在 AstrBot 插件管理中使用仓库地址 `https://github.com/yun474/astrbot_plugin_fish_tts` 安装，或导入插件 ZIP。手动安装时，把目录放到 `data/plugins/astrbot_plugin_fish_tts`，安装依赖并重启插件。
2. 填写 Fish 的 `api_key` 和克隆音色的 `reference_id`。默认接口为 `https://api.fish.audio/v1/tts`，默认模型 `s2-pro`，也可选择 `s2.1-pro` / `s2.1-pro-free`。
3. 设置 `probability`：`0.3` 是 30%，`1` 是每轮语音，`0` 是关闭自动语音但仍可使用工具。
4. 在「音频输出格式」中选择 `mp3` 或 `wav`，默认 `mp3`。在「语音台词提示词」中编辑表达要求、语气词、标签和示例。默认语速 `1.1`，音量 `0 dB`。Fish 的音量是分贝增益，不是 MiniMax 的音量倍率。
5. 使用该插件负责语音的会话，请关闭其他 TTS 插件和 AstrBot 内置自动 TTS，避免重复转换或回退文字被再次语音化。

插件包没有任何 API Key，主人需要在自己的 AstrBot 配置面板填写。

## 音频格式

Fish `/v1/tts` 成功时返回音频二进制。`audio_format` 可选 `mp3` / `wav`，默认 `mp3`；请求格式、响应检查和文件后缀同时切换。MP3 使用 128 kbps，WAV 使用未压缩 PCM；两种格式均使用 Fish 默认的 44.1 kHz、单声道。HTTP 分块由 `aiohttp` 合并后再写入文件，不进行 JSON、hex 或 base64 解码。

MP3 检查 ID3v2 标签后的 MPEG Layer III 帧头，也接受没有 ID3 的 MP3；WAV 检查 PCM 容器与首个采样帧，支持流式响应使用的未定长 WAV 头。该检查用于排除明显的格式错误，不等于完整音频解码。HTTP 错误、JSON 错误响应、空数据和不匹配的音频格式不会作为语音发送。

发送时使用 AstrBot `Record.fromFileSystem`。已核对 AstrBot 4.5.7 和 `f9ad300` 的 OneBot 适配器：它会读取音频并转成 `base64://` 的 `record` 消息交给协议端，具体转码和平台发送由 AstrBot 及协议端处理。

**QQ 官方机器人**的发送流程不同：已核对 AstrBot 4.5.7 和 `f9ad300` 的 QQ 官方适配器，最终会转换为腾讯 SILK 再上传。这里的 `mp3 / wav` 配置控制 Fish 的源音频。主人可选择 WAV 作为转码输入，仍需 AstrBot 的音频转码依赖正常；当前 Webhook 适配器继承同一发送实现。尚未使用真实 QQ 官方机器人联调。

## 概率语音

AstrBot 识别私聊、@ 或唤醒词后，插件在消息处理阶段只抽一次概率，并把结果保存到当前事件。普通群聊不会被插件唤醒，也不会按群号共享抽签结果。

命中后，本轮关闭流式输出。在 `on_llm_request` 中追加语音模式说明和可编辑提示词，保留原有人设。LLM 根据上下文写出带 Fish S2 方括号标签的台词；最终回复按配置合成一条 MP3 或 WAV，以语音替换文字，图片等其他消息组件保留。中间工具查询不触发合成。

默认提示词让模型自行判断情绪，没有明显情绪时用 `[happy]`，避免 `[calm]` 和 `[neutral]`；适当使用 `[angry]`、`[sad]`、`[chuckling]` 等。这里是可编辑的表达指令，没有关键词分类器、情绪路由、情绪音色映射或二次改写 LLM。提示词不能保证模型永远遵循标签要求，也不能保证听感。

插件不在回复完成后补抽概率，不截断超长台词，不为失败请求自动重试。未配置密钥或音色时正常文字回复；合成超时、HTTP 错误、音频无效、文件写入失败或内容超长时，保留去掉英文声音标签的文字。

## LLM 工具

`fish_tts_speak(text)` 接收完整台词，可含 S2 方括号标签。没有命中概率时，LLM 仍可根据用户要求调用工具；其余情况下默认正常文字回复，语音指导只用于工具参数。

工具每轮最多尝试一次。成功发送后，本轮后续 LLM 文字会被抑制，避免重复台词，其他类型消息组件保留。失败会向 LLM 返回明确结果，让它用文字回复。命中自动语音时提示 LLM 直接写最终台词；如果它仍调用了工具，以工具结果为准，不重复自动合成。

开启工具时，已唤醒的对话同样使用非流式输出，这是为了在发送前处理工具后的重复文字。若希望未命中概率的轮次仍然流式输出，关闭 `enable_tool` 即可。工具也受 AstrBot 的工具启用状态及当前人设工具集合限制。

## 配置

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `enabled` | `true` | 总开关 |
| `api_key` | 空 | Fish API Key |
| `api_url` | 官方 `/v1/tts` | 完整接口地址 |
| `reference_id` | 空 | 单个音色 ID |
| `model` | `s2-pro` | Fish S2 模型 |
| `audio_format` | `mp3` | 输出音频格式，可选 `mp3` / `wav` |
| `probability` | `0.3` | 唤醒时自动语音概率，0～1 |
| `enable_tool` | `true` | LLM 语音工具开关 |
| `speed` | `1.1` | 语速，0.5～2.0 |
| `volume` | `0.0` | 音量增益，单位 dB |
| `max_text_length` | `1000` | 包含标签的字符数上限 |
| `timeout` | `60` | Fish 请求超时秒数 |
| `voice_prompt` | 内置中文提示词 | 可编辑的台词、情绪及标签说明 |

合成结果保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_fish_tts/audio`。文件至少保留 24 小时；有新音频生成时最多每小时清理一次过期文件。卸载插件会关闭 HTTP 会话，不会立即删除尚可能被平台读取的音频。

## 兼容与验证

技术最低版本声明为 **AstrBot 4.5.7**：该版新增本插件依赖的逐事件 `enable_streaming` 覆盖读取，4.5.6 尚无此接口。注册、配置、LLM 请求/响应、发送前钩子、工具集合和音频组件已按 4.5.7 源码核对，并对当前源码 `f9ad300`（4.29.0-beta.2）复核调用顺序。

本地自动化测试使用隔离的 AstrBot 接口替身和本地 HTTP 服务，覆盖概率时机、提示词、工具去重、并发隔离和 API 成功/失败路径。音频测试使用可解码的本地合成 MP3，验证带/不带 ID3、分块传输、通用二进制 Content-Type，以及 WAV 接收、格式切换、MP3/WAV 响应错配和 Opus/AAC/残缺帧头的拒绝行为。没有启动完整 AstrBot，也没有使用真实 Fish 密钥或 QQ 账号联调；源码核对不等于实机测试通过。

适用于 AstrBot 内置 LLM 对话流程。其他插件在之后主动调用 LLM、修改流式开关、自行发消息，或 Dify/Coze 等外部 Agent 流程，不在本版自动语音保证范围内。平台需要支持 AstrBot `Record` 语音消息；AstrBot 进程必须能读取生成的本地音频。其他适配器的文件处理方式需按平台部署确认。

运行本地测试：`python -m unittest discover -s tests -v`。

## 参考

- [Fish TTS HTTP 接口](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech)
- [Fish S2 声音标签](https://docs.fish.audio/developer-guide/core-features/emotions)
- [AstrBot 4.5.7 源码](https://github.com/AstrBotDevs/AstrBot/tree/v4.5.7)

主人维护版本时记得补写 `CHANGELOG.md`。
