/* 훑기 모드 화면 (spec FR-21~23). 어두운 "라이트 테이블": 큰 사진 + 오른쪽 정보 + 아래 필름스트립.
   순수 로직은 review_logic.js, 표시 저장은 서버(ui/marks.py). app.js가 init으로 도구를 넘겨 준다.
   Esc로 마치면 "최종 확인"이 나오고, 거기서 계속 훑기 / 나누어 담기 / 요약으로를 고른다. ⌘Z는 직전 표시를 되돌린다. */
(function (root) {
  'use strict';
  var RL = root.BcutReviewLogic, L = root.BcutLogic;
  var ctx = null;   // {el, api, job, thumbUrl, photoUrl, rerender, onClose, openSort}
  var R = null;     // 훑는 중일 때만 있는 상태: {rows, marks, index, seen, skip, full, msg, history, final}
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
  function markUrl() { return '/api/jobs/' + ctx.job() + '/marks'; }
  function applyLocal(key, kind) { if (kind) R.marks[key] = kind; else delete R.marks[key]; }

  function open(rows, markList) {
    var ordered = RL.order(rows), marks = RL.marksMap(markList);
    R = {rows: ordered, marks: marks, index: RL.resumeIndex(ordered, marks), seen: {}, skip: false, full: false,
         msg: '', history: [], final: false};
    see(); ctx.rerender();
  }
  function exit(thenSort) {
    R = null; forgetBlobs(); ctx.onClose();
    if (thenSort) ctx.openSort();
  }
  function finish() { R.final = true; R.full = false; ctx.rerender(); }   // 마치기 -> 최종 확인
  function go(delta) {
    var i = RL.move(R.rows, R.index, delta, R.skip);
    R.msg = i === R.index ? (delta > 0 ? '마지막 사진이에요. 다 봤으면 Esc로 마치세요.' : '처음 사진이에요.') : '';
    R.index = i; R.full = false; see(); ctx.rerender();
  }
  function jump(i) { R.index = i; R.full = false; R.msg = ''; see(); ctx.rerender(); }

  /* 표시를 달고 바로 저장한다. 저장에 실패하면 되돌리고 그 사진으로 돌아온다 */
  function mark(pressed) {
    var row = R.rows[R.index], key = RL.markKey(row), before = R.marks[key] || null;
    var next = RL.nextMark(before, pressed), from = R.index;
    var change = {key: key, file: row.file, before: before, after: next, from: from};
    applyLocal(key, next); R.history = RL.recordChange(R.history, change);
    R.index = RL.move(R.rows, R.index, 1, R.skip);
    R.msg = R.index === from ? '마지막 사진이에요. 다 봤으면 Esc로 마치세요.' : '';
    R.full = false; see(); ctx.rerender();
    ctx.api('POST', markUrl(), {file: row.file, kind: next}).catch(function (e) {
      if (!R) return;
      applyLocal(key, before); R.history = RL.dropChange(R.history, change);
      R.index = from; R.final = false; R.msg = '표시를 저장하지 못했어요. 다시 눌러 주세요. (' + e.message + ')'; ctx.rerender();
    });
  }
  /* ⌘Z: 직전 표시를 되돌린다 (표시와 보던 사진이 함께 돌아온다). 되돌릴 것이 없어도 true: 이 화면이 처리한 것으로 본다 */
  function undo() {
    if (!R) return false;
    var c = RL.lastChange(R.history);
    if (!c) { R.msg = '되돌릴 표시가 없어요.'; ctx.rerender(); return true; }
    R.history = RL.dropLast(R.history); applyLocal(c.key, c.before);
    R.index = c.from; R.full = false; R.final = false; R.msg = '되돌렸어요.'; see(); ctx.rerender();
    ctx.api('POST', markUrl(), {file: c.file, kind: c.before}).catch(function (e) {
      if (!R) return;
      applyLocal(c.key, c.after); R.history = RL.recordChange(R.history, c);
      R.msg = '되돌리지 못했어요. 표시는 그대로예요. (' + e.message + ')'; ctx.rerender();
    });
    return true;
  }

  function handleKey(e) {   // 쓴 키면 true
    if (!R) return false;
    var k = String(e.key).toLowerCase();
    if ((e.metaKey || e.ctrlKey) && k === 'z' && !e.shiftKey) return undo();
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    if (R.final) { if (e.key === 'Escape') { exit(false); return true; } return false; }
    if (e.key === 'Escape') { finish(); return true; }
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
    end.addEventListener('click', finish);
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
  /* 최종 확인: 담기 전에 장수를 한 번 더 본다. 표시 안 한 사진이 많아도 막지 않고 숫자만 알려 준다 */
  function renderFinal() {
    var c = RL.counts(R.rows, R.marks);
    var o = ctx.el('div', 'lt'), box = ctx.el('div', 'lt-final');
    box.appendChild(ctx.el('h2', null, '훑기를 마쳤어요'));
    box.appendChild(ctx.el('p', 'lt-muted', '이대로 폴더에 나누어 담아도 되는지 확인해 주세요. 원본은 건드리지 않고 사본만 만들어요.'));
    var stats = ctx.el('div', 'lt-stats');
    [['pick', '셀렉', c.pick], ['maybe', '보류', c.maybe], ['discard', '버릴 컷', c.discard], ['none', '표시 안 함', c.none]].forEach(function (x) {
      var s = ctx.el('div', 'lt-stat ' + x[0]); s.appendChild(ctx.el('b', null, String(x[2]))); s.appendChild(ctx.el('span', null, x[1]));
      stats.appendChild(s);
    });
    box.appendChild(stats);
    box.appendChild(ctx.el('p', 'lt-muted', '셀렉은 "셀렉" 폴더에만, 보류는 "보류" 폴더에만 담겨요. 버릴 컷은 "버릴 것 같은 컷" 폴더에 함께 담겨요. 표시 안 한 사진은 도구가 본 대로 담겨요.'));
    if (R.msg) box.appendChild(ctx.el('div', 'lt-msg', R.msg));
    var row = ctx.el('div', 'lt-row');
    var more = ctx.el('button', null, '계속 훑기');
    more.addEventListener('click', function () { R.final = false; R.msg = ''; ctx.rerender(); });
    var sort = ctx.el('button', 'primary', '나누어 담기…');
    sort.addEventListener('click', function () { exit(true); });
    var back = ctx.el('button', null, '요약으로 (Esc)');
    back.addEventListener('click', function () { exit(false); });
    row.appendChild(more); row.appendChild(sort); row.appendChild(back); box.appendChild(row);
    box.appendChild(ctx.el('div', 'lt-keys', '⌘Z 방금 한 표시를 되돌리고 계속 훑어요'));
    o.appendChild(box);
    return o;
  }
  function render() {
    if (!R) return null;
    if (R.final) return renderFinal();
    var row = R.rows[R.index], current = R.marks[RL.markKey(row)] || null;
    var o = ctx.el('div', 'lt');
    o.appendChild(topBar());
    var main = ctx.el('div', 'lt-main');
    var stage = ctx.el('div', 'lt-stage' + (R.full ? ' full' : ''));
    var img = document.createElement('img'); img.alt = row.file;
    if (R.full) img.src = ctx.photoUrl(row.file, 'full'); else show(img, ctx.photoUrl(row.file, 'view'), true);
    stage.appendChild(img); main.appendChild(stage); main.appendChild(panel(row, current));
    o.appendChild(main); o.appendChild(filmstrip());
    o.appendChild(ctx.el('div', 'lt-keys', '← → 이동 · S 셀렉 · M 보류 · X 버릴 컷 (같은 키를 다시 누르면 해제) · ⌘Z 실행 취소 · D 의심 컷 건너뛰기 · Z 100% 확대 · Esc 마치기'));
    prefetch();
    return o;
  }

  root.BcutReview = {init: init, open: open, isOpen: isOpen, render: render, handleKey: handleKey, undo: undo};
})(window);
