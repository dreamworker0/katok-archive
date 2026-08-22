/**
 * web/text.js — 글자·마크다운 다루기.
 *
 * 이 함수들은 app.js 3,389줄 안에 있는 동안 **동작 검사가 하나도 없었다.** 닫힌
 * IIFE 라 node 에서 부를 방법이 없었고, 그래서 `tests/test_ui_contract.py` 가
 * 파이썬에서 app.js 의 소스 글자를 정규식으로 훑는 방식을 썼다. 그것은 "이 패턴이
 * 파일에 있다"를 확인할 뿐, `renderMarkdown` 이 표를 제대로 그리는지 `esc` 가
 * 따옴표를 막는지는 보지 않는다.
 *
 * 그리고 여기 모인 것이 마침 가장 위험한 축이다 — 보고서 본문을 HTML 로 바꾸는 길
 * 전체가 이 안에 있다. 발행하는 것이 요약과 결과물뿐인 아카이브에서 보고서는 유일한
 * 기록이고, 그것을 그리는 코드가 검사 밖에 있었다.
 */
const test = require("node:test");
const assert = require("node:assert");
const T = require("../web/text.js");

/* ─────────────────────────── 빠져나가지 못하게 ─────────────────────────── */

test("esc: 태그와 따옴표를 모두 막는다", () => {
  assert.equal(T.esc("<script>"), "&lt;script&gt;");
  // 따옴표를 빼먹으면 속성 안에 넣을 때 빠져나간다 — 이 파일은 href 를 그렇게 만든다.
  assert.equal(T.esc('a"b'), "a&quot;b");
  assert.equal(T.esc("a&b"), "a&amp;b");
  // & 를 먼저 바꿔야 한다. 나중에 바꾸면 &lt; 가 &amp;lt; 로 두 번 바뀐다.
  assert.equal(T.esc("<&>"), "&lt;&amp;&gt;");
});

test("esc: null·undefined·숫자도 문자열로 받는다", () => {
  assert.equal(T.esc(null), "");
  assert.equal(T.esc(undefined), "");
  assert.equal(T.esc(0), "0");
});

test("mdInline: javascript: 링크는 링크가 되지 않는다", () => {
  const out = T.mdInline("[누르세요](javascript:alert(1))");
  assert.ok(!out.includes("<a "), out);
  assert.ok(out.includes("javascript"), "글자로는 남아야 한다");
});

test("mdInline: http/https 만 링크가 된다", () => {
  assert.ok(T.mdInline("[x](https://a.com)").includes('href="https://a.com"'));
  assert.ok(T.mdInline("[x](http://a.com)").includes('href="http://a.com"'));
  assert.ok(!T.mdInline("[x](ftp://a.com)").includes("<a "));
  assert.ok(!T.mdInline("[x](/local/path)").includes("<a "));
});

test("mdInline: 링크는 새 창으로, 참조는 끊고 연다", () => {
  const out = T.mdInline("[x](https://a.com)");
  assert.ok(out.includes('target="_blank"'));
  assert.ok(out.includes('rel="noopener noreferrer"'));
});

test("mdInline: 본문에 적힌 태그는 escape 된 뒤에 서식이 붙는다", () => {
  const out = T.mdInline("**<b>굵게</b>**");
  assert.ok(out.includes("<strong>&lt;b&gt;굵게&lt;/b&gt;</strong>"), out);
});

test("linkify: http(s) 만 잡는다", () => {
  assert.ok(T.linkify("보세요 https://a.com/x 여기").includes('<a href="https://a.com/x"'));
  assert.equal(T.linkify("javascript:alert(1)"), "javascript:alert(1)");
});

/* ─────────────────────────── 서식 ─────────────────────────── */

test("mdInline: 코드·굵게·형광", () => {
  assert.equal(T.mdInline("`x`"), "<code>x</code>");
  assert.equal(T.mdInline("**x**"), "<strong>x</strong>");
  assert.ok(T.mdInline("==x==").includes('<mark class="key">x</mark>'));
});

test("renderMarkdown: 빈 줄로 문단이 갈린다", () => {
  const out = T.renderMarkdown("첫 문단.\n이어지는 줄.\n\n둘째 문단.");
  assert.equal((out.match(/<p>/g) || []).length, 2);
  assert.ok(out.includes("<p>첫 문단. 이어지는 줄.</p>"), out);
});

test("renderMarkdown: 제목 단계를 두 칸 낮춘다", () => {
  // 보고서는 카드 안에 들어간다. `#` 를 그대로 h1 로 내면 화면의 제목 구조를
  // 뒤엎어, 낭독기가 본문 소제목을 페이지 제목으로 읽는다. 그래서 두 칸 낮춘다.
  assert.ok(T.renderMarkdown("# 하나").includes("<h3>하나</h3>"));
  assert.ok(T.renderMarkdown("## 둘").includes("<h4>둘</h4>"));
  assert.ok(T.renderMarkdown("### 셋").includes("<h5>셋</h5>"));
  // h6 을 넘지 않는다 — 넘으면 <h7> 이라는 없는 태그가 나온다.
  assert.ok(T.renderMarkdown("###### 여섯").includes("<h6>여섯</h6>"));
  assert.ok(!T.renderMarkdown("###### 여섯").includes("<h7"));
});

