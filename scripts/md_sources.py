"""md 3 本（不正解の解説・全141問・正解の裏取り結果）と、照合の例外リストを読む関数。

ここでは 1 ファイルずつ「読めた形」を返す。問の過不足と、ファイルどうしの突き合わせは convert.py が行う。
形の崩れは、ファイル名と問番号つきの日本語の文で errors に積む（最初の 1 件で止めず、全部出す）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

CIRCLED = "①②③④⑤"
EXPL = "不正解の解説.md"
ORIG = "全141問.md"
VERI = "裏取り結果.md"
EXC = "order-exceptions.json"

QUESTION_HEAD = re.compile(r"^## 問(\d+)\s*$")
ANSWER_LINE = re.compile(r"^\*\*正解:\*\*\s*([①-⑤])\s*(.*)$")
CHOICE_HEAD = re.compile(r"^### ([①-⑤])\s*(.*)$")
ORIGINAL_CHOICE = re.compile(r"^-\s+(\*\*\[正解\]\*\*\s*)?([①-⑤])\s*(.*)$")
SOURCE_LINE = re.compile(r"^出典[:：]\s*(\S+?)\s*（作成者[:：]\s*(.+?)）\s*$")
NOTE_MARK = re.compile(r"^⚠️?\s*")
HTTP_URL = re.compile(r"https?://[^\s/?#\x00-\x1f\x7f]+[^\s\x00-\x1f\x7f]*")
TABLE_SEPARATOR = re.compile(r":?-+:?")

VERIFY_HEADER = ["問", "分類", "根拠・理由", "出典 URL"]
CLASSES = {"出典で確認": "confirmed", "出典で確認できず": "unconfirmed", "疑いあり": "doubtful"}
NO_URL = "—"
EXCEPTION_KEYS = {"no", "n", "check", "reason"}
# similarity: 類似度の照合で自分の番号が最も似ていない／number: 全141問.md の選択肢の番号の誤記
# answer: 全141問.md の [正解] の印が不正解の解説.md の正解と違う（n は採る正解＝不正解の解説.md の番号）
EXCEPTION_CHECKS = ("similarity", "number", "answer")


def circled(n: int) -> str:
    return CIRCLED[n - 1]


def join_paragraphs(lines: list[str]) -> str:
    """空行で区切られた段落を "\\n\\n" でつなぐ。各行は前後の空白を落とす（md の装飾は解釈しない）。"""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in [*lines, ""]:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    return "\n\n".join(paragraphs)


def split_questions(text: str, label: str) -> tuple[list[str], list[tuple[int, list[str]]], list[str]]:
    """本文を「## 問N」で区切る。戻り値は（最初の問より前の行, [(問番号, 行)], errors）。"""
    preamble: list[str] = []
    blocks: list[tuple[int, list[str]]] = []
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            m = QUESTION_HEAD.match(line)
            if m is None:
                errors.append(f"{label} {lineno} 行目: 「## 問N」の形でない見出し「{line.strip()}」")
                continue
            blocks.append((int(m.group(1)), []))
            continue
        (blocks[-1][1] if blocks else preamble).append(line)
    counts = Counter(no for no, _ in blocks)
    errors += [f"{label} 問{no}: 見出しが {c} 回ある" for no, c in sorted(counts.items()) if c > 1]
    return preamble, blocks, errors


# ---------------------------------------------------------------- 不正解の解説.md


def _note(lines: list[str], start: int, end: int, where: str) -> tuple[str | None, list[str]]:
    """正解の行と最初の選択肢見出しの間にある `> ⚠` の注記。先頭の「⚠」は落とす（見出しは画面側が付ける）。"""
    quoted: list[str] = []
    errors: list[str] = []
    for line in lines[start:end]:
        if line.lstrip().startswith(">"):
            quoted.append(re.sub(r"^\s*>\s?", "", line))
        elif line.strip():
            errors.append(f"{where}: 正解の行と選択肢の見出しの間に想定外の行「{line.strip()[:40]}」")
    if not quoted:
        return None, errors
    note = NOTE_MARK.sub("", join_paragraphs(quoted)).strip()
    if not note:
        errors.append(f"{where}: 注記（> の行）が空")
    return note or None, errors


