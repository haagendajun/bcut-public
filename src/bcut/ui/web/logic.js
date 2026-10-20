/* 화면의 순수 로직 (분류, 필터, 정렬, 집계). DOM을 쓰지 않아서 따로 시험할 수 있다 (tests/test_ui_logic.py). */
(function (root) {
  'use strict';
  var STATUS = {candidate: '버릴 것 같은 컷', review: '직접 확인', normal: '이상 없음',
                no_face: '얼굴 없음', unscorable: '판단 못 함', rescued: '남긴 컷'};
  var NOTE = {small_eye: '눈이 작게 찍힘', group: '여러 명 사진', read_error: '읽지 못함'};
  var NOTE_TIP = {small_eye: '눈이 아주 작게 찍혀서 눈 상태를 믿기 어려워요. 직접 봐 주세요.',
                  group: '여러 명이 찍혀 있어서 한 명이라도 감았는지 직접 확인하는 게 좋아요.',
                  read_error: '사진 파일을 읽지 못했어요. 직접 열어서 확인해 주세요.'};
  var REASON = {eyes_closed: '눈 감김', exposure: '너무 밝거나 어두움', blur: '흔들려 찍힘',
                out_of_focus: '초점이 안 맞음'};
  var TIERS = [['flagged', '의심되는 컷 전체'], ['candidate', '버릴 것 같은 컷'], ['review', '직접 확인'],
               ['rescued', '남긴 컷'], ['normal', '이상 없음'], ['other', '얼굴 없음·판단 못 함'],
               ['all', '전체']];

  function isRescued(row, rescued) {
    return !!rescued[row.file] && (row.status === 'candidate' || row.status === 'review');
  }
  /* 화면에서 쓰는 등급: 후보·확인 컷을 살리면 '정상'으로 간다 (정리 결과와 같은 규칙) */
  function tierOf(row, rescued) {
    if (isRescued(row, rescued)) return 'rescued';
    if (row.status === 'no_face' || row.status === 'unscorable') return 'other';
    return row.status;
  }
  function inTier(row, tier, rescued) {
    var t = tierOf(row, rescued);
    if (tier === 'all') return true;
    if (tier === 'flagged') return t === 'candidate' || t === 'review';
    return t === tier;
  }
  /* 살린 컷은 사유 목록에서도 빠진다 (정리 폴더의 사유별과 같은 규칙) */
  function reasonsOf(row, rescued) { return isRescued(row, rescued) ? [] : (row.reasons || []); }

  function filterRows(rows, rescued, f) {
    return rows.filter(function (r) {
      if (!inTier(r, f.tier, rescued)) return false;
      if (f.reason && reasonsOf(r, rescued).indexOf(f.reason) < 0) return false;
      if (f.note && r.note !== f.note) return false;
      if (f.mark && markOf(r, f.marks) !== f.mark) return false;   // 내 표시: pick | maybe | discard | none
      return true;
    });
  }
  /* 사용자가 단 표시. 없으면 'none' */
  function markOf(row, marks) { return (marks && marks[row.file]) || 'none'; }
  function markCounts(rows, marks) {
    var c = {pick: 0, maybe: 0, discard: 0, none: 0};
    rows.forEach(function (r) { c[markOf(r, marks)] += 1; });
    return c;
  }
  function cmpName(a, b) { return a.file < b.file ? -1 : a.file > b.file ? 1 : 0; }
  function sortRows(rows, key) {
    var out = rows.slice();
    out.sort(function (a, b) {
      if (key === 'name') return cmpName(a, b);
      if (key === 'faces') return (b.faces - a.faces) || cmpName(a, b);
      if (key === 'score') {
        var x = a.score === null ? 9 : a.score, y = b.score === null ? 9 : b.score;
        return (x - y) || cmpName(a, b);
      }
      var cx = a.confidence === null ? -1 : a.confidence, cy = b.confidence === null ? -1 : b.confidence;
      return (cy - cx) || cmpName(a, b);   // 확신도 높은 순 (기본)
    });
    return out;
  }
  function counts(rows, rescued) {
    var c = {candidate: 0, review: 0, rescued: 0, normal: 0, other: 0, total: rows.length, reasons: {}};
    rows.forEach(function (r) {
      c[tierOf(r, rescued)] += 1;
      reasonsOf(r, rescued).forEach(function (k) { c.reasons[k] = (c.reasons[k] || 0) + 1; });
    });
    return c;
  }
  function rescuedNames(rows, rescued) {
    return rows.filter(function (r) { return isRescued(r, rescued); }).map(function (r) { return r.file; });
  }
  function step(length, index, delta) {   // 보기 창에서 이전·다음 (끝에서 멈춘다)
    if (!length) return -1;
    return Math.max(0, Math.min(length - 1, index + delta));
  }
  function badges(row, rescued) {
    var out = [{cls: 'b-' + (isRescued(row, rescued) ? 'normal' : (row.status === 'no_face' || row.status === 'unscorable' ? 'other' : row.status)),
                text: isRescued(row, rescued) ? STATUS.rescued : STATUS[row.status] || row.status}];
    reasonsOf(row, rescued).forEach(function (k) { out.push({cls: 'b-review', text: REASON[k] || k}); });
    if (row.note) out.push({cls: 'b-other', text: NOTE[row.note] || row.note, tip: NOTE_TIP[row.note] || ''});
    return out;
  }
  /* 카드에 보여 줄 쉬운 설명 (점수 같은 숫자 대신 말로) */
  function explain(row, rescued) {
    if (isRescued(row, rescued)) return ['남기기로 했어요. 나누어 담으면 이상 없음 폴더로 가요.'];
    var out = [], rs = row.reasons || [];
    if (rs.indexOf('eyes_closed') >= 0) out.push(row.status === 'candidate' ? '눈이 거의 감긴 것 같아요.' : '눈이 감겼을 수도 있어요.');
    if (rs.indexOf('exposure') >= 0) {
      out.push({over_face: '얼굴이 너무 밝게 찍혔어요.', over_global: '사진 전체가 너무 밝아요.',
                under: '사진 전체가 너무 어두워요.'}[row.exposure] || '너무 밝거나 어두워요.');
    }
    if (rs.indexOf('blur') >= 0) out.push('사진 전체가 흔들린 것 같아요.');
    if (rs.indexOf('out_of_focus') >= 0) out.push('얼굴에 초점이 안 맞은 것 같아요.');
    if (!out.length) {
      if (row.note === 'read_error') out.push('사진을 읽지 못해서 직접 확인이 필요해요.');
      else if (row.status === 'no_face') out.push('얼굴이 없어서 눈은 보지 않았어요.');
      else if (row.status === 'unscorable') out.push('눈을 판단하기 어려웠어요.');
      else if (row.status === 'normal') out.push('눈이 떠 있고 큰 문제가 안 보여요.');
      else out.push('직접 확인해 주세요.');
    }
    return out;
  }
  /* 의심 정도 (확신도 숫자 대신 높음·보통·낮음) */
  function suspicion(conf) {
    if (conf === null || conf === undefined) return '';
    return conf >= 0.7 ? '높음' : conf >= 0.4 ? '보통' : '낮음';
  }
  function planLines(plan) {   // 정리 미리보기 문장
    var names = Object.keys(plan.counts);
    return names.map(function (n) { return n + ': ' + plan.counts[n] + '장'; });
  }
  /* 우선순위 묶음: 먼저 볼 것부터 위에서 아래로. 각 묶음 안은 의심 정도가 높은 순 */
  function priorityGroups(rows, rescued) {
    var b = {candidate: [], review: [], rescued: [], normal: [], other: []};
    rows.forEach(function (r) { b[tierOf(r, rescued)].push(r); });
    return [
      {id: 'candidate', rank: 1, title: '먼저 보세요', sub: '버릴 것 같은 컷',
       desc: '문제가 분명해 보이는 컷이에요. 버려도 되는지 먼저 확인하세요.', rows: sortRows(b.candidate, 'confidence')},
      {id: 'review', rank: 2, title: '그다음 확인하세요', sub: '직접 확인',
       desc: '도구가 확신하지 못한 컷이에요. 한 장씩 직접 보고 판단해 주세요.', rows: sortRows(b.review, 'confidence')},
      {id: 'rescued', rank: 0, title: '남기기로 한 컷', sub: '',
       desc: '나누어 담으면 이상 없음 폴더로 가요.', rows: sortRows(b.rescued, 'name')},
      {id: 'normal', rank: 3, title: '이상 없음', sub: '',
       desc: '문제가 안 보인 컷이에요. 급하면 건너뛰어도 돼요.', rows: sortRows(b.normal, 'name')},
      {id: 'other', rank: 3, title: '얼굴 없음 · 판단 못 함', sub: '',
       desc: '눈 상태를 보지 못한 컷이에요. 사람이 없거나 판단이 어려웠어요.', rows: sortRows(b.other, 'name')}
    ];
  }
  /* 화면에 펼쳐진 묶음의 사진을 위에서 아래 순서로 이은 목록 (크게 보기에서 이전·다음에 쓴다) */
  function visibleOrder(groups, open) {
    var out = [];
    groups.forEach(function (g) { if (open[g.id]) g.rows.forEach(function (r) { out.push(r); }); });
    return out;
  }
  function formatBytes(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : (n / 1e6).toFixed(0) + 'MB'; }

  var api = {STATUS: STATUS, NOTE: NOTE, NOTE_TIP: NOTE_TIP, REASON: REASON, TIERS: TIERS, tierOf: tierOf, inTier: inTier,
             reasonsOf: reasonsOf, filterRows: filterRows, markOf: markOf, markCounts: markCounts, sortRows: sortRows, counts: counts,
             rescuedNames: rescuedNames, step: step, badges: badges, explain: explain, suspicion: suspicion,
             planLines: planLines,
             formatBytes: formatBytes, isRescued: isRescued, priorityGroups: priorityGroups,
             visibleOrder: visibleOrder};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.BcutLogic = api;
})(typeof window !== 'undefined' ? window : this);
