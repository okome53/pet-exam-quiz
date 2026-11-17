"""scripts/convert.py を実データ（source/ の md 3 本と data/order-exceptions.json）に当てて確かめる。

source/ は公開リポジトリに入れないので、無いときは全部飛ばす。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import convert

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_js(js: str):
    assert js.startswith(convert.JS_PREFIX) and js.endswith(convert.JS_SUFFIX)
    return json.loads(js[len(convert.JS_PREFIX):-len(convert.JS_SUFFIX)])


REVIEWED_EXCEPTIONS = {(22, 4, "answer"), (122, 1, "answer"), (123, 4, "number"),
                       (138, 2, "similarity"), (138, 3, "similarity"), (138, 4, "similarity")}


@pytest.fixture(scope="module")
def real():
    src = REPO_ROOT / "source"
    if not all((src / name).exists() for name in convert.SOURCE_FILES):
        pytest.skip("source/ に元の md がないので、実データの確認を飛ばす")
    texts, errors = convert.read_sources(src)
    assert errors == []
    exceptions = (REPO_ROOT / "data" / "order-exceptions.json").read_text(encoding="utf-8")
    data, _, errors = convert.build(texts, exceptions)
    assert errors == [], "\n".join(errors)
    return data, json.loads(exceptions)


def test_real_counts(real):
    data, _ = real
    questions = data["questions"]
    assert [q["no"] for q in questions] == list(range(1, 142))
    assert data["meta"]["count"] == 141
    classes = {c: sum(q["verify"]["class"] == c for q in questions) for c in ("confirmed", "unconfirmed", "doubtful")}
    assert classes == {"confirmed": 112, "unconfirmed": 27, "doubtful": 2}
    assert {q["no"] for q in questions if q["note"]} == {23, 30, 66, 78, 86, 109, 113, 114, 124, 126}
    assert {q["no"] for q in questions if not q["verify"]["urls"]} == {38, 72, 115, 119, 120, 121, 127}
    assert data["meta"]["source_url"] == "https://ankimaker.com/workbooks/f3582e60-ded2-4fc7-a14a-547711df6c85"
    assert data["meta"]["author"] == "柚姫w"


def test_real_every_question_has_five_choices(real):
    data, _ = real
    for q in data["questions"]:
        assert [c["n"] for c in q["choices"]] == [1, 2, 3, 4, 5], q["no"]
        assert [c["n"] for c in q["choices"] if c["expl"] is None] == [q["answer"]], q["no"]
        assert all(c["text"] for c in q["choices"]) and q["stem"], q["no"]
        assert all(c["expl"] for c in q["choices"] if c["n"] != q["answer"]), q["no"]
        assert all(u.startswith(("http://", "https://")) for u in q["verify"]["urls"]), q["no"]


def test_real_exceptions_are_the_reviewed_ones(real):
    _, exceptions = real
    # 例外を足すときは中身を本人に見せてから。ここを書き換えずに例外だけ増やすと落ちる
    assert {(e["no"], e["n"], e["check"]) for e in exceptions} == REVIEWED_EXCEPTIONS


def test_real_js_round_trip(real):
    data, _ = real
    assert parse_js(convert.to_js(data)) == data


def test_written_outputs_match_sources(real):
    data, _ = real
    json_path, js_path = REPO_ROOT / "data" / "questions.json", REPO_ROOT / "docs" / "questions.js"
    if not (json_path.exists() and js_path.exists()):
        pytest.skip("書き出し済みのデータがない（python3 scripts/convert.py を先に実行する）")
    assert json.loads(json_path.read_text(encoding="utf-8")) == data, "source/ が変わった。convert.py を実行し直す"
    assert parse_js(js_path.read_text(encoding="utf-8")) == data
