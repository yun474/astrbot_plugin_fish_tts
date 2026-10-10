"""Fish S2 方括号提示及文字回退清理。"""

import re

DEFAULT_PROMPT = """按当前人设和上下文组织适合直接说出口的回复，简短自然，有明确的语气起伏。
情绪由你根据上下文判断：高兴就开心，受委屈可以难过，被冒犯可以生气；不要强行把所有内容都写得开心。没有明显情绪时用 [happy]，不要使用 [calm]、[neutral] 或要求平淡播报的标签。
Fish S2 使用英文半角方括号，不使用圆括号。句子主情绪放在该句前，情绪变化时再换标签，不要每个词都加标签。
常用情绪：开心 [happy]、兴奋 [excited]、惊喜 [delighted]、满意 [satisfied]、难过 [sad]、生气 [angry]、不满 [upset]、烦躁 [frustrated]、惊讶 [surprised]、害怕 [scared]、紧张 [nervous]、担心 [worried]、尴尬 [embarrassed]、好奇 [curious]、疑惑 [confused]、怀疑 [doubtful]、失望 [disappointed]、感激 [grateful]、自豪 [proud]、讽刺 [sarcastic]、厌恶 [disgusted]、同情 [empathetic]、坚定 [determined]。
说话方式：强调 [emphasis]、喊话 [shouting]、尖叫 [screaming]、耳语 [whispering]、轻声 [soft tone]、急促 [in a hurry tone]。
非语言发声：笑 [laughing]、轻笑 [chuckling]、抽泣 [sobbing]、大哭 [crying loudly]、叹气 [sighing]、哼声 [groaning]、喘气 [panting]、倒吸气 [gasping]、打哈欠 [yawning]、清嗓 [clear throat]。停顿用 [break] 或 [long-break]。
这些是常用示例，不是固定枚举；也可以用简短自然语言描述，如 [slightly sad]、[very excited]。每句以一种主情绪为主，避免堆叠矛盾标签。非语言发声只在自然需要时少量使用；中文的“嗯”“欸”“哎呀”“哼”等可以直接写进台词，不要机械添加。
只写需要说出口的台词和声音标签，不要 Markdown、代码块、表格、动作旁白或标签解释，不要编造背景音、切换说话人。
示例：[happy] 主人，你回来啦！[chuckling] 快说说今天有什么好玩的。
示例：[angry] 云云都说了不喜欢这个玩笑！[upset] 先听云云把话说完。"""

# 只清理语音模式下的英文方括号指示，保留中文括注、数组和 Markdown 链接。
CUE_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9 ,.'!?_-]*\](?!\()")


def plain_text(text: str) -> str:
    return CUE_RE.sub("", text).strip()
