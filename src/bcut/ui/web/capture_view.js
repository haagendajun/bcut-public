/* "Capture One에도 표시하기" 창 (spec FR-28, IA SO-02-APP). 미리보기가 먼저이고, 반영은 따로 한 번 더 누른다.
   별점·컬러 태그는 건드리지 않고 전용 키워드만 붙인다. 서버가 기존 apply/rollback을 부른다 (ui/capture.py). */
(function (root) {
  'use strict';
  var ctx = null;   // {el, api, job, rerender}
  var C = null;     // 창이 열려 있을 때만 있는 상태
  var KEY = 'bcut-capture-catalog';
  var KEYWORDS = ['bcut-셀렉', 'bcut-보류', 'bcut-버릴컷'];

  function init(c) {
    ctx = c;
    document.addEventListener('bcut-open-capture', open);
  }
  function isOpen() { return C !== null; }
  function remembered() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }
  function remember(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* 저장 못 해도 계속 */ } }
  function open() { C = {catalog: remembered(), res: null, busy: false, error: null, partial: false, back: false}; ctx.rerender(); }
  function close() { C = null; ctx.rerender(); }

  function call(action, commit) {
    var cat = C.catalog.trim();
    if (!cat) { C.error = '카탈로그 이름을 입력해 주세요.'; ctx.rerender(); return; }
    remember(cat);
    C.busy = true; C.error = null; ctx.rerender();
    var body = {action: action, catalog: cat, commit: !!commit, allow_partial: C.partial};
    ctx.api('POST', '/api/jobs/' + ctx.job() + '/capture-one', body)
      .then(function (j) { C.res = j; C.busy = false; ctx.rerender(); })
      .catch(function (e) { C.error = e.message; C.busy = false; ctx.rerender(); });
  }

  function line(p, text, cls) { p.appendChild(ctx.el('div', cls || 'muted', text)); }
  function counts(p, kc) {
    KEYWORDS.forEach(function (k) { if (kc[k]) line(p, k + ' ' + kc[k] + '장'); });
  }
  function guide(p, missing) {
    line(p, 'Capture One에 전용 키워드가 아직 없어요. 아무것도 바꾸지 않았어요. 카탈로그마다 한 번만 직접 만들어 주세요:', 'err');
    var ul = ctx.el('ul');
    missing.forEach(function (k) { ul.appendChild(ctx.el('li', null, k)); });
    p.appendChild(ul);
    line(p, '만드는 방법: 오른쪽 도구 탭 → 메타데이터 → 키워드 도구 → 사진 1장 선택 → 입력칸에 이름을 정확히 입력하고 Return. 만든 뒤 "미리보기"를 다시 눌러요.');
  }
  function names(title, list, total) {
    return title + ' ' + total + '장' + (list.length ? ': ' + list.join(', ') + (total > list.length ? ' …' : '') : '');
  }
  function renderApply(p, r) {
    if (r.missing_keywords && r.missing_keywords.length) return guide(p, r.missing_keywords);
    if (r.aborted) line(p, r.aborted, 'err');
    if (r.missing_total) line(p, names('카탈로그에서 못 찾은 사진', r.missing, r.missing_total), 'err');
    if (r.ambiguous_total) line(p, names('파일 이름이 겹쳐 건너뛰는 사진', r.ambiguous, r.ambiguous_total), 'err');
    if (r.mode === 'dry-run' && !r.aborted) line(p, '미리보기예요. 아직 Capture One에는 아무것도 하지 않았어요.');
    if (r.mode === 'commit' && !r.aborted) line(p, 'Capture One에서 ' + r.applied_files + '장에 키워드를 붙였어요. 별점·컬러 태그는 그대로예요.', null);
    counts(p, r.keyword_counts || {});
    if (r.already) line(p, '이미 붙어 있어 건너뜀 ' + r.already + '장');
    if (r.backup) line(p, '되돌리기용 기록: ' + r.backup);
    (r.violations || []).forEach(function (v) { line(p, '확인 실패: ' + v, 'err'); });
  }
  function renderBack(p, r) {
    if (r.aborted) return line(p, r.aborted, 'err');
    if (r.mode === 'dry-run') line(p, '되돌리기 미리보기예요. ' + r.strip_files + '장에서 이 앱이 붙인 키워드만 떼요 (직접 붙인 키워드·별점·태그는 그대로).');
    else line(p, r.stripped_files + '장에서 키워드를 뗐어요.');
    counts(p, r.keyword_counts || {});
    if (r.user_changed) line(p, '반영한 뒤 별점·태그를 바꾼 사진 ' + r.user_changed + '장은 그대로 둬요.');
    (r.violations || []).forEach(function (v) { line(p, '확인 실패: ' + v, 'err'); });
  }
  function renderBody(p) {
    var r = C.res;
    if (!r) return line(p, '셀렉·보류·버릴 컷 사진에 Capture One 전용 키워드를 붙여요. 별점·컬러 태그·기존 키워드는 건드리지 않아요. 먼저 미리보기로 확인해요.');
    if (r.action === 'rollback') renderBack(p, r); else renderApply(p, r);
  }
  function buttons(p) {
    var r = C.res, row = ctx.el('div', 'row');
    var pre = ctx.el('button', r ? null : 'primary', '미리보기');
    pre.disabled = C.busy; pre.addEventListener('click', function () { C.back = false; call('preview', false); });
    row.appendChild(pre);
    var canApply = r && r.action !== 'rollback' && r.mode === 'dry-run' && !r.aborted;
    if (canApply) {
      var go = ctx.el('button', 'primary', 'Capture One에 반영'); go.disabled = C.busy;
      go.addEventListener('click', function () { call('apply', true); });
      row.appendChild(go);
    }
    var back = ctx.el('button', 'ghost', r && r.action === 'rollback' && r.mode === 'dry-run' && !r.aborted ? '되돌리기 확정' : '붙인 키워드 되돌리기…');
    back.disabled = C.busy;
    back.addEventListener('click', function () { var confirm = r && r.action === 'rollback' && r.mode === 'dry-run' && !r.aborted; call('rollback', confirm); });
    row.appendChild(back);
    var done = ctx.el('button', 'ghost', '닫기'); done.addEventListener('click', close); row.appendChild(done);
    p.appendChild(row);
  }
  function render() {
    if (!C) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, 'Capture One에도 표시하기'));
    var lab = ctx.el('label'); lab.appendChild(document.createTextNode('Capture One 카탈로그 이름 '));
    var inp = ctx.el('input'); inp.type = 'text'; inp.value = C.catalog; inp.placeholder = '지금 열려 있는 카탈로그 이름';
    inp.addEventListener('input', function () { C.catalog = inp.value; });
    lab.appendChild(inp); p.appendChild(lab);
    var chk = ctx.el('label'); var cb = ctx.el('input'); cb.type = 'checkbox'; cb.checked = C.partial;
    cb.addEventListener('change', function () { C.partial = cb.checked; });
    chk.appendChild(cb); chk.appendChild(document.createTextNode(' 카탈로그에서 찾은 사진만 반영하기')); p.appendChild(chk);
    if (C.busy) line(p, '잠시만요… Capture One과 이야기하는 중이에요.');
    if (C.error) line(p, C.error, 'err');
    renderBody(p); buttons(p);
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal && !C.busy) close(); });
    return modal;
  }

  root.BcutCapture = {init: init, open: open, isOpen: isOpen, render: render};
})(window);
