/* 훑기 화면의 단축키 도움말(? 키)과 처음 한 번만 보이는 안내 (IA RV-09-APP).
   review.js가 부르는 작은 부품이다. 안내를 봤다는 기억은 이 화면 저장소에만 둔다. */
(function (root) {
  'use strict';
  var KEY = 'bcut-review-tip-seen';
  var KEYS = [['S', '셀렉으로 표시하고 다음 사진으로'], ['M', '보류로 표시하고 다음 사진으로'],
              ['X', '버릴 컷으로 표시하고 다음 사진으로'], ['같은 키를 다시', '표시를 해제해요'],
              ['← →', '이전·다음 사진'], ['⌘Z', '방금 한 표시를 되돌려요'],
              ['D', '의심 컷 건너뛰기 켜고 끄기'], ['F', '얼굴 박스 켜고 끄기'],
              ['Z', '100% 확대 켜고 끄기'], ['?', '이 도움말 열고 닫기'], ['Esc', '훑기 마치기 (도움말이 열려 있으면 닫기)']];

  function seen() { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  function remember() { try { localStorage.setItem(KEY, '1'); } catch (e) { /* 저장 못 해도 계속 */ } }

  /* 단축키 표 */
  function overlay(el, onClose) {
    var back = el('div', 'lt-help-back'), box = el('div', 'lt-help');
    box.appendChild(el('h3', null, '단축키'));
    var list = el('div', 'lt-help-list');
    KEYS.forEach(function (k) { list.appendChild(el('kbd', null, k[0])); list.appendChild(el('span', null, k[1])); });
    box.appendChild(list);
    var close = el('button', null, '닫기 (? 또는 Esc)'); close.addEventListener('click', onClose);
    box.appendChild(close); back.appendChild(box);
    back.addEventListener('click', function (e) { if (e.target === back) onClose(); });
    return back;
  }

  /* 처음 한 번만: 핵심 세 키 */
  function tip(el, onClose) {
    var t = el('div', 'lt-tip');
    t.appendChild(el('span', null, 'S 셀렉 · M 보류 · X 버릴 컷 — 누르면 표시하고 다음 사진으로 가요. ? 를 누르면 모든 단축키를 볼 수 있어요.'));
    var ok = el('button', null, '알겠어요'); ok.addEventListener('click', function () { remember(); onClose(); });
    t.appendChild(ok);
    return t;
  }

  root.BcutReviewHelp = {overlay: overlay, tip: tip, seen: seen, remember: remember};
})(window);
