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
  var root = document.getElementById('app');
  var TOKEN = root.dataset.token;
  var S = {view: 'start', folder: '', job: null, progress: {done: 0, total: 0}, rows: [], rescued: {}, notice: null,
           mode: 'priority', open: {candidate: true, review: true, rescued: true, normal: false, other: false},
           tier: 'flagged', reason: null, note: null, sort: 'confidence', size: 230, error: null,
           list: [], viewerIndex: -1, full: false, markCount: 0};

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
    hero.appendChild(el('p', 'lead', '행사 사진에서 눈을 감았거나 흔들린 사진처럼 버릴 만한 컷을 찾아서, 폴더로 나누어 줘요.'));
    hero.appendChild(el('div', 'trust', '사진은 이 컴퓨터 밖으로 나가지 않아요 · 원본은 보기만 하고 지우거나 옮기지 않아요'));
    hero.appendChild(Cloud.chip()); hero.appendChild(Records.button());
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
     ['2. 먼저 볼 컷부터 확인하세요', '문제가 분명한 컷이 맨 위에 나와요.'],
     ['3. 폴더로 나누어 담으세요', '버릴 것 같은 컷, 직접 확인, 이상 없음으로 사본을 나눠요.']].forEach(function (s) {
      var d = el('div'); d.appendChild(el('b', null, s[0])); d.appendChild(el('span', null, s[1])); steps.appendChild(d);
    });
    hero.appendChild(steps);
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
    api('GET', '/api/jobs/' + S.job + '/marks').then(function (j) { S.markCount = j.marks.length; render(); }).catch(function () {});
  }
  function startReview() {
    api('GET', '/api/jobs/' + S.job + '/marks').then(function (j) { Review.open(S.rows, j.marks); })
      .catch(function (e) { S.error = e.message; render(); });
  }
  Review.init({el: el, api: api, job: function () { return S.job; }, thumbUrl: thumbUrl, photoUrl: photoUrl,
               rerender: function () { render(); }, openSort: function () { SortView.open(); },
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
    var im = el('div', 'img'); im.tabIndex = 0;
    var img = document.createElement('img'); img.loading = 'lazy'; img.alt = r.file; img.src = thumbUrl(r.file);
    im.appendChild(img);
    var tier = L.tierOf(r, S.rescued);
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
  function overview(c) {
    var ov = el('div', 'overview');
    var left = c.candidate + c.review;
    ov.appendChild(el('h2', 'headline', left ? '먼저 확인할 컷이 ' + left + '장 있어요' : '확인할 컷이 없어요'));
    ov.appendChild(el('p', 'lead', '사진 ' + c.total + '장을 검사했어요. 아래에서 위부터 차례로 보면 중요한 것부터 끝나요.'));
    var meter = el('div', 'meter');
    var parts = [['candidate', 'var(--p1)', '버릴 것 같은 컷'], ['review', 'var(--p2)', '직접 확인'],
                 ['normal', 'var(--ok)', '이상 없음'], ['other', 'var(--faint)', '얼굴 없음·판단 못 함']];
    parts.forEach(function (p) {
      if (!c[p[0]]) return;
      var s = el('span', 'm-' + p[0]); s.style.flex = String(c[p[0]]); s.title = p[2] + ' ' + c[p[0]] + '장'; meter.appendChild(s);
    });
    ov.appendChild(meter);
    var lg = el('div', 'legend');
    parts.forEach(function (p) {
      var k = el('span', 'k'); var dot = el('span', 'dot'); dot.style.background = p[1]; k.appendChild(dot);
      k.appendChild(document.createTextNode(p[2] + ' ')); k.appendChild(el('b', null, String(c[p[0]]))); lg.appendChild(k);
    });
    ov.appendChild(lg);
    return ov;
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
  function renderAll(w, c) {
    var chips = el('div', 'chips');
    L.TIERS.forEach(function (t) {
      var n = L.filterRows(S.rows, S.rescued, {tier: t[0]}).length;
      var b = el('button', null, t[1] + ' ' + n); b.setAttribute('aria-pressed', String(S.tier === t[0]));
      b.addEventListener('click', function () { S.tier = t[0]; render(); }); chips.appendChild(b);
    });
    var tb = el('div', 'toolbar'); tb.appendChild(chips); w.appendChild(tb);
    var rs = Object.keys(c.reasons);
    if (rs.length) {
      var rb = el('div', 'toolbar'); rb.appendChild(el('label', null, '문제 종류'));
      var rc = el('div', 'chips');
      rs.forEach(function (k) {
        var b = el('button', null, (L.REASON[k] || k) + ' ' + c.reasons[k]); b.setAttribute('aria-pressed', String(S.reason === k));
        b.addEventListener('click', function () { S.reason = S.reason === k ? null : k; render(); }); rc.appendChild(b);
      });
      rb.appendChild(rc); w.appendChild(rb);
    }
    var ctl = el('div', 'toolbar');
    ctl.appendChild(el('label', null, '순서'));
    var sel = el('select');
    [['confidence', '의심 정도 높은 순'], ['score', '눈이 많이 감긴 순'], ['name', '파일 이름순'], ['faces', '사람 많은 순']].forEach(function (o) {
      var op = el('option', null, o[1]); op.value = o[0]; if (S.sort === o[0]) op.selected = true; sel.appendChild(op);
    });
    sel.addEventListener('change', function () { S.sort = sel.value; render(); });
    ctl.appendChild(sel); w.appendChild(ctl);
    S.list = L.sortRows(L.filterRows(S.rows, S.rescued, {tier: S.tier, reason: S.reason, note: S.note}), S.sort);
    w.appendChild(el('p', 'count', '지금 보이는 사진 ' + S.list.length + '장 / 전체 ' + c.total + '장'));
    if (!S.list.length) w.appendChild(el('div', 'empty', '이 조건에 맞는 사진이 없어요.'));
    else w.appendChild(gridOf(S.list, 0));
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
    other.addEventListener('click', function () { S.view = 'start'; S.rows = []; render(); });
    var sortBtn = el('button', null, '폴더로 나누어 담기…');
    sortBtn.addEventListener('click', function () { SortView.open(); });
    var reviewBtn = el('button', 'primary', S.markCount ? '이어서 훑기' : '훑기 시작');
    reviewBtn.addEventListener('click', startReview);
    act.appendChild(Cloud.chip()); act.appendChild(Records.button()); act.appendChild(other); act.appendChild(sortBtn); act.appendChild(reviewBtn); bar.appendChild(act);
    w.appendChild(bar);
    if (S.notice) w.appendChild(el('div', 'notice', S.notice));
    w.appendChild(overview(c));
    var tb = el('div', 'toolbar');
    var seg = el('div', 'seg');
    [['priority', '우선순위로 보기'], ['all', '전체 목록']].forEach(function (m) {
      var b = el('button', null, m[1]); b.setAttribute('aria-pressed', String(S.mode === m[0]));
      b.addEventListener('click', function () { S.mode = m[0]; render(); }); seg.appendChild(b);
    });
    tb.appendChild(seg); tb.appendChild(el('span', 'grow'));
    tb.appendChild(el('label', null, '사진 크기'));
    var rg = el('input'); rg.type = 'range'; rg.min = 150; rg.max = 360; rg.step = 10; rg.value = S.size;
    rg.addEventListener('input', function () { S.size = +rg.value; document.querySelectorAll('.grid').forEach(function (g) { g.style.setProperty('--w', S.size + 'px'); }); });
    tb.appendChild(rg);
    w.appendChild(tb);
    if (S.mode === 'priority') renderPriority(w); else renderAll(w, c);
    w.appendChild(el('p', 'note', '"이상 없음"은 눈 감김·너무 밝거나 어두움·흔들림·초점에서 문제가 안 보인다는 뜻이고, 좋은 사진이라는 뜻은 아니에요. 사진을 누르면 크게 볼 수 있고, "훑기 시작"을 누르면 한 장씩 넘기며 셀렉·보류·버릴 컷을 표시할 수 있어요.'));
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
    window.scrollTo(0, scroll);
  }
  document.addEventListener('keydown', function (e) {
    if (Review.isOpen()) { if (Review.handleKey(e)) e.preventDefault(); return; }
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
