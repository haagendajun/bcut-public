/* 기록 관리 창 (spec FR-34~36, IA RC-01-APP). 행사별 기록을 보고, 표시를 모두 해제하고,
   기록을 휴지통으로 옮기거나 되돌려 놓는다. 파일을 실제로 지우지 않는다 (ADR-0012).
   되돌리기 어려운 동작은 두 번 눌러야 실행된다. */
(function (root) {
  'use strict';
  var ctx = null;   // {el, api, rerender}
  var R = null;     // 창이 열려 있을 때만 있는 상태: {data, busy, error, msg, confirm}

  function init(c) { ctx = c; }
  function isOpen() { return R !== null; }
  function button() {
    var b = ctx.el('button', 'ghost', '기록 관리');
    b.title = '이 컴퓨터에 쌓인 표시·훑기·Capture One 반영 기록을 보고 정리해요.';
    b.addEventListener('click', open);
    return b;
  }
  function open() { R = {data: null, busy: false, error: null, msg: null, confirm: null}; ctx.rerender(); load(); }
  function close() { R = null; ctx.rerender(); }
  function load() {
    return ctx.api('GET', '/api/records').then(function (d) { R.data = d; ctx.rerender(); })
      .catch(function (e) { R.error = e.message; ctx.rerender(); });
  }
  function act(path, body, okMsg) {
    R.busy = true; R.error = null; R.msg = null; R.confirm = null; ctx.rerender();
    return ctx.api('POST', path, body).then(function (j) {
      R.busy = false; R.msg = okMsg(j);
      document.dispatchEvent(new CustomEvent('bcut-records-changed'));
      return load();
    }).catch(function (e) { R.busy = false; R.error = e.message; ctx.rerender(); });
  }

  /* 두 번 눌러야 실행되는 버튼 */
  function danger(id, label, run) {
    var asking = R.confirm === id;
    var b = ctx.el('button', asking ? 'primary' : 'ghost', asking ? '정말요? 한 번 더 누르면 실행해요' : label);
    b.disabled = R.busy;
    b.addEventListener('click', function () { if (asking) run(); else { R.confirm = id; ctx.rerender(); } });
    return b;
  }
  function line(p, text, cls) { p.appendChild(ctx.el('div', cls || 'muted', text)); }
  function minutes(s) { return s >= 60 ? Math.round(s / 60) + '분' : s + '초'; }
  function cloudText(d, ev) {
    if (!d.cloud.consented) return '클라우드: 아직 켜지 않았어요';
    return ev.cloud_pending ? '클라우드: 대기 ' + ev.cloud_pending + '건' : '클라우드: 모두 올라갔어요';
  }

  function renderCapture(p, ev, cap) {
    var row = ctx.el('div', 'row');
    var date = cap.created_at ? cap.created_at.replace('T', ' ').slice(0, 16) : '';
    row.appendChild(ctx.el('span', null, 'Capture One 반영 기록 · ' + cap.document + ' · ' + date + ' · ' + cap.photos + '장' +
      (cap.style_photos ? ' (별점·태그 ' + cap.style_photos + '장)' : '')));
    row.appendChild(danger('cap:' + ev.key + ':' + cap.path, '이 기록 지우기', function () {
      act('/api/records/trash', {kind: 'capture', event: ev.key, doc: cap.path}, function () {
        return 'Capture One 반영 기록을 휴지통으로 옮겼어요. 이 기록으로는 더 이상 되돌릴 수 없어요 (지운 기록에서 되돌려 놓을 수 있어요).';
      });
    }));
    p.appendChild(row);
  }
  function renderEvent(p, d, ev) {
    var box = ctx.el('div', 'card-box'), m = ev.marks, total = m.pick + m.maybe + m.discard;
    box.appendChild(ctx.el('h3', null, ev.name));
    line(box, '표시: 셀렉 ' + m.pick + ' · 보류 ' + m.maybe + ' · 버릴 컷 ' + m.discard);
    var rv = ev.reviews;
    line(box, rv.count ? '훑기 ' + rv.count + '번 · 본 사진 ' + rv.seen + '장 · 모두 ' + minutes(rv.seconds) : '훑기 기록 없음');
    line(box, cloudText(d, ev));
    ev.capture.forEach(function (cap) { renderCapture(box, ev, cap); });
    var row = ctx.el('div', 'row');
    if (total) {
      row.appendChild(danger('clear:' + ev.key, '표시 모두 해제 (' + total + '장)', function () {
        act('/api/records/clear-marks', {event: ev.key}, function (j) {
          return '표시 ' + j.cleared + '장을 해제했어요. 이력은 남아 있어요. Capture One에 이미 붙인 키워드·별점은 그대로예요.';
        });
      }));
    }
    row.appendChild(danger('event:' + ev.key, '이 행사 기록 지우기', function () {
      act('/api/records/trash', {kind: 'event', event: ev.key}, function () {
        return '행사 기록(표시·훑기)을 휴지통으로 옮겼어요. 사진과 Capture One은 그대로예요.';
      });
    }));
    box.appendChild(row); p.appendChild(box);
  }
  function renderTrash(p, d) {
    if (!d.trash.length) return;
    p.appendChild(ctx.el('h3', null, '지운 기록'));
    d.trash.forEach(function (t) {
      var row = ctx.el('div', 'row');
      row.appendChild(ctx.el('span', 'muted', t.label + ' · ' + (t.trashed_at || '').replace('T', ' ').slice(0, 16)));
      var back = ctx.el('button', 'ghost', '되돌려 놓기'); back.disabled = R.busy;
      back.addEventListener('click', function () {
        act('/api/records/restore', {id: t.id}, function () { return '기록을 되돌려 놓았어요.'; });
      });
      row.appendChild(back); p.appendChild(row);
    });
  }
  function render() {
    if (!R) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, '기록 관리'));
    line(p, '이 컴퓨터에 쌓인 기록이에요. "지우기"는 파일을 없애지 않고 휴지통으로 옮겨서, 언제든 되돌려 놓을 수 있어요. 사진 파일은 건드리지 않아요.');
    if (R.busy) line(p, '잠시만요…');
    if (R.error) line(p, R.error, 'err');
    if (R.msg) line(p, R.msg, 'ok');
    if (R.data) {
      if (!R.data.events.length) line(p, '아직 쌓인 기록이 없어요.');
      R.data.events.forEach(function (ev) { renderEvent(p, R.data, ev); });
      renderTrash(p, R.data);
    }
    var done = ctx.el('button', 'ghost', '닫기'); done.addEventListener('click', close);
    p.appendChild(ctx.el('div', 'row')).appendChild(done);
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal && !R.busy) close(); });
    return modal;
  }

  root.BcutRecords = {init: init, button: button, render: render, isOpen: isOpen};
})(window);
