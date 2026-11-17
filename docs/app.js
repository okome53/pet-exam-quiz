'use strict';
/* 画面。純関数は core.js、問題データは questions.js（const QUESTIONS）にある。
   文字はすべて textContent で入れる（データの文を HTML として解釈させない）。
   ブラウザ内に保存するのは設定だけ（解答の記録は Sprint 3 で足す）。 */

const SETTINGS_KEY = 'pet-exam-quiz:v1:settings';
const SCREENS = ['screen-top', 'screen-study', 'screen-finish'];
/* 問を出してからこの時間は解答を受け付けない（前の画面のボタンの二度押し対策。人が読んで選ぶより十分短い） */
const ANSWER_GUARD_MS = 400;

const app = {
  questions: [], byNo: new Map(), minNo: 1, maxNo: 1,
  settings: null,
  session: null,   // { queue, index, answered, correct, order, pickedN }
};

/* 0 以上 1 未満の乱数。暗号用の乱数が使えないブラウザでは Math.random に落とす */
function rng() {
  const c = window.crypto;
  if (c && typeof c.getRandomValues === 'function') {
    const buf = new Uint32Array(1);
    c.getRandomValues(buf);
    return buf[0] / 4294967296;
  }
  return Math.random();
}

/* ---- 設定の保存。保存領域が使えない環境（プライベートブラウズ等）でも、その場限りで動く ---- */
function loadSettings() {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;   // 読めない・中身が壊れている → 既定の設定で始める（normalizeSettings が埋める）
  }
}

function saveSettings(settings) {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    return true;
  } catch (e) {
    return false;
  }
}

/* ---- 画面の部品 ---- */
function byId(id) { return document.getElementById(id); }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* 空行で区切られた文を段落ごとの <p> にして parent に足す */
function appendParagraphs(parent, text) {
  for (const p of paragraphs(text)) parent.appendChild(el('p', null, p));
  return parent;
}

function button(cls, text, onClick) {
  const node = el('button', cls, text);
  node.type = 'button';
  node.addEventListener('click', onClick);
  return node;
}

function focusable(node) {
  node.tabIndex = -1;
  return node;
}

function showScreen(id, focusTarget) {
  for (const s of SCREENS) byId(s).hidden = s !== id;
  byId('to-top').hidden = id !== 'screen-study';
  window.scrollTo(0, 0);
  if (focusTarget) focusTarget.focus();
}

function showFatal(message) {
  for (const s of SCREENS) byId(s).hidden = true;
  byId('to-top').hidden = true;
  const box = byId('fatal');
  box.textContent = message;
  box.hidden = false;
}

/* ---- トップ（設定） ---- */
function setRadio(name, value) {
  for (const r of document.querySelectorAll(`input[name="${name}"]`)) r.checked = r.value === value;
}

function radioValue(name) {
  const r = document.querySelector(`input[name="${name}"]:checked`);
  return r ? r.value : 'original';
}

function fillSettingsForm(s) {
  setRadio('order', s.order);
  setRadio('choice-order', s.choiceOrder);
  byId('range-from').value = String(s.from);
  byId('range-to').value = String(s.to);
  showRangeError({ ok: true });
}

function showRangeError(range) {
  const msg = byId('range-error');
  msg.textContent = range.ok ? '' : range.error;
  msg.hidden = range.ok;
  for (const [field, id] of [['from', 'range-from'], ['to', 'range-to']]) {
    const bad = !range.ok && range.field === field;
    byId(id).setAttribute('aria-invalid', bad ? 'true' : 'false');
    if (bad) byId(id).focus();
  }
}

function onStart(event) {
  event.preventDefault();
  const range = parseRange(byId('range-from').value, byId('range-to').value, app.minNo, app.maxNo);
  showRangeError(range);
  if (!range.ok) return;
  const settings = { order: radioValue('order'), choiceOrder: radioValue('choice-order'), from: range.from, to: range.to };
  const queue = buildQueue(app.questions, settings, rng);
  if (!queue.length) {
    showRangeError({ ok: false, field: 'from', error: 'この範囲には問題がありません' });
    return;
  }
  app.settings = settings;
  byId('storage-note').hidden = saveSettings(settings);
  app.session = { queue, index: 0, answered: 0, correct: 0, order: null, pickedN: null };
  startQuestion();
}

function goTop() {
  app.session = null;
  fillSettingsForm(app.settings);
  showScreen('screen-top', byId('top-heading'));
}

/* ---- 勉強モード ---- */
function currentQuestion() {
  const s = app.session;
  return app.byNo.get(s.queue[s.index]);
}

function startQuestion() {
  app.session.order = choiceOrder(currentQuestion(), app.settings.choiceOrder, rng);
  app.session.pickedN = null;
  app.session.shownAt = performance.now();
  showScreen('screen-study', renderStudy());
}

