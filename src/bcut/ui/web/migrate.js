/* 예전 화면이 브라우저 저장소에 적어 둔 "남겨 둔 사진" 목록을 셀렉 표시로 옮긴다 (spec FR-27).
   이미 표시가 있는 사진은 건드리지 않는다. 옮긴 뒤에는 표시를 달아 두어 두 번 옮기지 않는다 (저장소 내용은 지우지 않는다). */
(function (root) {
  'use strict';
  function key(folder) { return 'bcut-rescue:' + folder; }
  function doneKey(folder) { return 'bcut-rescue-migrated:' + folder; }

  function readOld(folder) {
    try {
      if (localStorage.getItem(doneKey(folder))) return [];
      var raw = localStorage.getItem(key(folder));
      var names = raw ? JSON.parse(raw) : [];
      return Array.isArray(names) ? names.filter(function (n) { return typeof n === 'string'; }) : [];
    } catch (e) { return []; }
  }
  function markDone(folder, n) { try { localStorage.setItem(doneKey(folder), String(n)); } catch (e) {} }

  /* 옮길 사진: 이번 검사에 있고 아직 표시가 없는 것 (순수 함수라 따로 시험한다) */
  function todo(names, rows, marks) {
    var inScan = {}, has = {};
    rows.forEach(function (r) { inScan[r.file] = true; });
    marks.forEach(function (m) { has[m.file] = true; });
    return names.filter(function (f) { return inScan[f] && !has[f]; });
  }

  /* 옮긴 사진 수를 돌려준다 (옮길 것이 없으면 0) */
  function toPicks(folder, rows, api, job) {
    var names = readOld(folder);
    if (!names.length) return Promise.resolve(0);
    return api('GET', '/api/jobs/' + job + '/marks').then(function (j) {
      var list = todo(names, rows, j.marks);
      return list.reduce(function (p, f) {
        return p.then(function () { return api('POST', '/api/jobs/' + job + '/marks', {file: f, kind: 'pick'}); });
      }, Promise.resolve()).then(function () { markDone(folder, list.length); return list.length; });
    }).catch(function () { return 0; });
  }

  root.BcutMigrate = {toPicks: toPicks, todo: todo};
})(window);
