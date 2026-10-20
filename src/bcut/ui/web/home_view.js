/* 결과 화면의 윗부분 (IA RV-08-APP): 훑기를 주인공으로 두고, 검사 요약은 한 줄로 줄이고,
   덜 쓰는 버튼은 "더보기"에 모은다. app.js가 부르는 작은 부품 모음이다. */
(function (root) {
  'use strict';
  var ctx = null;          // {el}
  var H = {menu: false};   // 더보기 메뉴가 열려 있는가

  var PARTS = [['candidate', 'var(--p1)', '버릴 것 같은 컷'], ['review', 'var(--p2)', '직접 확인'],
               ['normal', 'var(--ok)', '이상 없음'], ['other', 'var(--faint)', '얼굴 없음·판단 못 함']];

  function init(c, rerender) {
    ctx = c;
    document.addEventListener('click', function (e) {   // 메뉴 밖을 누르면 닫는다
      if (H.menu && !e.target.closest('.more-wrap')) { H.menu = false; rerender(); }
    });
    document.addEventListener('keydown', function (e) {
      if (H.menu && e.key === 'Escape') { H.menu = false; rerender(); }
    });
  }

  /* ⋯ 더보기: 항목은 버튼 목록 */
  function moreMenu(items, rerender) {
    var wrap = ctx.el('span', 'more-wrap');
    var b = ctx.el('button', 'ghost', '더보기 ⋯'); b.setAttribute('aria-haspopup', 'true');
    b.setAttribute('aria-expanded', String(H.menu));
    b.addEventListener('click', function (e) { e.stopPropagation(); H.menu = !H.menu; rerender(); });
    wrap.appendChild(b);
    if (H.menu) {
      var pop = ctx.el('div', 'more-pop');
      items.forEach(function (it) { pop.appendChild(it); });
      pop.addEventListener('click', function () { H.menu = false; setTimeout(rerender, 0); });   // 항목을 고르면 메뉴를 닫는다
      wrap.appendChild(pop);
    }
    return wrap;
  }

  /* 훑기가 주인공인 카드 */
  function hero(c, marks, onStart) {
    var box = ctx.el('div', 'hero-card'), left = c.candidate + c.review;
    var text = ctx.el('div', 'hero-text');
    var done = marks.pick + marks.maybe + marks.discard;
    text.appendChild(ctx.el('h2', null, done ? '이어서 훑어요' : '훑기부터 시작해요'));
    text.appendChild(ctx.el('p', 'lead', done
      ? '표시한 사진 ' + done + '장 · 셀렉 ' + marks.pick + ' · 보류 ' + marks.maybe + ' · 버릴 컷 ' + marks.discard
      : '큰 화면에서 한 장씩 보며 셀렉(S)·보류(M)·버릴 컷(X)을 표시해요.'));
    if (left) text.appendChild(ctx.el('p', 'muted', '도구가 먼저 보라고 한 컷이 ' + left + '장 있어요. 훑을 때 이유와 함께 흐리게 보여 줘요.'));
    box.appendChild(text);
    var go = ctx.el('button', 'primary hero-go', done ? '이어서 훑기' : '훑기 시작');
    go.addEventListener('click', onStart);
    box.appendChild(go);
    return box;
  }

  /* 검사 요약 한 줄: 막대 + 범례 */
  function compact(c) {
    var ov = ctx.el('div', 'overview compact');
    var meter = ctx.el('div', 'meter');
    PARTS.forEach(function (p) {
      if (!c[p[0]]) return;
      var s = ctx.el('span', 'm-' + p[0]); s.style.flex = String(c[p[0]]); s.title = p[2] + ' ' + c[p[0]] + '장'; meter.appendChild(s);
    });
    ov.appendChild(meter);
    var lg = ctx.el('div', 'legend');
    lg.appendChild(ctx.el('span', 'k muted', '도구의 검사 · 사진 ' + c.total + '장'));
    PARTS.forEach(function (p) {
      var k = ctx.el('span', 'k'), dot = ctx.el('span', 'dot'); dot.style.background = p[1]; k.appendChild(dot);
      k.appendChild(document.createTextNode(p[2] + ' ')); k.appendChild(ctx.el('b', null, String(c[p[0]]))); lg.appendChild(k);
    });
    ov.appendChild(lg);
    return ov;
  }

  root.BcutHome = {init: init, moreMenu: moreMenu, hero: hero, compact: compact};
})(window);