def _choice_sections(lines: list[str], heads: list[int], where: str) -> tuple[dict[int, dict], list[str]]:
    """「### ①」見出しごとの（選択肢の文, 解説）。解説は次の見出しまでの段落。"""
    choices: dict[int, dict] = {}
    errors: list[str] = []
    for pos, i in enumerate(heads):
        m = CHOICE_HEAD.match(lines[i])
        n, text = CIRCLED.index(m.group(1)) + 1, m.group(2).strip()
        body = lines[i + 1:heads[pos + 1] if pos + 1 < len(heads) else len(lines)]
        expl = join_paragraphs(body)
        if not text:
            errors.append(f"{where} {circled(n)}: 選択肢の見出しの文が空")
        if not expl:
            errors.append(f"{where} {circled(n)}: 不正解の解説が空")
        if n in choices:
            errors.append(f"{where}: 選択肢の見出し {circled(n)} が 2 回ある")
        choices.setdefault(n, {"text": text, "expl": expl})
    return choices, errors


def _check_layout(lines: list[str], answer_at: int, where: str) -> tuple[list[int], list[str]]:
    """見出しと `>` の行の位置を確かめ、「### ①」見出しの行番号を返す。"""
    errors: list[str] = []
    heads: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            if CHOICE_HEAD.match(line) is None:
                errors.append(f"{where}: 想定外の見出し「{line.strip()[:40]}」")
            elif i < answer_at:
                errors.append(f"{where}: 選択肢の見出し「{line.strip()[:20]}」が正解の行より前にある")
            else:
                heads.append(i)
    first = heads[0] if heads else len(lines)
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">") and not answer_at < i < first:
            errors.append(f"{where}: 注記（> の行）が正解の行の直後以外にある「{line.strip()[:40]}」")
    return heads, errors


def parse_explanation_block(no: int, lines: list[str]) -> tuple[dict | None, list[str]]:
    """不正解の解説.md の 1 問。問題文・正解（番号と文）・不正解 4 つ（文と解説）・注記を取る。"""
    where = f"{EXPL} 問{no}"
    answers = [i for i, line in enumerate(lines) if line.startswith("**正解:**")]
    if len(answers) != 1:
        return None, [f"{where}: 正解の行（**正解:**）が {len(answers)} 個（1 個のはず）"]
    answer_at = answers[0]
    m = ANSWER_LINE.match(lines[answer_at])
    if m is None or not m.group(2).strip():
        return None, [f"{where}: 正解の行が「**正解:** ④ 文」の形でない"]
    answer = CIRCLED.index(m.group(1)) + 1
    heads, errors = _check_layout(lines, answer_at, where)
    stem = join_paragraphs(lines[:answer_at])
    if not stem:
        errors.append(f"{where}: 問題文が空")
    note, errs = _note(lines, answer_at + 1, heads[0] if heads else len(lines), where)
    errors += errs
    choices, errs = _choice_sections(lines, heads, where)
    errors += errs
    if len(heads) != 4:
        errors.append(f"{where}: 不正解の選択肢の見出し（###）が {len(heads)} 個（4 個のはず）")
    numbers = sorted([answer, *(CIRCLED.index(CHOICE_HEAD.match(lines[i]).group(1)) + 1 for i in heads)])
    if numbers != [1, 2, 3, 4, 5]:
        errors.append(f"{where}: 正解と見出しの番号が①〜⑤の 1 つずつになっていない（{''.join(map(circled, numbers))}）")
    if errors:
        return None, errors
    choices[answer] = {"text": m.group(2).strip(), "expl": None}
    return {"no": no, "stem": stem, "answer": answer, "choices": choices, "note": note}, []


