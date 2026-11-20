"""予想問題（data/mock/*.json → docs/mock.js）の検査と、4 択の問で採点・解説の対応がずれないことを確かめる。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import build_mock

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "data" / "mock"
MOCK_JS = REPO_ROOT / "docs" / "mock.js"
CORE_JS = REPO_ROOT / "docs" / "core.js"


def _question(answer: int = 2) -> dict:
    return {
        "no": 1, "field": "第1分野", "stem": "問題文", "answer": answer,
        "choices": [{"n": n, "text": f"選択肢{n}", "expl": None if n == answer else f"解説{n}"} for n in range(1, 5)],
        "verify": {"class": "confirmed", "label": "出典で確認", "reason": "根拠", "urls": ["https://example.org/"],
                   "ref_texts": []},
        "note": None,
    }


def _set(**over) -> dict:
    return {"id": "mock9", "title": "予想問題⑨", "questions": [_question()], **over}


def test_good_set_passes() -> None:
    assert build_mock.check_set("x.json", _set()) == []


@pytest.mark.parametrize("break_it, message", [
    (lambda q: q["choices"][1].update(expl="正解に解説"), "正解の選択肢 2 に解説がある"),
    (lambda q: q["choices"][0].update(expl=None), "不正解の選択肢 1 に解説がない"),
    (lambda q: q["choices"][2].update(n=4), "選択肢 3 の番号が 4"),
    (lambda q: q.update(answer=5), "正解 5 が選択肢の番号にない"),
    (lambda q: q["verify"].update(label="疑いあり"), "分類 'confirmed' と札 '疑いあり' が合わない"),
    (lambda q: q["verify"].update(urls=[]), "「出典で確認」なのに出典の URL がない"),
    (lambda q: q["verify"].update(urls=["http://example.org/"]), "https の URL の配列になっていない"),
    (lambda q: q.update(verify=None), "verify の項目が"),
    (lambda q: q.update(note=""), "note は null か空でない文"),
])
def test_broken_question_is_reported(break_it, message: str) -> None:
    s = _set()
    break_it(s["questions"][0])
    errors = build_mock.check_set("x.json", s)
    assert any(message in e for e in errors), errors


@pytest.mark.parametrize("over, message", [
    ({"id": "main"}, "main は使えない"),
    ({"id": "Mock-1"}, "英小文字で始まる"),
    ({"questions": [dict(_question(), no=2)]}, "1 番目の問の番号が 2"),
])
def test_broken_set_is_reported(over: dict, message: str) -> None:
    errors = build_mock.check_set("x.json", _set(**over))
    assert any(message in e for e in errors), errors


def test_nothing_is_written_when_a_check_fails(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    bad = _set()
    bad["questions"][0]["answer"] = 9
    (src / "a.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "mock.js"
    assert build_mock.main(["--src", str(src), "--out-js", str(out)]) == 1
    assert not out.exists()


def test_duplicate_ids_are_reported(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps(_set(), ensure_ascii=False), encoding="utf-8")
    _, errors = build_mock.build(tmp_path)
    assert any("id が重複" in e for e in errors)


def test_js_cannot_break_out_of_the_script_tag() -> None:
    s = _set()
    s["questions"][0]["stem"] = "</script><!--"
    js = build_mock.to_js([s])
    assert "</script" not in js and "<!--" not in js


# ---- 実データ ----
@pytest.fixture(scope="module")
def sets() -> list[dict]:
    got, errors = build_mock.build(MOCK_DIR)
    assert errors == []
    return got


def test_real_data_passes_and_mock_js_is_up_to_date(sets: list[dict]) -> None:
    assert [(s["id"], len(s["questions"])) for s in sets] == [("mock1", 30), ("mock2", 30)]
    assert MOCK_JS.read_text(encoding="utf-8") == build_mock.to_js(sets), \
        "docs/mock.js が data/mock/ と違う。python3 scripts/build_mock.py で作り直す"


def test_four_choice_grading_and_explanations_line_up(tmp_path: Path, sets: list[dict]) -> None:
    """4 択の全問・元の順とランダムで、正解の行に根拠、他の行にその選択肢の解説が付き、採点が正解の番号と合う。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無いので JS の確認を飛ばす")
    expr = """MOCK_SETS.map(s => s.questions.map(q => {
      let k = 11; const rng = () => (k = (k * 16807) % 2147483647) / 2147483647;
      return ['original', 'random'].map(mode => {
        const order = choiceOrder(q, mode, rng);
        return { order, rows: explanationRows(q, order, order[0], mode),
                 ok: order.map(n => grade(q, n)) };
      });
    }))"""
    script = tmp_path / "run.js"
    script.write_text("\n".join([MOCK_JS.read_text(encoding="utf-8"), CORE_JS.read_text(encoding="utf-8"),
                                 f"console.log(JSON.stringify({expr}));"]), encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    for s, per_set in zip(sets, got):
        for q, cases in zip(s["questions"], per_set):
            choices = {c["n"]: c for c in q["choices"]}
            for case in cases:
                assert sorted(case["order"]) == [1, 2, 3, 4]
                assert case["ok"] == [n == q["answer"] for n in case["order"]]
                for pos, (n, row) in enumerate(zip(case["order"], case["rows"])):
                    assert row["n"] == n and row["isPicked"] == (pos == 0)
                    expected = q["verify"]["reason"] if n == q["answer"] else choices[n]["expl"]
                    assert row["body"] == expected and row["text"] == choices[n]["text"]

