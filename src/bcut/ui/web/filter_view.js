/* "전체 목록" 보기의 걸러 보기 (IA RV-08-APP). 세 줄로 정리했다:
   ① 도구의 판정(+ 아래에 들여쓴 문제 종류)  ② 내 표시(셀렉·보류·버릴 컷·아직 안 함)  ③ 순서.
   판정과 내 표시는 함께 걸러진다 (예: "버릴 것 같은 컷" 중에서 내가 "셀렉"한 사진). */
(function (root) {
  'use strict';
  var MARKS = [['pick', '★ 셀렉'], ['maybe', '? 보류'], ['discard', '✕ 버릴 컷'], ['none', '아직 표시 안 함']];
  var SORTS = [['confidence', '의심 정도 높은 순'], ['score', '눈이 많이 감긴 순'], ['name', '파일 이름순'],
               ['faces', '사람 많은 순']];

  function chip(el, text, on, fn) {
    var b = el('button', null, text); b.setAttribute('aria-pressed', String(on));
    b.addEventListener('click', fn); return b;
  }
  function group(el, label) {
    var tb = el('div', 'toolbar'); tb.appendChild(el('label', 'fgroup', label));
    var chips = el('div', 'chips'); tb.appendChild(chips);
    return {tb: tb, chips: chips};
  }

  /* x: {el, S, L, render, gridOf} */
  function render(x, w, c) {
    var el = x.el, S = x.S, L = x.L;
    var g1 = group(el, '도구의 판정');
    var label = {};
    L.TIERS.forEach(function (t) { label[t[0]] = t[1]; });
    function tierChip(id, cls) {
      var n = L.filterRows(S.rows, S.rescued, {tier: id}).length;
      if (id === 'rescued' && !n) return null;   // 예전에 남겨 둔 컷은 셀렉으로 옮겨져서 보통 비어 있다
      var b = chip(el, (id === 'all' ? '전체' : label[id]) + ' ' + n, S.tier === id, function () { S.tier = id; x.render(); });
      if (cls) b.className = cls;
      return b;
    }
    g1.chips.appendChild(tierChip('all'));                       // 맨 앞: 내 표시의 "전체"와 같은 자리
    var sus = el('span', 'chip-group'); sus.title = '의심되는 컷 전체 = 버릴 것 같은 컷 + 직접 확인';
    ['flagged', 'candidate', 'review', 'rescued'].forEach(function (id, i) {
      var b = tierChip(id, i ? 'sub' : 'parent'); if (b) sus.appendChild(b);
    });
    g1.chips.appendChild(sus);                                   // 의심되는 컷은 한 묶음 (위: 전체, 아래: 둘로 나눔)
    ['normal', 'other'].forEach(function (id) { g1.chips.appendChild(tierChip(id)); });
    w.appendChild(g1.tb);
    var suspectTier = S.tier === 'flagged' || S.tier === 'candidate' || S.tier === 'review';
    var rs = Object.keys(c.reasons);
    if (!suspectTier) S.reason = null;   // 문제 종류는 의심되는 컷에만 있다
    if (suspectTier && rs.length) {
      var g4 = group(el, '└ 문제 종류'); g4.tb.className += ' sub-row';
      rs.forEach(function (k) {
        g4.chips.appendChild(chip(el, (L.REASON[k] || k) + ' ' + c.reasons[k], S.reason === k, function () {
          S.reason = S.reason === k ? null : k; x.render();
        }));
      });
      w.appendChild(g4.tb);
    }

    var g2 = group(el, '내 표시'), mc = L.markCounts(S.rows, S.markMap);
    g2.chips.appendChild(chip(el, '전체 ' + S.rows.length, !S.mark, function () { S.mark = null; x.render(); }));
    MARKS.forEach(function (m) {
      g2.chips.appendChild(chip(el, m[1] + ' ' + mc[m[0]], S.mark === m[0], function () {
        S.mark = S.mark === m[0] ? null : m[0];
        if (S.mark) S.tier = 'all';   // 칩의 장수와 목록이 같아지게 판정 걸러내기를 푼다
        x.render();
      }));
    });
    w.appendChild(g2.tb);

    var g3 = el('div', 'toolbar');
    g3.appendChild(el('span', 'grow'));
    g3.appendChild(el('label', null, '순서'));
    var sel = el('select');
    SORTS.forEach(function (o) {
      var op = el('option', null, o[1]); op.value = o[0]; if (S.sort === o[0]) op.selected = true; sel.appendChild(op);
    });
    sel.addEventListener('change', function () { S.sort = sel.value; x.render(); });
    g3.appendChild(sel); w.appendChild(g3);

    S.list = L.sortRows(L.filterRows(S.rows, S.rescued, {tier: S.tier, reason: S.reason, note: S.note,
                                                       mark: S.mark, marks: S.markMap}), S.sort);
    var bar = el('div', 'toolbar');
    bar.appendChild(el('span', 'count', '지금 보이는 사진 ' + S.list.length + '장 / 전체 ' + c.total + '장'));
    var filtered = S.tier !== 'all' || S.reason || S.mark;
    if (filtered) {
      var clear = el('button', 'ghost', '필터 모두 풀기');
      clear.addEventListener('click', function () { S.tier = 'all'; S.reason = null; S.mark = null; x.render(); });
      bar.appendChild(clear);
    }
    w.appendChild(bar);
    if (!S.list.length) w.appendChild(el('div', 'empty', '이 조건에 맞는 사진이 없어요.'));
    else w.appendChild(x.gridOf(S.list, 0));
  }

  root.BcutFilters = {render: render};
})(window);
