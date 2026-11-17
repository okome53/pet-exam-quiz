'use strict';
/* 愛玩動物飼養管理士2級 問題演習の純関数。
   このファイルには画面・保存・現在時刻・乱数に触れない関数だけを置く（tests/test_core.py が node でそのまま読み込んで試す）。
   乱数は呼び出し側が rng（0 以上 1 未満を返す関数）として渡す。
   選択肢は常に元の番号 n で扱い、並べ替えは「n の並び」を作るだけにする。採点も解説も n で引くので、並べ替えても対応はずれない。 */

const CIRCLED = ['①', '②', '③', '④', '⑤'];
const LETTERS = ['A', 'B', 'C', 'D', 'E'];
const ORDERS = ['original', 'random'];

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
function buildQueue(questions, opts, rng) {
  const nos = questions
    .filter(q => q.no >= opts.from && q.no <= opts.to)
    // 絞り込みを足すのはここ。Sprint 3 の「間違えた問だけ」は、記録を引数で受け取って .filter を 1 段足す
    .map(q => q.no);
  return opts.order === 'random' ? shuffle(nos, rng) : nos;
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
    order: order(s.order), choiceOrder: order(s.choiceOrder),
    from: rangeOk ? s.from : min, to: rangeOk ? s.to : max,
  };
}

if (typeof module !== 'undefined') {
  module.exports = {
    shuffle, buildQueue, choiceOrder, choiceLabel, circled, grade, explanationRows, rowTitle,
    paragraphs, toInt, parseRange, normalizeSettings,
  };
}