test("renderMarkdown: 표는 가로 스크롤 상자에 담긴다", () => {
  const out = T.renderMarkdown("| 가 | 나 |\n|---|---|\n| 1 | 2 |");
  assert.ok(out.includes('<div class="md-table">'), "표가 상자 없이 나오면 좁은 화면에서 몸통이 밀린다");
  assert.ok(out.includes("<th>가</th>"));
  assert.ok(out.includes("<td>2</td>"));
});

test("renderMarkdown: 목록은 글머리와 번호를 가른다", () => {
  assert.ok(T.renderMarkdown("- 가\n- 나").includes("<ul><li>가</li><li>나</li></ul>"));
  assert.ok(T.renderMarkdown("1. 가\n2. 나").includes("<ol>"));
});

test("renderMarkdown: 인용과 구분선", () => {
  assert.ok(T.renderMarkdown("> 한 말").includes("<blockquote>한 말</blockquote>"));
  assert.ok(T.renderMarkdown("---").includes("<hr />"));
});

test("renderMarkdown: CRLF 로 와도 같게 그린다", () => {
  // 보고서 md 폴더는 CRLF 다.
  assert.equal(T.renderMarkdown("가\r\n\r\n나"), T.renderMarkdown("가\n\n나"));
});

test("renderMarkdown: 빈 입력·null 에도 터지지 않는다", () => {
  assert.equal(T.renderMarkdown(""), "");
  assert.equal(T.renderMarkdown(null), "");
});

/* ────────────────── 사진·링크 자리표 (보고서의 핵심 장치) ────────────────── */

test("renderMarkdown: 사진 자리표는 앵커로 바뀐다", () => {
  // 본문 그 대목 뒤에 자리표를 남기면 화면이 media 발행본에서 같은 id 를 찾아 끼운다.
  // 사람이 두 군데를 맞춰 적는 것이 아니라 자리만 가리키므로 어긋날 여지가 없다.
  const out = T.renderMarkdown("앞 문장.\n\n![[msg-000123]]\n\n뒤 문장.");
  assert.ok(out.includes('data-anchor="msg-000123"'), out);
});

test("renderMarkdown: 링크 자리표도 앵커로 바뀐다", () => {
  const out = T.renderMarkdown("![[link:abc_123]]");
  assert.ok(out.includes('data-link-anchor="abc_123"'), out);
});

test("renderMarkdown: 자리표는 한 줄을 통째로 차지할 때만 앵커다", () => {
  // 문장 속에 우연히 같은 꼴이 들어오면 그건 글자다.
  const out = T.renderMarkdown("이런 표기 ![[msg-1]] 를 글 안에 적으면");
  assert.ok(!out.includes("data-anchor="), out);
});

test("renderMarkdown: 자리표의 id 는 안전한 글자만 받는다", () => {
  const out = T.renderMarkdown('![[a"><script>]]');
  assert.ok(!out.includes("<script>"), out);
  assert.ok(!out.includes("data-anchor="), "이상한 id 는 앵커로 만들지 않는다");
});

/* ─────────────────────────── 태그 맞추기 ─────────────────────────── */

test("tagFold: 표기가 달라도 같은 곳에 닿는다", () => {
  // 발행 때 'Claude Code' 를 '클로드 코드' 로 합쳐 놓았으니, 사람이 쓴 원래 표기를
  // 눌렀을 때도 같은 키가 나와야 태그가 열린다. 어긋나면 글자 검색으로 떨어진다.
  assert.equal(T.tagFold("Claude Code"), T.tagFold("클로드 코드"));
  assert.equal(T.tagFold("Gemini"), "제미나이");
  assert.equal(T.tagFold("gemini"), "제미나이");
});

test("tagFold: 띄어쓰기·하이픈·밑줄·점을 똑같이 본다", () => {
  const want = T.tagFold("차량 운행일지");
  for (const s of ["차량운행일지", "차량-운행일지", "차량_운행일지", "차량.운행일지",
                   "  차량   운행일지  "]) {
    assert.equal(T.tagFold(s), want, s);
  }
});

test("tagFold: 조각마다 따로 음역한다", () => {
  assert.equal(T.tagFold("Claude-Code"), "클로드코드");
  assert.equal(T.tagFold("github python"), "깃허브파이썬");
});

test("tagFold: 대응이 없는 말은 소문자로 둔다", () => {
  assert.equal(T.tagFold("Kubernetes"), "kubernetes");
});

