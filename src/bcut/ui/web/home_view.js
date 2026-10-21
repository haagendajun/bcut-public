/* 결과 화면의 윗부분 (IA RV-08-APP): 훑기를 주인공으로 두고, 검사 요약은 한 줄로 줄이고,
   덜 쓰는 버튼은 "더보기"에 모은다. app.js가 부르는 작은 부품 모음이다. */
(function (root) {
  'use strict';
  var ctx = null;          // {el}
  var H = {menu: false};   // 더보기 메뉴가 열려 있는가

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
  function hero(c, marks) {
    var box = ctx.el('div', 'hero-card'), left = c.candidate + c.review;
    var text = ctx.el('div', 'hero-text');
    var done = marks.pick + marks.maybe + marks.discard;
    text.appendChild(ctx.el('h2', null, done ? '이어서 훑어요' : '훑기부터 시작해요'));
    text.appendChild(ctx.el('p', 'lead', done
      ? '표시한 사진 ' + done + '장 · 셀렉 ' + marks.pick + ' · 보류 ' + marks.maybe + ' · 버릴 컷 ' + marks.discard
      : '큰 화면에서 한 장씩 보며 셀렉(S)·보류(M)·버릴 컷(X)을 표시해요.'));
    if (left) text.appendChild(ctx.el('p', 'muted', '도구가 먼저 보라고 한 컷이 ' + left + '장 있어요. 훑을 때 이유와 함께 흐리게 보여 줘요.'));
    box.appendChild(text);
    return box;
  }

  /* 검사 요약: 색이 다른 유리 카드 세 장 (버릴 것 같은 컷 · 직접 확인 · 이상 없음) */
  var CARDS = [['candidate', 'pink', '버릴 것 같은 컷', '먼저 보세요 · 이유와 함께 표시해 뒀어요'],
               ['review', 'lavender', '직접 확인', '앱이 판단하기 어려운 컷이에요'],
               ['normal', 'mint', '이상 없음', '눈·흔들림 문제가 안 보여요']];
  function compact(c) {
    var ov = ctx.el('div', 'overview compact');
    var row = ctx.el('div', 'stat3');
    CARDS.forEach(function (p) {
      var card = ctx.el('article', 'gcard ' + p[1] + ' stat');
      card.appendChild(ctx.el('div', 'stat-l', p[2]));
      var low = ctx.el('div', null);
      low.appendChild(ctx.el('div', 'stat-n', String(c[p[0]])));
      low.appendChild(ctx.el('div', 'stat-s', p[3]));
      card.appendChild(low);
      row.appendChild(card);
    });
    ov.appendChild(row);
    if (c.other) ov.appendChild(ctx.el('p', 'muted stat-more', '얼굴이 없거나 판단하지 못한 사진 ' + c.other + '장은 위 숫자에 들어 있지 않아요.'));
    return ov;
  }

  root.BcutHome = {init: init, moreMenu: moreMenu, hero: hero, compact: compact};
})(window);
