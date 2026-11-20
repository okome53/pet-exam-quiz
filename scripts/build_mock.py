#!/usr/bin/env python3
"""予想問題（data/mock/*.json）→ docs/mock.js（アプリが読むデータ）。検査込み。

使い方:
  python3 scripts/build_mock.py [--src DIR] [--out-js PATH]

data/mock/ の JSON 1 本が 1 回分の問題集。ファイル名の順に並べて const MOCK_SETS に入れる。
JSON は印刷物から文字起こしした問題・選択肢と、このアプリのために作った正解・解説・裏取りを手で持つ（変換元の md は無い）。
検査に 1 つでも落ちたら、見つけた問題をすべて標準エラーに出して終了コード 1。そのときは何も書き出さない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from convert import write_outputs

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_PREFIX = "const MOCK_SETS = "
# 裏取りの分類と画面の札（data/questions.json と同じ 3 つ）
LABELS = {"confirmed": "出典で確認", "unconfirmed": "出典で確認できず", "doubtful": "疑いあり"}
SET_KEYS = {"id", "title", "questions"}
Q_KEYS = {"no", "field", "stem", "answer", "choices", "verify", "note"}
CHOICE_KEYS = {"n", "text", "expl"}
VERIFY_KEYS = {"class", "label", "reason", "urls", "ref_texts"}
# 141 問の問題集は id を持たない（記録の保存場所が既存のまま）。予想問題の id は保存場所の名前に使う
RESERVED_IDS = {"main"}


def _text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def check_question(where: str, q) -> list[str]:
    if not isinstance(q, dict) or set(q) != Q_KEYS:
        return [f"{where}: 項目が {sorted(Q_KEYS)} になっていない"]
    errors: list[str] = []
    for key in ("field", "stem"):
        if not _text(q[key]):
            errors.append(f"{where}: {key} が空")
    choices = q["choices"]
    if not isinstance(choices, list) or len(choices) < 2:
        return errors + [f"{where}: 選択肢が 2 つ以上の配列になっていない"]
    for i, c in enumerate(choices, 1):
        if not isinstance(c, dict) or set(c) != CHOICE_KEYS:
            errors.append(f"{where}: 選択肢 {i} の項目が {sorted(CHOICE_KEYS)} になっていない")
            continue
        if c["n"] != i:
            errors.append(f"{where}: 選択肢 {i} の番号が {c['n']!r}（1 から順に振る）")
        if not _text(c["text"]):
            errors.append(f"{where}: 選択肢 {i} の文が空")
        if c["n"] == q["answer"]:
            if c["expl"] is not None:
                errors.append(f"{where}: 正解の選択肢 {i} に解説がある（正解の根拠は verify.reason に書く）")
        elif not _text(c["expl"]):
            errors.append(f"{where}: 不正解の選択肢 {i} に解説がない")
    if not (isinstance(q["answer"], int) and 1 <= q["answer"] <= len(choices)):
        errors.append(f"{where}: 正解 {q['answer']!r} が選択肢の番号にない")
    v = q["verify"]
    if not isinstance(v, dict) or set(v) != VERIFY_KEYS:
        errors.append(f"{where}: verify の項目が {sorted(VERIFY_KEYS)} になっていない")
    else:
        if LABELS.get(v["class"]) != v["label"]:
            errors.append(f"{where}: verify の分類 {v['class']!r} と札 {v['label']!r} が合わない")
        if not _text(v["reason"]):
            errors.append(f"{where}: 正解の根拠（verify.reason）が空")
        urls = v["urls"]
        if not isinstance(urls, list) or not all(isinstance(u, str) and u.startswith("https://") for u in urls):
            errors.append(f"{where}: verify.urls が https の URL の配列になっていない")
        if v["class"] == "confirmed" and not urls:
            errors.append(f"{where}: 「出典で確認」なのに出典の URL がない")
        if not isinstance(v["ref_texts"], list) or not all(_text(t) for t in v["ref_texts"]):
            errors.append(f"{where}: verify.ref_texts が文の配列になっていない")
    if q["note"] is not None and not _text(q["note"]):
        errors.append(f"{where}: note は null か空でない文")
    return errors


def check_set(name: str, s) -> list[str]:
    if not isinstance(s, dict) or set(s) != SET_KEYS:
        return [f"{name}: 項目が {sorted(SET_KEYS)} になっていない"]
    errors: list[str] = []
    if not (isinstance(s["id"], str) and re.fullmatch(r"[a-z][a-z0-9]{0,15}", s["id"])) or s["id"] in RESERVED_IDS:
        errors.append(f"{name}: id {s['id']!r} は英小文字で始まる英小文字・数字 16 字まで（main は使えない）")
    if not _text(s["title"]):
        errors.append(f"{name}: title が空")
    qs = s["questions"]
    if not isinstance(qs, list) or not qs:
        return errors + [f"{name}: questions が空"]
    for i, q in enumerate(qs, 1):
        no = q.get("no") if isinstance(q, dict) else None
        if no != i:
            errors.append(f"{name}: {i} 番目の問の番号が {no!r}（1 から順に振る）")
        errors += check_question(f"{name} 問{i}", q)
    return errors


def build(src: Path) -> tuple[list[dict], list[str]]:
    paths = sorted(src.glob("*.json"))
    if not paths:
        return [], [f"予想問題の JSON がない: {src}"]
    sets: list[dict] = []
    errors: list[str] = []
    for path in paths:
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: JSON として読めない（{exc}）")
            continue
        errors += check_set(path.name, s)
        sets.append(s)
    ids = [s.get("id") for s in sets if isinstance(s, dict)]
    if len(ids) != len(set(ids)):
        errors.append(f"id が重複している: {ids}")
    return sets, errors


def to_js(sets: list[dict]) -> str:
    """<script src> で読む JS。`<` を \\u003c にして `</script` や `<!--` で抜け出せないようにする。"""
    text = json.dumps(sets, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return JS_PREFIX + text + ";\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="予想問題の JSON からクイズのデータを作る（検査に落ちたら何も書かない）")
    parser.add_argument("--src", type=Path, default=REPO_ROOT / "data" / "mock")
    parser.add_argument("--out-js", type=Path, default=REPO_ROOT / "docs" / "mock.js")
    args = parser.parse_args(argv)
    sets, errors = build(args.src)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(f"検査で {len(errors)} 件の問題が見つかった。何も書き出していない。", file=sys.stderr)
        return 1
    try:
        write_outputs([(args.out_js, to_js(sets))])
    except OSError as exc:
        print(f"書き出しに失敗した: {exc}", file=sys.stderr)
        return 1
    summary = "・".join(f"{s['title']} {len(s['questions'])} 問" for s in sets)
    print(f"{summary} を書き出した: {args.out_js}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
