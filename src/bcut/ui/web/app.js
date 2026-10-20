/* 폴더 정리 앱 화면 (Phase 3b S3). 화면 로직(분류·필터·정렬·우선순위 묶음)은 logic.js에 있다. 서버 API는 ui/server.py. */
(function () {
  'use strict';
  var L = window.BcutLogic;
  var root = document.getElementById('app');
  var TOKEN = root.dataset.token;
  var S = {view: 'start', folder: '', job: null, progress: {done: 0, total: 0}, rows: [], rescued: {},
           mode: 'priority', open: {candidate: true, review: true, rescued: true, normal: false, other: false},
           tier: 'flagged', reason: null, note: null, sort: 'confidence', size: 230, error: null,
           list: [], viewerIndex: -1, full: false, sortModal: null};

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

  /* ---- 남기기 기억 (이 컴퓨터의 브라우저 저장소에만) ---- */
  function rescueKey() { return 'bcut-rescue:' + S.folder; }
  function loadRescued() {
    S.rescued = {};
    try { var raw = localStorage.getItem(rescueKey()); if (raw) JSON.parse(raw).forEach(function (f) { S.rescued[f] = true; }); } catch (e) {}
  }
  function saveRescued() { try { localStorage.setItem(rescueKey(), JSON.stringify(Object.keys(S.rescued))); } catch (e) {} }
  function toggleRescue(file) {
    if (S.rescued[file]) delete S.rescued[file]; else S.rescued[file] = true;
    saveRescued(); render();
  }

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
      S.rows = j.rows; loadRescued(); S.view = 'results'; S.mode = 'priority'; S.tier = 'flagged'; S.reason = null; S.note = null;
      S.open = {candidate: true, review: true, rescued: true, normal: false, other: false}; render();
    });
  }
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
    else if (tier === 'rescued') im.appendChild(el('span', 'tag t0', '남김'));
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
    if (isFlagged(r)) {
      var btn = el('button', 'keep', rescued ? '남기기 취소' : '남기기');
      btn.addEventListener('click', function () { toggleRescue(r.file); });
      body.appendChild(btn);
    }
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
    var parts = [['candidate', 'var(--p1)', '버릴 것 같은 컷'], ['review', 'var(--p2)', '직접 확인'], ['rescued', 'var(--accent)', '남긴 컷'],
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
    w.appendChild(el('p', 'count', '지금 보이는 사진 ' + S.list.length + '장 / 전체 ' + c.total + '장 · 남기기로 한 컷 ' + c.rescued + '장'));
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
    var sortBtn = el('button', 'primary', '폴더로 나누어 담기…');
    sortBtn.addEventListener('click', openSort);
    act.appendChild(other); act.appendChild(sortBtn); bar.appendChild(act);
    w.appendChild(bar);
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
    w.appendChild(el('p', 'note', '"이상 없음"은 눈 감김·너무 밝거나 어두움·흔들림·초점에서 문제가 안 보인다는 뜻이고, 좋은 사진이라는 뜻은 아니에요. 사진을 누르면 크게 볼 수 있고, "남기기"한 컷은 나누어 담을 때 "이상 없음" 폴더로 가요.'));
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
    if (isFlagged(r)) btn(L.isRescued(r, S.rescued) ? '남기기 취소 (R)' : '남기기 (R)', function () { toggleRescue(r.file); }, 'primary');
    btn('닫기 (Esc)', closeViewer);
    o.appendChild(top);
    o.appendChild(el('div', 'why', L.explain(r, S.rescued).join(' ')));
    var stage = el('div', 'stage' + (S.full ? ' full' : ''));
    var img = document.createElement('img'); img.alt = r.file; img.src = photoUrl(r.file, S.full ? 'full' : 'view');
    stage.appendChild(img); o.appendChild(stage);
    return o;
  }

  /* ---- 정리 흐름 ---- */
  function openSort() { S.sortModal = {out: null, byReason: true, plan: null, result: null, busy: true, error: null}; render(); previewSort(); }
  function sortRequest(commit) {
    var m = S.sortModal;
    var body = {rescue: L.rescuedNames(S.rows, S.rescued), commit: commit, by_reason: m.byReason};
    if (m.out) body.out = m.out;
    return api('POST', '/api/jobs/' + S.job + '/sort', body);
  }
  function previewSort() {
    var m = S.sortModal; m.busy = true; m.error = null; render();
    sortRequest(false).then(function (j) { m.plan = j; if (!m.out) m.out = j.out_root; m.busy = false; render(); })
      .catch(function (e) { m.error = e.message; m.busy = false; render(); });
  }
  function commitSort() {
    var m = S.sortModal; m.busy = true; m.error = null; render();
    sortRequest(true).then(function (j) { m.result = j; m.busy = false; render(); })
      .catch(function (e) { m.error = e.message; m.busy = false; render(); });
  }
  function renderSort() {
    var m = S.sortModal; if (!m) return null;
    var modal = el('div', 'modal'); var p = el('div', 'panel');
    p.appendChild(el('h2', null, m.result ? '다 담았어요' : '폴더로 나누어 담기'));
    if (m.error) p.appendChild(el('div', 'err', m.error));
    if (m.result) {
      var r = m.result;
      p.appendChild(el('p', null, '원본은 그대로예요. 아래 새 폴더에 사본을 나누어 담았어요. 폴더를 열어서 확인해 보세요.'));
      p.appendChild(el('div', 'path', r.result_dir || ''));
      L.planLines(r).forEach(function (t) { p.appendChild(el('div', 'muted', t)); });
      if (r.aborted) p.appendChild(el('div', 'err', friendly(r.aborted)));
      if (r.mismatches && r.mismatches.length) p.appendChild(el('div', 'err', '원본과 크기가 다른 사본이 ' + r.mismatches.length + '개 있어요. 폴더를 지우고 다시 담아 주세요.'));
      var row = el('div', 'row');
      var open = el('button', 'primary', 'Finder에서 열기');
      open.addEventListener('click', function () { api('POST', '/api/reveal', {path: r.result_dir}).catch(function (e) { m.error = e.message; render(); }); });
      var close = el('button', null, '닫기'); close.addEventListener('click', function () { S.sortModal = null; render(); });
      row.appendChild(open); row.appendChild(close); p.appendChild(row);
    } else {
      var pl = m.plan;
      if (pl) {
        p.appendChild(el('p', null, '사진 ' + pl.photos + '장을 아래처럼 폴더에 나누어 담아요 (사본 ' + pl.placements + '개). 원본은 건드리지 않아요.'));
        var ul = el('ul'); L.planLines(pl).forEach(function (t) { ul.appendChild(el('li', null, t)); }); p.appendChild(ul);
        if (pl.rescued.length) p.appendChild(el('div', 'muted', '남기기로 한 컷 ' + pl.rescued.length + '장은 "이상 없음" 폴더로 가요.'));
        p.appendChild(el('div', 'muted', pl.method === 'clone' ? '빠르게 복사해요 (저장 공간을 거의 쓰지 않아요)' :
          '복사해요 (저장 공간이 약 ' + L.formatBytes(pl.needs_space) + ' 필요해요)'));
        if (pl.missing.length) p.appendChild(el('div', 'err', '검사한 뒤 사라진 사진 ' + pl.missing.length + '장은 빼고 담아요.'));
        if (pl.aborted) p.appendChild(el('div', 'err', friendly(pl.aborted)));
      }
      p.appendChild(el('div', 'muted', '저장할 위치'));
      p.appendChild(el('div', 'path', m.out || '…'));
      var chk = el('label'); var cb = el('input'); cb.type = 'checkbox'; cb.checked = m.byReason;
      cb.addEventListener('change', function () { m.byReason = cb.checked; previewSort(); });
      chk.appendChild(cb); chk.appendChild(document.createTextNode(' 문제 종류별 폴더도 만들기 (눈 감김, 흔들려 찍힘 등)')); p.appendChild(chk);
      var row2 = el('div', 'row');
      var change = el('button', null, '위치 바꾸기…');
      change.addEventListener('click', function () { chooseFolder().then(function (f) { if (f) { m.out = f; previewSort(); } }); });
      var cancel = el('button', null, '취소'); cancel.addEventListener('click', function () { S.sortModal = null; render(); });
      var go = el('button', 'primary', m.busy ? '잠시만요…' : '나누어 담기');
      go.disabled = m.busy || !pl || !!pl.aborted || !pl.photos; go.addEventListener('click', commitSort);
      row2.appendChild(change); row2.appendChild(cancel); row2.appendChild(go); p.appendChild(row2);
    }
    modal.appendChild(p);
    return modal;
  }

  /* ---- 그리기 ---- */
  function render() {
    var scroll = window.scrollY;
    root.textContent = '';
    var main = S.view === 'results' ? renderResults() : S.view === 'progress' ? renderProgress() : renderStart();
    root.appendChild(main);
    var v = S.viewerIndex >= 0 ? renderViewer() : null; if (v) root.appendChild(v);
    var m = renderSort(); if (m) root.appendChild(m);
    window.scrollTo(0, scroll);
  }
  document.addEventListener('keydown', function (e) {
    if (S.viewerIndex < 0 || S.sortModal) return;
    var r = S.list[S.viewerIndex];
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowRight') { S.viewerIndex = L.step(S.list.length, S.viewerIndex, 1); S.full = false; render(); }
    else if (e.key === 'ArrowLeft') { S.viewerIndex = L.step(S.list.length, S.viewerIndex, -1); S.full = false; render(); }
    else if ((e.key === 'z' || e.key === 'Z')) { S.full = !S.full; render(); }
    else if ((e.key === 'r' || e.key === 'R') && r && isFlagged(r)) toggleRescue(r.file);
  });
  // 앱 메뉴 '파일 > 폴더 열기…'에서 고른 폴더
  if (window.bcutShell && window.bcutShell.onOpenFolder) window.bcutShell.onOpenFolder(function (p) { startScan(p); });
  render();
})();
