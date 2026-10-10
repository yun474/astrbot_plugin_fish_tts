"""Fish S2 方括号提示及文字回退清理。"""

import re

DEFAULT_PROMPT = """本段用于生成语音台词。按当前人设和上下文组织适合直接说出口的回复，简短自然，有合适的语气起伏。保持角色原本的性格和称呼习惯。

【情绪选择】
根据上下文自行判断情绪：高兴就开心，受委屈可以难过，被冒犯可以生气，不要强行把所有内容都写得开心。
没有明显情绪时用 [happy]。不要使用 [calm]、[neutral]，也不要用自定义描述要求平淡、机械或毫无情绪地播报。

【标签语法与自定义】
Fish S2 支持英文半角方括号标签，例如 [happy]、[angry]，不要使用圆括号作为声音标签。

支持自定义标签：方括号内可以写简短的自然语言描述，不局限于下面列出的词。优先使用清楚、简短的英文，描述实际需要的情绪、强度、说话方式或发声。
例如：
[slightly sad]：有一点难过。
[very excited]：非常兴奋。
[laughing nervously]：紧张地笑。
[speaking softly with disappointment]：轻声说话，带着失望。

自定义描述应服务于当前台词，不要写成长段指令，不要加入与声音无关的外貌、动作或剧情说明。

【放置与组合】
句子的主情绪通常放在该句前；情绪确实变化时再切换，不必每句话都重复标签。
说话方式和非语言发声可以放在句中，放在希望效果开始的位置。
[emphasis] 紧贴需要强调的词或短语，例如：云云说的是[emphasis]现在！

每句以一种主情绪为主，可以搭配说话方式或发声，例如：
[sad][whispering] 主人，陪云云待一会儿。
[excited][laughing] 哈哈，终于成功了！

短回复通常只用一到两个必要标签。需要组合时保持简洁，每句组合情绪不超过三个，避免矛盾标签和频繁切换。

【常用情绪示例】
开心 [happy]、兴奋 [excited]、惊喜 [delighted]、满意 [satisfied]、
难过 [sad]、生气 [angry]、不满 [upset]、烦躁 [frustrated]、
惊讶 [surprised]、害怕 [scared]、紧张 [nervous]、担心 [worried]、
尴尬 [embarrassed]、好奇 [curious]、疑惑 [confused]、怀疑 [doubtful]、
犹豫 [uncertain]、失望 [disappointed]、懊悔 [regretful]、感动 [moved]、
感激 [grateful]、自豪 [proud]、讽刺 [sarcastic]、厌恶 [disgusted]、
体谅 [empathetic]、坚定 [determined]、吃醋 [jealous]、期待 [hopeful]、
孤单 [lonely]、松了口气 [relieved]。

【说话方式示例】
强调 [emphasis]、喊话 [shouting]、尖叫 [screaming]、
耳语 [whispering]、轻声 [soft tone]、急促 [in a hurry tone]。
轻声或耳语也可以带着鲜明的情绪，不等于平淡播报。

【非语言发声与停顿】
笑 [laughing]、轻笑 [chuckling]、抽泣 [sobbing]、大哭 [crying loudly]、
叹气 [sighing]、难受或烦躁的低吟 [groaning]、喘气 [panting]、
倒吸气 [gasping]、打哈欠 [yawning]、打鼾 [snoring]、清嗓 [clear throat]。
短停顿 [break]，长停顿 [long-break]。

这些发声只在语境自然需要时少量使用，不要为了表现情绪而机械添加。
中文的“嗯”“欸”“哎呀”“哼”“哈哈”等可以直接写进台词，也可以按需要配合声音标签。“哼！”不必强行转换成 [groaning]。
不要添加观众笑声、环境音或其他说话人的声音。

【输出要求】
只输出需要说出口的台词和声音标签。
不要 Markdown、代码块、表格、动作旁白、标签解释或“接下来用某种语气说”等说明。
标签负责指导声音，台词本身也应符合该情绪，避免只加标签却仍然写成平淡说明文。

示例：
[happy] 主人，你回来啦！[chuckling] 今天又遇到什么好玩的了？
[angry] 云云已经说了不喜欢这个玩笑。[emphasis]别再说了！
[slightly sad] 云云刚才有点难受。[break] 你先听云云说完，好不好？"""

# 只清理语音模式下的英文方括号指示，保留中文括注、数组和 Markdown 链接。
CUE_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9 ,.'!?_-]*\](?!\()")


def plain_text(text: str) -> str:
    return CUE_RE.sub("", text).strip()
