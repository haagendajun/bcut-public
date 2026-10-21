/* 폴더 정리 앱 화면 (Phase 3b S3). 화면 로직(분류·필터·정렬·우선순위 묶음)은 logic.js에 있다. 서버 API는 ui/server.py. */
(function () {
  'use strict';
  var L = window.BcutLogic;
  var Review = window.BcutReview;
  var SortView = window.BcutSortView;
  var Migrate = window.BcutMigrate;
  var Cloud = window.BcutCloud;
  var Capture = window.BcutCapture;
  var Records = window.BcutRecords;
  var Finish = window.BcutFinish;
  var Home = window.BcutHome;
  var Filters = window.BcutFilters;
  var root = document.getElementById('app');
  var TOKEN = root.dataset.token;
  var S = {view: 'start', folder: '', job: null, progress: {done: 0, total: 0}, rows: [], rescued: {}, notice: null,
           mode: 'priority', open: {candidate: true, review: true, rescued: true, normal: false, other: false},
           tier: 'flagged', reason: null, note: null, sort: 'confidence', size: 230, error: null,
           list: [], viewerIndex: -1, full: false, markCount: 0,
           markKinds: {pick: 0, maybe: 0, discard: 0}, markMap: {}, mark: null, listOpen: false};

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  /* 서버가 주는 문장은 개발자 말투라서, 알려진 것은 쉬운 말로 바꿔 보여 준다 */
  var FRIENDLY = [
    ['사진(CR3)이 없다', '이 폴더에는 카메라 원본(RAW) 사진이 없어요. 다른 폴더를 골라 주세요.'],
    ['폴더가 없다', '폴더를 찾을 수 없어요. 경로를 다시 확인해 주세요.'],
    ['절대 경로', '폴더 경로가 올바르지 않아요. "폴더 선택…"으로 골라 주세요.'],
    ['행사 폴더 안이다', '저장할 위치가 사진 폴더 안이에요. 사진 폴더 밖의 다른 곳을 골라 주세요.'],
    ['분석이 아직 끝나지 않았다', '검사가 아직 끝나지 않았어요. 잠시 기다려 주세요.'],
    ['디스크 여유 공간이 부족', '저장 공간이 모자라요. 같은 디스크 안의 폴더를 고르면 공간을 거의 쓰지 않아요.'],
    ['토큰이 필요', '앱과의 연결이 끊겼어요. 앱을 껐다가 다시 켜 주세요.'],
    ['허용되지 않은', '앱과의 연결이 올바르지 않아요. 앱을 껐다가 다시 켜 주세요.'],
    ['이메일 또는 비밀번호', '이메일 또는 비밀번호가 맞지 않거나 로그인이 만료됐어요. 다시 입력해 주세요.'],
    ['먼저 올리기 안내', '먼저 안내에 동의해 주세요.'],
    ['인터넷에 연결하지', '인터넷에 연결되지 않았어요. 연결되면 다시 올라가요.'],
    ['없는 작업', '이전 검사 결과를 찾을 수 없어요. 폴더를 다시 열어 주세요.']
  ];
  function friendly(msg) {
    for (var i = 0; i < FRIENDLY.length; i++) if (String(msg).indexOf(FRIENDLY[i][0]) >= 0) return FRIENDLY[i][1];
    return '문제가 생겼어요. (' + msg + ')';
  }
  function api(method, path, body) {
    var opt = {method: method, headers: {'X-Token': TOKEN}};
    if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(friendly(j.error || ('요청 실패 ' + r.status)));
        return j;
      });
    });
  }
  function url(path) { return path + (path.indexOf('?') < 0 ? '?' : '&') + 't=' + TOKEN; }
  function thumbUrl(f) { return url('/api/jobs/' + S.job + '/thumb/' + encodeURIComponent(f)); }
  function photoUrl(f, size) { return url('/api/jobs/' + S.job + '/photo/' + encodeURIComponent(f) + '?size=' + size); }
  function isFlagged(r) { return r.status === 'candidate' || r.status === 'review'; }

  /* ---- 시작 화면 ---- */
  function chooseFolder() {
    // 앱(Electron)에서는 맥 기본 폴더 창을, 브라우저에서는 서버가 띄우는 창을 쓴다
    if (window.bcutShell && window.bcutShell.chooseFolder) return window.bcutShell.chooseFolder();
    return api('POST', '/api/choose-folder', {}).then(function (j) { return j.folder; });
  }
  function dropPath(file) {
    if (window.bcutShell && window.bcutShell.pathForFile) return window.bcutShell.pathForFile(file);
    return file.path || '';
  }
  function renderStart() {
    var w = el('div', 'wrap');
    var hero = el('div', 'hero');
    hero.appendChild(el('h1', null, 'bcut'));
    hero.appendChild(el('p', 'lead', '행사 사진에서 좋은 컷을 골라요. 눈을 감았거나 흔들린 컷은 도구가 먼저 표시해 줘요.'));
    hero.appendChild(el('div', 'trust', '사진은 이 컴퓨터 밖으로 나가지 않아요 · 원본은 보기만 하고 지우거나 옮기지 않아요'));
    var drop = el('div', 'drop');
    drop.appendChild(el('h2', null, '사진이 들어 있는 폴더를 여기에 끌어다 놓으세요'));
    drop.appendChild(el('p', null, '카메라 원본(RAW, CR3) 사진이 있는 폴더'));
    var pick = el('button', 'primary', '폴더 선택…');
    pick.addEventListener('click', function () {
      chooseFolder().then(function (f) { if (f) startScan(f); }).catch(function (e) { S.error = e.message; render(); });
    });
    drop.appendChild(pick);
    ['dragenter', 'dragover'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
    drop.addEventListener('drop', function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      var p = f ? dropPath(f) : '';
      if (!p) { S.error = '끌어다 놓은 폴더를 알아내지 못했어요. "폴더 선택…"을 누르거나 아래에 폴더 경로를 붙여 넣어 주세요.'; render(); return; }
      startScan(p);
    });
    hero.appendChild(drop);
    var row = el('div', 'pathrow');
    var input = el('input'); input.type = 'text'; input.placeholder = '또는 폴더 경로를 붙여 넣기 (예: /Users/me/photos/행사)'; input.value = S.folder;
    var go = el('button', null, '검사 시작');
    go.addEventListener('click', function () { if (input.value.trim()) startScan(input.value.trim()); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && input.value.trim()) startScan(input.value.trim()); });
    row.appendChild(input); row.appendChild(go); hero.appendChild(row);
    if (S.error) hero.appendChild(el('div', 'err', S.error));
    var steps = el('div', 'steps');
    [['1. 폴더를 고르세요', '사진을 하나씩 검사해요. 400장에 20초쯤 걸려요.'],
     ['2. 훑으며 고르세요', '큰 화면에서 한 장씩 보며 셀렉·보류·버릴 컷을 표시해요.'],
     ['3. 마무리하세요', 'Capture One에 표시하거나, 폴더로 나누어 담아요.']].forEach(function (s) {
      var d = el('div'); d.appendChild(el('b', null, s[0])); d.appendChild(el('span', null, s[1])); steps.appendChild(d);
    });
    hero.appendChild(steps);
    var tools = el('div', 'start-tools'); tools.appendChild(Cloud.chip()); tools.appendChild(Records.button());
    hero.appendChild(tools);
    w.appendChild(hero);
    return w;
  }

  /* ---- 검사 ---- */
  function startScan(folder) {
    S.error = null; S.folder = folder;
    api('POST', '/api/scan', {folder: folder}).then(function (j) {
      S.job = j.job; S.view = 'progress'; S.progress = {done: 0, total: 0}; render(); poll();
    }).catch(function (e) { S.error = e.message; S.view = 'start'; render(); });
  }
  function poll() {
    api('GET', '/api/jobs/' + S.job).then(function (j) {
      S.progress = {done: j.done, total: j.total};
      if (j.state === 'error') { S.error = '사진을 검사하지 못했어요. (' + j.error + ')'; S.view = 'start'; render(); return; }
      if (j.state === 'done') { return loadResults(); }
      render(); setTimeout(poll, 500);
    }).catch(function (e) { S.error = e.message; S.view = 'start'; render(); });
  }
  function loadResults() {
    return api('GET', '/api/jobs/' + S.job + '/results').then(function (j) {
      S.rows = j.rows; S.notice = null; S.view = 'results'; S.mode = 'priority'; S.tier = 'flagged'; S.reason = null; S.note = null;
      S.open = {candidate: true, review: true, rescued: true, normal: false, other: false}; render();
      Migrate.toPicks(S.folder, S.rows, api, S.job).then(function (n) {
        if (n) S.notice = '이전에 남겨 둔 사진 ' + n + '장을 셀렉으로 옮겼어요.';
        refreshMarkCount();
      });
    });
  }
  /* ---- 훑기 모드 (review.js) ---- */
  function refreshMarkCount() {
    api('GET', '/api/jobs/' + S.job + '/marks').then(function (j) {
      S.markCount = j.marks.length;
      S.markKinds = {pick: 0, maybe: 0, discard: 0};
      S.markMap = {};
      j.marks.forEach(function (m) { S.markKinds[m.kind] = (S.markKinds[m.kind] || 0) + 1; S.markMap[m.file] = m.kind; });
      render();
    }).catch(function () {});
  }
  function startReview() {
    api('GET', '/api/jobs/' + S.job + '/marks').then(function (j) { Review.open(S.rows, j.marks); })
      .catch(function (e) { S.error = e.message; render(); });
  }
  Review.init({el: el, api: api, job: function () { return S.job; }, thumbUrl: thumbUrl, photoUrl: photoUrl,
               rerender: function () { render(); }, finishWith: function (kind) { if (kind === 'capture') Capture.open(); else SortView.open(); },
               onClose: function () { render(); refreshMarkCount(); }});
  // 앱 메뉴의 "실행 취소"(⌘Z)가 훑는 중이면 직전 표시를 되돌린다. 아니면 기본 동작(글자 입력 되돌리기)을 그대로 둔다
  window.addEventListener('bcut-undo', function (e) { if (Review.undo()) e.preventDefault(); });

  function renderProgress() {
    var w = el('div', 'wrap'); var c = el('div', 'center');
    c.appendChild(el('h1', null, '사진을 검사하는 중이에요…'));
    c.appendChild(el('p', 'muted', S.folder));
    var bar = el('div', 'progress'); var inner = el('div');
    var pct = S.progress.total ? Math.round(100 * S.progress.done / S.progress.total) : 0;
    inner.style.width = pct + '%'; bar.appendChild(inner); c.appendChild(bar);
    c.appendChild(el('p', 'muted', S.progress.done + ' / ' + S.progress.total + '장 (' + pct + '%)'));
    w.appendChild(c);
    return w;
  }

  /* ---- 결과 화면 ---- */
  function itemFor(r, index) {
    var rescued = L.isRescued(r, S.rescued);
    var it = el('div', 'item' + (rescued ? ' saved' : ''));
    var im = el('div', 'img loading'); im.tabIndex = 0;
    var img = document.createElement('img'); img.loading = 'lazy'; img.alt = r.file;
    function loaded() { im.classList.remove('loading'); }
    img.addEventListener('load', loaded); img.addEventListener('error', loaded);
    img.src = thumbUrl(r.file);
    if (img.complete) loaded();
    im.appendChild(img);
    var tier = L.tierOf(r, S.rescued);
    var mk = S.markMap[r.file];
    if (mk) im.appendChild(el('span', 'mark-tag m-' + mk, mk === 'pick' ? '★ 셀렉' : mk === 'maybe' ? '? 보류' : '✕ 버릴 컷'));
    if (tier === 'candidate') im.appendChild(el('span', 'tag t1', '1순위'));
    else if (tier === 'review') im.appendChild(el('span', 'tag t2', '2순위'));
    function open() { openViewer(index); }
    im.addEventListener('click', open);
    im.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    it.appendChild(im);
    var body = el('div', 'body');
    var lines = L.explain(r, S.rescued);
    var why = el('div', 'why', lines[0]);
    var rest = lines.slice(1).join(' ');
    var flagged = !rescued && isFlagged(r);
    if (flagged && L.suspicion(r.confidence)) rest = (rest ? rest + ' ' : '') + '의심 정도 ' + L.suspicion(r.confidence);
    if (rest) why.appendChild(el('small', null, rest));
    body.appendChild(why);
    var b = el('div', 'row');
    L.badges(r, S.rescued).forEach(function (x, i) {
      if (i === 0 && flagged) return;   // 등급은 사진 위 표시(1순위·2순위)로 보여 준다
      var sp = el('span', 'badge ' + x.cls, x.text); if (x.tip) sp.title = x.tip; b.appendChild(sp);
    });
    if (b.childNodes.length) body.appendChild(b);
    body.appendChild(el('div', 'name', r.file));
    it.appendChild(body);
    return it;
  }
  function gridOf(rows, startIndex) {
    var grid = el('div', 'grid'); grid.style.setProperty('--w', S.size + 'px');
    rows.forEach(function (r, i) { grid.appendChild(itemFor(r, startIndex + i)); });
    return grid;
  }
  function renderPriority(w) {
    var groups = L.priorityGroups(S.rows, S.rescued);
    S.list = L.visibleOrder(groups, S.open);
    var idx = 0, shown = 0;
    groups.forEach(function (g) {
      if (!g.rows.length) return;
      shown += 1;
      var sec = el('section', 'section');
      var head = el('div', 'section-head');
      head.appendChild(el('div', 'rank r' + g.rank, g.rank === 0 ? '남' : g.rank === 3 ? '–' : String(g.rank)));
      var txt = el('div', 'txt'); var h = el('h2', null, g.title + (g.sub ? ' · ' + g.sub : ''));
      h.appendChild(el('span', 'n', g.rows.length + '장')); txt.appendChild(h); txt.appendChild(el('p', null, g.desc)); head.appendChild(txt);
      var tog = el('button', 'ghost', S.open[g.id] ? '접기' : '펼쳐서 보기');
      tog.addEventListener('click', function () { S.open[g.id] = !S.open[g.id]; render(); });
      head.appendChild(tog); sec.appendChild(head);
      if (S.open[g.id]) { sec.appendChild(gridOf(g.rows, idx)); idx += g.rows.length; }
      else sec.appendChild(el('div', 'collapsed-note', g.rows.length + '장이 접혀 있어요.'));
      w.appendChild(sec);
    });
    if (!shown) w.appendChild(el('div', 'empty', '보여 줄 사진이 없어요.'));
  }
  /* 보기 전환 알약이 이전 자리에서 새 자리로 미끄러진다 (동작 줄이기를 켜면 그냥 바뀐다) */
  function slideSeg() {
    var from = S.segFrom; S.segFrom = null;
    if (from == null || !window.matchMedia || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    requestAnimationFrame(function () {
      var now = document.querySelector('.res-details .seg [aria-pressed=true]');
      if (!now || !now.animate) return;
      var dx = from - now.getBoundingClientRect().left;
      if (Math.abs(dx) > 1) now.animate([{transform: 'translateX(' + dx + 'px)'}, {transform: 'none'}], {duration: 260, easing: 'ease-out'});
    });
  }
  function renderAll(w, c) {
    Filters.render({el: el, S: S, L: L, render: render, gridOf: gridOf}, w, c);
  }
  function renderResults() {
    var w = el('div', 'wrap');
    var c = L.counts(S.rows, S.rescued);
    var bar = el('div', 'appbar');
    var title = el('div', 'title');
    title.appendChild(el('h1', null, S.folder.split('/').filter(Boolean).pop() || S.folder));
    title.appendChild(el('div', 'sub', S.folder + ' · 사진 ' + c.total + '장'));
    bar.appendChild(title);
    var act = el('div', 'actions');
    var other = el('button', 'ghost', '다른 폴더 열기');
    other.addEventListener('click', function () { S.view = 'start'; S.rows = []; S.listOpen = false; render(); });
    var sortBtn = el('button', null, '마무리하기…');
    sortBtn.addEventListener('click', function () { Finish.open(); });
    var reviewBtn = el('button', 'lime', S.markCount ? '이어서 훑기' : '훑기 시작');
    reviewBtn.addEventListener('click', startReview);
    act.appendChild(Home.moreMenu([Cloud.chip(), Records.button(), other], render));
    act.appendChild(sortBtn); act.appendChild(reviewBtn); bar.appendChild(act);
    w.appendChild(bar);
    if (S.notice) w.appendChild(el('div', 'notice', S.notice));
    w.appendChild(Home.hero(c, S.markKinds));
    w.appendChild(Home.compact(c));
    var det = el('details', 'res-details'); det.open = S.listOpen;
    det.addEventListener('toggle', function () { S.listOpen = det.open; });
    det.appendChild(el('summary', null, '검사 결과를 목록으로 보기 (우선순위·전체)'));
    var tb = el('div', 'toolbar');
    var seg = el('div', 'seg');
    [['priority', '우선순위로 보기'], ['all', '전체 목록']].forEach(function (m) {
      var b = el('button', null, m[1]); b.setAttribute('aria-pressed', String(S.mode === m[0]));
      b.addEventListener('click', function () {
        var cur = seg.querySelector('[aria-pressed=true]');
        S.segFrom = cur ? cur.getBoundingClientRect().left : null;
        S.mode = m[0]; render(); slideSeg();
      }); seg.appendChild(b);
    });
    tb.appendChild(seg); tb.appendChild(el('span', 'grow'));
    tb.appendChild(el('label', null, '사진 크기'));
    var rg = el('input'); rg.type = 'range'; rg.min = 150; rg.max = 360; rg.step = 10; rg.value = S.size;
    rg.addEventListener('input', function () { S.size = +rg.value; document.querySelectorAll('.grid').forEach(function (g) { g.style.setProperty('--w', S.size + 'px'); }); });
    tb.appendChild(rg);
    det.appendChild(tb);
    var lw = det;
    if (S.mode === 'priority') renderPriority(lw); else renderAll(lw, c);
    w.appendChild(det);
    det.appendChild(el('p', 'note', '"이상 없음"은 눈 감김·너무 밝거나 어두움·흔들림·초점에서 문제가 안 보인다는 뜻이고, 좋은 사진이라는 뜻은 아니에요. 사진을 누르면 크게 볼 수 있고, "훑기 시작"을 누르면 한 장씩 넘기며 셀렉·보류·버릴 컷을 표시할 수 있어요.'));
    return w;
  }

  /* ---- 크게 보기 ---- */
  function openViewer(i) { S.viewerIndex = i; S.full = false; render(); }
  function closeViewer() { S.viewerIndex = -1; render(); }
  function renderViewer() {
    var r = S.list[S.viewerIndex];
    if (!r) return null;
    var o = el('div', 'overlay');
    var top = el('div', 'top');
    top.appendChild(el('strong', null, r.file));
    top.appendChild(el('span', null, L.badges(r, S.rescued).map(function (x) { return x.text; }).join(' · ')));
    top.appendChild(el('span', null, (S.viewerIndex + 1) + ' / ' + S.list.length));
    function btn(label, fn, cls) { var b = el('button', cls || null, label); b.addEventListener('click', fn); top.appendChild(b); return b; }
    btn('← 이전', function () { S.viewerIndex = L.step(S.list.length, S.viewerIndex, -1); S.full = false; render(); });
    btn('다음 →', function () { S.viewerIndex = L.step(S.list.length, S.viewerIndex, 1); S.full = false; render(); });
    btn(S.full ? '화면에 맞추기 (Z)' : '크게 보기 100% (Z)', function () { S.full = !S.full; render(); });
    btn('닫기 (Esc)', closeViewer);
    o.appendChild(top);
    o.appendChild(el('div', 'why', L.explain(r, S.rescued).join(' ')));
    var stage = el('div', 'stage' + (S.full ? ' full' : ''));
    var img = document.createElement('img'); img.alt = r.file; img.src = photoUrl(r.file, S.full ? 'full' : 'view');
    stage.appendChild(img); o.appendChild(stage);
    return o;
  }

  SortView.init({el: el, api: api, job: function () { return S.job; }, chooseFolder: chooseFolder, friendly: friendly,
                 rerender: function () { render(); }});

  Cloud.init({el: el, api: api, rerender: function () { render(); }});
  Capture.init({el: el, api: api, job: function () { return S.job; }, rerender: function () { render(); }});
  Records.init({el: el, api: api, rerender: function () { render(); }});
  Home.init({el: el}, function () { render(); });
  Finish.init({el: el, markCount: function () { return S.markCount; }, openSort: function () { SortView.open(); },
               openCapture: function () { Capture.open(); }, rerender: function () { render(); }});
  document.addEventListener('bcut-records-changed', function () { if (S.job) refreshMarkCount(); });

  /* ---- 그리기 ---- */
  function render() {
    var scroll = window.scrollY;
    root.textContent = '';
    var main = S.view === 'results' ? renderResults() : S.view === 'progress' ? renderProgress() : renderStart();
    root.appendChild(main);
    var v = S.viewerIndex >= 0 ? renderViewer() : null; if (v) root.appendChild(v);
    var rv = Review.render(); if (rv) root.appendChild(rv);
    document.body.classList.toggle('lt-open', Review.isOpen());
    var m = SortView.render(); if (m) root.appendChild(m);
    var cm = Cloud.render(); if (cm) root.appendChild(cm);
    var cp = Capture.render(); if (cp) root.appendChild(cp);
    var rc = Records.render(); if (rc) root.appendChild(rc);
    var fn = Finish.render(); if (fn) root.appendChild(fn);
    window.scrollTo(0, scroll);
  }
  document.addEventListener('keydown', function (e) {
    if (Review.isOpen()) { if (Review.handleKey(e)) e.preventDefault(); return; }
    if (e.key === 'Escape') {   // 열려 있는 창을 Esc로 닫는다
      var top = [Capture, Records, Finish, Cloud, SortView].filter(function (m) { return m.isOpen(); })[0];
      if (top) { top.close(); e.preventDefault(); return; }
    }
    if (S.viewerIndex < 0 || SortView.isOpen()) return;
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowRight') { S.viewerIndex = L.step(S.list.length, S.viewerIndex, 1); S.full = false; render(); }
    else if (e.key === 'ArrowLeft') { S.viewerIndex = L.step(S.list.length, S.viewerIndex, -1); S.full = false; render(); }
    else if ((e.key === 'z' || e.key === 'Z')) { S.full = !S.full; render(); }
  });
  // 앱 메뉴 '파일 > 폴더 열기…'에서 고른 폴더
  if (window.bcutShell && window.bcutShell.onOpenFolder) window.bcutShell.onOpenFolder(function (p) { startScan(p); });
  render();
})();
