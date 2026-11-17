#!/usr/bin/env python3
"""md 3 本 → data/questions.json と docs/questions.js（アプリが読むデータ）。検査込み。

使い方:
  python3 scripts/convert.py [--source DIR] [--out-json PATH] [--out-js PATH] [--report PATH] [--exceptions PATH]

- 表示する文（問題文・選択肢・解説・注記）は「不正解の解説.md」から取る
- 「全141問.md」は元の選択肢の順と正解の番号を確かめるためだけに読む
- 「正解の裏取り結果.md」から分類・根拠・出典 URL を取る
検査に 1 つでも落ちたら、見つけた問題をすべて標準エラーに出して終了コード 1。そのときは何も書き出さない。
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

from md_sources import (CLASSES, EXC, EXPL, ORIG, VERI, circled, parse_exceptions, parse_explanations,
                        parse_original, parse_verification)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_COUNT = 141
EXPLANATIONS_FILE = "愛玩動物飼養管理士2級_2026_不正解の解説.md"
ORIGINAL_FILE = "愛玩動物飼養管理士2級_2026_全141問.md"
VERIFICATION_FILE = "愛玩動物飼養管理士2級_2026_正解の裏取り結果.md"
SOURCE_FILES = (EXPLANATIONS_FILE, ORIGINAL_FILE, VERIFICATION_FILE)
JS_PREFIX = "const QUESTIONS = "
JS_SUFFIX = ";\n"
LOWEST_ROWS = 15
CHECK_NAMES = {"similarity": "類似度", "number": "番号の誤記", "answer": "正解の印の食い違い"}


def normalize(text: str) -> str:
    """照合用の正規化。全角・半角の違い（NFKC）と空白の有無を無視する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def similarity(a: str, b: str) -> float:
    # autojunk=False: 長い文で頻出の文字を無視する difflib の既定を切り、文の長さで類似度が揺れないようにする
    return difflib.SequenceMatcher(None, normalize(a), normalize(b), autojunk=False).ratio()


def _nums(numbers) -> str:
    return "・".join(str(n) for n in numbers)


def check_numbers(label: str, found, expected_count: int) -> list[str]:
    """問が 1〜expected_count の 1 回ずつそろっているか（重複は読むときに見ている）。"""
    want = set(range(1, expected_count + 1))
    missing, extra = sorted(want - set(found)), sorted(set(found) - want)
    errors = []
    if missing:
        errors.append(f"{label}: 問がない（{expected_count} 問のはず）: 問{_nums(missing)}")
    if extra:
        errors.append(f"{label}: 1〜{expected_count} の外の問がある: 問{_nums(extra)}")
    return errors


def resolve_original(no: int, entry: dict, fixes: set[int]) -> tuple[dict[int, str] | None, int | None,
                                                                       set[int], list[str]]:
    """全141問.md の 1 問の選択肢を {番号: 文} にする。fixes は「n 行目の番号を n と読み替える」例外。
    戻り値は（{番号: 文}, 正解の番号, 使った読み替え, errors）。"""
    where = f"{ORIG} 問{no}"
    lines = entry["choices"]
    if len(lines) != 5:
        return None, None, set(), [f"{where}: 「**解説**」より前の選択肢の行が {len(lines)} 個（5 個のはず）"]
    used = {pos for pos, (label, _, _) in enumerate(lines, 1) if pos in fixes and label != pos}
    numbers = [pos if pos in used else label for pos, (label, _, _) in enumerate(lines, 1)]
    errors = []
    if sorted(numbers) != [1, 2, 3, 4, 5]:
        errors.append(f"{where}: 選択肢の番号が①〜⑤の 1 つずつになっていない（{''.join(map(circled, numbers))}）")
    correct = [n for n, (_, _, mark) in zip(numbers, lines) if mark]
    if len(correct) != 1:
        errors.append(f"{where}: [正解] の印が {len(correct)} 個（1 個のはず）")
    if errors:
        return None, None, used, errors
    return {n: text for n, (_, text, _) in zip(numbers, lines)}, correct[0], used, []


def match_choices(no: int, mine: dict[int, str], theirs: dict[int, str],
                  allowed: set[int]) -> tuple[list[dict], set[int], list[str]]:
    """不正解の解説.md の k 番に最も似ているのが全141問.md の k 番か（同点も不可）。allowed は確認済みの例外。"""
    rows, used, errors = [], set(), []
    for k in range(1, 6):
        ratios = {j: similarity(mine[k], theirs[j]) for j in range(1, 6)}
        top = max(ratios.values())
        best = [j for j, r in ratios.items() if r == top]
        others = [r for j, r in ratios.items() if j != k]
        rows.append({"no": no, "n": k, "ratio": ratios[k], "best": best, "best_ratio": top,
                     "next_ratio": max(others), "exception": False})
        if best == [k]:
            continue
        if k in allowed:
            used.add(k)
            rows[-1]["exception"] = True
            continue
        errors.append(f"問{no} {circled(k)}: {EXPL} の{circled(k)}に最も似ている {ORIG} の選択肢が"
                      f" {''.join(map(circled, best))}（{top:.3f}）で、同じ番号の{circled(k)}は {ratios[k]:.3f}。"
                      f"中身を確かめて {EXC} に理由つきで載せるか、元の md を直す")
    return rows, used, errors


