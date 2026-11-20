'use strict';
/* 画面。純関数は core.js、問題データは questions.js（const QUESTIONS）にある。
   文字はすべて textContent で入れる（データの文を HTML として解釈させない）。
   ブラウザ内に保存するのは設定と解答の記録。解いている途中の位置は保存しない。 */

const SETTINGS_KEY = 'pet-exam-quiz:v1:settings';
const RECORDS_KEY = 'pet-exam-quiz:v1:records';
/* 形の違う記録は集計に使わず、消さずにここへ退避する */
const RECORDS_BAD_KEY = 'pet-exam-quiz:v1:records-bad';
/* 最後に選んだ問題集の id。141 問の問題集（main）の記録は上の 2 つのまま、予想問題は末尾に :<id> を付けた場所に分けて持つ */
const SET_KEY = 'pet-exam-quiz:v1:set';
const MAIN_SET_ID = 'main';
const SCREENS = ['screen-top', 'screen-study', 'screen-finish', 'screen-test', 'screen-score'];
/* 問を出してからこの時間は解答を受け付けない（前の画面のボタンの二度押し対策。人が読んで選ぶより十分短い） */
const ANSWER_GUARD_MS = 400;

const app = {
  sets: [],        // { id, title, questions }。先頭が 141 問の問題集
  setId: MAIN_SET_ID,
  questions: [], byNo: new Map(), nos: [], minNo: 1, maxNo: 1,
  settings: null,
  records: {},     // core.js の splitRecords を通した記録
  session: null,   // 勉強モード: { queue, index, answered, correct, order, pickedN, shownAt }
  test: null,      // テストモード: { nos, orders, picks, index, shownAt, graded }
  leaveArmed: false,   // テストの途中で「トップへ戻る」を 1 回押した状態
  leaveArmedAt: 0,     // 1 回目を押した時刻（素早い 2 回タップを 2 回目として通さないため）
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

/* ---- 保存層。保存領域が使えない環境（プライベートブラウズ・容量超過など）では、メモリに持ってその場限りで動く ---- */
const store = (() => {
  let usable = true;
  const mem = {};
  try {
    const probe = 'pet-exam-quiz:__probe';
    window.localStorage.setItem(probe, '1');
    window.localStorage.removeItem(probe);
  } catch (e) {
    usable = false;
  }
  return {
    get usable() { return usable; },
    /* 保存されていなければ null。JSON として読めなければ文字列のまま返す（記録なら splitRecords が退避に回す） */
    get(key) {
      if (!usable) return key in mem ? mem[key] : null;
      let raw;
      try { raw = window.localStorage.getItem(key); } catch (e) { return null; }
      if (raw === null) return null;
      try { return JSON.parse(raw); } catch (e) { return raw; }
    },
    /* 保存できれば true。途中で保存できなくなったら、以後はメモリに持つ */
    set(key, value) {
      if (usable) {
        try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { usable = false; }
      }
      mem[key] = value;
      return false;
    },
  };
})();

/* SIMPLIFIED(2026-11-17): 記録は起動時に 1 回読み、保存のたびに全体を書く。2 つのタブで同時に解くと、後から保存した側だけが残る — 複数タブ・複数端末で使う声が出たら、保存の直前に読み直して足し合わせる */
function recordsKey(id) { return id === MAIN_SET_ID ? RECORDS_KEY : `${RECORDS_KEY}:${id}`; }
function recordsBadKey(id) { return id === MAIN_SET_ID ? RECORDS_BAD_KEY : `${RECORDS_BAD_KEY}:${id}`; }

function loadRecords(id) {
  const { good, bad } = splitRecords(store.get(recordsKey(id)));
  if (bad.length) {
    // 前回までの退避分に足す。退避先の中身が配列でなくても捨てない
    const kept = store.get(recordsBadKey(id));
    const list = Array.isArray(kept) ? kept : (kept === null ? [] : [kept]);
    store.set(recordsBadKey(id), list.concat(bad));
    store.set(recordsKey(id), good);
  }
  return good;
}

function saveRecords() {
  store.set(recordsKey(app.setId), app.records);
  showStorageNote();
}

function showStorageNote() {
  byId('storage-note').hidden = store.usable;
}

/* 1 問の解答を記録する。時刻は記録の順を残すためだけに使う */
function record(no, correct, at) {
  app.records = recordAnswer(app.records, no, correct, at);
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
  /* 終わりの画面には自前の「トップへ戻る」があるので、ヘッダのボタンは解いている間と採点結果だけに出す */
  byId('to-top').hidden = !['screen-study', 'screen-test', 'screen-score'].includes(id);
  disarmLeave();
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

function radioValue(name, fallback) {
  const r = document.querySelector(`input[name="${name}"]:checked`);
  return r ? r.value : fallback;
}

function fillSettingsForm(s) {
  setRadio('set', app.setId);
  setRadio('mode', s.mode);
  setRadio('order', s.order);
  setRadio('choice-order', s.choiceOrder);
  byId('range-from').value = String(s.from);
  byId('range-to').value = String(s.to);
  byId('wrong-only').checked = s.wrongOnly;
  showRangeError({ ok: true });
  showStartError('');
}

function showStartError(message) {
  const box = byId('start-error');
  box.textContent = message;
  box.hidden = !message;
}

/* ---- トップの記録 ---- */
function currentSet() { return app.sets.find(x => x.id === app.setId); }

function renderStats() {
  const st = stats(app.records, app.nos);
  byId('stats-heading').textContent = `これまでの記録（${currentSet().title}）`;
  byId('stat-solved').textContent = `${st.solved} / ${st.total} 問`;
  byId('stat-rate').textContent = st.rate === null ? '—' : `${st.rate}%（${st.lastOk} 問）`;
  byId('stat-wrong').textContent = `${st.wrong} 問`;
  byId('reset-open').disabled = Object.keys(app.records).length === 0;
  closeReset();
}

/* 記録を消すのは 2 段階（ブラウザの確認ダイアログは使わない） */
function openReset() {
  const st = stats(app.records, app.nos);
  byId('reset-text').textContent = `${currentSet().title}の記録（解いた問 ${st.solved} 問）をすべて消します。ほかの問題集の記録は消えません。消した記録は元に戻せません。`;
  byId('reset-open').hidden = true;
  byId('reset-confirm').hidden = false;
  byId('reset-done').textContent = '';
  byId('reset-no').focus();
}

function closeReset() {
  byId('reset-open').hidden = false;
  byId('reset-confirm').hidden = true;
}

function doReset() {
  app.records = {};
  saveRecords();
  renderStats();
  byId('reset-done').textContent = `${currentSet().title}の記録を消しました。`;
  byId('stats-heading').focus();
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
  showStartError('');
  const range = parseRange(byId('range-from').value, byId('range-to').value, app.minNo, app.maxNo);
  showRangeError(range);
  if (!range.ok) return;
  const settings = {
    mode: radioValue('mode', 'study'), order: radioValue('order', 'original'),
    choiceOrder: radioValue('choice-order', 'original'), from: range.from, to: range.to,
    wrongOnly: byId('wrong-only').checked,
  };
  /* 対象が 0 問なら理由を出して始めない */
  const pool = buildQueue(app.questions, Object.assign({}, settings, { order: 'original' }), rng, app.records);
  if (!pool.length) {
    showStartError(settings.wrongOnly
      ? 'この範囲には、間違えた問（最後の解答が不正解の問）がありません。範囲を広げるか、「間違えた問だけ」を外してください。'
      : 'この範囲には問題がありません。');
    byId('start-error').focus();
    return;
  }
  showStartError('');
  app.settings = settings;
  store.set(SETTINGS_KEY, settings);
  showStorageNote();
  if (settings.mode === 'test') {
    startTest(buildTest(pool, TEST_SIZE, settings.order, rng));
  } else {
    const queue = settings.order === 'random' ? shuffle(pool, rng) : pool;
    app.session = { queue, index: 0, answered: 0, correct: 0, order: null, pickedN: null };
    startQuestion();
  }
}

function goTop() {
  app.session = null;
  app.test = null;
  fillSettingsForm(app.settings);
  byId('reset-done').textContent = '';
  renderStats();
  showScreen('screen-top', byId('top-heading'));
}

/* テストを解いている途中（採点前に 1 問でも答えた）なら、1 回目は確かめるだけにする */
function onHeaderTop() {
  const t = app.test;
  const inProgress = t && !t.graded && t.picks.some(p => p !== null);
  if (inProgress && !app.leaveArmed) {
    app.leaveArmed = true;
    app.leaveArmedAt = performance.now();
    byId('to-top').textContent = '答えを捨てて戻る';
    byId('leave-note').textContent = 'テストの答えはまだ採点していません。もう一度押すと答えを捨ててトップへ戻ります。';
    return;
  }
  /* iPhone では素早い 2 回タップがそのまま 2 回の押下になる。1 回目の直後の押下は確かめたことにしない */
  if (inProgress && performance.now() - app.leaveArmedAt < ANSWER_GUARD_MS) return;
  goTop();
}

function disarmLeave() {
  app.leaveArmed = false;
  byId('to-top').textContent = 'トップへ戻る';
  byId('leave-note').textContent = '';
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
  const q = currentQuestion();
  const ok = grade(q, n);
  if (ok) s.correct += 1;
  /* 勉強モードは解答ごとに記録する */
  record(q.no, ok, Date.now());
  saveRecords();
  renderStudy().focus();
}

/* 解答後: 正誤の行 → 5 つの選択肢の解説（全部開いて）→ 問の注意 → 次へ（withNext が false なら次へを付けない） */
function renderResult(q, rows, mode, pickedN, withNext = true) {
  const ok = grade(q, pickedN);
  const correct = rows.find(r => r.isCorrect);
  const section = el('section', `result ${ok ? 'is-ok' : 'is-ng'}`);
  const heading = focusable(el('h3', 'result-head', ok ? '○ 正解' : `× 不正解（正解は ${rowTitle(correct, mode)}）`));
  const list = el('ol', 'expl-list');
  for (const row of rows) list.appendChild(renderRow(row, mode));
  section.append(heading, list);
  if (q.note) section.appendChild(renderNote(q.note));
  if (withNext) section.appendChild(nextButton());
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

/* ---- テストモード（10 問まとめて解き、最後に採点） ---- */
function startTest(nos) {
  const mode = app.settings.choiceOrder;
  app.test = {
    nos, orders: nos.map(no => choiceOrder(app.byNo.get(no), mode, rng)), picks: nos.map(() => null),
    index: 0, shownAt: 0, graded: null,
  };
  moveTest(0);
}

function moveTest(index) {
  const t = app.test;
  t.index = Math.max(0, Math.min(index, t.nos.length - 1));
  t.shownAt = performance.now();
  showScreen('screen-test', renderTest());
}

function answeredCount(t) { return t.picks.filter(p => p !== null).length; }

/* 今の問を描き直し、問番号の見出しを返す */
function renderTest() {
  const t = app.test;
  const q = app.byNo.get(t.nos[t.index]);
  const mode = app.settings.choiceOrder;
  const total = t.nos.length;
  const done = answeredCount(t);
  const heading = focusable(el('h2', 'q-no', `問${q.no}`));
  const card = el('article', 'card');
  card.append(heading, appendParagraphs(el('div', 'stem'), q.stem),
    renderTestChoices(explanationRows(q, t.orders[t.index], t.picks[t.index], mode)));

  const nav = el('div', 'button-row');
  const prev = button('step', '← 前の問', () => moveTest(t.index - 1));
  const next = button('step', '次の問 →', () => moveTest(t.index + 1));
  prev.disabled = t.index === 0;
  next.disabled = t.index === total - 1;
  nav.append(prev, next);

  const gradeBtn = button('primary', '採点する', onGradeTest);
  gradeBtn.disabled = done < total;
  gradeBtn.id = 'grade-test';
  const hint = el('p', 'hint', done < total
    ? `あと ${total - done} 問答えると採点できます。`
    : 'すべて答えました。見直してから「採点する」を押してください。');

  byId('screen-test').replaceChildren(
    el('p', 'progress', `${t.index + 1} / ${total}（答えた問 ${done} / ${total}）`), card, nav, renderJump(), gradeBtn, hint);
  return heading;
}

/* テストの選択肢。選んでも解説は出さず、選んだものに印を付けるだけ。採点までは何度でも選び直せる */
function renderTestChoices(rows) {
  const list = el('ol', 'choices');
  for (const row of rows) {
    const body = el('span', 'choice-body');
    body.appendChild(el('span', 'choice-text', row.text));
    if (row.isPicked) {
      const box = el('span', 'marks');
      box.appendChild(el('span', 'mark mark-picked', '選んだ答え'));
      body.appendChild(box);
    }
    const btn = el('button', `choice${row.isPicked ? ' is-selected' : ''}`);
    btn.type = 'button';
    btn.dataset.n = String(row.n);
    btn.setAttribute('aria-pressed', row.isPicked ? 'true' : 'false');
    btn.append(el('span', 'choice-label', row.label), body);
    btn.addEventListener('click', () => onTestPick(row.n));
    const li = el('li');
    li.appendChild(btn);
    list.appendChild(li);
  }
  return list;
}

function onTestPick(n) {
  const t = app.test;
  if (!t || t.graded) return;
  /* 「次の問 →」の 2 回目のタップが、次の問の選択肢に当たって答えになるのを防ぐ */
  if (performance.now() - t.shownAt < ANSWER_GUARD_MS) return;
  t.picks[t.index] = n;
  renderTest();
  const picked = byId('screen-test').querySelector(`button.choice[data-n="${n}"]`);
  if (picked) picked.focus({ preventScroll: true });
}

/* 10 問の行き来。答えた問には ✓ を付ける（色だけで区別しない） */
function renderJump() {
  const t = app.test;
  const list = el('ol', 'jump');
  list.setAttribute('aria-label', '問の一覧');
  t.nos.forEach((no, i) => {
    const answered = t.picks[i] !== null;
    const btn = button(`jump-btn${answered ? ' is-answered' : ''}`, `${i + 1}${answered ? ' ✓' : ''}`, () => moveTest(i));
    btn.setAttribute('aria-label', `${i + 1} 問目（問${no}・${answered ? '答えた' : 'まだ答えていない'}）`);
    if (i === t.index) btn.setAttribute('aria-current', 'step');
    const li = el('li');
    li.appendChild(btn);
    list.appendChild(li);
  });
  return list;
}

function onGradeTest() {
  const t = app.test;
  if (!t || t.graded || answeredCount(t) < t.nos.length) return;
  t.graded = gradeTest(t.nos.map(no => app.byNo.get(no)), t.picks);
  /* テストは採点したときにまとめて記録する（同じ時刻） */
  const at = Date.now();
  for (const r of t.graded.results) record(r.no, r.ok, at);
  saveRecords();
  showScreen('screen-score', renderScore());
}

/* 採点結果: 点数 → 10 問の正誤の一覧 → 10 問分の解説（勉強モードと同じ表示） */
function renderScore() {
  const t = app.test;
  const g = t.graded;
  const mode = app.settings.choiceOrder;
  const heading = focusable(el('h2', 'score-head', `${g.total} 問中 ${g.correct} 問正解`));
  const summary = el('ol', 'score-list');
  const details = el('div', 'score-details');
  g.results.forEach((r, i) => {
    const q = app.byNo.get(r.no);
    const itemHead = focusable(el('h3', 'q-no', `${i + 1} 問目・問${q.no}`));
    const card = el('article', 'card');
    card.append(itemHead, appendParagraphs(el('div', 'stem'), q.stem));
    const item = el('section', 'score-item');
    item.append(card, renderResult(q, explanationRows(q, t.orders[i], r.pickedN, mode), mode, r.pickedN, false).section);
    details.appendChild(item);

    const jump = button(`score-jump ${r.ok ? 'is-ok' : 'is-ng'}`, `${i + 1}. 問${q.no}　${r.ok ? '○ 正解' : '× 不正解'}`, () => {
      item.scrollIntoView({ block: 'start' });
      itemHead.focus({ preventScroll: true });
    });
    const li = el('li');
    li.appendChild(jump);
    summary.appendChild(li);
  });
  byId('screen-score').replaceChildren(heading, el('p', 'hint', '問を押すと、その問の解説へ移ります。'), summary, details,
    button('primary', 'トップへ戻る', goTop));
  return heading;
}

/* ---- 問題集 ---- */
/* 問題集を切り替える。問・範囲・記録をその問題集のものにする */
function selectSet(id) {
  app.setId = id;
  app.questions = currentSet().questions;
  app.byNo = new Map(app.questions.map(q => [q.no, q]));
  app.nos = app.questions.map(q => q.no);
  app.minNo = Math.min(...app.nos);
  app.maxNo = Math.max(...app.nos);
  app.records = loadRecords(id);
  byId('range-hint').textContent = `${app.minNo}〜${app.maxNo} の問番号で指定します（全 ${app.questions.length} 問）。`;
}

/* 問題集のラジオボタン（データから作る）。選択肢の数も添える（141 問は 5 択、予想問題は 4 択） */
function renderSetChoices() {
  const field = byId('set-field');
  for (const s of app.sets) {
    const input = el('input');
    input.type = 'radio';
    input.name = 'set';
    input.value = s.id;
    input.addEventListener('change', () => onSetChange(s.id));
    const label = el('label', 'option');
    label.append(input, ` ${s.title}（${s.questions.length} 問・${s.questions[0].choices.length} 択）`);
    field.appendChild(label);
  }
}

/* 切り替えたら、範囲はその問題集の全体に戻す */
function onSetChange(id) {
  selectSet(id);
  store.set(SET_KEY, id);
  byId('range-from').value = String(app.minNo);
  byId('range-to').value = String(app.maxNo);
  showRangeError({ ok: true });
  showStartError('');
  byId('reset-done').textContent = '';
  renderStats();
  showStorageNote();
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
  /* mock.js が読めなかったときは、141 問の問題集だけで動く */
  const mocks = typeof MOCK_SETS !== 'undefined' && Array.isArray(MOCK_SETS) ? MOCK_SETS : [];
  app.sets = [{ id: MAIN_SET_ID, title: 'ankimaker の問題集', questions: QUESTIONS.questions }]
    .concat(mocks.filter(x => x && typeof x.id === 'string' && Array.isArray(x.questions) && x.questions.length));
  const saved = store.get(SET_KEY);
  selectSet(app.sets.some(x => x.id === saved) ? saved : MAIN_SET_ID);
  app.settings = normalizeSettings(store.get(SETTINGS_KEY), app.minNo, app.maxNo);
  renderSetChoices();
  byId('settings-form').addEventListener('submit', onStart);
  byId('to-top').addEventListener('click', onHeaderTop);
  byId('reset-open').addEventListener('click', openReset);
  byId('reset-no').addEventListener('click', () => { closeReset(); byId('reset-open').focus(); });
  byId('reset-yes').addEventListener('click', doReset);
  fillSettingsForm(app.settings);
  renderStats();
  showStorageNote();
  showScreen('screen-top');
}

/* 想定外のエラーで画面が止まったときに、止まったことだけは伝える */
window.addEventListener('error', () => {
  showFatal('表示中に問題が起きました。ページを読み込み直してください。');
});

init();
