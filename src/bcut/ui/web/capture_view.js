/* "Capture One에도 표시하기" 창 (spec FR-28, IA SO-02-APP).
   위에서 아래로: ① 어디에 ② 무엇을 ③ 미리보기 결과, 버튼은 아래에 고정한다.
   미리보기가 먼저이고 반영은 따로 한 번 더 누른다. 서버가 기존 apply/rollback을 부른다 (ui/capture.py). */
(function (root) {
  'use strict';
  var ctx = null;   // {el, api, job, rerender}
  var C = null;     // 창이 열려 있을 때만 있는 상태
  var KEY = 'bcut-capture-catalog', STYLE_KEY = 'bcut-capture-style';
  var KINDS = [['pick', '셀렉', 'bcut-셀렉'], ['maybe', '보류', 'bcut-보류'], ['discard', '버릴 컷', 'bcut-버릴컷']];
  var COLORS = ['안 줌', '빨강', '주황', '노랑', '초록', '파랑', '분홍', '보라'];   // 번호 1~7 (Capture One 순서)
  var SWATCH = ['transparent', '#e5484d', '#f08a24', '#f5c518', '#3fae5a', '#3b82f6', '#ec6aa8', '#8b5cf6'];

  function init(c) { ctx = c; document.addEventListener('bcut-open-capture', open); }
  function isOpen() { return C !== null; }
  function get(k) { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }
  function put(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 저장 못 해도 계속 */ } }
  function loadStyle() {
    var base = {pick: {rating: 0, color: 0}, maybe: {rating: 0, color: 0}, discard: {rating: 0, color: 0}};
    try { var s = JSON.parse(get(STYLE_KEY) || 'null'); if (s && s.style) return s; } catch (e) { /* 기본값 */ }
    return {style: base, overwrite: false};
  }
  function open() {
    var st = loadStyle();
    C = {catalog: get(KEY), res: null, busy: false, error: null, partial: false, style: st.style,
         overwrite: !!st.overwrite, more: false, docs: null, docsError: null};
    ctx.rerender();
    loadDocs();
  }
  /* Capture One에 지금 열려 있는 카탈로그·세션을 가져와 고르게 한다 (이름을 직접 안 써도 되게) */
  function loadDocs() {
    var mine = C;
    ctx.api('POST', '/api/jobs/' + ctx.job() + '/capture-one', {action: 'documents'})
      .then(function (j) {
        if (C !== mine) return;
        C.docs = j.documents || [];
        if (C.docs.length === 1) C.catalog = C.docs[0].name;   // 하나뿐이면 그게 지금 쓸 수 있는 문서다
        ctx.rerender();
      })
      .catch(function (e) { if (C !== mine) return; C.docs = []; C.docsError = e.message; ctx.rerender(); });
  }
  function close() { if (C && C.busy) return; C = null; ctx.rerender(); }
  function stale() { C.res = null; C.error = null; ctx.rerender(); }   // 값을 바꾸면 미리보기를 다시 한다

  function chosenStyle() {
    var out = {}, any = false;
    KINDS.forEach(function (k) {
      var v = C.style[k[0]], o = {};
      if (v.rating) o.rating = v.rating;
      if (v.color) o.color = v.color;
      if (o.rating || o.color) { out[k[0]] = o; any = true; }
    });
    return any ? out : null;
  }
  var BUSY = {
    preview: 'Capture One에서 사진을 찾아 몇 장에 붙을지 세고 있어요. 아무것도 바꾸지 않아요.',
    'apply+': '이름표를 붙이고, 고른 별점·색을 준 뒤 다시 읽어 확인하고 있어요. 사진 수가 많으면 조금 걸려요.',
    rollback: '되돌릴 수 있는 것을 찾고 있어요. 아무것도 바꾸지 않아요.',
    'rollback+': '붙였던 것을 이전 값으로 되돌리고 있어요.'
  };
  function busyBar(p) {
    var w = ctx.el('div', 'ind'), bar = ctx.el('div', 'ind-bar');
    bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-busy', 'true'); bar.setAttribute('aria-label', 'Capture One 작업 중');
    w.appendChild(bar); w.appendChild(ctx.el('div', 'ind-text', C.busyText || '잠시만요…')); p.appendChild(w);
  }
  function call(action, commit) {
    var cat = C.catalog.trim();
    if (!cat) { C.error = '카탈로그나 세션 이름을 입력해 주세요.'; ctx.rerender(); return; }
    put(KEY, cat);
    C.busy = true; C.error = null; C.busyText = BUSY[action + (commit ? '+' : '')] || BUSY.preview; ctx.rerender();
    var body = {action: action, catalog: cat, commit: !!commit, allow_partial: C.partial};
    var st = chosenStyle();
    if (st) { body.style = st; body.overwrite = C.overwrite; }
    put(STYLE_KEY, JSON.stringify({style: C.style, overwrite: C.overwrite}));
    ctx.api('POST', '/api/jobs/' + ctx.job() + '/capture-one', body)
      .then(function (j) { C.res = j; C.busy = false; C.scroll = true; ctx.rerender(); })
      .catch(function (e) { C.error = e.message; C.busy = false; ctx.rerender(); });
  }

  /* ---- 작은 부품 ---- */
  function box(cls, title) {
    var b = ctx.el('div', 'cap-card ' + cls);
    if (title) b.appendChild(ctx.el('div', 'cap-card-title', title));
    return b;
  }
  function note(p, text, cls) { p.appendChild(ctx.el('div', cls || 'muted', text)); }
  function section(p, num, title) {
    var h = ctx.el('div', 'cap-sec'); h.appendChild(ctx.el('span', 'cap-num', num));
    h.appendChild(ctx.el('b', null, title)); p.appendChild(h);
  }
  function stars(v, kind) {
    var wrap = ctx.el('span', 'cap-stars'), cur = C.style[kind];
    for (var i = 1; i <= 5; i++) (function (n) {
      var b = ctx.el('button', 'cap-star' + (n <= cur.rating ? ' on' : ''), n <= cur.rating ? '★' : '☆');
      b.type = 'button'; b.title = n + '점'; b.setAttribute('aria-pressed', String(n === cur.rating));
      b.setAttribute('aria-label', '별점 ' + n + '점');
      b.addEventListener('click', function () { cur.rating = cur.rating === n ? 0 : n; stale(); });
      wrap.appendChild(b);
    })(i);
    wrap.appendChild(ctx.el('span', 'cap-val', cur.rating ? cur.rating + '점' : '안 줌'));
    return wrap;
  }
  function swatches(kind) {
    var wrap = ctx.el('span', 'cap-colors'), cur = C.style[kind];
    for (var i = 1; i <= 7; i++) (function (n) {
      var b = ctx.el('button', 'cap-sw' + (n === cur.color ? ' on' : ''), n === cur.color ? '✓' : '');
      b.type = 'button'; b.style.background = SWATCH[n]; b.title = COLORS[n];
      b.setAttribute('aria-label', '컬러 태그 ' + COLORS[n]); b.setAttribute('aria-pressed', String(n === cur.color));
      b.addEventListener('click', function () { cur.color = cur.color === n ? 0 : n; stale(); });
      wrap.appendChild(b);
    })(i);
    wrap.appendChild(ctx.el('span', 'cap-val', COLORS[cur.color]));
    return wrap;
  }
  function styleSummary(kind) {
    var c = C.style[kind], parts = [];
    if (c.rating) parts.push('★ ' + c.rating + '점');
    if (c.color) parts.push('색 ' + COLORS[c.color]);
    return parts.length ? parts.join(' · ') : '이름표만';
  }
  function row(label, content) {
    var r = ctx.el('div', 'cap-row'); r.appendChild(ctx.el('span', 'cap-rl', label)); r.appendChild(content); return r;
  }
  function renderChoices(p) {
    section(p, '2', '무엇을 붙일까요?');
    note(p, '이름표는 항상 붙어요. 별점과 색은 주고 싶은 것만 골라요. 안 고르면 그대로 둬요.', 'muted cap-sub');
    KINDS.forEach(function (k) {
      var card = ctx.el('div', 'cap-kcard gcard ' + (k[0] === 'pick' ? 'lime' : k[0] === 'maybe' ? 'lavender' : 'pink'));
      var head = ctx.el('div', 'cap-khead');
      var left = ctx.el('div', 'cap-kleft');
      left.appendChild(ctx.el('b', null, k[1]));
      left.appendChild(ctx.el('span', 'cap-kw', '이름표 ' + k[2]));
      head.appendChild(left);
      head.appendChild(ctx.el('span', 'cap-ksum' + (styleSummary(k[0]) === '이름표만' ? '' : ' on'), styleSummary(k[0])));
      card.appendChild(head);
      card.appendChild(row('별점', stars(null, k[0])));
      card.appendChild(row('색', swatches(k[0])));
      p.appendChild(card);
    });
    var more = ctx.el('details', 'cap-more'); more.open = C.more;
    more.addEventListener('toggle', function () { C.more = more.open; });
    more.appendChild(ctx.el('summary', null, '자세한 설정'));
    function check(text, key) {
      var l = ctx.el('label', 'cap-check'), cb = ctx.el('input'); cb.type = 'checkbox'; cb.checked = C[key];
      cb.addEventListener('change', function () { C[key] = cb.checked; stale(); });
      l.appendChild(cb); l.appendChild(document.createTextNode(' ' + text)); more.appendChild(l);
    }
    check('이미 별점·컬러 태그가 있는 사진도 바꾸기 (끄면 건너뛰어요)', 'overwrite');
    check('Capture One에서 찾은 사진만 반영하기 (못 찾은 사진이 있어도 계속)', 'partial');
    p.appendChild(more);
  }

  /* ---- 결과 ---- */
  function summary(card, r) {
    var kc = r.keyword_counts || {}, st = r.style || {};
    KINDS.forEach(function (k) { if (kc[k[2]]) note(card, k[1] + ' ' + kc[k[2]] + '장 · 키워드 ' + k[2]); });
    var rc = Object.keys(st.rating_counts || {}).map(function (k) { return '★' + k + ' ' + st.rating_counts[k] + '장'; });
    var cc = Object.keys(st.color_counts || {}).map(function (k) { return COLORS[k] + ' ' + st.color_counts[k] + '장'; });
    if (rc.length) note(card, '별점: ' + rc.join(', '));
    if (cc.length) note(card, '컬러 태그: ' + cc.join(', '));
    if (r.already) note(card, '이미 키워드가 있어 건너뜀 ' + r.already + '장');
    if (st.skipped_rating || st.skipped_color) note(card, '이미 값이 있어 건너뜀: 별점 ' + st.skipped_rating + '장, 컬러 태그 ' + st.skipped_color + '장 (자세한 설정에서 바꿀 수 있어요)');
  }
  function names(title, list, total) {
    return title + ' ' + total + '장' + (list.length ? ': ' + list.join(', ') + (total > list.length ? ' …' : '') : '');
  }
  function guide(p, missing) {
    var c = box('bad', 'Capture One에 전용 키워드가 아직 없어요 (아무것도 바꾸지 않았어요)');
    var ul = ctx.el('ul'); missing.forEach(function (k) { ul.appendChild(ctx.el('li', null, k)); }); c.appendChild(ul);
    note(c, '카탈로그나 세션마다 한 번만 직접 만들어요: 도구 탭 → 메타데이터 → 키워드 → 사진 1장 선택 → 이름을 정확히 입력하고 Return. 만든 뒤 "미리보기"를 다시 눌러요.');
    p.appendChild(c);
  }
  function renderApplyResult(p, r) {
    if (r.missing_keywords && r.missing_keywords.length) return guide(p, r.missing_keywords);
    if (r.aborted) { var e = box('bad', r.aborted); p.appendChild(e); }
    if (r.missing_total) note(p, names('Capture One에서 못 찾은 사진', r.missing, r.missing_total), 'err');
    if (r.ambiguous_total) note(p, names('파일 이름이 겹쳐 건너뛰는 사진', r.ambiguous, r.ambiguous_total), 'err');
    if (r.aborted) return;
    var done = r.mode === 'commit';
    var title = done ? (r.applied_files ? '✓ ' + r.applied_files + '장에 반영했어요' : '✓ 새로 붙일 것이 없어요 (이미 모두 반영돼 있어요)')
      : '미리보기예요 · 아직 Capture One에는 아무것도 하지 않았어요';
    var c = box(done ? 'ok' : 'info', title);
    if (!done) note(c, '대상 ' + r.planned + '장 중 ' + r.matched + '장을 Capture One에서 찾았어요' + (r.session ? ' (열려 있는 문서: 세션)' : ''));
    summary(c, r);
    if (done && r.style && r.style.applied) note(c, '별점·컬러 태그도 줬어요.');
    if (done) {
      var d = ctx.el('details', 'cap-more'); d.appendChild(ctx.el('summary', null, '되돌리기 정보'));
      if (r.session) note(d, '세션에는 카탈로그 백업이 없어서, 아래 되돌리기용 기록으로 대신해요.');
      if (r.backup) note(d, r.backup, 'path');
      c.appendChild(d);
    }
    (r.violations || []).concat((r.style && r.style.violations) || []).forEach(function (v) { note(c, '확인 실패: ' + v, 'err'); });
    p.appendChild(c);
  }
  function renderBackResult(p, r) {
    if (r.aborted) return p.appendChild(box('bad', r.aborted));
    var done = r.mode === 'commit';
    var c = box(done ? 'ok' : 'info', done ? '✓ ' + r.stripped_files + '장에서 되돌렸어요' : '되돌리기 미리보기예요 · ' + r.strip_files + '장에서 이 앱이 붙인 키워드를 떼요');
    note(c, '직접 붙인 키워드와, 그 사이 직접 바꾼 별점·태그는 그대로 둬요.');
    var b = r.style;
    if (b && b.has_record) {
      note(c, '별점·컬러 태그: ' + b.restore + '장을 이전 값으로 ' + (b.restored ? '돌렸어요' : '돌려요') +
        (b.already_restored ? ' · 이미 이전 값이라 할 일이 없는 사진 ' + b.already_restored + '장' : '') +
        (b.kept_user_changed ? ' · 그 사이 직접 바꿔서 그대로 두는 사진 ' + b.kept_user_changed + '장' : ''));
    }
    if (r.user_changed) note(c, '반영한 뒤 별점·태그를 바꾼 사진 ' + r.user_changed + '장은 그대로 둬요.');
    (r.violations || []).forEach(function (v) { note(c, '확인 실패: ' + v, 'err'); });
    p.appendChild(c);
  }

  /* ---- 아래 고정 버튼 ---- */
  function foot() {
    var f = ctx.el('div', 'cap-foot'), r = C.res;
    function btn(label, cls, fn) { var x = ctx.el('button', cls, label); x.type = 'button'; x.disabled = C.busy; x.addEventListener('click', fn); f.appendChild(x); return x; }
    var back = r && r.action === 'rollback', dry = r && r.mode === 'dry-run' && !r.aborted;
    if (!back) btn('붙인 것 되돌리기…', 'ghost cap-left', function () { call('rollback', false); });
    f.appendChild(ctx.el('span', 'cap-spacer'));
    var finished = r && r.mode === 'commit' && !r.aborted;   // 반영·되돌리기가 끝났으면 닫기가 주 버튼
    btn('닫기', finished ? 'primary' : 'ghost', close);
    if (finished) return f;
    if (back && dry) {
      btn('되돌리기 확정', 'primary', function () { call('rollback', true); });
    } else if (!back && dry && r.action === 'preview') {
      btn('다시 미리보기', null, function () { call('preview', false); });
      btn('Capture One에 반영', 'primary', function () { call('apply', true); });
    } else {
      btn(C.busy ? '잠시만요…' : '미리보기', 'primary', function () { call('preview', false); });
    }
    return f;
  }

  function renderDocs(body) {
    if (C.docs === null) { note(body, 'Capture One에 열려 있는 것을 찾는 중이에요…'); }
    else if (C.docs.length) {
      var row = ctx.el('div', 'cap-docs');
      C.docs.forEach(function (d) {
        var on = d.name === C.catalog;
        var b = ctx.el('button', 'cap-doc' + (on ? ' on' : ''), (on ? '✓ ' : '') + d.name + ' · ' + (d.kind === 'session' ? '세션' : '카탈로그'));
        b.type = 'button'; b.setAttribute('aria-pressed', String(on));
        b.addEventListener('click', function () { C.catalog = d.name; stale(); });
        row.appendChild(b);
      });
      body.appendChild(row);
      note(body, 'Capture One에서 지금 열려 있는 것이에요. 눌러서 고르세요.');
    } else {
      note(body, C.docsError || 'Capture One에 열린 카탈로그나 세션이 없어요. Capture One에서 먼저 열어 주세요.', 'err');
    }
    var more = ctx.el('details', 'cap-manual'); more.open = !!(C.docs && !C.docs.length);
    more.appendChild(ctx.el('summary', null, '목록에 없으면 이름을 직접 쓰기'));
    var inp = ctx.el('input'); inp.type = 'text'; inp.value = C.catalog; inp.placeholder = '예: sejun.cosessiondb (확장자까지)';
    inp.addEventListener('input', function () { C.catalog = inp.value; });
    more.appendChild(inp); body.appendChild(more);
  }

  /* 위쪽 단계 표시: 지금 어디까지 왔는지 한눈에 (① 어디에 ② 무엇을 ③ 미리보기·결과) */
  function stepper() {
    var at = C.res && !C.res.aborted ? 3 : (C.catalog.trim() ? 2 : 1);
    var w = ctx.el('ol', 'cap-steps');
    [['어디에', 1], ['무엇을', 2], ['결과 확인', 3]].forEach(function (s) {
      var li = ctx.el('li', s[1] < at ? 'done' : s[1] === at ? 'now' : '');
      if (s[1] === at) li.setAttribute('aria-current', 'step');
      li.appendChild(ctx.el('span', 'cap-step-n', s[1] < at ? '✓' : String(s[1])));
      li.appendChild(ctx.el('span', null, s[0]));
      w.appendChild(li);
    });
    return w;
  }

  function render() {
    if (!C) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel cap-panel');
    var head = ctx.el('div', 'cap-head'); head.appendChild(ctx.el('h2', null, 'Capture One에도 표시하기'));
    var x = ctx.el('button', 'ghost cap-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', '닫기'); x.addEventListener('click', close);
    head.appendChild(x); p.appendChild(head);
    p.appendChild(stepper());
    var body = ctx.el('div', 'cap-body');
    section(body, '1', '어디에 붙일까요?');
    renderDocs(body);
    renderChoices(body);
    if (C.busy) { busyBar(body); setTimeout(function () { var r = document.querySelector('.ind'); if (r) r.scrollIntoView({block: 'nearest'}); }, 0); }
    if (C.error) body.appendChild(box('bad', C.error));
    if (C.res) { section(body, '3', '결과'); body.lastChild.className += ' cap-result'; if (C.res.action === 'rollback') renderBackResult(body, C.res); else renderApplyResult(body, C.res); }
    else note(body, '먼저 "미리보기"로 몇 장에 무엇이 붙는지 확인해요. 미리보기는 Capture One을 바꾸지 않아요.', 'muted cap-hint');
    p.appendChild(body); p.appendChild(foot());
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal && !C.busy) close(); });
    if (C.scroll) {   // 결과가 새로 오면 결과가 보이게 내려 준다
      C.scroll = false;
      setTimeout(function () { var r = document.querySelector('.cap-result'); if (r) r.scrollIntoView({block: 'start'}); }, 0);
    }
    return modal;
  }

  root.BcutCapture = {init: init, open: open, isOpen: isOpen, render: render, close: close};
})(window);
