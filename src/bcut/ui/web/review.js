/* 훑기 모드 화면 (spec FR-21·22). 어두운 "라이트 테이블": 큰 사진 + 오른쪽 정보 + 아래 필름스트립.
   순수 로직은 review_logic.js, 표시 저장은 서버(ui/marks.py). app.js가 init으로 도구를 넘겨 준다. */
(function (root) {
  'use strict';
  var RL = root.BcutReviewLogic, L = root.BcutLogic;
  var ctx = null;   // {el, api, job, thumbUrl, photoUrl, rerender, onClose}
  var R = null;     // 훑는 중일 때만 있는 상태: {rows, marks, index, seen, skip, full, msg}
  var RADIUS = 12;  // 필름스트립은 지금 사진 앞뒤 12장만 그린다
  var KEEP = 10;    // 큰 사진은 메모리에 최근 10장만 둔다

  /* 사진을 메모리에만 받아 둔다 (디스크 캐시 없음). 키를 눌러 화면을 다시 그려도 깜빡이지 않고, 다음 사진은 미리 받는다 */
  var blobs = {}, pending = {}, photoOrder = [];
  function blobUrl(url, heavy) {
    if (blobs[url]) return Promise.resolve(blobs[url]);
    if (!pending[url]) {
      pending[url] = fetch(url).then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.blob(); })
        .then(function (b) {
          var u = URL.createObjectURL(b); blobs[url] = u; delete pending[url];
          if (heavy) {
            photoOrder.push(url);
            while (photoOrder.length > KEEP) { var old = photoOrder.shift(); URL.revokeObjectURL(blobs[old]); delete blobs[old]; }
          }
          return u;
        }).catch(function (e) { delete pending[url]; throw e; });
    }
    return pending[url];
  }
  function show(img, url, heavy) {
    if (blobs[url]) { img.src = blobs[url]; return; }
    blobUrl(url, heavy).then(function (u) { if (img.isConnected) img.src = u; }).catch(function () {});
  }
  function forgetBlobs() {
    Object.keys(blobs).forEach(function (k) { URL.revokeObjectURL(blobs[k]); });
    blobs = {}; pending = {}; photoOrder = [];
  }

  function init(c) { ctx = c; }
  function isOpen() { return R !== null; }
  function see() { R.seen[R.index] = true; }

  function open(rows, markList) {
    var ordered = RL.order(rows), marks = RL.marksMap(markList);
    R = {rows: ordered, marks: marks, index: RL.resumeIndex(ordered, marks), seen: {}, skip: false, full: false, msg: ''};
    see(); ctx.rerender();
  }
  function close() {
    var done = R ? RL.counts(R.rows, R.marks) : null;
    R = null; forgetBlobs(); ctx.onClose(done);
  }
  function go(delta) {
    var i = RL.move(R.rows, R.index, delta, R.skip);
    R.msg = i === R.index ? (delta > 0 ? '마지막 사진이에요.' : '처음 사진이에요.') : '';
    R.index = i; R.full = false; see(); ctx.rerender();
  }
  function jump(i) { R.index = i; R.full = false; R.msg = ''; see(); ctx.rerender(); }

  /* 표시를 달고 바로 저장한다. 저장에 실패하면 되돌리고 그 사진으로 돌아온다 */
  function mark(pressed) {
    var row = R.rows[R.index], key = RL.markKey(row), before = R.marks[key] || null;
    var next = RL.nextMark(before, pressed), from = R.index;
    if (next) R.marks[key] = next; else delete R.marks[key];
    R.index = RL.move(R.rows, R.index, 1, R.skip);
    R.msg = R.index === from ? '마지막 사진이에요.' : '';
    R.full = false; see(); ctx.rerender();
    ctx.api('POST', '/api/jobs/' + ctx.job() + '/marks', {file: row.file, kind: next}).catch(function (e) {
      if (!R) return;
      if (before) R.marks[key] = before; else delete R.marks[key];
      R.index = from; R.msg = '표시를 저장하지 못했어요. 다시 눌러 주세요. (' + e.message + ')'; ctx.rerender();
    });
  }

  function handleKey(e) {   // 쓴 키면 true
    if (!R || e.metaKey || e.ctrlKey || e.altKey) return false;
    var k = String(e.key).toLowerCase();
    if (e.key === 'Escape') { close(); return true; }
    if (e.key === 'ArrowRight') { go(1); return true; }
    if (e.key === 'ArrowLeft') { go(-1); return true; }
    if (RL.KEY_TO_KIND[k]) { if (!e.repeat) mark(RL.KEY_TO_KIND[k]); return true; }   // 꾹 눌러도 한 장만
    if (k === 'd') { R.skip = !R.skip; R.msg = ''; ctx.rerender(); return true; }
    if (k === 'z') { R.full = !R.full; ctx.rerender(); return true; }
    return false;
  }

  function chip(kind) {
    var m = kind ? RL.MARKS[kind] : null;
    return ctx.el('div', 'lt-chip ' + (kind || 'none'), m ? m.icon + ' ' + m.label : '표시 없음');
  }
  function topBar() {
    var c = RL.counts(R.rows, R.marks), seen = Object.keys(R.seen).length;
    var top = ctx.el('div', 'lt-top');
    top.appendChild(ctx.el('strong', null, R.rows[R.index].file));
    top.appendChild(ctx.el('span', 'lt-progress', '셀렉 ' + c.pick + '장 · 본 사진 ' + seen + ' / 전체 ' + c.total));
    var skip = ctx.el('button', null, '의심 컷 건너뛰기 ' + (R.skip ? '켜짐' : '꺼짐') + ' (D)');
    skip.setAttribute('aria-pressed', String(R.skip));
    skip.addEventListener('click', function () { R.skip = !R.skip; ctx.rerender(); });
    var end = ctx.el('button', null, '마치기 (Esc)');
    end.addEventListener('click', close);
    top.appendChild(skip); top.appendChild(end);
    return top;
  }
  function panel(row, current) {
    var p = ctx.el('div', 'lt-panel');
    p.appendChild(ctx.el('div', 'lt-label', '지금 표시'));
    p.appendChild(chip(current));
    p.appendChild(ctx.el('div', 'lt-label', '도구가 본 것'));
    var why = ctx.el('div', 'lt-why', L.explain(row, {})[0]);
    if (RL.isSuspect(row) && L.suspicion(row.confidence)) why.appendChild(ctx.el('small', null, '의심 정도 ' + L.suspicion(row.confidence)));
    p.appendChild(why);
    p.appendChild(ctx.el('div', 'lt-muted', (R.index + 1) + ' / ' + R.rows.length));
    if (R.msg) p.appendChild(ctx.el('div', 'lt-msg', R.msg));
    return p;
  }
  function filmstrip() {
    var strip = ctx.el('div', 'lt-strip'), range = RL.windowRange(R.rows.length, R.index, RADIUS);
    for (var i = range[0]; i < range[1]; i++) {
      (function (i) {
        var r = R.rows[i], kind = R.marks[RL.markKey(r)];
        var t = ctx.el('button', 'lt-thumb' + (i === R.index ? ' cur' : '') + (RL.isSuspect(r) ? ' dim' : ''));
        t.title = r.file + (kind ? ' · ' + RL.MARKS[kind].label : '');
        var img = document.createElement('img'); img.alt = r.file; show(img, ctx.thumbUrl(r.file), false); t.appendChild(img);
        if (kind) t.appendChild(ctx.el('span', 'lt-mark ' + kind, RL.MARKS[kind].icon));
        t.addEventListener('click', function () { jump(i); });
        strip.appendChild(t);
      })(i);
    }
    setTimeout(function () {   // 지금 사진이 가운데에 오게 한다
      var cur = strip.querySelector('.cur'); if (cur) cur.scrollIntoView({inline: 'center', block: 'nearest'});
    }, 0);
    return strip;
  }
  function prefetch() {   // 다음 두 장과 이전 한 장을 미리 받아 둔다
    var next = RL.move(R.rows, R.index, 1, R.skip), after = RL.move(R.rows, next, 1, R.skip);
    var prev = RL.move(R.rows, R.index, -1, R.skip);
    [next, after, prev].forEach(function (i) {
      if (i !== R.index) blobUrl(ctx.photoUrl(R.rows[i].file, 'view'), true).catch(function () {});
    });
  }
  function render() {
    if (!R) return null;
    var row = R.rows[R.index], current = R.marks[RL.markKey(row)] || null;
    var o = ctx.el('div', 'lt');
    o.appendChild(topBar());
    var main = ctx.el('div', 'lt-main');
    var stage = ctx.el('div', 'lt-stage' + (R.full ? ' full' : ''));
    var img = document.createElement('img'); img.alt = row.file;
    if (R.full) img.src = ctx.photoUrl(row.file, 'full'); else show(img, ctx.photoUrl(row.file, 'view'), true);
    stage.appendChild(img); main.appendChild(stage); main.appendChild(panel(row, current));
    o.appendChild(main); o.appendChild(filmstrip());
    o.appendChild(ctx.el('div', 'lt-keys', '← → 이동 · S 셀렉 · M 보류 · X 버릴 컷 (같은 키를 다시 누르면 해제) · D 의심 컷 건너뛰기 · Z 100% 확대 · Esc 마치기'));
    prefetch();
    return o;
  }

  root.BcutReview = {init: init, open: open, isOpen: isOpen, render: render, handleKey: handleKey};
})(window);
