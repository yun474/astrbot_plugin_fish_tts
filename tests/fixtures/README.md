# 音频测试样本

两个样本均由 FFmpeg 的 `sine` 滤镜本地合成：440 Hz、0.12 秒、44.1 kHz、单声道、MP3 128 kbps。不含用户录音或 Fish 生成内容。

`tone_id3.mp3` 带 ID3v2.3 标签；`tone_frames.mp3` 从 MPEG Layer III 帧开始，不带 ID3/Xing。FFprobe 已确认两者均为 MP3 / 44100 Hz / mono / 128000 bps。

用于验证 HTTP 音频保存、分块重组和格式检查。插件运行和日常单元测试不需要 FFmpeg；AstrBot 的平台音频处理是否需要 FFmpeg 由框架和适配器决定。
