# File: app/utils/escape_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import re

# --- JSON escape map ---
_JSON_ESC_MAP = {
    '"': r'\"',
    '\\': r'\\',
    '\b': r'\b',
    '\f': r'\f',
    '\n': r'\n',
    '\r': r'\r',
    '\t': r'\t',
}

# Inverse for unescape
_JSON_UNESC_MAP = {v: k for k, v in _JSON_ESC_MAP.items()}

# --- Regex patterns ---
_RE_JSON_ESC = re.compile(r'[\b\f\n\r\t"\\]')
_RE_JSON_UNESC = re.compile(r'\\[bfnrt"\\]')
_RE_SAFE_UNESCAPE = re.compile(
    r'(\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|\\x[0-9a-fA-F]{2}|\\[nrtbf"\'\\])'
)


# --- Core escape functions ---

def _json_encode_char(c: str) -> str:
    if c in _JSON_ESC_MAP:
        return _JSON_ESC_MAP[c]
    o = ord(c)
    if 0x00 <= o < 0x20 or (0x7F <= o < 0xA0):
        return fr'\u{o:04x}'  # optionally: \x?? for ASCII control
    return c  # leave emojis and printable Unicode untouched


def json_escape(txt: str) -> str:
    return ''.join(_json_encode_char(c) for c in txt)


def json_unescape(txt: str) -> str:
    return _RE_JSON_UNESC.sub(lambda m: _JSON_UNESC_MAP[m.group(0)], txt)


# --- Safe escape (generic ASCII + control) ---
def _safe_encode_char(c: str) -> str:
    o = ord(c)
    if c == '\\': return r'\\'
    if c == '\n': return r'\n'
    if c == '\r': return r'\r'
    if c == '\t': return r'\t'
    if c == '\b': return r'\b'
    if c == '\f': return r'\f'
    if 0x00 <= o < 0x20 or (0x7F <= o < 0xA0):
        return fr'\x{o:02x}'
    if o > 0xFFFF:
        return fr'\U{o:08x}'
    return c  # printable, including emojis


def safe_escape(txt: str) -> str:
    return ''.join(_safe_encode_char(c) for c in txt)


def _decode_match(m):
    s = m.group(0)
    if s in _JSON_UNESC_MAP:
        return _JSON_UNESC_MAP[s]
    if s.startswith(r'\x'): return chr(int(s[2:], 16))
    if s.startswith(r'\u'): return chr(int(s[2:], 16))
    if s.startswith(r'\U'): return chr(int(s[2:], 16))
    return s


def safe_unescape(txt: str) -> str:
    return _RE_SAFE_UNESCAPE.sub(_decode_match, txt)
