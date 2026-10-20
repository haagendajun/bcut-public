/* 기록 관리 창 (spec FR-34~36, IA RC-01-APP). 행사별 기록을 보고, 표시를 모두 해제하고,
   Capture One 반영을 되돌리고, 기록을 휴지통으로 옮기거나 되돌려 놓는다.
   파일을 실제로 지우지 않는다 (ADR-0012). 되돌리기 어려운 동작은 두 번 눌러야 실행된다.
   한 줄은 "왼쪽 글자 · 오른쪽 끝 버튼"으로 통일한다. */
(function (root) {
  'use strict';
  var ctx = null;   // {el, api, rerender}
  var R = null;     // 창이 열려 있을 때만 있는 상태: {data, busy, error, msg, confirm, pv}

  function init(c) { ctx = c; }
  function isOpen() { return R !== null; }
  function button() {
    var b = ctx.el('button', 'ghost', '기록 관리');
    b.title = '이 컴퓨터에 쌓인 표시·훑기·Capture One 반영 기록을 보고 정리해요.';
    b.addEventListener('click', open);
    return b;
  }
  function open() { R = {data: null, busy: false, error: null, msg: null, confirm: null, pv: {}}; ctx.rerender(); load(); }
  function close() { if (R && R.busy) return; R = null; ctx.rerender(); }
  function load() {
    return ctx.api('GET', '/api/records').then(function (d) { R.data = d; ctx.rerender(); })
      .catch(function (e) { R.error = e.message; ctx.rerender(); });
  }
  function act(path, body, okMsg) {
    R.busy = true; R.error = null; R.msg = null; R.confirm = null; ctx.rerender();
    return ctx.api('POST', path, body).then(function (j) {
      R.busy = false; R.msg = okMsg(j); R.pv = {};
      document.dispatchEvent(new CustomEvent('bcut-records-changed'));
      return load();
    }).catch(function (e) { R.busy = false; R.error = e.message; ctx.rerender(); });
  }

  /* ---- 작은 부품 ---- */
  function line(p, text, cls) { var d = ctx.el('div', cls || 'muted', text); p.appendChild(d); return d; }
  function btn(label, cls, fn) {
    var b = ctx.el('button', cls, label); b.type = 'button'; b.disabled = R.busy; b.addEventListener('click', fn); return b;
  }
  /* 두 번 눌러야 실행되는 위험 버튼 (붉은 테두리) */
  function danger(id, label, run) {
    var asking = R.confirm === id;
    return btn(asking ? '정말요? 한 번 더 누르면 실행해요' : label, asking ? 'danger on' : 'danger', function () {
      if (asking) run(); else { R.confirm = id; ctx.rerender(); }
    });
  }
  function rowOf(left, right) {   // 왼쪽 글자 · 오른쪽 끝 버튼
    var r = ctx.el('div', 'rec-row'), l = ctx.el('div', 'rec-left'), b = ctx.el('div', 'rec-btns');
    left.forEach(function (n) { l.appendChild(n); }); right.forEach(function (n) { b.appendChild(n); });
    r.appendChild(l); r.appendChild(b); return r;
  }
  function stamp(t) { return t ? t.replace('T', ' ').slice(0, 16) : ''; }
  function minutes(s) { return s >= 60 ? Math.round(s / 60) + '분' : s + '초'; }
  function stat(label, value) {
    var s = ctx.el('div', 'rec-stat'); s.appendChild(ctx.el('b', null, String(value))); s.appendChild(ctx.el('span', null, label)); return s;
  }

  /* ---- Capture One 반영 기록 한 줄 ---- */
  function previewText(p) {
    if (p.aborted) return p.aborted;
    var st = p.style || {}, bits = ['키워드 ' + p.strip_files + '장'];
    if (st.restore) bits.push('별점·컬러 태그 ' + st.restore + '장');
    var extra = [];
    if (p.already_clean) extra.push('이미 돌아간 ' + p.already_clean + '장');
    if (st.already_restored) extra.push('별점·태그가 이미 이전 값인 ' + st.already_restored + '장');
    if (st.kept_user_changed) extra.push('그 사이 직접 바꾼 ' + st.kept_user_changed + '장은 그대로');
    return bits.join(' · ') + '을 되돌려요' + (extra.length ? ' (' + extra.join(', ') + ')' : '');
  }
  function renderCapture(box, ev, cap) {
    var id = 'cap:' + ev.key + ':' + cap.path, body = {event: ev.key, doc: cap.path};
    var what = cap.photos + '장에 키워드' + (cap.style_photos ? ' · 별점·컬러 태그 ' + cap.style_photos + '장' : '');
    var undo = btn('되돌리기', 'ghost', function () {
      R.busy = true; R.error = null; R.msg = null; ctx.rerender();
      ctx.api('POST', '/api/records/capture-rollback', body).then(function (p) { R.busy = false; R.pv[id] = p; ctx.rerender(); })
        .catch(function (e) { R.busy = false; R.error = e.message; ctx.rerender(); });
    });
    var del = danger(id + ':trash', '기록 지우기', function () {
      act('/api/records/trash', {kind: 'capture', event: ev.key, doc: cap.path}, function () {
        return 'Capture One 반영 기록을 휴지통으로 옮겼어요. 이 기록으로는 더 이상 되돌릴 수 없어요 (지운 기록에서 되돌려 놓을 수 있어요).';
      });
    });
    var left = [ctx.el('b', null, cap.document + ' · ' + stamp(cap.created_at)), ctx.el('span', 'muted', what)];
    box.appendChild(rowOf(left, [undo, del]));
    var p = R.pv[id];
    if (!p) return;
    var pv = ctx.el('div', 'rec-preview'); pv.appendChild(ctx.el('div', p.aborted ? 'err' : null, previewText(p)));
    if (!p.aborted) {
      pv.appendChild(btn('되돌리기 확정', 'primary', function () {
        act('/api/records/capture-rollback', Object.assign({commit: true}, body), function (r) {
          return 'Capture One에서 되돌렸어요: 키워드 ' + r.stripped_files + '장' + (r.style && r.style.restore ? ', 별점·컬러 태그 ' + r.style.restore + '장' : '') + '.';
        });
      }));
    }
    pv.appendChild(btn('취소', 'ghost', function () { delete R.pv[id]; ctx.rerender(); }));
    box.appendChild(pv);
  }

  /* ---- 행사 카드 ---- */
  function renderEvent(p, d, ev) {
    var box = ctx.el('div', 'card-box'), m = ev.marks, rv = ev.reviews;
    var head = ctx.el('div', 'rec-head'); head.appendChild(ctx.el('h3', null, ev.name));
    var cloud = !d.cloud.consented ? '클라우드 꺼짐' : ev.cloud_pending ? '클라우드 대기 ' + ev.cloud_pending + '건' : '클라우드 올림 완료';
    head.appendChild(ctx.el('span', 'rec-badge', cloud)); box.appendChild(head);
    var stats = ctx.el('div', 'rec-stats');
    stats.appendChild(stat('셀렉', m.pick)); stats.appendChild(stat('보류', m.maybe)); stats.appendChild(stat('버릴 컷', m.discard));
    stats.appendChild(stat(rv.count ? '훑기 ' + rv.count + '번 · ' + minutes(rv.seconds) : '훑기 기록 없음', rv.count ? rv.seen + '장' : '–'));
    box.appendChild(stats);
    if (ev.capture.length) {
      box.appendChild(ctx.el('div', 'rec-sub', 'Capture One 반영 기록'));
      ev.capture.forEach(function (cap) { renderCapture(box, ev, cap); });
    }
    var total = m.pick + m.maybe + m.discard, foot = ctx.el('div', 'rec-foot');
    foot.appendChild(total ? btn('표시 모두 해제 (' + total + '장)', null, function () {
      act('/api/records/clear-marks', {event: ev.key}, function (j) {
        return '표시 ' + j.cleared + '장을 해제했어요. 이력은 남아 있어요. Capture One에 이미 붙인 키워드·별점은 그대로예요.';
      });
    }) : ctx.el('span'));
    foot.appendChild(danger('event:' + ev.key, '이 행사 기록 지우기', function () {
      act('/api/records/trash', {kind: 'event', event: ev.key}, function () {
        return '행사 기록(표시·훑기)을 휴지통으로 옮겼어요. 사진과 Capture One은 그대로예요.';
      });
    }));
    box.appendChild(foot);
    line(box, '"지우기"는 파일을 없애지 않고 휴지통으로 옮겨요. 아래 "지운 기록"에서 되돌려 놓을 수 있어요.', 'muted small-note');
    p.appendChild(box);
  }

  /* ---- 지운 기록: 행사별로 묶음 ---- */
  function renderTrash(p, d) {
    var det = ctx.el('details', 'rec-trash'); det.open = !!R.trashOpen;
    det.addEventListener('toggle', function () { R.trashOpen = det.open; });
    det.appendChild(ctx.el('summary', null, d.trash.length ? '지운 기록 ' + d.trash.length + '개' : '지운 기록 없음'));
    var groups = {};
    d.trash.forEach(function (t) { (groups[t.group] = groups[t.group] || []).push(t); });
    Object.keys(groups).forEach(function (g) {
      det.appendChild(ctx.el('div', 'rec-sub', g));
      groups[g].forEach(function (t) {
        var back = btn('되돌려 놓기', 'ghost', function () {
          act('/api/records/restore', {id: t.id}, function () { return '기록을 되돌려 놓았어요.'; });
        });
        det.appendChild(rowOf([ctx.el('b', null, t.title), ctx.el('span', 'muted', stamp(t.trashed_at) + ' 에 지웠어요')], [back]));
      });
    });
    p.appendChild(det);
  }

  function render() {
    if (!R) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel rec-panel');
    var xb = ctx.el('button', 'ghost x-btn', '✕'); xb.type = 'button'; xb.setAttribute('aria-label', '닫기'); xb.addEventListener('click', close);
    p.appendChild(xb); p.appendChild(ctx.el('h2', null, '기록 관리'));
    line(p, '이 컴퓨터에 쌓인 기록이에요. 사진 파일은 건드리지 않아요.');
    if (R.busy) line(p, '잠시만요…');
    if (R.error) line(p, R.error, 'err');
    if (R.msg) line(p, R.msg, 'ok');
    if (R.data) {
      if (!R.data.events.length) line(p, '아직 쌓인 기록이 없어요.');
      R.data.events.forEach(function (ev) { renderEvent(p, R.data, ev); });
      renderTrash(p, R.data);
    }
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal && !R.busy) close(); });
    return modal;
  }

  root.BcutRecords = {init: init, button: button, render: render, isOpen: isOpen, close: close};
})(window);
