"""scripts/convert.py の検査と書き出しを確かめる。

小さな見本 md（2 問）で「落ちるべきものが落ちる」「癖のある書き方を読める」を見る。
実データでの確認は tests/test_convert_real.py。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import convert
from md_sources import parse_original

COUNT = 2

EXPL_MD = """# テスト用 不正解の解説

前書き（最初の問より前の文は読まない）。

## 問1

一段落目の問題文。

二段落目の問題文。

**正解:** ②猫は完全肉食動物である。

> ⚠ 問1 への注記。

### ① 犬は草だけを食べる。

犬は雑食に近い。

### ③ ウサギは肉を食べる。

ウサギは草食である。

### ④ハムスターは昼に活動する。

ハムスターは夜行性である。

### ⑤ インコは単独で暮らす。

インコは群れで暮らす。

## 問2

日本の首都を選ぶ。

**正解:** ①東京

### ② 大阪

大阪は首都ではない。

### ③ 名古屋

名古屋は首都ではない。

### ④ 札幌

札幌は首都ではない。

### ⑤ 福岡

福岡は首都ではない。
"""

ORIG_MD = """# テスト用 全問

出典: https://example.com/workbooks/abc（作成者: 作者A）
取得日: 2026-11-14

## 問1

一段落目の問題文。

- ① 犬は草だけを食べる。
- **[正解]** ②猫は完全肉食動物である。
- ③ ウサギは肉を食べる。
- ④ハムスターは昼に活動する。
- ⑤ インコは単独で暮らす。

**解説**

- ① 解説節の行は選択肢として読まない。
- **[正解]** ③ 解説節の印も読まない。

## 問2

日本の首都を選ぶ。

- **[正解]** ① 東京
- ② 大阪
- ③ 名古屋
- ④ 札幌
- ⑤ 福岡

**解説**

① 正答。
"""

URL_A = "https://example.com/a"
URL_LAW = "https://laws.e-gov.go.jp/api/1/articles;lawNum=平成十八年法律第四十九号;article=2"
VERI_MD = f"""# テスト用 裏取り

