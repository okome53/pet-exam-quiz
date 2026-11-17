'use strict';
/* 愛玩動物飼養管理士2級 問題演習の純関数。
   このファイルには画面・保存・現在時刻・乱数に触れない関数だけを置く（tests/test_core.py が node でそのまま読み込んで試す）。
   乱数は呼び出し側が rng（0 以上 1 未満を返す関数）として渡す。
   選択肢は常に元の番号 n で扱い、並べ替えは「n の並び」を作るだけにする。採点も解説も n で引くので、並べ替えても対応はずれない。 */

const CIRCLED = ['①', '②', '③', '④', '⑤'];
const LETTERS = ['A', 'B', 'C', 'D', 'E'];
const ORDERS = ['original', 'random'];
const MODES = ['study', 'test'];
const TEST_SIZE = 10;

function shuffle(list, rng) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/* 出題の並び（問番号の配列）。questions は問番号の順で届くので、元の順番はその順のまま。
   opts = { from, to, order: 'original'|'random' }（from・to は問番号で、両端を含む） */
function buildQueue(questions, opts, rng, records) {
  const nos = questions
    .filter(q => q.no >= opts.from && q.no <= opts.to)
    .filter(q => !opts.wrongOnly || isWrong(records, q.no))
    .map(q => q.no);
  return opts.order === 'random' ? shuffle(nos, rng) : nos;
}

/* テストの出題（問番号の配列）。pool は範囲と絞り込みを済ませた問番号（元の順番）。
   重複なしで size 問。足りなければある分だけ。元の順番なら pool の頭から、ランダムなら pool から無作為に */
function buildTest(pool, size, order, rng) {
  return (order === 'random' ? shuffle(pool, rng) : pool.slice()).slice(0, size);
}

/* テストの採点。qs は出題した問（画面の順）、picks はそれぞれで選んだ元の番号（未解答は null） */
function gradeTest(qs, picks) {
  const results = qs.map((q, i) => ({ no: q.no, pickedN: picks[i], ok: grade(q, picks[i]) }));
  return { total: qs.length, correct: results.filter(r => r.ok).length, results };
}

/* 選択肢を画面に並べる順（元の番号 n の配列） */
function choiceOrder(q, mode, rng) {
  const ns = q.choices.map(c => c.n);
  return mode === 'random' ? shuffle(ns, rng) : ns;
}

/* 画面の位置（0 始まり）の呼び名。元の順番は ①〜⑤（位置と元の番号が同じ）、ランダムは A〜E */
function choiceLabel(pos, mode) {
  return (mode === 'random' ? LETTERS : CIRCLED)[pos];
}

function circled(n) { return CIRCLED[n - 1]; }

/* 採点。選んだ選択肢の元の番号と正解の番号を比べる */
function grade(q, pickedN) { return pickedN === q.answer; }

/* 解答後に出す解説の行（画面の並び順・5 行）。
   不正解の選択肢はその解説（expl）、正解の選択肢は裏取りの根拠（verify.reason）と分類の札を持つ。
   出典の URL と出典名はデータには残すが画面に出さないので、ここでも読まない（2026-11-17 本人判断）。
   pickedN が null なら解答前（どの行も isPicked は false） */
function explanationRows(q, order, pickedN, mode) {
  return order.map((n, pos) => {
    const choice = q.choices.find(c => c.n === n);
    const isCorrect = n === q.answer;
    const row = {
      label: choiceLabel(pos, mode), n, origLabel: circled(n), isCorrect, isPicked: n === pickedN,
      text: choice.text, body: isCorrect ? q.verify.reason : choice.expl, kind: isCorrect ? 'correct' : 'wrong',
    };
    /* 正解の行は裏取りの根拠の文だけを出す。分類の札は出さない（2026-11-17 本人判断） */
    return row;
  });
}

/* 行の見出し。ランダムのときは元の番号も添える（注記と根拠が元の番号で選択肢を指すため） */
function rowTitle(row, mode) {
  return mode === 'random' ? `${row.label}（元の${row.origLabel}）` : row.label;
}

/* 空行（\n\n）で段落に分ける。空の段落は捨てる */
function paragraphs(text) {
  return String(text === null || text === undefined ? '' : text)
    .split(/\n[ \t　]*\n/).map(s => s.trim()).filter(Boolean);
}

/* 問番号の入力欄の文字を整数にする。全角数字も受ける。数字以外が混ざれば null */
function toInt(text) {
  const s = String(text === null || text === undefined ? '' : text).normalize('NFKC').trim();
  return /^\d{1,4}$/.test(s) ? Number(s) : null;
}

