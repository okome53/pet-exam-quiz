"""アプリの JS（docs/core.js の純関数と、docs/ の公開物の形）を確かめる。

core.js をそのまま node で読み込み、式を評価した値を JSON で受け取る（~/Projects/ipa-fe-study/tests/test_app_core.py と同じ仕組み）。
採点と解説の対応は、実データ 141 問 × 種 5 つ × 画面の位置 5 つで、Python 側で data/questions.json から独立に作った期待値と比べる。
画面側（app.js）は `node --check` と文字列の検査だけ。node が無い環境では JS を動かす確認を飛ばす。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
CORE_PATH = DOCS / "core.js"
APP_PATH = DOCS / "app.js"
DATA_JS_PATH = DOCS / "questions.js"
INDEX_PATH = DOCS / "index.html"

# 純関数のファイルに置かないもの（DOM・保存・現在時刻・乱数・タイマー）
IMPURE_WORDS = ("document", "window", "localStorage", "Date.now", "new Date()", "Math.random", "setInterval",
                "setTimeout")
# 文字を HTML として解釈させる書き方・文字列をコードとして動かす書き方
UNSAFE_WORDS = ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(", "new Function")

# 種を固定した乱数（Park–Miller）。ランダム順を同じ結果で再現するため
SEEDED_RNG = "(() => { let s = 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; })()"
SEEDS = (1, 7, 42, 2024, 99991)
CIRCLED = "①②③④⑤"
LETTERS = "ABCDE"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無いので JS の確認を飛ばす")
    return node


def run_core(tmp_path: Path, expr: str, with_data: bool = False):
    parts = [DATA_JS_PATH.read_text(encoding="utf-8")] if with_data else []
    parts += [CORE_PATH.read_text(encoding="utf-8"), f"console.log(JSON.stringify({expr}));"]
    script = tmp_path / "run.js"
    script.write_text("\n".join(parts), encoding="utf-8")
    result = subprocess.run([_node(), str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return json.loads((REPO_ROOT / "data" / "questions.json").read_text(encoding="utf-8"))["questions"]


# ---- 純関数 ----
def test_core_is_pure() -> None:
    core = CORE_PATH.read_text(encoding="utf-8")
    assert [w for w in IMPURE_WORDS if w in core] == []


def test_shuffle_is_a_reproducible_permutation(tmp_path: Path) -> None:
    items = list(range(1, 21))
    call = f"shuffle({json.dumps(items)}, {SEEDED_RNG})"
    first, second, original = run_core(tmp_path, f"(() => {{ const a = {json.dumps(items)};"
                                                 f" return [{call}, {call}, (shuffle(a, {SEEDED_RNG}), a)]; }})()")
    assert first == second
    assert sorted(first) == items and first != items
    assert original == items   # 元の配列は書き換えない


QS = [{"no": n} for n in range(1, 11)]


@pytest.mark.parametrize(("opts", "expected"), [
    ({"from": 1, "to": 10, "order": "original"}, list(range(1, 11))),
    ({"from": 3, "to": 5, "order": "original"}, [3, 4, 5]),
    ({"from": 7, "to": 7, "order": "original"}, [7]),
    ({"from": 11, "to": 20, "order": "original"}, []),
])
def test_build_queue_range(tmp_path: Path, opts: dict, expected: list[int]) -> None:
    assert run_core(tmp_path, f"buildQueue({json.dumps(QS)}, {json.dumps(opts)}, {SEEDED_RNG})") == expected


def test_build_queue_random_keeps_the_range(tmp_path: Path) -> None:
    opts = {"from": 2, "to": 9, "order": "random"}
    call = f"buildQueue({json.dumps(QS)}, {json.dumps(opts)}, {SEEDED_RNG})"
    first, second = run_core(tmp_path, f"[{call}, {call}]")
    assert first == second
    assert sorted(first) == list(range(2, 10)) and first != list(range(2, 10))


def test_choice_label_and_order(tmp_path: Path) -> None:
    got = run_core(tmp_path, "[[0, 1, 2, 3, 4].map(p => choiceLabel(p, 'original')),"
                             " [0, 1, 2, 3, 4].map(p => choiceLabel(p, 'random')),"
                             " choiceOrder({choices: [1, 2, 3, 4, 5].map(n => ({n}))}, 'original', () => 0)]")
    assert got == [list(CIRCLED), list(LETTERS), [1, 2, 3, 4, 5]]


def test_grade(tmp_path: Path) -> None:
    assert run_core(tmp_path, "[grade({answer: 4}, 4), grade({answer: 4}, 3), grade({answer: 4}, null)]") == [
        True, False, False]


def test_row_title(tmp_path: Path) -> None:
    got = run_core(tmp_path, "[rowTitle({label: '③', origLabel: '③'}, 'original'),"
                             " rowTitle({label: 'A', origLabel: '③'}, 'random')]")
    assert got == ["③", "A（元の③）"]


def test_paragraphs(tmp_path: Path) -> None:
    got = run_core(tmp_path, "[paragraphs('一。\\n\\n二。\\n \\n三。'), paragraphs('一行\\n続き'), paragraphs(''),"
                             " paragraphs(null), paragraphs('\\n\\n一。\\n\\n')]")
    assert got == [["一。", "二。", "三。"], ["一行\n続き"], [], [], ["一。"]]


@pytest.mark.parametrize(("from_text", "to_text", "expected"), [
    ("1", "141", {"ok": True, "from": 1, "to": 141}),
    (" 12 ", "３０", {"ok": True, "from": 12, "to": 30}),   # 前後の空白と全角数字は受ける
    ("5", "5", {"ok": True, "from": 5, "to": 5}),
    ("", "141", "from"), ("0", "141", "from"), ("1.5", "141", "from"), ("-1", "141", "from"), ("abc", "141", "from"),
    ("1", "142", "to"), ("1", "", "to"),
    ("30", "12", "from"),   # はじめ ＞ おわり
])
def test_parse_range(tmp_path: Path, from_text: str, to_text: str, expected) -> None:
    got = run_core(tmp_path, f"parseRange({json.dumps(from_text)}, {json.dumps(to_text)}, 1, 141)")
    if isinstance(expected, dict):
        assert got == expected
    else:
        assert got["ok"] is False and got["field"] == expected and got["error"]


def test_normalize_settings(tmp_path: Path) -> None:
    default = {"mode": "study", "order": "original", "choiceOrder": "original", "from": 1, "to": 141,
               "wrongOnly": False}
    good = {"mode": "test", "order": "random", "choiceOrder": "random", "from": 10, "to": 20, "wrongOnly": True}
    cases = ["null", "[]", "'x'", json.dumps(good), json.dumps({**good, "order": "x"}),
             json.dumps({**good, "from": 30}), json.dumps({**good, "to": 999}), json.dumps({**good, "from": "10"}),
             json.dumps({**good, "mode": "exam"}), json.dumps({**good, "wrongOnly": "true"})]
    got = run_core(tmp_path, f"[{', '.join(cases)}].map(s => normalizeSettings(s, 1, 141))")
    assert got == [default, default, default, good, {**good, "order": "original"},
                   {**good, "from": 1, "to": 141}, {**good, "from": 1, "to": 141}, {**good, "from": 1, "to": 141},
                   {**good, "mode": "study"}, {**good, "wrongOnly": False}]


# ---- テストモード ----
POOL = list(range(5, 31))   # 範囲で絞った後の問番号（元の順番）


def test_build_test_original_takes_the_head(tmp_path: Path) -> None:
    got = run_core(tmp_path, f"[buildTest({POOL}, 10, 'original', {SEEDED_RNG}),"
                             f" buildTest([3, 4, 5], 10, 'original', {SEEDED_RNG}), buildTest([], 10, 'random', {SEEDED_RNG})]")
    assert got == [POOL[:10], [3, 4, 5], []]   # 足りなければある分だけ


def test_build_test_random_has_no_duplicates(tmp_path: Path) -> None:
    exprs = [f"buildTest({POOL}, 10, 'random', (() => {{ let s = {seed}; return () => (s = (s * 16807) % 2147483647)"
             f" / 2147483647; }})())" for seed in SEEDS]
    results = run_core(tmp_path, f"[{', '.join(exprs)}]")
    for got in results:
        assert len(got) == 10 and len(set(got)) == 10 and set(got) <= set(POOL)
    assert any(got != POOL[:10] for got in results)
    assert len({tuple(g) for g in results}) > 1   # 種ごとに違う 10 問になる
    small = run_core(tmp_path, f"buildTest([7, 8, 9], 10, 'random', {SEEDED_RNG})")
    assert sorted(small) == [7, 8, 9]


def test_grade_test(tmp_path: Path) -> None:
    got = run_core(tmp_path, "gradeTest([{no: 3, answer: 2}, {no: 9, answer: 5}, {no: 1, answer: 1}], [2, 4, null])")
    assert got == {"total": 3, "correct": 1, "results": [
        {"no": 3, "pickedN": 2, "ok": True}, {"no": 9, "pickedN": 4, "ok": False}, {"no": 1, "pickedN": None, "ok": False}]}


# ---- 解答の記録 ----
def test_record_answer_counts_and_keeps_the_original(tmp_path: Path) -> None:
    got = run_core(tmp_path, """(() => {
      const r0 = {};
      const r1 = recordAnswer(r0, 12, false, 100);
      const r2 = recordAnswer(r1, 12, true, 200);
      const r3 = recordAnswer(r2, 5, true, 300);
      const r4 = recordAnswer(r3, 12, false, 400);
      return [r0, r1, r2, r4];
    })()""")
    r0, r1, r2, r4 = got
    assert r0 == {}   # 元の記録は書き換えない
    assert r1 == {"12": {"n": 1, "ok": 0, "last": False, "at": 100}}
    assert r2 == {"12": {"n": 2, "ok": 1, "last": True, "at": 200}}
    assert r4 == {"12": {"n": 3, "ok": 1, "last": False, "at": 400}, "5": {"n": 1, "ok": 1, "last": True, "at": 300}}


def test_stats(tmp_path: Path) -> None:
    records = {"1": {"n": 2, "ok": 1, "last": True, "at": 1}, "2": {"n": 1, "ok": 0, "last": False, "at": 1},
               "3": {"n": 3, "ok": 3, "last": True, "at": 1}, "999": {"n": 1, "ok": 0, "last": False, "at": 1}}
    got = run_core(tmp_path, f"[stats({json.dumps(records)}, [1, 2, 3, 4]), stats({{}}, [1, 2, 3])]")
    # データに無い問（999）の記録は数えない
    assert got[0] == {"total": 4, "solved": 3, "lastOk": 2, "wrong": 1, "rate": 67}
    assert got[1] == {"total": 3, "solved": 0, "lastOk": 0, "wrong": 0, "rate": None}


def test_wrong_only_filters_by_the_last_answer(tmp_path: Path) -> None:
    records = {"2": {"n": 1, "ok": 0, "last": False, "at": 1}, "4": {"n": 2, "ok": 1, "last": True, "at": 1},
               "6": {"n": 3, "ok": 1, "last": False, "at": 1}, "12": {"n": 1, "ok": 0, "last": False, "at": 1}}
    opts = {"from": 1, "to": 10, "order": "original", "wrongOnly": True}
    got = run_core(tmp_path, f"[buildQueue({json.dumps(QS)}, {json.dumps(opts)}, {SEEDED_RNG}, {json.dumps(records)}),"
                             f" buildQueue({json.dumps(QS)}, {json.dumps(opts)}, {SEEDED_RNG}, {{}}),"
                             f" buildQueue({json.dumps(QS)}, {json.dumps({**opts, 'wrongOnly': False})}, {SEEDED_RNG},"
                             f" {json.dumps(records)})]")
    # 12 は範囲の外・4 は最後に正解・解いていない問は入らない
    assert got == [[2, 6], [], list(range(1, 11))]


GOOD_RECORD = {"n": 2, "ok": 1, "last": True, "at": 1700000000000}


@pytest.mark.parametrize(("raw", "good_keys", "bad_count"), [
    ("null", [], 0),
    ("undefined", [], 0),
    ("{}", [], 0),
    (json.dumps({"3": GOOD_RECORD}), ["3"], 0),
    ("'{壊れた JSON'", [], 1),          # JSON として読めなかった文字列は全体を退避
    ("[1, 2]", [], 1),
    ("42", [], 1),
    (json.dumps({"3": GOOD_RECORD, "x": GOOD_RECORD, "0": GOOD_RECORD, "03": GOOD_RECORD}), ["3"], 3),
    (json.dumps({"3": {**GOOD_RECORD, "ok": 3}}), [], 1),          # 正解回数 ＞ 回数
    (json.dumps({"3": {**GOOD_RECORD, "n": 0, "ok": 0}}), [], 1),
    (json.dumps({"3": {**GOOD_RECORD, "n": 1.5}}), [], 1),
    (json.dumps({"3": {**GOOD_RECORD, "last": "true"}}), [], 1),
    (json.dumps({"3": {**GOOD_RECORD, "at": "昨日"}}), [], 1),
    (json.dumps({"3": {**GOOD_RECORD, "extra": 1}}), [], 1),
    (json.dumps({"3": None, "4": [], "5": GOOD_RECORD}), ["5"], 2),
])
def test_split_records_keeps_bad_entries(tmp_path: Path, raw: str, good_keys: list[str], bad_count: int) -> None:
    got = run_core(tmp_path, f"splitRecords({raw})")
    assert sorted(got["good"]) == good_keys
    assert all(v == GOOD_RECORD for v in got["good"].values())
    assert len(got["bad"]) == bad_count


def test_split_records_does_not_drop_the_bad_values(tmp_path: Path) -> None:
    raw = {"7": GOOD_RECORD, "8": {"n": "壊れ"}, "__proto__": {"x": 1}}
    got = run_core(tmp_path, f"splitRecords(JSON.parse({json.dumps(json.dumps(raw))}))")
    assert got["good"] == {"7": GOOD_RECORD}
    assert sorted(got["bad"], key=lambda b: b["no"]) == [{"no": "8", "value": {"n": "壊れ"}},
                                                         {"no": "__proto__", "value": {"x": 1}}]
    # 文字列ごと読めなかった場合は、その文字列をそのまま退避する
    assert run_core(tmp_path, "splitRecords('{壊れ')") == {"good": {}, "bad": ["{壊れ"]}


# ---- 実データ 141 問: 画面の位置で選んだ答えの判定と解説の対応がずれないこと ----
ALL_CASES_EXPR = """(() => {
  const out = [];
  const runs = [['original', 0]].concat(%s.map(seed => ['random', seed]));
  for (const [mode, seed] of runs) {
    let s = seed;
    const rng = () => (s = (s * 16807) %% 2147483647) / 2147483647;
    for (const q of QUESTIONS.questions) {
      const order = choiceOrder(q, mode, rng);
      const picks = order.map((n, pos) => {
        const rows = explanationRows(q, order, order[pos], mode);
        return { grade: grade(q, order[pos]), rows: rows.map(r => [r.label, r.n, r.origLabel, r.isCorrect, r.isPicked,
          r.kind, r.text, r.body, r.badge ? r.badge.label : null, Object.keys(r).sort().join(',')]) };
      });
      const before = explanationRows(q, order, null, mode).map(r => r.isPicked);
      out.push({ mode, seed, no: q.no, order, picks, before });
    }
  }
  return out;
})()"""

ROW_KEYS = "body,isCorrect,isPicked,kind,label,n,origLabel,text"


def _check_question_case(case: dict, q: dict) -> None:
    order, mode = case["order"], case["mode"]
    assert sorted(order) == [1, 2, 3, 4, 5]
    if mode == "original":
        assert order == [1, 2, 3, 4, 5]
    assert case["before"] == [False] * 5   # 解答前はどれも選んでいない
    choices = {c["n"]: c for c in q["choices"]}
    for pos, pick in enumerate(case["picks"]):
        picked_n = order[pos]
        assert pick["grade"] is (picked_n == q["answer"])
        rows = pick["rows"]
        assert len(rows) == 5
        assert sum(r[3] for r in rows) == 1 and sum(r[4] for r in rows) == 1
        for i, (label, n, orig, is_correct, is_picked, kind, text, body, badge, keys) in enumerate(rows):
            assert n == order[i]
            assert label == (LETTERS[i] if mode == "random" else CIRCLED[i])
            assert orig == CIRCLED[n - 1]
            assert is_picked is (i == pos)
            assert is_correct is (n == q["answer"])
            assert text == choices[n]["text"]
            if is_correct:
                # 正解の行は根拠の文だけで、分類の札は出さない（2026-11-17 本人判断）
                assert (kind, body, badge) == ("correct", q["verify"]["reason"], None)
                assert keys == ROW_KEYS
            else:
                assert (kind, body, badge) == ("wrong", choices[n]["expl"], None)
                assert body and keys == ROW_KEYS


def test_every_question_every_position_maps_grade_and_explanations(tmp_path: Path, questions: list[dict]) -> None:
    cases = run_core(tmp_path, ALL_CASES_EXPR % json.dumps(list(SEEDS)), with_data=True)
    by_no = {q["no"]: q for q in questions}
    assert len(cases) == len(questions) * (1 + len(SEEDS)) == 141 * 6
    for case in cases:
        _check_question_case(case, by_no[case["no"]])
    shuffled = sum(c["order"] != [1, 2, 3, 4, 5] for c in cases if c["mode"] == "random")
    assert shuffled > 0.7 * 141 * len(SEEDS)   # ランダムが実際に並べ替えている（恒等の並びは 1/120 の確率）


# ---- 画面側と公開物の形 ----
def test_app_js_parses() -> None:
    result = subprocess.run([_node(), "--check", str(APP_PATH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_scripts_share_the_page_without_name_clashes(tmp_path: Path) -> None:
    """index.html は questions.js・core.js・app.js を順に読む。3 つは同じ大域で動くので、宣言がぶつからないこと。"""
    joined = tmp_path / "joined.js"
    joined.write_text("\n".join(p.read_text(encoding="utf-8") for p in (DATA_JS_PATH, CORE_PATH, APP_PATH)),
                      encoding="utf-8")
    result = subprocess.run([_node(), "--check", str(joined)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", [CORE_PATH, APP_PATH], ids=lambda p: p.name)
def test_no_html_injection_or_dynamic_code(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert [w for w in UNSAFE_WORDS if w in text] == []


@pytest.mark.parametrize("path", [CORE_PATH, APP_PATH], ids=lambda p: p.name)
def test_source_urls_are_not_shown(path: Path) -> None:
    """出典の URL と出典名は画面に出さない（2026-11-17 本人判断）。データには残っている。"""
    text = path.read_text(encoding="utf-8")
    assert ".urls" not in text and "ref_texts" not in text


def test_index_html_head() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert '<meta name="referrer" content="no-referrer">' in html
    assert ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'self\';'
            ' style-src \'self\'; img-src \'self\'; base-uri \'none\'; form-action \'none\'">') in html
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in html
    assert "<title>愛玩動物飼養管理士2級 問題演習</title>" in html


def test_index_html_has_no_inline_code_or_root_paths() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts == ['<script src="questions.js">', '<script src="core.js">', '<script src="app.js">']
    assert "style=" not in html and "<style" not in html
    assert re.search(r"""\bon[a-z]+\s*=""", html) is None   # onclick= などのインラインの処理
    # GitHub Pages ではサイトが /pet-exam-quiz/ の下に載るので、/ で始まる参照は壊れる
    assert re.findall(r"""(?:src|href)="/""", html) == []


