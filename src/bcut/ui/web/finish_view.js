/* "어떻게 마무리할까요?" 창 (spec FR-37, IA FN-01-APP). 마무리 방법 둘 중 하나를 고른다:
   ① Capture One에 표시 (원본·폴더는 그대로)  ② 폴더로 나누어 담기 (사본을 만듦).
   고르면 이 창은 닫히고, 고른 쪽 창이 열린다. 다른 방법이 필요하면 다시 열어 고르면 된다. */
(function (root) {
  'use strict';
  var ctx = null;   // {el, markCount, openCapture, openSort, rerender}
  var F = null;     // 창이 열려 있을 때만 있는 상태

  function init(c) { ctx = c; }
  function isOpen() { return F !== null; }
  function open() { F = {}; ctx.rerender(); }
  function close() { F = null; ctx.rerender(); }
  function choose(fn) { F = null; ctx.rerender(); fn(); }

  function card(icon, title, lines, onPick) {
    var b = ctx.el('button', 'fin-card'); b.type = 'button';
    b.appendChild(ctx.el('span', 'fin-icon', icon));
    var t = ctx.el('span', 'fin-text'); t.appendChild(ctx.el('b', null, title));
    lines.forEach(function (l) { t.appendChild(ctx.el('span', 'muted', l)); });
    b.appendChild(t);
    b.addEventListener('click', function () { choose(onPick); });
    return b;
  }
  function render() {
    if (!F) return null;
    var modal = ctx.el('div', 'modal'), p = ctx.el('div', 'panel');
    p.appendChild(ctx.el('h2', null, '어떻게 마무리할까요?'));
    var n = ctx.markCount();
    p.appendChild(ctx.el('p', 'muted', n ? '지금 표시한 사진은 ' + n + '장이에요. 하나를 골라 주세요.' : '아직 표시한 사진이 없어요. 훑기에서 먼저 셀렉·보류·버릴 컷을 표시해 주세요.'));
    var list = ctx.el('div', 'fin-list');
    list.appendChild(card('🏷', 'Capture One에 표시하기', [
      '원본과 폴더는 그대로 두고, Capture One 안에서 표시해요.',
      '키워드(셀렉·보류·버릴 컷)를 붙이고, 원하면 별점·컬러 태그도 줘요.',
      '사본을 만들지 않아서 저장 공간을 쓰지 않아요. Capture One이 켜져 있어야 해요.'], ctx.openCapture));
    list.appendChild(card('📁', '폴더로 나누어 담기', [
      '셀렉·보류·판정별 폴더에 사진 사본을 만들어요. 원본은 그대로예요.',
      'Capture One 없이 폴더로 전달하거나 다른 프로그램에서 쓸 때 좋아요.',
      '같은 디스크에서는 저장 공간을 거의 쓰지 않아요.'], ctx.openSort));
    p.appendChild(list);
    p.appendChild(ctx.el('p', 'muted', '다른 방법이 필요하면 나중에 "마무리하기"로 다시 열어서 고르면 돼요.'));
    var row = ctx.el('div', 'row'), cancel = ctx.el('button', 'ghost', '닫기');
    cancel.addEventListener('click', close); row.appendChild(cancel); p.appendChild(row);
    var xb = ctx.el('button', 'ghost x-btn', '✕'); xb.type = 'button'; xb.setAttribute('aria-label', '닫기'); xb.addEventListener('click', close); p.appendChild(xb);
    modal.appendChild(p);
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
    return modal;
  }

  root.BcutFinish = {init: init, open: open, render: render, isOpen: isOpen, close: close};
})(window);