def parse_explanations(text: str) -> tuple[dict[int, dict], list[str]]:
    _, blocks, errors = split_questions(text, EXPL)
    questions: dict[int, dict] = {}
    for no, lines in blocks:
        question, errs = parse_explanation_block(no, lines)
        errors += errs
        if question is not None:
            questions.setdefault(no, question)
    return questions, errors


# ---------------------------------------------------------------- 全141問.md


def _source_meta(preamble: list[str]) -> tuple[dict | None, list[str]]:
    """冒頭の「出典: URL（作成者: 名前）」の行から、出典の URL と作成者を取る。"""
    found = [m for m in map(SOURCE_LINE.match, preamble) if m]
    if len(found) != 1:
        return None, [f"{ORIG}: 冒頭の「出典: URL（作成者: 名前）」の行が {len(found)} 個（1 個のはず）"]
    url, author = found[0].group(1), found[0].group(2).strip()
    if not HTTP_URL.fullmatch(url):
        return None, [f"{ORIG}: 出典が http:// か https:// で始まる URL でない「{url}」"]
    return {"source_url": url, "author": author}, []


def parse_original(text: str) -> tuple[dict | None, dict[int, dict], list[str]]:
    """全141問.md。各問の「**解説**」より前にある選択肢の行だけを、行の順に（番号, 文, 正解の印）で取る。
    解説節が無い問は、問の終わりまでを選択肢の範囲とする（実データでは問21）。"""
    preamble, blocks, errors = split_questions(text, ORIG)
    meta, errs = _source_meta(preamble)
    errors += errs
    questions: dict[int, dict] = {}
    for no, lines in blocks:
        cut = next((i for i, line in enumerate(lines) if line.strip() == "**解説**"), None)
        choices = []
        for line in lines if cut is None else lines[:cut]:
            m = ORIGINAL_CHOICE.match(line)
            if m:
                choices.append((CIRCLED.index(m.group(2)) + 1, m.group(3).strip(), m.group(1) is not None))
            elif "[正解]" in line:
                errors.append(f"{ORIG} 問{no}: 選択肢の行でない所に [正解] がある「{line.strip()[:40]}」")
        questions.setdefault(no, {"choices": choices, "has_kaisetsu": cut is not None})
    return meta, questions, errors


# ---------------------------------------------------------------- 裏取り結果.md


def _cells(line: str) -> list[str] | None:
    if not (line.startswith("|") and line.endswith("|")) or len(line) < 2:
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def is_source_name(item: str) -> bool:
    """URL ではない出典名（実データでは問101「環境省マニュアル（カメレオンの節）」）。リンクにはせず文字で出す。
    URL もどき（`javascript:`・`example.com/x`・`//host`）を取り違えないよう、`:` `/` `\\` を含むものと、
    ASCII の文字だけでできたものは出典名と見なさない（＝検査で落ちる）。"""
    flat = unicodedata.normalize("NFKC", item)
    return any(ord(c) > 0x7F for c in flat) and re.search(r"[:/\\\x00-\x1f\x7f]", flat) is None


def split_sources(cell: str, where: str) -> tuple[list[str], list[str], list[str]]:
    """出典 URL の欄を「／」で分ける。戻り値は（URL, URL でない出典名, errors）。「—」は出典なし。"""
    if cell == NO_URL:
        return [], [], []
    if not cell:
        return [], [], [f"{where}: 出典 URL の欄が空（出典がないときは「{NO_URL}」）"]
    urls: list[str] = []
    names: list[str] = []
    errors: list[str] = []
    for item in (part.strip() for part in cell.split("／")):
        if HTTP_URL.fullmatch(item):
            urls.append(item)
        elif is_source_name(item):
            names.append(item)
        else:
            errors.append(f"{where}: http:// か https:// で始まる URL でない出典「{item}」")
    return urls, names, errors


