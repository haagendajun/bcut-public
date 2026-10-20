/* 훑기 모드의 순수 로직 (순서, 표시, 이동, 집계). DOM을 쓰지 않아서 따로 시험한다 (tests/test_ui_review_logic.py).
   spec FR-21·22: 촬영 순서로 한 장씩, S/M/X 표시, 같은 키를 다시 누르면 해제, 의심 컷은 건너뛰기를 켤 수 있다. */
(function (root) {
  'use strict';
  var MARKS = {pick: {label: '셀렉', key: 's', icon: '✓'}, maybe: {label: '보류', key: 'm', icon: '●'},
               discard: {label: '버릴 컷', key: 'x', icon: '✕'}};
  var KEY_TO_KIND = {s: 'pick', m: 'maybe', x: 'discard'};

  function markKey(row) { return row.file + '|' + row.size; }   // 사진 구분: 파일 이름 + 크기 (ADR-0004)
  /* 도구가 의심한 컷 (버릴 것 같은 컷, 직접 확인). 흐리게만 보이고 숨기지 않는다 (ADR-0007) */
  function isSuspect(row) { return row.status === 'candidate' || row.status === 'review'; }
  /* 촬영 순서. 지금은 파일 이름순으로 대신한다 (카메라 연번 = 촬영 순서, spec 가정 A6) */
  function order(rows) {
    return rows.slice().sort(function (a, b) { return a.file < b.file ? -1 : a.file > b.file ? 1 : 0; });
  }
  function marksMap(list) {
    var m = {};
    list.forEach(function (x) { m[x.file + '|' + x.size] = x.kind; });
    return m;
  }
  /* 같은 키를 다시 누르면 해제, 다른 키면 바꾼다. 지금 표시 -> 눌린 표시에 따른 새 표시(null이면 없음) */
  function nextMark(current, pressed) { return current === pressed ? null : pressed; }

  /* 한 칸 이동. 건너뛰기가 켜져 있으면 의심 컷은 지나친다. 갈 곳이 없으면 그 자리에 머문다 */
  function move(rows, index, delta, skipSuspect) {
    var i = index + delta;
    while (i >= 0 && i < rows.length) {
      if (!(skipSuspect && isSuspect(rows[i]))) return i;
      i += delta;
    }
    return index;
  }
  /* "이어서 훑기": 마지막으로 표시한 사진 다음. 표시가 없으면 처음 */
  function resumeIndex(rows, marks) {
    var last = -1;
    rows.forEach(function (r, i) { if (marks[markKey(r)]) last = i; });
    return last < 0 ? 0 : Math.min(rows.length - 1, last + 1);
  }
  function counts(rows, marks) {
    var c = {pick: 0, maybe: 0, discard: 0, none: 0, total: rows.length};
    rows.forEach(function (r) { var k = marks[markKey(r)]; if (k) c[k] += 1; else c.none += 1; });
    return c;
  }
  /* 필름스트립에 그릴 범위 (1500장을 한꺼번에 그리지 않는다) */
  function windowRange(total, index, radius) {
    return [Math.max(0, index - radius), Math.min(total, index + radius + 1)];
  }

  var api = {MARKS: MARKS, KEY_TO_KIND: KEY_TO_KIND, markKey: markKey, isSuspect: isSuspect, order: order,
             marksMap: marksMap, nextMark: nextMark, move: move, resumeIndex: resumeIndex, counts: counts,
             windowRange: windowRange};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.BcutReviewLogic = api;
})(typeof window !== 'undefined' ? window : this);
