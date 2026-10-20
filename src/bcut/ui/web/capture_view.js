/* "Capture One에도 표시하기" 창 (spec FR-28, IA SO-02-APP). 미리보기가 먼저이고, 반영은 따로 한 번 더 누른다.
   별점·컬러 태그는 건드리지 않고 전용 키워드만 붙인다. 서버가 기존 apply/rollback을 부른다 (ui/capture.py). */
(function (root) {
  'use strict';
  var ctx = null;   // {el, api, job, rerender}
  var C = null;     // 창이 열려 있을 때만 있는 상태
  var KEY = 'bcut-capture-catalog';
  var KEYWORDS = ['bcut-셀렉', 'bcut-보류', 'bcut-버릴컷'];
  var KINDS = [['pick', '셀렉'], ['maybe', '보류'], ['discard', '버릴 컷']];
  var COLORS = ['안 줌', '빨강', '주황', '노랑', '초록', '파랑', '분홍', '보라'];   // 번호 1~7 (Capture One 순서)
  var SWATCH = ['transparent', '#e5484d', '#f08a24', '#f5c518', '#3fae5a', '#3b82f6', '#ec6aa8', '#8b5cf6'];
  var STYLE_KEY = 'bcut-capture-style';

  function init(c) {
    ctx = c;
    document.addEventListener('bcut-open-capture', open);
  }
  function isOpen() { return C !== null; }
  function remembered() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }
  function remember(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* 저장 못 해도 계속 */ } }
  function loadStyle() {
    var base = {pick: {rating: 0, color: 0}, maybe: {rating: 0, color: 0}, discard: {rating: 0, color: 0}};
    try { var s = JSON.parse(localStorage.getItem(STYLE_KEY) || 'null'); if (s && s.style) return s; } catch (e) { /* 기억 못 해도 계속 */ }
    return {style: base, overwrite: false};
  }
  function saveStyle() { try { localStorage.setItem(STYLE_KEY, JSON.stringify({style: C.style, overwrite: C.overwrite})); } catch (e) { /* 저장 못 해도 계속 */ } }
  function open() {
    var st = loadStyle();
    C = {catalog: remembered(), res: null, busy: false, error: null, partial: false, back: false, style: st.style, overwrite: !!st.overwrite};
    ctx.rerender();
  }
  function close() { C = null; ctx.rerender(); }

  function call(action, commit) {
    var cat = C.catalog.trim();
    if (!cat) { C.error = '카탈로그나 세션 이름을 입력해 주세요.'; ctx.rerender(); return; }
    remember(cat);
    C.busy = true; C.error = null; ctx.rerender();
    var body = {action: action, catalog: cat, commit: !!commit, allow_partial: C.partial};
    var st = chosenStyle();
    if (st) { body.style = st; body.overwrite = C.overwrite; }
    saveStyle();
    ctx.api('POST', '/api/jobs/' + ctx.job() + '/capture-one', body)
      .then(function (j) { C.res = j; C.busy = false; ctx.rerender(); })
      .catch(function (e) { C.error = e.message; C.busy = false; ctx.rerender(); });
  }

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
    if (r.session) line(p, '열려 있는 문서는 세션이에요.');
    if (r.mode === 'dry-run' && !r.aborted) line(p, '미리보기예요. 아직 Capture One에는 아무것도 하지 않았어요.');
    if (r.mode === 'commit' && !r.aborted) line(p, 'Capture One에서 ' + r.applied_files + '장에 키워드를 붙였어요.' + (r.style && r.style.applied ? '' : ' 별점·컬러 태그는 그대로예요.'), null);
    counts(p, r.keyword_counts || {});
    if (r.already) line(p, '이미 붙어 있어 건너뜀 ' + r.already + '장');
    if (r.session && r.mode === 'commit') line(p, '세션에는 카탈로그 백업이 없어서, 아래 되돌리기용 기록으로 대신해요.');
    if (r.backup) line(p, '되돌리기용 기록: ' + r.backup);
    (r.violations || []).forEach(function (v) { line(p, '확인 실패: ' + v, 'err'); });
    styleLines(p, r.style);
  }
  function renderBack(p, r) {
    if (r.aborted) return line(p, r.aborted, 'err');
    if (r.mode === 'dry-run') line(p, '되돌리기 미리보기예요. ' + r.strip_files + '장에서 이 앱이 붙인 키워드만 떼요 (직접 붙인 키워드·별점·태그는 그대로).');
    else line(p, r.stripped_files + '장에서 키워드를 뗐어요.');
    counts(p, r.keyword_counts || {});
    if (r.user_changed) line(p, '반영한 뒤 별점·태그를 바꾼 사진 ' + r.user_changed + '장은 그대로 둬요.');
    var b = r.style;
    if (b && b.has_record) line(p, '별점·컬러 태그: ' + b.restore + '장을 이전 값으로 ' + (b.restored ? '돌렸어요' : '돌려요') + (b.kept_user_changed ? ' (그 사이 직접 바꾼 ' + b.kept_user_changed + '장은 그대로 둬요)' : '') + '.');
    (r.violations || []).forEach(function (v) { line(p, '확인 실패: ' + v, 'err'); });
  }
  function renderBody(p) {
    var r = C.res;
    if (!r) return line(p, '셀렉·보류·버릴 컷 사진에 Capture One 전용 키워드를 붙여요. 별점·컬러 태그는 위에서 고른 것만 주고, 기존 키워드는 건드리지 않아요. 먼저 미리보기로 확인해요.');
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
    var back = ctx.el('button', 'ghost', r && r.action === 'rollback' && r.mode === 'dry-run' && !r.aborted ? '되돌리기 확정' : '붙인 키워드·별점·태그 되돌리기…');
    back.disabled = C.busy;
    back.addEventListener('click', function () { var confirm = r && r.action === 'rollback' && r.mode === 'dry-run' && !r.aborted; call('rollback', confirm); });
    row.appendChild(back);
    var done = ctx.el('button', 'ghost', '닫기'); done.addEventListener('click', close); row.appendChild(done);
    p.appendChild(row);
  }
  function pick(options, value, onChange) {
    var sel = ctx.el('select');
    options.forEach(function (t, i) { var op = ctx.el('option', null, t); op.value = String(i); if (i === value) op.selected = true; sel.appendChild(op); });
    sel.addEventListener('change', function () { onChange(parseInt(sel.value, 10)); C.res = null; ctx.rerender(); });   // 값을 바꾸면 미리보기를 다시 해야 한다
    return sel;
  }
  function renderStyle(p) {
    p.appendChild(ctx.el('div', 'muted', '별점·컬러 태그도 줄까요? (선택이에요. "안 줌"이면 키워드만 붙고 별점·태그는 그대로예요)'));
    var stars = ['안 줌', '★ 1', '★★ 2', '★★★ 3', '★★★★ 4', '★★★★★ 5'];
    KINDS.forEach(function (k) {
      var v = C.style[k[0]], row = ctx.el('div', 'row');
      row.appendChild(ctx.el('b', null, k[1]));
      row.appendChild(ctx.el('span', 'muted', '별점'));
      row.appendChild(pick(stars, v.rating, function (n) { v.rating = n; }));
      row.appendChild(ctx.el('span', 'muted', '컬러 태그'));
      var sw = ctx.el('span'); sw.style.cssText = 'display:inline-block;width:14px;height:14px;border-radius:50%;background:' + SWATCH[v.color];
      row.appendChild(sw);
      row.appendChild(pick(COLORS, v.color, function (n) { v.color = n; }));
      p.appendChild(row);
    });
    var ow = ctx.el('label'), cb = ctx.el('input'); cb.type = 'checkbox'; cb.checked = C.overwrite;
    cb.addEventListener('change', function () { C.overwrite = cb.checked; C.res = null; ctx.rerender(); });
    ow.appendChild(cb); ow.appendChild(document.createTextNode(' 이미 별점·컬러 태그가 있는 사진도 바꾸기 (끄면 건너뛰어요)'));
    p.appendChild(ow);
  }
  function styleLines(p, st) {
    if (!st) return;
    var rc = Object.keys(st.rating_counts || {}).map(function (k) { return '★' + k + ' ' + st.rating_counts[k] + '장'; });
    var cc = Object.keys(st.color_counts || {}).map(function (k) { return COLORS[k] + ' ' + st.color_counts[k] + '장'; });
    if (rc.length) line(p, '별점: ' + rc.join(', '));
    if (cc.length) line(p, '컬러 태그: ' + cc.join(', '));
    if (st.skipped_rating || st.skipped_color) line(p, '이미 값이 있어 건너뜀: 별점 ' + st.skipped_rating + '장, 컬러 태그 ' + st.skipped_color + '장');
    if (st.applied) line(p, '별점·컬러 태그도 줬어요. 되돌리기로 이전 값으로 돌릴 수 있어요.');
    (st.violations || []).forEach(function (v) { line(p, '확인 실패: ' + v, 'err'); });
  }
  function render() {
    if (!C) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, 'Capture One에도 표시하기'));
    var lab = ctx.el('label'); lab.appendChild(document.createTextNode('Capture One 카탈로그 또는 세션 이름 '));
    var inp = ctx.el('input'); inp.type = 'text'; inp.value = C.catalog; inp.placeholder = '지금 열려 있는 카탈로그나 세션 이름';
    inp.addEventListener('input', function () { C.catalog = inp.value; });
    lab.appendChild(inp); p.appendChild(lab);
    var chk = ctx.el('label'); var cb = ctx.el('input'); cb.type = 'checkbox'; cb.checked = C.partial;
    cb.addEventListener('change', function () { C.partial = cb.checked; });
    chk.appendChild(cb); chk.appendChild(document.createTextNode(' 카탈로그에서 찾은 사진만 반영하기')); p.appendChild(chk);
    if (C.busy) line(p, '잠시만요… Capture One과 이야기하는 중이에요.');
    if (C.error) line(p, C.error, 'err');
    renderStyle(p);
    renderBody(p); buttons(p);
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal && !C.busy) close(); });
    return modal;
  }

  root.BcutCapture = {init: init, open: open, isOpen: isOpen, render: render};
})(window);