test("tagFold: 빈 값에도 터지지 않는다", () => {
  assert.equal(T.tagFold(""), "");
  assert.equal(T.tagFold(null), "");
});

/* ─────────────────────────── 링크 갈라내기 ─────────────────────────── */

test("hostOf: 호스트만 꺼내고 www 는 떼어낸다", () => {
  assert.equal(T.hostOf("https://www.example.com/a/b?c=1"), "example.com");
  assert.equal(T.hostOf("http://sub.example.co.kr/"), "sub.example.co.kr");
});

test("hostOf: 주소가 아니면 빈 값", () => {
  assert.equal(T.hostOf("그냥 글"), "");
  assert.equal(T.hostOf(""), "");
});

test("linkifyHosts: 이미 <a> 나 <code> 안에 있는 글자는 건드리지 않는다", () => {
  // 태그 경계를 세어 판단하므로 링크 안의 링크나 코드 속 주소가 깨지지 않는다.
  const map = [{ host: "example.com", url: "https://example.com" }];
  const inside = '<a href="https://example.com">example.com</a>';
  assert.equal(T.linkifyHosts(inside, map), inside);
  const code = "<code>example.com</code>";
  assert.equal(T.linkifyHosts(code, map), code);
});

test("linkifyHosts: 맨 글자는 링크로 만든다", () => {
  const map = [{ host: "example.com", url: "https://example.com" }];
  const out = T.linkifyHosts("<p>example.com 을 공개했다</p>", map);
  assert.ok(out.includes("<a "), out);
  assert.ok(out.includes("https://example.com"), out);
});

test("linkifyHosts: 대응이 없으면 원문 그대로", () => {
  assert.equal(T.linkifyHosts("<p>x</p>", []), "<p>x</p>");
  assert.equal(T.linkifyHosts("<p>x</p>", null), "<p>x</p>");
});

/* ─────────────────────────── 사람이 읽는 값 ─────────────────────────── */

test("fmtSize: 단위를 넘길 때 자리를 바꾼다", () => {
  assert.equal(T.fmtSize(512), "1 KB");          // 0 KB 라고 적지 않는다
  assert.equal(T.fmtSize(1024 * 300), "300 KB");
  assert.equal(T.fmtSize(1024 * 1024 * 2.5), "2.5 MB");
});

test("initial: 괄호 안 소속은 떼고 첫 글자만", () => {
  assert.equal(T.initial("홍길동 (어딘가복지관)"), "홍");
  assert.equal(T.initial(""), "?");
  assert.equal(T.initial(null), "?");
});

test("hashHue: 같은 이름은 늘 같은 색, 값은 0~359", () => {
  assert.equal(T.hashHue("홍길동"), T.hashHue("홍길동"));
  for (const n of ["가", "홍길동", "", "aaaaaaaaaaaaaaaaaaaa"]) {
    const h = T.hashHue(n);
    assert.ok(h >= 0 && h < 360, `${n} → ${h}`);
  }
});

test("agoText: 지난 시간을 사람 말로", () => {
  const ago = (ms) => T.agoText(new Date(Date.now() - ms).toISOString());
  assert.equal(ago(5 * 1000), "방금");
  assert.equal(ago(5 * 60 * 1000), "5분 전");
  assert.equal(ago(3 * 3600 * 1000), "3시간 전");
  assert.equal(ago(2 * 86400 * 1000), "2일 전");
});

test("msAgo·agoText: 읽을 수 없는 값은 조용히 넘어간다", () => {
  // 화면에 "NaN분 전" 이 뜨는 것보다 아무 말도 안 하는 편이 낫다.
  assert.equal(T.msAgo(null), null);
  assert.equal(T.msAgo("어제쯤"), null);
  assert.equal(T.agoText(null), "");
  assert.equal(T.agoText("어제쯤"), "");
});

/* ─────────────────────── app.js 와 어긋나지 않게 ─────────────────────── */

test("내보내는 이름이 app.js 가 묶는 이름과 같다", () => {
  // app.js 는 `var esc = T.esc;` 처럼 이름을 다시 묶는다. 여기서 이름을 빼거나
  // 바꾸면 그 줄이 undefined 를 묶고, 화면은 첫 렌더에서 조용히 멈춘다.
  const fs = require("fs");
  const path = require("path");
  const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
  const bound = [...app.matchAll(/^\s+var (\w+) = T\.(\w+);$/gm)];
  assert.ok(bound.length > 10, `app.js 가 묶는 이름이 ${bound.length}개뿐이다`);
  for (const [, name, prop] of bound) {
    assert.equal(name, prop, "이름과 속성이 다르면 읽는 사람이 헷갈린다");
    assert.equal(typeof T[name], "function", `text.js 가 ${name} 을 안 내보낸다`);
  }
});
