/* "폴더로 나누어 담기" 창 (app.js에서 나눠 낸 파일). 미리보기가 기본이고, 담기 전에 폴더별 장수를 보여 준다.
   셀렉·보류·버릴 컷 표시는 서버에 저장된 것을 서버가 읽어 쓴다 (spec FR-25). */
(function (root) {
  'use strict';
  var L = root.BcutLogic;
  var ctx = null;   // {el, api, job, chooseFolder, friendly, rerender}
  var M = null;     // 창이 열려 있을 때만 있는 상태

  function init(c) { ctx = c; }
  function isOpen() { return M !== null; }
  function close() { M = null; ctx.rerender(); }

  function request(commit) {
    var body = {commit: commit, by_reason: M.byReason};
    if (M.out) body.out = M.out;
    return ctx.api('POST', '/api/jobs/' + ctx.job() + '/sort', body);
  }
  function preview() {
    M.busy = true; M.error = null; ctx.rerender();
    request(false).then(function (j) { M.plan = j; if (!M.out) M.out = j.out_root; M.busy = false; ctx.rerender(); })
      .catch(function (e) { M.error = e.message; M.busy = false; ctx.rerender(); });
  }
  function commit() {
    M.busy = true; M.error = null; ctx.rerender();
    request(true).then(function (j) { M.result = j; M.busy = false; ctx.rerender(); })
      .catch(function (e) { M.error = e.message; M.busy = false; ctx.rerender(); });
  }
  function open() {
    M = {out: null, byReason: true, plan: null, result: null, busy: true, error: null};
    ctx.rerender(); preview();
  }

  /* 표시한 사진이 어느 폴더로 가는지 쉬운 말로 */
  function markLines(plan) {
    var m = plan.marked || {}, out = [];
    if (m.pick) out.push('셀렉 ' + m.pick + '장은 "셀렉" 폴더에만 담겨요.');
    if (m.maybe) out.push('보류 ' + m.maybe + '장은 "보류" 폴더에만 담겨요.');
    if (m.discard) out.push('버릴 컷 ' + m.discard + '장은 "버릴 것 같은 컷" 폴더에 함께 담겨요.');
    return out;
  }
  function renderDone(p) {
    var r = M.result;
    p.appendChild(ctx.el('p', null, '원본은 그대로예요. 아래 새 폴더에 사본을 나누어 담았어요. 폴더를 열어서 확인해 보세요.'));
    p.appendChild(ctx.el('div', 'path', r.result_dir || ''));
    L.planLines(r).forEach(function (t) { p.appendChild(ctx.el('div', 'muted', t)); });
    if (r.aborted) p.appendChild(ctx.el('div', 'err', ctx.friendly(r.aborted)));
    if (r.mismatches && r.mismatches.length) p.appendChild(ctx.el('div', 'err', '원본과 크기가 다른 사본이 ' + r.mismatches.length + '개 있어요. 폴더를 지우고 다시 담아 주세요.'));
    var row = ctx.el('div', 'row');
    var reveal = ctx.el('button', 'primary', 'Finder에서 열기');
    reveal.addEventListener('click', function () { ctx.api('POST', '/api/reveal', {path: r.result_dir}).catch(function (e) { M.error = e.message; ctx.rerender(); }); });
    var done = ctx.el('button', null, '닫기'); done.addEventListener('click', close);
    row.appendChild(reveal); row.appendChild(done); p.appendChild(row);
  }
  function renderPlan(p) {
    var pl = M.plan;
    if (pl) {
      p.appendChild(ctx.el('p', null, '사진 ' + pl.photos + '장을 아래처럼 폴더에 나누어 담아요 (사본 ' + pl.placements + '개). 원본은 건드리지 않아요.'));
      var ul = ctx.el('ul'); L.planLines(pl).forEach(function (t) { ul.appendChild(ctx.el('li', null, t)); }); p.appendChild(ul);
      markLines(pl).forEach(function (t) { p.appendChild(ctx.el('div', 'muted', t)); });
      p.appendChild(ctx.el('div', 'muted', pl.method === 'clone' ? '빠르게 복사해요 (저장 공간을 거의 쓰지 않아요)' :
        '복사해요 (저장 공간이 약 ' + L.formatBytes(pl.needs_space) + ' 필요해요)'));
      if (pl.missing.length) p.appendChild(ctx.el('div', 'err', '검사한 뒤 사라진 사진 ' + pl.missing.length + '장은 빼고 담아요.'));
      if (pl.aborted) p.appendChild(ctx.el('div', 'err', ctx.friendly(pl.aborted)));
    }
    p.appendChild(ctx.el('div', 'muted', '저장할 위치'));
    p.appendChild(ctx.el('div', 'path', M.out || '…'));
    var chk = ctx.el('label'); var cb = ctx.el('input'); cb.type = 'checkbox'; cb.checked = M.byReason;
    cb.addEventListener('change', function () { M.byReason = cb.checked; preview(); });
    chk.appendChild(cb); chk.appendChild(document.createTextNode(' 문제 종류별 폴더도 만들기 (눈 감김, 흔들려 찍힘 등)')); p.appendChild(chk);
    var row = ctx.el('div', 'row');
    var change = ctx.el('button', null, '위치 바꾸기…');
    change.addEventListener('click', function () { ctx.chooseFolder().then(function (f) { if (f) { M.out = f; preview(); } }); });
    var cancel = ctx.el('button', null, '취소'); cancel.addEventListener('click', close);
    var go = ctx.el('button', 'primary', M.busy ? '잠시만요…' : '나누어 담기');
    go.disabled = M.busy || !pl || !!pl.aborted || !pl.photos; go.addEventListener('click', commit);
    row.appendChild(change); row.appendChild(cancel); row.appendChild(go); p.appendChild(row);
  }
  function render() {
    if (!M) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, M.result ? '다 담았어요' : '폴더로 나누어 담기'));
    if (M.error) p.appendChild(ctx.el('div', 'err', M.error));
    if (M.result) renderDone(p); else renderPlan(p);
    var xb = ctx.el('button', 'ghost x-btn', '✕'); xb.type = 'button'; xb.setAttribute('aria-label', '닫기'); xb.addEventListener('click', close); p.appendChild(xb);
    modal.appendChild(p);
    return modal;
  }

  root.BcutSortView = {init: init, open: open, isOpen: isOpen, render: render, close: close};
})(window);
