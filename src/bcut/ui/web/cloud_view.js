/* 클라우드 올리기 화면: 상태 표시, 동의 안내, 로그인, 지금 올리기 (spec FR-29~33, IA CL-01·02-APP).
   비밀번호는 입력칸에만 있고 보낸 즉시 지운다. 상태 문구는 글자와 아이콘을 함께 쓴다 (색만으로 구분하지 않음). */
(function (root) {
  'use strict';
  var ctx = null;                       // {el, api, rerender}
  var C = {st: null, open: false, busy: false, error: null};
  var EVERY_MS = 5 * 60 * 1000;

  var LABEL = {need_consent: ['☁', '클라우드 저장 켜기'], need_login: ['🔑', '로그인 필요'],
               synced: ['✓', '올림 완료'], pending: ['⏳', '대기'], error: ['⚠', '올리기 실패']};

  function init(c) {
    ctx = c;
    refresh().then(function () { sync(); });
    setInterval(function () { sync(); }, EVERY_MS);
    document.addEventListener('bcut-review-recorded', function () { sync(); });   // 훑기를 마칠 때
  }
  function set(st) { C.st = st; ctx.rerender(); }
  function refresh() {
    return ctx.api('GET', '/api/cloud/status').then(set).catch(function () {});
  }
  /* 동의·로그인이 되어 있을 때만 서버가 요청을 보낸다. 아니면 상태만 돌려준다 */
  function sync() {
    if (C.busy) return Promise.resolve();
    C.busy = true; C.error = null; ctx.rerender();
    return ctx.api('POST', '/api/cloud/sync', {}).then(set).catch(function (e) { C.error = e.message; })
      .then(function () { C.busy = false; ctx.rerender(); });
  }
  function post(path, body) {
    C.busy = true; C.error = null; ctx.rerender();
    return ctx.api('POST', path, body || {}).then(function (st) { C.busy = false; set(st); return st; })
      .catch(function (e) { C.busy = false; C.error = e.message; ctx.rerender(); });
  }

  function chipText() {
    var s = C.st;
    if (!s) return ['☁', '클라우드'];
    if (C.busy || s.syncing) return ['↻', '올리는 중…'];
    var l = LABEL[s.state] || LABEL.error;
    return [l[0], l[1] + (s.pending && s.state !== 'need_consent' ? ' ' + s.pending + '건' : '')];
  }
  function chip() {
    var t = chipText();
    var b = ctx.el('button', 'ghost cloud-chip', t[0] + ' ' + t[1]);
    b.title = '표시와 훑기 기록을 내 데이터베이스에 올려 두는 기능이에요 (사진은 올라가지 않아요).';
    b.addEventListener('click', function () { C.open = true; C.error = null; refresh(); ctx.rerender(); });
    return b;
  }

  function close() { C.open = false; ctx.rerender(); }
  function bullets(p, title, items) {
    p.appendChild(ctx.el('div', 'muted', title));
    var ul = ctx.el('ul');
    items.forEach(function (t) { ul.appendChild(ctx.el('li', null, t)); });
    p.appendChild(ul);
  }
  function renderConsent(p) {
    bullets(p, '올라가는 것', ['셀렉·보류·버릴 컷을 단 사진의 파일 이름과 크기, 표시 종류와 시각',
                              '훑기 한 번의 시작·끝 시각과 본 사진 수, 표시 수', '행사 이름(폴더 이름)']);
    bullets(p, '올라가지 않는 것', ['사진 파일과 미리보기 그림', '컴퓨터 안의 폴더 위치(경로)']);
    p.appendChild(ctx.el('p', 'muted', '내 계정의 데이터베이스에만 쌓이고, 지우는 동작은 없어요. 인터넷이 없어도 훑기는 그대로 되고, 연결되면 이어서 올라가요.'));
    var ok = ctx.el('button', 'primary', '동의하고 켜기');
    ok.addEventListener('click', function () { post('/api/cloud/consent'); });
    p.appendChild(ok);
  }
  function renderLogin(p) {
    p.appendChild(ctx.el('p', null, '이메일과 비밀번호로 한 번 로그인하면 다음부터는 자동으로 올라가요. 비밀번호는 저장하지 않아요.'));
    var email = ctx.el('input'); email.type = 'text'; email.placeholder = '이메일'; email.autocomplete = 'username';
    var pw = ctx.el('input'); pw.type = 'password'; pw.placeholder = '비밀번호'; pw.autocomplete = 'current-password';
    var go = ctx.el('button', 'primary', '로그인');
    function submit() {
      var body = {email: email.value, password: pw.value}; pw.value = '';
      post('/api/cloud/login', body).then(function () { sync(); });
    }
    go.addEventListener('click', submit);
    pw.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
    var row = ctx.el('div', 'row'); row.appendChild(email); row.appendChild(pw); row.appendChild(go);
    p.appendChild(row);
  }
  function renderStatus(p, s) {
    var t = chipText();
    p.appendChild(ctx.el('p', null, t[0] + ' ' + t[1]));
    p.appendChild(ctx.el('div', 'muted', (s.email || '') + (s.last_sync_at ? ' · 마지막으로 올린 때 ' + s.last_sync_at.replace('T', ' ').slice(0, 16) : '')));
    if (s.error) p.appendChild(ctx.el('div', 'err', s.error + ' (표시는 이 컴퓨터에 안전하게 있어요. 다시 시도하면 이어서 올라가요.)'));
    var row = ctx.el('div', 'row');
    var now = ctx.el('button', 'primary', '지금 올리기'); now.disabled = C.busy;
    now.addEventListener('click', function () { sync(); });
    var out = ctx.el('button', null, '로그아웃');
    out.addEventListener('click', function () { post('/api/cloud/logout'); });
    row.appendChild(now); row.appendChild(out); p.appendChild(row);
  }
  function render() {
    if (!C.open || !C.st) return null;
    var s = C.st;
    var modal = ctx.el('div', 'modal');
    var p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, '클라우드에 올리기'));
    if (!s.consented) renderConsent(p);
    else if (!s.signed_in) renderLogin(p);
    else renderStatus(p, s);
    if (C.error) p.appendChild(ctx.el('div', 'err', C.error));
    var done = ctx.el('button', 'ghost', '닫기'); done.addEventListener('click', close);
    p.appendChild(ctx.el('div', 'row')).appendChild(done);
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
    return modal;
  }
  function isOpen() { return C.open; }

  root.BcutCloud = {init: init, chip: chip, render: render, isOpen: isOpen, sync: sync};
})(window);
