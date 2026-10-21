/* 알림바 (화면 아래 가운데에 잠깐 떴다가 사라진다). 실수로 한 일을 바로 "되돌리기"로 취소할 수 있게 한다.
   알림은 최대 세 개까지 위로 쌓이고, 마우스를 올려 두면 그 알림은 사라지지 않는다.
   스크린 리더에는 알림으로 읽힌다. */
(function (root) {
  'use strict';
  var stack = null;
  var SHOW_MS = 9000, MAX = 3;

  function holder() {
    if (stack && stack.parentNode) return stack;
    stack = document.createElement('div');
    stack.className = 'snack-stack';
    stack.setAttribute('role', 'status');
    stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
    return stack;
  }
  function drop(bar) { if (bar.parentNode) bar.parentNode.removeChild(bar); }

  /* show('휴지통으로 옮겼어요', {label: '되돌려 놓기', onAction: fn, ms: 9000}) */
  function show(text, opts) {
    opts = opts || {};
    var box = holder(), bar = document.createElement('div'), timer = null;
    bar.className = 'snack';
    function arm(ms) { if (timer) clearTimeout(timer); timer = setTimeout(function () { drop(bar); }, ms); }
    var msg = document.createElement('span');
    msg.className = 'snack-text';
    msg.textContent = text;
    bar.appendChild(msg);
    if (opts.label && opts.onAction) {
      var act = document.createElement('button');
      act.type = 'button';
      act.className = 'snack-act';
      act.textContent = opts.label;
      act.addEventListener('click', function () { var f = opts.onAction; drop(bar); f(); });
      bar.appendChild(act);
    }
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'snack-x';
    x.textContent = '✕';
    x.setAttribute('aria-label', '알림 닫기');
    x.addEventListener('click', function () { drop(bar); });
    bar.appendChild(x);
    bar.addEventListener('mouseenter', function () { if (timer) { clearTimeout(timer); timer = null; } });
    bar.addEventListener('mouseleave', function () { arm(SHOW_MS / 2); });
    box.appendChild(bar);
    while (box.children.length > MAX) drop(box.firstChild);
    arm(opts.ms || SHOW_MS);
  }
  function hide() { if (stack) while (stack.firstChild) drop(stack.firstChild); }

  root.BcutSnack = {show: show, hide: hide};
})(window);