/* 範囲の入力の検査。field は直す欄（'from'|'to'） */
function parseRange(fromText, toText, min, max) {
  const from = toInt(fromText);
  const to = toInt(toText);
  const outside = n => n === null || n < min || n > max;
  if (outside(from)) return { ok: false, field: 'from', error: `「はじめ」には ${min}〜${max} の数字を入れてください` };
  if (outside(to)) return { ok: false, field: 'to', error: `「おわり」には ${min}〜${max} の数字を入れてください` };
  if (from > to) return { ok: false, field: 'from', error: '「はじめ」は「おわり」と同じか小さい数にしてください' };
  return { ok: true, from, to };
}

/* ブラウザに保存してあった設定を読み直す。形の違う項目は既定値に戻す（壊れた保存で画面を止めない） */
function normalizeSettings(raw, min, max) {
  const s = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const order = v => (ORDERS.includes(v) ? v : 'original');
  const rangeOk = Number.isInteger(s.from) && Number.isInteger(s.to) && min <= s.from && s.from <= s.to && s.to <= max;
  return {
    mode: MODES.includes(s.mode) ? s.mode : 'study',
    order: order(s.order), choiceOrder: order(s.choiceOrder),
    from: rangeOk ? s.from : min, to: rangeOk ? s.to : max,
    wrongOnly: s.wrongOnly === true,
  };
}

/* ---- 解答の記録 ----
   形: { "<問番号>": { n: 解いた回数, ok: 正解した回数, last: 最後の解答が正解か, at: 最後に解いた時刻（ミリ秒） } }
   時刻は呼び出し側が渡す（このファイルは現在時刻に触れない） */
function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function isRecordOk(r) {
  return isPlainObject(r)
    && Number.isInteger(r.n) && r.n >= 1
    && Number.isInteger(r.ok) && r.ok >= 0 && r.ok <= r.n
    && typeof r.last === 'boolean'
    && Number.isFinite(r.at) && r.at >= 0
    && Object.keys(r).length === 4;
}

/* 保存してあった記録を、使えるもの（good）と形の違うもの（bad）に分ける。bad は捨てずに呼び出し側が退避する。
   全体がオブジェクトでなければ、全体を 1 件の bad にする（何も保存されていない null・undefined は空） */
function splitRecords(raw) {
  const good = {};
  if (raw === null || raw === undefined) return { good, bad: [] };
  if (!isPlainObject(raw)) return { good, bad: [raw] };
  const bad = [];
  for (const key of Object.keys(raw)) {
    if (/^[1-9]\d{0,3}$/.test(key) && isRecordOk(raw[key])) {
      const r = raw[key];
      good[key] = { n: r.n, ok: r.ok, last: r.last, at: r.at };
    } else {
      bad.push({ no: key, value: raw[key] });
    }
  }
  return { good, bad };
}

function recordOf(records, no) {
  return records && Object.prototype.hasOwnProperty.call(records, String(no)) ? records[String(no)] : null;
}

/* 最後の解答が不正解の問か（一度も解いていない問は含めない） */
function isWrong(records, no) {
  const r = recordOf(records, no);
  return r !== null && r.last === false;
}

/* 1 問の解答を足した新しい記録を返す（元の records は書き換えない） */
function recordAnswer(records, no, correct, at) {
  const prev = recordOf(records, no);
  const next = Object.assign({}, records);
  next[String(no)] = {
    n: (prev ? prev.n : 0) + 1, ok: (prev ? prev.ok : 0) + (correct ? 1 : 0), last: correct === true, at,
  };
  return next;
}

/* トップに出す集計。nos は今のデータにある問番号（データに無い問の記録は数えない）。
   rate は「最後の解答が正解」の割合（％・整数に丸める）。解いた問が 0 なら null */
function stats(records, nos) {
  let solved = 0, lastOk = 0;
  for (const no of nos) {
    const r = recordOf(records, no);
    if (!r) continue;
    solved += 1;
    if (r.last) lastOk += 1;
  }
  return {
    total: nos.length, solved, lastOk, wrong: solved - lastOk,
    rate: solved ? Math.round((lastOk / solved) * 100) : null,
  };
}

if (typeof module !== 'undefined') {
  module.exports = {
    TEST_SIZE, shuffle, buildQueue, buildTest, gradeTest, choiceOrder, choiceLabel, circled, grade, explanationRows,
    rowTitle, paragraphs, toInt, parseRange, normalizeSettings,
    isRecordOk, splitRecords, isWrong, recordAnswer, stats,
  };
}