def cross_check(expl: dict, orig: dict, exceptions: list[dict]) -> tuple[list[dict], list[str]]:
    """2 ファイルの正解の番号と選択肢の順を突き合わせる。使われなかった例外も失敗にする。"""
    keys = {check: {(e["no"], e["n"]) for e in exceptions if e["check"] == check} for check in CHECK_NAMES}
    fixes, allowed = keys["number"], keys["similarity"]
    rows, used, errors = [], set(), []
    for no in sorted(set(expl) & set(orig)):
        q = expl[no]
        theirs, correct, fixed, errs = resolve_original(no, orig[no], {n for m, n in fixes if m == no})
        used |= {(no, n, "number") for n in fixed}
        errors += errs
        if theirs is None:
            continue
        if correct != q["answer"] and (no, q["answer"]) in keys["answer"]:
            used.add((no, q["answer"], "answer"))
        elif correct != q["answer"]:
            errors.append(f"問{no}: 正解の番号が食い違う（{EXPL} は{circled(q['answer'])}・{ORIG} は{circled(correct)}）。"
                          f"どちらが正しいか確かめて {EXC} に理由つきで載せるか、元の md を直す")
        mine = {n: c["text"] for n, c in q["choices"].items()}
        found, ok, errs = match_choices(no, mine, theirs, {n for m, n in allowed if m == no})
        rows += found
        used |= {(no, n, "similarity") for n in ok}
        errors += errs
    for e in exceptions:
        if (e["no"], e["n"], e["check"]) not in used:
            errors.append(f"{EXC}: 問{e['no']} {circled(e['n'])}（{CHECK_NAMES[e['check']]}）の例外が使われていない。"
                          "照合が通るようになったなら消す")
    return rows, errors


def assemble(q: dict, verify: dict) -> dict:
    choices = [{"n": n, "text": c["text"], "expl": c["expl"]} for n, c in sorted(q["choices"].items())]
    return {"no": q["no"], "stem": q["stem"], "answer": q["answer"], "choices": choices,
            "verify": verify, "note": q["note"]}


def build(sources: dict[str, str], exceptions_text: str | None,
          expected_count: int = EXPECTED_COUNT) -> tuple[dict | None, str | None, list[str]]:
    """md 3 本の本文（ファイル名 → 文字列）から（データ, レポート, errors）を作る。errors があればデータは None。"""
    expl, errors = parse_explanations(sources[EXPLANATIONS_FILE])
    meta, orig, errs = parse_original(sources[ORIGINAL_FILE])
    errors += errs
    verify, errs = parse_verification(sources[VERIFICATION_FILE])
    errors += errs
    exceptions, errs = parse_exceptions(exceptions_text)
    errors += errs
    for label, found in ((EXPL, expl), (ORIG, orig), (VERI, verify)):
        errors += check_numbers(label, found, expected_count)
    rows, errs = cross_check(expl, orig, exceptions)
    errors += errs
    if errors:
        return None, None, errors
    inputs = {name: hashlib.sha256(sources[name].encode("utf-8")).hexdigest() for name in SOURCE_FILES}
    questions = [assemble(expl[no], verify[no]) for no in sorted(expl)]
    data = {"meta": {**meta, "count": len(questions), "inputs": inputs}, "questions": questions}
    no_kaisetsu = sorted(no for no, entry in orig.items() if not entry["has_kaisetsu"])
    return data, render_report(data, rows, exceptions, no_kaisetsu), []


# ---------------------------------------------------------------- レポート


def _report_counts(data: dict, no_kaisetsu: list[int]) -> list[str]:
    questions = data["questions"]
    classes = Counter(q["verify"]["label"] for q in questions)
    notes = [q["no"] for q in questions if q["note"]]
    no_url = [q["no"] for q in questions if not q["verify"]["urls"]]
    names = [(q["no"], t) for q in questions for t in q["verify"]["ref_texts"]]
    lines = ["## 件数", "", f"- 問題数: {len(questions)}", "", "| 裏取りの分類 | 件数 |", "|---|---|"]
    lines += [f"| {label} | {classes.get(label, 0)} |" for label in CLASSES]
    lines += ["", f"- 問題全体への注記（`> ⚠`）: {len(notes)} 問（問{_nums(notes)}）。"
                  "先頭の「⚠」は除いて note に入れた（見出しは画面側で付ける）",
              f"- 出典 URL がない問: {len(no_url)} 問（問{_nums(no_url)}）"]
    lines += [f"- URL ではない出典名（リンクにせず文字で出す・verify.ref_texts）: 問{no}「{t}」" for no, t in names]
    if no_kaisetsu:
        lines.append(f"- {ORIG} に「**解説**」節がない問: 問{_nums(no_kaisetsu)}（問の終わりまでを選択肢の範囲として読んだ）")
    return lines


