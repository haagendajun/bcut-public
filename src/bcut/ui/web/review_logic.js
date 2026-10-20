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

  /* 눈 확대: 얼굴의 눈 상자들을 합쳐 양쪽 눈이 들어오는 가로로 긴 영역을 만든다 (좌표는 사진 크기에 대한 비율).
     w, h는 사진 픽셀 크기. 눈 위치가 없으면 null. 가로:세로가 1:0.45가 되게 픽셀 비율을 맞추고 사진 안으로 밀어 넣는다 */
  function eyeCrop(face, w, h) {
    if (!face || !face.eyes || !face.eyes.length) return null;
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    face.eyes.forEach(function (b) {
      x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]); x1 = Math.max(x1, b[0] + b[2]); y1 = Math.max(y1, b[1] + b[3]);
    });
    var cw = Math.min(1, Math.max((x1 - x0) * 1.5, 0.03));
    var ch = Math.min(1, cw * 0.45 * (w / h));
    var x = Math.min(Math.max((x0 + x1) / 2 - cw / 2, 0), 1 - cw), y = Math.min(Math.max((y0 + y1) / 2 - ch / 2, 0), 1 - ch);
    return {x: x, y: y, w: cw, h: ch};
  }

  /* 실행 취소 기록: 표시를 달 때마다 {key, file, before, after, from}을 쌓고, 최근 것부터 되돌린다 */
  var HISTORY_LIMIT = 200;
  function recordChange(history, change) {
    var h = history.concat([change]);
    return h.length > HISTORY_LIMIT ? h.slice(h.length - HISTORY_LIMIT) : h;
  }
  function lastChange(history) { return history.length ? history[history.length - 1] : null; }
  function dropLast(history) { return history.slice(0, -1); }
  function dropChange(history, change) { return history.filter(function (h) { return h !== change; }); }

  var api = {MARKS: MARKS, eyeCrop: eyeCrop, recordChange: recordChange, lastChange: lastChange, dropLast: dropLast,
             dropChange: dropChange, KEY_TO_KIND: KEY_TO_KIND, markKey: markKey, isSuspect: isSuspect, order: order,
             marksMap: marksMap, nextMark: nextMark, move: move, resumeIndex: resumeIndex, counts: counts,
             windowRange: windowRange};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.BcutReviewLogic = api;
})(typeof window !== 'undefined' ? window : this);