def test_ids_used_by_app_exist_in_index_html() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    app = APP_PATH.read_text(encoding="utf-8")
    ids = re.findall(r"""\bid="([^"]+)\"""", html)
    assert len(ids) == len(set(ids)), "index.html の id が重複している"
    used = set(re.findall(r"""(?:byId|getElementById)\(\s*'([^']+)'\s*\)""", app))
    used |= set(re.findall(r"""SCREENS = \[([^\]]*)\]""", app)[0].replace("'", "").replace(" ", "").split(","))
    assert used and sorted(used - set(ids)) == []
    names = set(re.findall(r"""(?:setRadio|radioValue)\('([^']+)'""", app))
    assert names and all(f'name="{n}"' in html for n in names)


def test_no_robots_txt_and_nojekyll_present() -> None:
    assert not (DOCS / "robots.txt").exists()   # noindex の meta だけにする（2026-11-17 本人判断）
    assert (DOCS / ".nojekyll").exists()


def test_storage_keys_are_namespaced() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    assert "const SETTINGS_KEY = 'pet-exam-quiz:v1:settings';" in app
    assert "const RECORDS_KEY = 'pet-exam-quiz:v1:records';" in app
    assert "const RECORDS_BAD_KEY = 'pet-exam-quiz:v1:records-bad';" in app
    keys = re.findall(r"""'(pet-exam-quiz:[^']*)'""", app)
    assert keys and all(k.startswith("pet-exam-quiz:") for k in keys)


def test_no_browser_dialogs() -> None:
    """記録のリセットは画面内の 2 段階ボタンで行い、ブラウザの確認ダイアログは使わない。"""
    app = APP_PATH.read_text(encoding="utf-8")
    assert re.search(r"""\b(?:confirm|alert|prompt)\(""", app) is None