def _verify_row(lineno: int, line: str) -> tuple[dict | None, list[str]]:
    cells = _cells(line)
    if cells is None or len(cells) != 4:
        return None, [f"{VERI} {lineno} 行目: 4 列の表の行として読めない"]
    no_cell, label, reason, url_cell = cells
    if not re.fullmatch(r"[0-9]+", no_cell):
        return None, [f"{VERI} {lineno} 行目: 問の欄「{no_cell}」が数字でない"]
    where = f"{VERI} 問{int(no_cell)}"
    errors: list[str] = []
    if label not in CLASSES:
        errors.append(f"{where}: 分類「{label}」が 3 種類（{'・'.join(CLASSES)}）のどれでもない")
    if not reason:
        errors.append(f"{where}: 根拠・理由が空")
    urls, names, errs = split_sources(url_cell, where)
    errors += errs
    entry = {"no": int(no_cell), "class": CLASSES.get(label), "label": label, "reason": reason,
             "urls": urls, "ref_texts": names}
    return entry, errors


def parse_verification(text: str) -> tuple[dict[int, dict], list[str]]:
    """裏取り結果.md の表。1 行目が見出し、2 行目が区切り、3 行目からが 1 問 1 行。"""
    rows = [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1) if line.strip().startswith("|")]
    if len(rows) < 2:
        return {}, [f"{VERI}: 表が見つからない"]
    errors: list[str] = []
    if _cells(rows[0][1]) != VERIFY_HEADER:
        errors.append(f"{VERI} {rows[0][0]} 行目: 表の見出しが「{' | '.join(VERIFY_HEADER)}」でない")
    separator = _cells(rows[1][1])
    if separator is None or not all(TABLE_SEPARATOR.fullmatch(c) for c in separator):
        errors.append(f"{VERI} {rows[1][0]} 行目: 表の区切りの行（|---|）でない")
    result: dict[int, dict] = {}
    for lineno, line in rows[2:]:
        entry, errs = _verify_row(lineno, line)
        errors += errs
        if entry is None:
            continue
        no = entry.pop("no")
        if no in result:
            errors.append(f"{VERI} 問{no}: 行が 2 つある")
        result.setdefault(no, entry)
    return result, errors


# ---------------------------------------------------------------- order-exceptions.json


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _exception_entry(item: object) -> tuple[dict | None, str | None]:
    if not isinstance(item, dict):
        return None, "オブジェクト（{...}）でない"
    unknown = sorted(set(item) - EXCEPTION_KEYS)
    if unknown:
        return None, f"知らない項目がある（{', '.join(unknown)}）"
    no, n = item.get("no"), item.get("n")
    check = item.get("check", "similarity")
    reason = item.get("reason")
    if not _is_int(no) or no < 1:
        return None, "no が 1 以上の整数でない"
    if not _is_int(n) or not 1 <= n <= 5:
        return None, "n が 1〜5 の整数でない"
    if check not in EXCEPTION_CHECKS:
        return None, f"check が {' / '.join(EXCEPTION_CHECKS)} のどれでもない"
    if not isinstance(reason, str) or not reason.strip():
        return None, "reason（理由）が空"
    return {"no": no, "n": n, "check": check, "reason": reason.strip()}, None


def parse_exceptions(text: str | None) -> tuple[list[dict], list[str]]:
    """照合の例外。形は [{"no": 問, "n": 番号, "check": "similarity"|"number"|"answer", "reason": 理由}]。
    check を省いたら similarity。ファイルが無い（text が None）なら例外なし。"""
    if text is None:
        return [], []
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"{EXC}: JSON として読めない（{exc.lineno} 行目: {exc.msg}）"]
    if not isinstance(raw, list):
        return [], [f"{EXC}: 一番外側が配列（[...]）でない"]
    entries: list[dict] = []
    errors: list[str] = []
    seen: set[tuple] = set()
    for index, item in enumerate(raw, 1):
        entry, error = _exception_entry(item)
        if entry is None:
            errors.append(f"{EXC} {index} 件目: {error}")
            continue
        key = (entry["no"], entry["n"], entry["check"])
        if key in seen:
            errors.append(f"{EXC} {index} 件目: 問{entry['no']} {circled(entry['n'])}（{entry['check']}）が 2 回ある")
            continue
        seen.add(key)
        entries.append(entry)
    return entries, errors