| 問 | 分類 | 根拠・理由 | 出典 URL |
|---|---|---|---|
| 1 | 出典で確認 | 根拠その1。 | {URL_A} ／ {URL_LAW} |
| 2 | 疑いあり | 根拠その2。 | — |
"""

SWAPPED_ORIG = ORIG_MD.replace("- ③ ウサギは肉を食べる。\n- ④ハムスターは昼に活動する。",
                               "- ③ハムスターは昼に活動する。\n- ④ ウサギは肉を食べる。")


def sources(expl: str = EXPL_MD, orig: str = ORIG_MD, veri: str = VERI_MD) -> dict[str, str]:
    return {convert.EXPLANATIONS_FILE: expl, convert.ORIGINAL_FILE: orig, convert.VERIFICATION_FILE: veri}


def build(exceptions: list | None = None, count: int = COUNT, **texts):
    text = None if exceptions is None else json.dumps(exceptions, ensure_ascii=False)
    return convert.build(sources(**texts), text, expected_count=count)


def errors_of(**kwargs) -> str:
    data, report, errors = build(**kwargs)
    assert data is None and report is None and errors
    return "\n".join(errors)


def replaced(text: str, old: str, new: str) -> str:
    assert old in text  # 置き換えが空振りしたら、見本の作りが変わっている
    return text.replace(old, new, 1)


def parse_js(js: str):
    assert js.startswith(convert.JS_PREFIX) and js.endswith(convert.JS_SUFFIX)
    return json.loads(js[len(convert.JS_PREFIX):-len(convert.JS_SUFFIX)])


# ---------------------------------------------------------------- 落ちるべきもの


def test_four_choices_in_explanations_fails():
    expl = replaced(EXPL_MD, "### ⑤ インコは単独で暮らす。\n\nインコは群れで暮らす。\n\n", "")
    assert "問1: 不正解の選択肢の見出し（###）が 3 個（4 個のはず）" in errors_of(expl=expl)


def test_four_choice_lines_in_original_fails():
    orig = replaced(ORIG_MD, "- ⑤ インコは単独で暮らす。\n", "")
    assert "問1: 「**解説**」より前の選択肢の行が 4 個（5 個のはず）" in errors_of(orig=orig)


def test_two_correct_markers_fail():
    orig = replaced(ORIG_MD, "- ③ ウサギは肉を食べる。", "- **[正解]** ③ ウサギは肉を食べる。")
    assert "問1: [正解] の印が 2 個（1 個のはず）" in errors_of(orig=orig)


def test_two_answer_lines_fail():
    expl = replaced(EXPL_MD, "**正解:** ①東京", "**正解:** ①東京\n\n**正解:** ② 大阪")
    assert "問2: 正解の行（**正解:**）が 2 個（1 個のはず）" in errors_of(expl=expl)


def test_missing_verification_row_fails():
    veri = replaced(VERI_MD, "| 2 | 疑いあり | 根拠その2。 | — |\n", "")
    assert "裏取り結果.md: 問がない（2 問のはず）: 問2" in errors_of(veri=veri)


def test_duplicate_verification_row_fails():
    veri = VERI_MD + "| 2 | 出典で確認 | 2 つ目の行。 | — |\n"
    assert "裏取り結果.md 問2: 行が 2 つある" in errors_of(veri=veri)


def test_empty_wrong_explanation_fails():
    expl = replaced(EXPL_MD, "ウサギは草食である。\n\n", "")
    assert "問1 ③: 不正解の解説が空" in errors_of(expl=expl)


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x",
                                 "ftp://example.com/a", "example.com/a", "//example.com/a", "https://"])
def test_non_http_url_fails(bad):
    veri = replaced(VERI_MD, URL_A, bad)
    assert f"http:// か https:// で始まる URL でない出典「{bad}」" in errors_of(veri=veri)


def test_swapped_order_without_exception_fails():
    errors = errors_of(orig=SWAPPED_ORIG)
    assert "問1 ③: 不正解の解説.md の③に最も似ている 全141問.md の選択肢が ④" in errors
    assert "問1 ④:" in errors


def test_tie_in_similarity_fails():
    orig = replaced(ORIG_MD, "- ③ 名古屋", "- ③ 大阪")
    assert "問2 ②: 不正解の解説.md の②に最も似ている 全141問.md の選択肢が ②③（1.000）" in errors_of(orig=orig)


def test_stale_exception_fails():
    errors = errors_of(exceptions=[{"no": 1, "n": 5, "reason": "照合は通るので使われない例外"}])
    assert "問1 ⑤（類似度）の例外が使われていない" in errors


def test_unknown_class_fails():
    veri = replaced(VERI_MD, "| 疑いあり |", "| たぶん正しい |")
    assert "分類「たぶん正しい」が 3 種類" in errors_of(veri=veri)


def test_answer_mismatch_needs_exception():
    orig = replaced(replaced(ORIG_MD, "- **[正解]** ① 東京", "- ① 東京"), "- ⑤ 福岡", "- **[正解]** ⑤ 福岡")
    assert "問2: 正解の番号が食い違う（不正解の解説.md は①・全141問.md は⑤）" in errors_of(orig=orig)
    data, _, errors = build(orig=orig, exceptions=[{"no": 2, "n": 1, "check": "answer", "reason": "印の付け誤り"}])
    assert errors == [] and data["questions"][1]["answer"] == 1
    # n は採る正解（不正解の解説.md の番号）。違う番号を書いた例外は使われずに落ちる
    wrong = [{"no": 2, "n": 5, "check": "answer", "reason": "番号を取り違えた例外"}]
    assert "問2 ⑤（正解の印の食い違い）の例外が使われていない" in errors_of(orig=orig, exceptions=wrong)


def test_number_typo_needs_exception():
    orig = replaced(ORIG_MD, "- ④ 札幌", "- ③ 札幌")
    assert "問2: 選択肢の番号が①〜⑤の 1 つずつになっていない（①②③③⑤）" in errors_of(orig=orig)
    data, _, errors = build(orig=orig, exceptions=[{"no": 2, "n": 4, "check": "number", "reason": "4 行目の誤記"}])
    assert errors == [] and data["questions"][1]["choices"][3]["text"] == "札幌"
    # 番号が合っている行への読み替えは、使われない例外として落ちる
    stale = [{"no": 2, "n": 4, "check": "number", "reason": "誤記のない行"}]
    assert "問2 ④（番号の誤記）の例外が使われていない" in errors_of(exceptions=stale)


def test_note_outside_expected_place_fails():
    expl = replaced(EXPL_MD, "ウサギは草食である。\n", "ウサギは草食である。\n\n> ⚠ 迷子の注記\n")
    assert "注記（> の行）が正解の行の直後以外にある" in errors_of(expl=expl)


def test_expected_count_mismatch_fails():
    assert "不正解の解説.md: 問がない（3 問のはず）: 問3" in errors_of(count=3)


def test_missing_source_header_fails():
    orig = replaced(ORIG_MD, "出典: https://example.com/workbooks/abc（作成者: 作者A）\n", "")
    assert "「出典: URL（作成者: 名前）」の行が 0 個" in errors_of(orig=orig)


@pytest.mark.parametrize("entry, words", [
    ({"no": 1, "n": 3}, "reason（理由）が空"),
    ({"no": 1, "n": 6, "reason": "x"}, "n が 1〜5 の整数でない"),
    ({"no": 1, "n": 3, "check": "other", "reason": "x"}, "check が"),
    ({"no": 1, "n": 3, "reason": "x", "extra": 1}, "知らない項目がある（extra）"),
])
def test_malformed_exception_fails(entry, words):
    assert words in errors_of(exceptions=[entry])


# ---------------------------------------------------------------- 読めるべきもの


def test_fixture_builds():
    data, report, errors = build()
    assert errors == []
    assert data["meta"]["source_url"] == "https://example.com/workbooks/abc"
    assert data["meta"]["author"] == "作者A"
    assert data["meta"]["count"] == 2
    q1, q2 = data["questions"]
    assert q1["stem"] == "一段落目の問題文。\n\n二段落目の問題文。"
    assert [c["n"] for c in q1["choices"]] == [1, 2, 3, 4, 5]
    assert [c["expl"] is None for c in q1["choices"]] == [False, True, False, False, False]
    assert q1["choices"][2]["expl"] == "ウサギは草食である。"
    assert "# 変換レポート" in report


def test_circled_digit_without_space():
    data, _, _ = build()
    q1, q2 = data["questions"]
    assert q1["answer"] == 2 and q1["choices"][1]["text"] == "猫は完全肉食動物である。"
    assert q1["choices"][3]["text"] == "ハムスターは昼に活動する。"
    assert q2["answer"] == 1 and q2["choices"][0]["text"] == "東京"


def test_choice_lines_inside_kaisetsu_are_ignored():
    _, questions, errors = parse_original(ORIG_MD)
    assert errors == []
    texts = [text for _, text, _ in questions[1]["choices"]]
    assert len(texts) == 5 and not any("解説節" in t for t in texts)
    assert [mark for _, _, mark in questions[1]["choices"]] == [False, True, False, False, False]


def test_note_is_captured_without_warning_mark():
    data, _, _ = build()
    assert data["questions"][0]["note"] == "問1 への注記。"
    assert data["questions"][1]["note"] is None


def test_urls_split_and_dash_means_none():
    data, _, _ = build()
    v1, v2 = (q["verify"] for q in data["questions"])
    assert v1 == {"class": "confirmed", "label": "出典で確認", "reason": "根拠その1。",
                  "urls": [URL_A, URL_LAW], "ref_texts": []}
    assert v2["class"] == "doubtful" and v2["urls"] == [] and v2["ref_texts"] == []


def test_source_name_without_url_is_kept_as_text():
    veri = replaced(VERI_MD, URL_A, "環境省マニュアル（カメレオンの節）")
    data, _, errors = build(veri=veri)
    assert errors == []
    assert data["questions"][0]["verify"]["urls"] == [URL_LAW]
    assert data["questions"][0]["verify"]["ref_texts"] == ["環境省マニュアル（カメレオンの節）"]


def test_swapped_order_passes_with_reviewed_exception():
    exceptions = [{"no": 1, "n": 3, "check": "similarity", "reason": "見本で入れ替えた③"},
                  {"no": 1, "n": 4, "reason": "見本で入れ替えた④（check を省くと類似度）"}]
    data, report, errors = build(orig=SWAPPED_ORIG, exceptions=exceptions)
    assert errors == []
    assert "見本で入れ替えた③" in report and "| 1 | ④ | 類似度 |" in report


def test_to_js_escapes_script_breakers():
    data = {"s": "</script><!--     &"}
    js = convert.to_js(data)
    assert "<" not in js and " " not in js and " " not in js
    assert parse_js(js) == data


# ---------------------------------------------------------------- CLI と書き出し


def fixture_argv(tmp_path: Path, **texts) -> tuple[list[str], Path, Path]:
    src = tmp_path / "source"
    src.mkdir()
    for name, text in sources(**texts).items():
        (src / name).write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    argv = ["--source", str(src), "--out-json", str(out / "q.json"), "--out-js", str(out / "docs" / "q.js"),
            "--report", str(out / "report.md"), "--exceptions", str(tmp_path / "なし.json")]
    return argv, src, out


def test_main_writes_three_outputs(tmp_path):
    argv, src, out = fixture_argv(tmp_path)
    assert convert.main(argv, expected_count=COUNT) == 0
    data = json.loads((out / "q.json").read_text(encoding="utf-8"))
    assert parse_js((out / "docs" / "q.js").read_text(encoding="utf-8")) == data
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# 変換レポート")
    for name, digest in data["meta"]["inputs"].items():
        assert hashlib.sha256((src / name).read_bytes()).hexdigest() == digest
    assert sorted(p.name for p in out.rglob("*")) == ["docs", "q.js", "q.json", "report.md"]


def test_failure_writes_nothing(tmp_path, capsys):
    argv, _, out = fixture_argv(tmp_path, veri=replaced(VERI_MD, URL_A, "javascript:alert(1)"))
    assert convert.main(argv, expected_count=COUNT) == 1
    assert not out.exists()
    assert "何も書き出していない" in capsys.readouterr().err


def test_failure_keeps_previous_outputs(tmp_path):
    argv, _, out = fixture_argv(tmp_path, expl=replaced(EXPL_MD, "ウサギは草食である。\n\n", ""))
    out.mkdir()
    (out / "q.json").write_text("前回の中身", encoding="utf-8")
    assert convert.main(argv, expected_count=COUNT) == 1
    assert (out / "q.json").read_text(encoding="utf-8") == "前回の中身"
    assert [p.name for p in out.iterdir()] == ["q.json"]


def test_missing_source_file_fails(tmp_path, capsys):
    argv, src, out = fixture_argv(tmp_path)
    (src / convert.VERIFICATION_FILE).unlink()
    assert convert.main(argv, expected_count=COUNT) == 1
    assert not out.exists()
    assert "入力がない" in capsys.readouterr().err