def _report_exceptions(exceptions: list[dict]) -> list[str]:
    lines = ["## 照合の例外（data/order-exceptions.json）", ""]
    if not exceptions:
        return [*lines, "なし"]
    lines += ["| 問 | 番号 | 種類 | 理由 |", "|---|---|---|---|"]
    for e in sorted(exceptions, key=lambda e: (e["no"], e["n"])):
        lines.append(f"| {e['no']} | {circled(e['n'])} | {CHECK_NAMES[e['check']]} | {e['reason']} |")
    return lines


def _report_lowest(rows: list[dict]) -> list[str]:
    lines = [f"## 選択肢の照合で類似度が低い {LOWEST_ROWS} 件", "",
             f"{EXPL} の k 番と {ORIG} の k 番の類似度（NFKC・空白除去の後の difflib の ratio）。低い順。",
             "", "| 問 | 番号 | 同じ番号との類似度 | 最も似ている番号（類似度） | 他の番号の最大 | 例外 |",
             "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["ratio"], r["no"], r["n"]))[:LOWEST_ROWS]:
        best = "".join(map(circled, r["best"]))
        lines.append(f"| {r['no']} | {circled(r['n'])} | {r['ratio']:.3f} | {best}（{r['best_ratio']:.3f}） | "
                     f"{r['next_ratio']:.3f} | {'あり' if r['exception'] else ''} |")
    return lines


def render_report(data: dict, rows: list[dict], exceptions: list[dict], no_kaisetsu: list[int]) -> str:
    inputs = [f"- `{name}`: `{digest}`" for name, digest in data["meta"]["inputs"].items()]
    parts = [["# 変換レポート", "", "`python3 scripts/convert.py` が書き出す。手で直さない。", "", "## 入力（sha256）", "",
              *inputs], _report_counts(data, no_kaisetsu), _report_exceptions(exceptions), _report_lowest(rows)]
    return "\n\n".join("\n".join(part) for part in parts) + "\n"


# ---------------------------------------------------------------- 書き出し


def to_js(data: dict) -> str:
    """<script src> で読む JS。`<` を \\u003c にして `</script` や `<!--` で抜け出せないようにする。"""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return JS_PREFIX + text + JS_SUFFIX


def write_outputs(outputs: list[tuple[Path, str]]) -> None:
    """全部を一時ファイルに書き終えてから置き換える。途中で失敗したら一時ファイルを消す。"""
    staged: list[tuple[str, Path]] = []
    try:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            staged.append((tmp, path))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.chmod(tmp, 0o644)  # mkstemp は 600 で作る。公開物なので通常のファイルと同じ権限にそろえる
        for tmp, path in staged:
            os.replace(tmp, path)
    finally:
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)


def read_sources(source_dir: Path) -> tuple[dict[str, str], list[str]]:
    """md 3 本を読む。改行は変換しない（sha256 がファイルそのものと一致するように）。"""
    sources: dict[str, str] = {}
    errors: list[str] = []
    for name in SOURCE_FILES:
        path = source_dir / name
        try:
            sources[name] = path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            errors.append(f"入力がない: {path}")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"入力を UTF-8 の文として読めない: {path}（{exc}）")
    return sources, errors


def read_exceptions(path: Path) -> str | None:
    """照合の例外リストの本文。ファイルが無ければ None（例外なし）。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="md 3 本からクイズのデータを作る（検査に落ちたら何も書かない）")
    parser.add_argument("--source", type=Path, default=REPO_ROOT / "source", help="md 3 本のあるフォルダ")
    parser.add_argument("--out-json", type=Path, default=REPO_ROOT / "data" / "questions.json")
    parser.add_argument("--out-js", type=Path, default=REPO_ROOT / "docs" / "questions.js")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "data" / "convert-report.md")
    parser.add_argument("--exceptions", type=Path, default=REPO_ROOT / "data" / "order-exceptions.json")
    return parser.parse_args(argv)


def fail(errors: list[str]) -> int:
    for error in errors:
        print(error, file=sys.stderr)
    print(f"検査で {len(errors)} 件の問題が見つかった。何も書き出していない。", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None, expected_count: int = EXPECTED_COUNT) -> int:
    args = parse_args(argv)
    sources, errors = read_sources(args.source)
    try:
        exceptions_text = read_exceptions(args.exceptions)
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"照合の例外リストを読めない: {args.exceptions}（{exc}）")
    if errors:
        return fail(errors)
    data, report, errors = build(sources, exceptions_text, expected_count)
    if errors:
        return fail(errors)
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        write_outputs([(args.out_json, body), (args.out_js, to_js(data)), (args.report, report)])
    except OSError as exc:
        return fail([f"書き出しに失敗した: {exc}"])
    classes = Counter(q["verify"]["label"] for q in data["questions"])
    summary = "・".join(f"{label} {classes.get(label, 0)}" for label in CLASSES)
    print(f"{data['meta']['count']} 問を書き出した（{summary}）: {args.out_json} / {args.out_js} / {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