/* 今の問を描き直し、次に読む場所（解答前は問番号、解答後は正誤の行）を返す */
function renderStudy() {
  const s = app.session;
  const q = currentQuestion();
  const mode = app.settings.choiceOrder;
  const rows = explanationRows(q, s.order, s.pickedN, mode);
  const heading = focusable(el('h2', 'q-no', `問${q.no}`));
  const card = el('article', 'card');
  card.append(heading, appendParagraphs(el('div', 'stem'), q.stem));
  /* 解答後は選択肢のボタンを消し、解説の 5 行だけを残す（各行に選択肢の文と印がある・2026-11-17 本人判断） */
  if (s.pickedN === null) card.appendChild(renderChoices(rows));
  byId('screen-study').replaceChildren(el('p', 'progress', `${s.index + 1} / ${s.queue.length}`), card);
  if (s.pickedN === null) return heading;
  const result = renderResult(q, rows, mode, s.pickedN);
  byId('screen-study').appendChild(result.section);
  return result.heading;
}

function marks(row) {
  const box = el('span', 'marks');
  if (row.isCorrect) box.appendChild(el('span', 'mark mark-correct', '✓ 正解'));
  if (row.isPicked) box.appendChild(el('span', 'mark mark-picked', 'あなたの解答'));
  return box;
}

/* 解答前の選択肢のボタン */
function renderChoices(rows) {
  const list = el('ol', 'choices');
  for (const row of rows) {
    const body = el('span', 'choice-body');
    body.appendChild(el('span', 'choice-text', row.text));
    const btn = el('button', 'choice');
    btn.type = 'button';
    btn.append(el('span', 'choice-label', row.label), body);
    btn.addEventListener('click', () => onAnswer(row.n));
    const li = el('li');
    li.appendChild(btn);
    list.appendChild(li);
  }
  return list;
}

function onAnswer(n) {
  const s = app.session;
  if (!s || s.pickedN !== null) return;   // 二度押し
  /* 「次の問へ」「はじめる」の 2 回目のタップが、同じ位置に出た次の問の選択肢に当たって解答になるのを防ぐ */
  if (performance.now() - s.shownAt < ANSWER_GUARD_MS) return;
  s.pickedN = n;
  s.answered += 1;
  if (grade(currentQuestion(), n)) s.correct += 1;
  renderStudy().focus();
}

/* 解答後: 正誤の行 → 5 つの選択肢の解説（全部開いて）→ 問の注意 → 次へ */
function renderResult(q, rows, mode, pickedN) {
  const ok = grade(q, pickedN);
  const correct = rows.find(r => r.isCorrect);
  const section = el('section', `result ${ok ? 'is-ok' : 'is-ng'}`);
  const heading = focusable(el('h3', 'result-head', ok ? '○ 正解' : `× 不正解（正解は ${rowTitle(correct, mode)}）`));
  const list = el('ol', 'expl-list');
  for (const row of rows) list.appendChild(renderRow(row, mode));
  section.append(heading, list);
  if (q.note) section.appendChild(renderNote(q.note));
  section.appendChild(nextButton());
  return { section, heading };
}

function renderRow(row, mode) {
  const li = el('li', `expl expl-${row.kind}${row.isPicked ? ' is-picked' : ''}`);
  const head = el('p', 'expl-head');
  head.append(el('span', 'expl-label', rowTitle(row, mode)), marks(row));
  li.append(head, appendParagraphs(el('div', 'expl-choice'), row.text));
  li.appendChild(appendParagraphs(el('div', 'expl-body'), row.body));
  return li;
}

function renderNote(note) {
  const box = el('aside', 'note');
  box.appendChild(el('h4', 'note-head', '⚠ この問の注意'));
  return appendParagraphs(box, note);
}

function nextButton() {
  const s = app.session;
  const last = s.index + 1 >= s.queue.length;
  return button('primary next', last ? '結果を見る' : '次の問へ', last ? showFinish : nextQuestion);
}

function nextQuestion() {
  app.session.index += 1;
  startQuestion();
}

function showFinish() {
  const s = app.session;
  const heading = focusable(el('h2', null, 'おつかれさまでした'));
  const summary = el('p', 'finish-summary', `解いた問: ${s.answered} 問 ／ 正解: ${s.correct} 問`);
  byId('screen-finish').replaceChildren(heading, summary, button('primary', 'トップへ戻る', goTop));
  showScreen('screen-finish', heading);
}

/* ---- 起動 ---- */
function dataOk() {
  return typeof QUESTIONS !== 'undefined' && QUESTIONS && QUESTIONS.meta
    && Array.isArray(QUESTIONS.questions) && QUESTIONS.questions.length > 0;
}

function init() {
  if (!dataOk()) {
    showFatal('問題データを読み込めませんでした。ページを読み込み直してください。');
    return;
  }
  app.questions = QUESTIONS.questions;
  app.byNo = new Map(app.questions.map(q => [q.no, q]));
  app.minNo = Math.min(...app.byNo.keys());
  app.maxNo = Math.max(...app.byNo.keys());
  app.settings = normalizeSettings(loadSettings(), app.minNo, app.maxNo);
  byId('range-hint').textContent = `${app.minNo}〜${app.maxNo} の問番号で指定します（全 ${app.questions.length} 問）。`;
  byId('settings-form').addEventListener('submit', onStart);
  byId('to-top').addEventListener('click', goTop);
  fillSettingsForm(app.settings);
  showScreen('screen-top');
}

/* 想定外のエラーで画面が止まったときに、止まったことだけは伝える */
window.addEventListener('error', () => {
  showFatal('表示中に問題が起きました。ページを読み込み直してください。');
});

init();
