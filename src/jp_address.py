from __future__ import annotations

import re

_FW_TO_HW = str.maketrans(
    {
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "－": "-",
        "ー": "-",
        "―": "-",
        "−": "-",
        "〒": "",
        "　": "",
    }
)


KANJI_DIGITS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


def normalize_addr(s: str) -> str:
    out = (s or "").strip().translate(_FW_TO_HW)
    out = _normalize_kanji_number_tokens(out)
    return out


def num_to_kanji(n: int) -> str:
    if n <= 10:
        return KANJI_DIGITS[n]
    if n < 20:
        return "十" + KANJI_DIGITS[n - 10]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return KANJI_DIGITS[tens] + "十"
    return KANJI_DIGITS[tens] + "十" + KANJI_DIGITS[ones]


_KANJI_TO_INT = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _kanji_to_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token in _KANJI_TO_INT and token != "十":
        return _KANJI_TO_INT[token]
    if token == "十":
        return 10

    if "十" in token:
        parts = token.split("十")
        if len(parts) != 2:
            return None
        left, right = parts
        tens = 1 if left == "" else _KANJI_TO_INT.get(left)
        ones = 0 if right == "" else _KANJI_TO_INT.get(right)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _normalize_kanji_number_tokens(addr: str) -> str:
    def repl_chome(m: re.Match) -> str:
        n = _kanji_to_int(m.group("num"))
        if n is None:
            return m.group(0)
        return f"{n}丁目"

    def repl_ban(m: re.Match) -> str:
        n = _kanji_to_int(m.group("num"))
        if n is None:
            return m.group(0)
        return f"{n}{m.group('unit')}"

    out = re.sub(r"(?P<num>[一二三四五六七八九十〇零]+)丁目", repl_chome, addr)
    out = re.sub(r"(?P<num>[一二三四五六七八九十〇零]+)(?P<unit>番|号)", repl_ban, out)
    return out


_RE_TOKYO = re.compile(r"^東京都(?P<muni>.+?(?:区|市|町|村))(?P<rest>.*)$")


def split_tokyo_municipality(addr: str) -> tuple[str | None, str]:
    a = normalize_addr(addr)
    m = _RE_TOKYO.match(a)
    if not m:
        return None, a
    return m.group("muni"), m.group("rest")


_RE_CHOME = re.compile(r"(?P<town>.+?)(?P<chome>\d+)丁目(?P<rest>.*)$")
_RE_HYPHEN = re.compile(r"(?P<town>.+?)(?P<chome>\d+)-(?P<block>\d+)(?:-(?P<go>\d+))?.*$")
_RE_BLOCK_NO_CHOME = re.compile(r"(?P<town>.+?)(?P<block>\d+)(?:番(?:地)?|号).*$")


def parse_town_chome_block(addr: str) -> tuple[str | None, int | None, int | None]:
    """町名+丁目+街区(番)を粗く推定する.

    返り値:
      - town: 町名(丁目手前まで)
      - chome: 丁目(数値)
      - block: 街区(最初の番地相当の数値)
    """

    a = normalize_addr(addr)
    _, rest = split_tokyo_municipality(a)
    rest = rest.lstrip()

    m = _RE_CHOME.match(rest)
    if m:
        town = m.group("town")
        chome = int(m.group("chome"))
        after = m.group("rest")
        # 丁目の次に出る数値を街区として扱う(例: 15番3号 -> 15)
        m2 = re.search(r"(\d{1,4})", after)
        block = int(m2.group(1)) if m2 else None
        return town, chome, block

    m = _RE_HYPHEN.match(rest)
    if m:
        town = m.group("town")
        chome = int(m.group("chome"))
        block = int(m.group("block"))
        return town, chome, block

    # 丁目なし住所(例: 日本橋兜町11番5号)から街区を抽出する
    m = _RE_BLOCK_NO_CHOME.match(rest)
    if m:
        town = m.group("town").strip()
        block = int(m.group("block"))
        return town, None, block

    # 町名のみの住所は oaza フォールバック用に town だけ返す
    if rest and re.fullmatch(r"[^\d,，、]+", rest):
        return rest, None, None

    return None, None, None


def build_oaza_chome_name(town: str, chome: int) -> str:
    return f"{town}{num_to_kanji(chome)}丁目"
