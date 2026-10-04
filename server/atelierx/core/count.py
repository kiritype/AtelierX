"""Measure text the way the platform preset counts it (`count`): utf8_bytes, chars, or tokens:<tokenizer>.

No tokenizer files are bundled yet, so token counts are an estimate (03-llm: 토큰 수). The web gauge uses the same rule.
"""

import math
import re

HANGUL = re.compile(r'[가-힣ㄱ-ㆎ]')


def estimate_tokens(text):
    """Rough count: a Hangul syllable is about one token, other text about four characters per token."""
    hangul = len(HANGUL.findall(text))
    return hangul + math.ceil((len(text) - hangul) / 4)


def measure(text, mode):
    """Return (amount, estimated)."""
    mode = mode or 'utf8_bytes'
    if mode == 'chars':
        return len(text), False
    if mode.startswith('tokens'):
        return estimate_tokens(text), True
    return len(text.encode('utf-8')), False
