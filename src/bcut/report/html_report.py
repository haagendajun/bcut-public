"""HTML 리포트 (PRD FR-17, devplan T1.18).

분석 결과를 사진 썸네일, 등급, 사유, 점수와 함께 보여 주는 **파일 하나**를 만든다.
- 서버가 필요 없다. 브라우저에서 파일을 열면 필터·정렬·"살리기"가 동작한다.
- **외부 주소를 쓰지 않는다** (글꼴, 스크립트, 이미지 모두 파일 안에 있다). 제약 C1.
- 썸네일이 들어 있으므로 **이 컴퓨터 안에서만 쓰고 다른 사람에게 보내지 않는다.**
- 파일 이름은 화면에 글자로만 넣는다 (HTML로 해석하지 않는다).
- 사유(눈 감김, 노출)별로 필터할 수 있다. 한 사진에 두 사유가 함께 걸릴 수 있다.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from bcut.scan import PhotoResult
from bcut.score.exposure import ExposureThresholds
from bcut.score.eyes import EyesThresholds
from bcut.score.sharpness import SharpnessThresholds

DEFAULT_SCOPE = "눈 감김·노출·흔들림·초점 판정"  # 지금 판정하는 사유


def default_title(folder_name: str) -> str:
    """제목에는 행사 이름을 넣는다 (브라우저 탭에서 리포트를 구분할 수 있게)."""
    return f"{folder_name} · 1차 컷 리포트"


def _data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def build_payload(
    results: Sequence[PhotoResult],
    *,
    folder_name: str,
    generated_at: str,
    thresholds: EyesThresholds,
    exposure_thresholds: ExposureThresholds,
    sharpness_thresholds: SharpnessThresholds,
    thumbs_mode: str,
    title: str,
    scope: str,
) -> dict:
    return {
        "id": f"{folder_name}:{len(results)}",
        "title": title,
        "scope": scope,
        "folder": folder_name,
        "generatedAt": generated_at,
        "thumbsMode": thumbs_mode,
        "thresholds": {
            "candidate": thresholds.candidate_max,
            "review": thresholds.review_max,
            "minEyeWidthFrac": thresholds.min_eye_width_frac,
            "groupFaceRatio": thresholds.group_face_ratio,
            "exposureFaceHi": exposure_thresholds.face_hi_frac,
            "exposureGlobalHi": exposure_thresholds.global_hi_frac,
            "exposureDarkP99": exposure_thresholds.dark_p99,
            "sharpBest": sharpness_thresholds.best_blur_min,
            "sharpFace": sharpness_thresholds.face_blur_min,
            "sharpFacePx": sharpness_thresholds.min_face_px,
        },
        "photos": [
            {
                "f": r.file, "st": r.status,
                "es": r.eyes_status if r.eyes_status is not None else r.status,
                "sc": r.score, "nt": r.note,
                "xk": r.exposure_kind, "xp": r.exposure_p99, "xf": r.exposure_face_hi,
                "xg": r.exposure_global_hi, "xs": r.exposure_severity,
                "bk": r.sharpness_kind, "bb": r.sharpness_best, "bf": r.sharpness_face,
                "bs": r.sharpness_severity, "cf": r.confidence,
                "rs": list(r.reasons),
                "fc": r.face_count, "cc": r.faces_considered, "ew": r.eye_width_frac,
                "er": r.error, "th": _data_uri(r.thumbnail) if r.thumbnail else None,
            }
            for r in results
        ],
    }


def _json_for_script(payload: dict) -> str:
    """<script> 안에 안전하게 넣을 JSON. '<'를 이스케이프해 </script> 같은 문자열이 끼어들 수 없게 한다."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_html(
    results: Sequence[PhotoResult],
    *,
    folder_name: str,
    generated_at: str,
    thresholds: EyesThresholds | None = None,
    exposure_thresholds: ExposureThresholds | None = None,
    sharpness_thresholds: SharpnessThresholds | None = None,
    thumbs_mode: str = "all",
    title: str | None = None,
    scope: str = DEFAULT_SCOPE,
) -> str:
    title = title or default_title(folder_name)
    payload = build_payload(
        results, folder_name=folder_name, generated_at=generated_at,
        thresholds=thresholds or EyesThresholds(),
        exposure_thresholds=exposure_thresholds or ExposureThresholds(),
        sharpness_thresholds=sharpness_thresholds or SharpnessThresholds(),
        thumbs_mode=thumbs_mode, title=title, scope=scope,
    )
    safe_title = (title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return TEMPLATE.replace("__TITLE__", safe_title).replace("__DATA__", _json_for_script(payload))


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fafaf8;--surface:#fff;--text:#1f1f1e;--muted:#6b6a65;--border:rgba(0,0,0,.14);
--cand-bg:#fcebeb;--cand-fg:#791f1f;--rev-bg:#faeeda;--rev-fg:#633806;--ok-bg:#eaf3de;--ok-fg:#27500a;
--gray-bg:#f1efe8;--gray-fg:#444441;--accent:#185fa5;--warn-bg:#faeeda;--warn-fg:#633806}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a19;--surface:#262625;--text:#ecebe6;--muted:#a3a29b;
--border:rgba(255,255,255,.18);--cand-bg:#501313;--cand-fg:#f7c1c1;--rev-bg:#412402;--rev-fg:#fac775;
--ok-bg:#173404;--ok-fg:#c0dd97;--gray-bg:#2c2c2a;--gray-fg:#d3d1c7;--accent:#85b7eb;
--warn-bg:#412402;--warn-fg:#fac775}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;font-weight:500;margin:0 0 4px}
.meta{color:var(--muted);font-size:13px;margin:0 0 14px}
.banner{background:var(--warn-bg);color:var(--warn-fg);border-radius:8px;padding:10px 14px;font-size:13px;margin:0 0 16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:0 0 16px}
.card{background:var(--surface);border:.5px solid var(--border);border-radius:10px;padding:10px 14px}
.card .n{font-size:24px;font-weight:500;line-height:1.2}.card .l{font-size:12px;color:var(--muted)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.bar .sep{width:1px;height:22px;background:var(--border)}
.bar label{font-size:13px;color:var(--muted)}
button,select,input[type=range]{font:inherit;font-size:13px}
button,select{background:var(--surface);color:var(--text);border:.5px solid var(--border);border-radius:8px;padding:5px 11px;cursor:pointer}
button:hover,select:hover{border-color:var(--accent)}
button[aria-pressed=true]{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.count{font-size:13px;color:var(--muted);margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--w,170px),1fr));gap:10px}
.item{background:var(--surface);border:.5px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.item.saved{opacity:.45}
.item .img{aspect-ratio:3/2;background:var(--gray-bg);display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px;text-align:center;padding:6px}
.item img{width:100%;height:100%;object-fit:contain;display:block}
.item .body{padding:8px 10px;display:flex;flex-direction:column;gap:5px;font-size:12px}
.name{font-weight:500;word-break:break-all}
.row{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.badge{border-radius:6px;padding:1px 8px;font-size:12px}
.b-candidate{background:var(--cand-bg);color:var(--cand-fg)}
.b-review{background:var(--rev-bg);color:var(--rev-fg)}
.b-normal{background:var(--ok-bg);color:var(--ok-fg)}
.b-other{background:var(--gray-bg);color:var(--gray-fg)}
.muted{color:var(--muted)}
.item button{width:100%;padding:4px}
.empty{padding:40px 0;text-align:center;color:var(--muted)}
.note{font-size:12px;color:var(--muted);margin-top:18px}
</style>
</head>
<body>
<div class="wrap">
<h1 id="title"></h1>
<p class="meta" id="meta"></p>
<div class="banner">이 파일에는 사진 썸네일이 들어 있어요. <b>이 컴퓨터에서만 보고, 다른 사람에게 보내지 마세요.</b> 도구는 사진을 삭제하지 않고, 이 화면의 &ldquo;살리기&rdquo;도 파일에는 아무것도 쓰지 않아요(브라우저에만 기억해요).</div>
<div class="cards" id="cards"></div>
<div class="bar" id="tiers" role="group" aria-label="등급 필터"></div>
<div class="bar" id="reasons" role="group" aria-label="판정 종류 필터"></div>
<div class="bar" id="notes" role="group" aria-label="세부 사유 필터"></div>
<div class="bar">
<label for="sort">정렬</label>
<select id="sort">
<option value="score">가장 감긴 순 (눈 점수 낮은 순)</option>
<option value="conf">확신도 높은 순</option>
<option value="exposure">노출 이상이 심한 순</option>
<option value="sharp">흐림이 심한 순</option>
<option value="name">파일 이름순</option>
<option value="faces">얼굴 많은 순</option>
</select>
<label for="size">썸네일 크기</label>
<input type="range" id="size" min="110" max="320" step="10" value="170">
<span class="sep"></span>
<button id="dl-saved">살린 컷 이름 저장</button>
<button id="dl-visible">보이는 컷 이름 저장</button>
<button id="clear-saved">살림 모두 지우기</button>
</div>
<p class="count" id="count"></p>
<div class="grid" id="grid"></div>
<p class="note" id="foot"></p>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('data').textContent);
var P=D.photos;
var STATUS={candidate:'B컷 후보',review:'사람이 확인',normal:'정상',no_face:'얼굴 없음',unscorable:'판정 불가'};
var NOTE={small_eye:'눈이 좁음',group:'단체 사진',read_error:'읽기 실패'};
var REASON={eyes_closed:'눈 감김',exposure:'노출',blur:'흔들림',out_of_focus:'초점 실패'};
var XKIND={over_face:'얼굴이 하얗게 날아감',over_global:'사진이 하얗게 날아감',under:'너무 어두움'};
var TIERS=[['flagged','후보+확인'],['candidate','B컷 후보'],['review','사람이 확인'],['normal','정상'],['other','얼굴 없음·판정 불가'],['all','전체']];
var st={tier:'flagged',reason:null,note:null,sort:'score'};
var KEY='bcut-saved:'+D.id;
var saved={};
try{var raw=localStorage.getItem(KEY);if(raw){JSON.parse(raw).forEach(function(f){saved[f]=true;});}}catch(e){}
function persist(){try{localStorage.setItem(KEY,JSON.stringify(Object.keys(saved)));}catch(e){}}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function inTier(p,t){
 if(t==='all')return true;
 if(t==='flagged')return p.st==='candidate'||p.st==='review';
 if(t==='other')return p.st==='no_face'||p.st==='unscorable';
 return p.st===t;
}
function count(t){var n=0;P.forEach(function(p){if(inTier(p,t))n++;});return n;}
function countReason(r){var n=0;P.forEach(function(p){if(p.rs.indexOf(r)>=0)n++;});return n;}
function badgeClass(s){return s==='candidate'?'b-candidate':s==='review'?'b-review':s==='normal'?'b-normal':'b-other';}
function visible(){
 var list=P.filter(function(p){
  return inTier(p,st.tier)&&(!st.reason||p.rs.indexOf(st.reason)>=0)&&(!st.note||p.nt===st.note);});
 if(st.sort==='name')list.sort(function(a,b){return a.f<b.f?-1:a.f>b.f?1:0;});
 else if(st.sort==='faces')list.sort(function(a,b){return b.fc-a.fc||(a.f<b.f?-1:1);});
 else if(st.sort==='conf')list.sort(function(a,b){
  var x=a.cf===null?-1:a.cf,y=b.cf===null?-1:b.cf;return y-x||(a.f<b.f?-1:1);});
 else if(st.sort==='sharp')list.sort(function(a,b){
  var x=a.bs===null?-1:a.bs,y=b.bs===null?-1:b.bs;return y-x||(a.f<b.f?-1:1);});
 else if(st.sort==='exposure')list.sort(function(a,b){
  var x=a.xs===null?-1:a.xs,y=b.xs===null?-1:b.xs;return y-x||(a.f<b.f?-1:1);});
 else list.sort(function(a,b){
  var x=a.sc===null?9:a.sc,y=b.sc===null?9:b.sc;return x-y||(a.f<b.f?-1:1);});
 return list;
}
function download(name,lines){
 var blob=new Blob([lines.join('\\n')+'\\n'],{type:'text/plain;charset=utf-8'});
 var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;
 document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);
}
function renderStatic(){
 document.getElementById('title').textContent=D.title;
 var th=D.thresholds;
 document.getElementById('meta').textContent=D.scope+' · 사진 '+P.length+'장 · 만든 시각 '+D.generatedAt+
  ' · 눈 기준: 후보 점수 \\u2264 '+th.candidate+', 확인 \\u2264 '+th.review+', 눈 폭 비율 < '+th.minEyeWidthFrac+
  ' · 노출 기준: 얼굴 날아감 \\u2265 '+Math.round(th.exposureFaceHi*100)+'%(얼굴 없으면 전체 \\u2265 '+Math.round(th.exposureGlobalHi*100)+'%), 상위 1% 밝기 \\u2264 '+th.exposureDarkP99+
  ' · 흐림 기준: 가장 선명한 곳 \\u2265 '+th.sharpBest+', 얼굴(폭 '+th.sharpFacePx+'px 이상) \\u2265 '+th.sharpFace+
  ' · 썸네일 '+(D.thumbsMode==='all'?'전체':'후보·확인·판정 불가만');
 var cards=document.getElementById('cards');
 [['t','candidate','B컷 후보'],['t','review','사람이 확인'],['t','normal','정상'],['t','other','얼굴 없음·판정 불가'],
  ['r','eyes_closed','눈 감김으로 올라온 컷'],['r','exposure','노출로 올라온 컷'],
  ['r','blur','흔들림으로 올라온 컷'],['r','out_of_focus','초점 실패로 올라온 컷']].forEach(function(c){
  var n=c[0]==='t'?count(c[1]):countReason(c[1]);
  var d=el('div','card');d.appendChild(el('div','n',String(n)));d.appendChild(el('div','l',c[2]));cards.appendChild(d);});
 var tiers=document.getElementById('tiers');
 TIERS.forEach(function(t){var b=el('button',null,t[1]+' '+count(t[0]));b.dataset.tier=t[0];
  b.addEventListener('click',function(){st.tier=t[0];render();});tiers.appendChild(b);});
 var reasons=document.getElementById('reasons');
 reasons.appendChild(el('label',null,'판정 종류'));
 Object.keys(REASON).forEach(function(k){
  var b=el('button',null,REASON[k]+' '+countReason(k));b.dataset.reason=k;
  b.addEventListener('click',function(){st.reason=(st.reason===k)?null:k;render();});reasons.appendChild(b);});
 var notes=document.getElementById('notes');
 notes.appendChild(el('label',null,'세부 사유'));
 Object.keys(NOTE).forEach(function(k){
  var n=P.filter(function(p){return p.nt===k;}).length;if(!n)return;
  var b=el('button',null,NOTE[k]+' '+n);b.dataset.note=k;
  b.addEventListener('click',function(){st.note=(st.note===k)?null:k;render();});notes.appendChild(b);});
 if(!notes.querySelector('button'))notes.style.display='none';
 document.getElementById('sort').addEventListener('change',function(e){st.sort=e.target.value;render();});
 document.getElementById('size').addEventListener('input',function(e){
  document.getElementById('grid').style.setProperty('--w',e.target.value+'px');});
 document.getElementById('dl-saved').addEventListener('click',function(){
  download('bcut-saved.txt',Object.keys(saved).sort());});
 document.getElementById('dl-visible').addEventListener('click',function(){
  download('bcut-visible.txt',visible().map(function(p){return p.f;}));});
 document.getElementById('clear-saved').addEventListener('click',function(){saved={};persist();render();});
 document.getElementById('foot').textContent='\"정상\"은 눈 감김, 노출, 흔들림·초점에 이상이 없다는 뜻이고, A컷이라는 뜻은 아니에요. 좋은 컷을 고르는 일은 사람이 해요. 눈 점수는 두 눈 중 덜 감긴 쪽 눈의 열림 비율이에요(낮을수록 감김). 노출은 얼굴이 하얗게 날아가거나 사진 전체가 너무 어두운 명백한 경우만 \"사람이 확인\"으로 보내요(가벼운 노출 어긋남은 잡지 않아요). 흔들림·초점 실패도 사진 어디에도 선명한 곳이 없거나 얼굴이 분명히 흐린 경우만 \"사람이 확인\"으로 보내고, 얼굴이 작은 컷(폭 '+th.sharpFacePx+'px 미만)은 얼굴 흐림을 판정하지 않아요. 썸네일의 상자는 눈 감김 판정에 쓴 얼굴이에요(굵은 상자가 등급을 정한 얼굴).';
}
function render(){
 document.querySelectorAll('#tiers button').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.tier===st.tier));});
 document.querySelectorAll('#reasons button').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.reason===st.reason));});
 document.querySelectorAll('#notes button').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.note===st.note));});
 var list=visible();var grid=document.getElementById('grid');grid.textContent='';
 document.getElementById('count').textContent='보이는 컷 '+list.length+'장 / 전체 '+P.length+'장 · 내가 살린 컷 '+Object.keys(saved).length+'장';
 if(!list.length){grid.appendChild(el('div','empty','이 조건에 맞는 컷이 없어요.'));return;}
 list.forEach(function(p){
  var it=el('div','item'+(saved[p.f]?' saved':''));
  var im=el('div','img');
  if(p.th){var img=document.createElement('img');img.loading='lazy';img.decoding='async';img.alt=p.f;img.src=p.th;im.appendChild(img);}
  else im.textContent=p.st==='normal'?'정상 (썸네일 없음)':'썸네일 없음';
  it.appendChild(im);
  var body=el('div','body');body.appendChild(el('div','name',p.f));
  var r1=el('div','row');r1.appendChild(el('span','badge '+badgeClass(p.st),STATUS[p.st]||p.st));
  if(p.rs.indexOf('eyes_closed')>=0)r1.appendChild(el('span','badge '+badgeClass(p.es),'눈 감김'));
  if(p.xk)r1.appendChild(el('span','badge b-review','노출: '+(XKIND[p.xk]||p.xk)));
  if(p.bk)r1.appendChild(el('span','badge b-review',REASON[p.bk]||p.bk));
  if(p.nt)r1.appendChild(el('span','badge b-other',NOTE[p.nt]||p.nt));
  body.appendChild(r1);
  var r2=el('div','row muted');
  r2.textContent=(p.sc===null?'눈 점수 없음':'눈 점수 '+p.sc.toFixed(3))+' · 얼굴 '+p.fc+(p.cc>1?' (판정 '+p.cc+')':'')+(p.cf===null||p.cf===undefined?'':' · 확신도 '+p.cf.toFixed(2));
  body.appendChild(r2);
  if(p.xk){
   var r3=el('div','row muted');
   var line='상위 1% 밝기 '+Math.round(p.xp);
   if(p.xk==='over_face'&&p.xf!==null)line+=' · 얼굴 날아감 '+Math.round(p.xf*100)+'%';
   else if(p.xk==='over_global')line+=' · 사진 날아감 '+Math.round(p.xg*100)+'%';
   r3.textContent=line;
   body.appendChild(r3);
  }
  if(p.bk){
   var r4=el('div','row muted');
   r4.textContent=(p.bk==='blur'?'가장 선명한 곳도 흐림 ':'얼굴 흐림 ')+(p.bk==='blur'?p.bb:p.bf).toFixed(2)+' (클수록 흐림)';
   body.appendChild(r4);
  }
  if(p.er){body.appendChild(el('div','muted','오류: '+p.er));}
  var b=el('button',null,saved[p.f]?'살림 취소':'살리기');
  b.addEventListener('click',function(){if(saved[p.f])delete saved[p.f];else saved[p.f]=true;persist();render();});
  body.appendChild(b);it.appendChild(body);grid.appendChild(it);
 });
}
renderStatic();render();
})();
</script>
</body>
</html>
"""
