/* ============ 말로 찾기·도움말 (web/ask.js) ============
 *
 * 위쪽 검색창은 글자가 똑같아야 찾는다(timeline.js threadMatches). "한글 자동화
 * 얘기 어디 있었지?" 처럼 말로 치면 한 건도 안 나온다. 그럴 때 여기서 질문을 찾을
 * 말로 바꿔 주제를 고른다(smartSearch). "글자 크게 하려면?" 같은 사용법 질문은
 * 도움말 화면의 안내로 잇는다(matchGuides · ArchiveHelp).
 *
 * 처음엔 오른쪽 아래에 떠 있는 '물어보기' 대화창이었다(2026-10-30). 뜻을 헤아리지
 * 못하는데 대화 모양이라 '알아듣는다' 는 기대를 주고, 위쪽 검색창과 찾는 칸이 둘이
 * 되어 검색창과 도움말로 나눴다. 대화 모양은 claude -p 로 답을 붙일 때 다시 쓴다.
 *
 * AI 를 부르지 않는다. 이미 받아 둔 주제(ctx.data().THREADS)에서만 찾으므로 새로
 * 드러나는 자료가 없다 — 숨긴 주제·내려 달라고 한 글은 애초에 여기 오지 않는다.
 *
 * 위쪽은 순수 함수(검사는 tests/ask.test.js), 아래 ArchiveHelp 는 도움말 화면이다.
 * text.js 와 같은 방식으로 브라우저에서는 전역, node 에서는 require 로 쓴다.
 */
(function () {
  "use strict";

  /* ---------- 질문을 찾을 말로 바꾸기 ---------- */

  // 조사. 긴 것부터 떼야 '에서' 를 '서' 로 잘못 떼지 않는다.
  var JOSA = ["에서는", "으로는", "이라고", "에서", "으로", "까지", "부터", "한테", "에게",
              "처럼", "이랑", "하고", "보다", "라고", "이나", "은", "는", "이", "가", "을",
              "를", "에", "의", "도", "만", "로", "와", "과", "랑", "나", "님"];

  // 조사를 뗀 뒤 남은 동사 끝('비교한' → '비교', '내리고' → '내리'). 뗀 말은 원래 말의
  // 앞부분이라, 잘못 떼도 찾는 범위가 조금 넓어질 뿐 맞던 것을 놓치지는 않는다.
  var VERB_END = ["했는데", "하려면", "으려면", "였지", "였나", "였어", "이었", "려면",
                  "으면", "하게", "해서", "하고", "했다", "한", "고", "요"];

  // 질문에 흔히 붙지만 주제를 가리키지 않는 말. 보고서 본문에 흔해서 남겨 두면
  // 아무 주제나 걸린다.
  var STOP = ("어디 어디서 언제 누가 누구 뭐 뭐야 무엇 무슨 어떤 어떻게 왜 좀 그 저 이 " +
              "이거 그거 저거 그때 지난번 예전 전에 혹시 관련 얘기 이야기 대화 내용 글 " +
              "주제 정리 공유 방법 알려 알고 싶어 궁금 있는 있던 했던 나온 나왔던 올린 " +
              "올렸던 하는 우리 여기 거기 찾기 찾는 보기 보고 있다 없다 것 거 수 등 " +
              "다시 같은 관한 대한 대해 얼마 싶어요 하려 하기 하려면 내리고 되나 님").split(" ");

  // 끝이 이렇게 맺히면 묻는 말(동사)이다. 명사 끝('이미지'의 '지')은 건드리지 않게
  // 맺음 전체로만 본다.
  var ENDING = /(했던|했었지|했었|했지|했나|했어|하던|하나요|인가요|인가|인지|있었지|있었나|있었어|있나요|있어요|있나|있어|었지|았지|됐어|됐나|됐지|됐던|되었|던가|나요|까요|세요|해줘|알려줘|찾아줘|보여줘|줘요|줘)$/;

  function cutOne(w, list) {
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      if (w.length - s.length >= 2 && w.slice(-s.length) === s) return w.slice(0, -s.length);
    }
    return w;
  }

  // 복수 '들' 은 조사 앞에 붙는다('도구들이' → '도구들' → '도구'). 조사를 뗀 뒤 한 번 더.
  function stem(word) { return cutOne(cutOne(cutOne(word, JOSA), ["들"]), VERB_END); }

  /** 질문 → 찾을 말 목록. 겹치는 말은 한 번만. */
  function queryTerms(q) {
    var seen = {}, out = [];
    String(q || "").toLowerCase().split(/[^0-9a-z가-힣ㄱ-ㅎ+#.]+/).forEach(function (raw) {
      var w = raw.replace(/^[#.]+|[.]+$/g, "");
      if (!w || ENDING.test(w) || STOP.indexOf(w) !== -1) return;
      // '글을'·'님이' 처럼 두 글자짜리는 조사를 떼면 한 글자라 stem 이 손대지 않는다.
      // 뗀 것이 묻는 말이면 버린다.
      if (w.length === 2 && STOP.indexOf(w.charAt(0)) !== -1 && JOSA.indexOf(w.charAt(1)) !== -1) return;
      w = stem(w);
      if (w.length < 2 || STOP.indexOf(w) !== -1 || seen[w]) return;
      seen[w] = 1; out.push(w);
    });
    return out;
  }

  /**
   * 질문에 그대로 나온 태그. 이어진 말 1~3개를 붙여 본다('앱 제작' → '앱제작').
   * 질문 전체를 한 줄로 붙여 찾으면 말 경계를 넘어 엉뚱한 태그가 걸린다.
   * @param tags [{tag, count}] — tag_index.tags
   * @param fold 태그 표기 맞추기(text.js tagFold)
   */
  function tagHits(q, tags, fold) {
    var words = String(q || "").toLowerCase().split(/[^0-9a-z가-힣+#.]+/).filter(Boolean);
    var grams = {};
    for (var i = 0; i < words.length; i++) {
      for (var n = 1; n <= 3 && i + n <= words.length; n++) {
        var part = words.slice(i, i + n);
        grams[fold(part.join(" "))] = 1;
        part[part.length - 1] = stem(part[part.length - 1]);
        grams[fold(part.join(" "))] = 1;
      }
    }
    return (tags || []).filter(function (r) {
      var k = fold(r.tag); return k.length >= 2 && grams[k]; });
  }

  /** 질문에 나온 참여자 이름. 두 글자 미만은 우연히 겹치므로 보지 않는다. */
  function namesIn(q, names) {
    var text = String(q || "");
    return (names || []).filter(function (n) { return n && n.length >= 2 && text.indexOf(n) !== -1; });
  }

  /* ---------- 주제 찾기 ----------
   * 칸마다 무게가 다르다 — 제목에 있으면 거의 그 주제이고, 보고서 본문에 있으면
   * 스쳐 지나간 말일 수 있다. AI 보고서는 웹에서 찾아 붙인 말이 많아 더 낮게 둔다.
   * 제목·태그·요약에 맞은 말(strong)마다 STRONG 을 더 얹는다 — 말 하나가 제목에
   * 맞은 주제보다 말 둘이 요약에 맞은 주제가 묻는 것에 가깝다. 본문에서만 맞은
   * 주제(strong 0)는 화면이 따로 다룬다(실측: '내리고' 가 보고서 81개에 걸렸다). */
  var WEIGHT = { title: 6, tags: 4, summary: 3, report: 1, ai: 0.5 };
  var STRONG = 5;

  var hayCache = { list: null, map: null };
  function hayOf(threads) {
    if (hayCache.list === threads) return hayCache.map;
    var map = {};
    threads.forEach(function (t) {
      map[t.id] = {
        title: String(t.title || "").toLowerCase(),
        tags: (t.tags || []).concat(t.keywords || []).join(" ").toLowerCase(),
        summary: String(t.summary || "").toLowerCase(),
        report: String(t.report || "").toLowerCase(),
        ai: String(t.ai_report || "").toLowerCase(),
      };
    });
    hayCache = { list: threads, map: map };
    return map;
  }

  /**
   * @param threads 화면에 받아 둔 주제 전부
   * @param terms   queryTerms() 결과
   * @param people  namesIn() 결과 — 있으면 그 사람이 참여한 주제만
   * @returns [{thread, score, strong}] 맞은 것만, 가까운 순
   */
  function rankThreads(threads, terms, people) {
    threads = threads || [];
    people = people || [];
    var hay = hayOf(threads);
    var rows = [];
    threads.forEach(function (t) {
      if (people.length && !people.every(function (p) {
        return (t.participants || []).indexOf(p) !== -1; })) return;
      var h = hay[t.id], score = 0, strong = 0;
      terms.forEach(function (w) {
        var s = 0;
        if (h.title.indexOf(w) !== -1) s += WEIGHT.title;
        if (h.tags.indexOf(w) !== -1) s += WEIGHT.tags;
        if (h.summary.indexOf(w) !== -1) s += WEIGHT.summary;
        if (s > 0) { strong += 1; s += STRONG; }
        if (h.report.indexOf(w) !== -1) s += WEIGHT.report;
        if (h.ai.indexOf(w) !== -1) s += WEIGHT.ai;
        score += s;
      });
      // 사람만 물었으면('김OO 글') 말이 없어도 그 사람 주제를 최근 순으로 준다.
      if (!terms.length && people.length) { score = 1; strong = 1; }
      if (score > 0) rows.push({ thread: t, score: score, strong: strong });
    });
    rows.sort(function (a, b) {
      return b.score - a.score ||
        String(b.thread.start_date || "").localeCompare(String(a.thread.start_date || ""));
    });
    return rows;
  }

  /* ---------- 사용법 안내 ----------
   * 사이트에 실제로 있는 것만 적는다. 안내가 가리키는 화면이 이 사람에게 없으면
   * (로그인 안 한 사람의 '내 글 관리') 단추를 그리지 않는다 — 화면 쪽이 가린다. */
  function guides(pickMax) {
    return [
      { id: "search", q: "검색은 어떻게 해요?",
        keys: ["검색", "찾는 법", "찾으려면"],
        a: "위쪽 검색창에 낱말을 치면 그 글자가 들어간 주제가 나와요. 글자가 똑같은 주제가 없으면 말로 친 질문(\"한글 자동화 얘기 어디 있었지?\")에서 낱말을 골라 맞는 주제를 찾아 드려요. 사람 이름을 같이 쓰면 그 사람이 참여한 주제로 좁혀요." },
      { id: "ai", q: "AI에게 물어보려면?",
        keys: ["ai에게", "물어보", "챗봇", "질문하"],
        a: "검색창에 궁금한 것을 치면 결과 위에 'AI에게 물어보기' 단추가 나와요. 누르면 AI가 전체 기록에서 맞는 주제를 골라 읽고 자세히 답하고, 근거가 된 주제를 달아 줘요. 하루 20번까지 물을 수 있고, AI가 쓴 답이라 틀릴 수 있으니 근거 주제에서 확인해 주세요." },
      { id: "remove", q: "내 글을 내리고 싶어요",
        keys: ["삭제", "지우", "지워", "내리", "내려", "숨기", "숨겨", "내 글", "내글", "개인정보"],
        a: "'내 글 관리'에서 내 기록을 골라 내려 달라고 요청할 수 있어요. 요청한 기록은 다음 발행부터 빠지고, 되돌리려면 관리자에게 요청해야 해요.",
        view: "mine", go: "내 글 관리 열기" },
      { id: "name", q: "내 이름이 안 나오게 하려면?",
        keys: ["이름", "실명", "익명"],
        a: "'내 글 관리'에서 '관심 주제 화면에 내 이름 내지 않기'를 켜면 그 화면에 이름이 나오지 않아요.",
        view: "mine", go: "내 글 관리 열기" },
      { id: "photos", q: "사진은 어디서 봐요?",
        keys: ["사진", "이미지", "갤러리", "캡처"],
        a: "대화에 올라온 사진은 '갤러리'에 날짜와 사람별로 모여 있어요. 사진 아래 글씨를 누르면 그 사진이 나온 주제로 가요.",
        view: "gallery", go: "갤러리 열기" },
      { id: "files", q: "첨부파일은 어디 있어요?",
        keys: ["첨부", "파일", "다운", "내려받"],
        a: "'첨부파일'에 모여 있어요. 카톡이 파일을 14일만 보관해서, 그 전에 받아 두지 못한 파일은 이름만 남아 있어요.",
        view: "files", go: "첨부파일 열기" },
      { id: "font", q: "글자를 크게 하려면?",
        keys: ["글자", "글씨", "폰트", "크게", "작아"],
        a: "왼쪽 아래 '가' 단추를 누를 때마다 보통 → 크게 → 아주 크게로 바뀌어요. 휴대폰에서는 아래 '더보기' → '글자 크기'예요." },
      { id: "theme", q: "어두운 화면으로 보려면?",
        keys: ["다크", "어둡", "어두운", "밤 모드", "테마"],
        a: "왼쪽 아래 달 모양 단추로 바꿀 수 있어요. 휴대폰에서는 아래 '더보기' → '다크 모드'예요." },
      { id: "tags", q: "태그로 모아 보려면?",
        keys: ["태그", "해시", "겹쳐"],
        a: "'태그' 화면에서 태그를 최대 " + pickMax + "개까지 고르면 그 태그가 모두 붙은 주제만 남아요.",
        view: "tags", go: "태그 열기" },
      { id: "graph", q: "관계망은 뭐예요?",
        keys: ["관계망", "관계", "그래프", "네트워크"],
        a: "주제·도구·사람이 서로 어떻게 이어지는지 그린 그림이에요. 점을 누르면 이어진 것과 그 근거가 된 주제가 나와요.",
        view: "graph", go: "관계망 열기" },
      { id: "stats", q: "누가 가장 많이 이야기했어요?",
        keys: ["통계", "몇 명", "몇 개", "가장 많이", "제일 많이", "순위"],
        a: "'통계'에서 사람별·주제별 대화량과 시간대를 볼 수 있어요.",
        view: "stats", go: "통계 열기" },
      { id: "install", q: "휴대폰에 앱처럼 깔 수 있어요?",
        keys: ["설치", "앱으로", "홈 화면", "홈화면", "바로가기"],
        a: "휴대폰 브라우저 메뉴에서 '홈 화면에 추가'를 누르면 앱처럼 열 수 있어요." },
      { id: "share", q: "이 화면을 남에게 보여 주려면?",
        keys: ["링크", "주소", "공유하"],
        a: "보고 있는 화면이 주소에 그대로 남아요. 주소창의 주소를 건네면 같은 화면이 열려요(그분도 구성원이어야 해요)." },
    ];
  }

  /** 질문에 걸린 안내. 걸린 말이 많은 순. */
  function matchGuides(q, list) {
    var text = String(q || "").toLowerCase();
    var flat = text.replace(/\s+/g, "");
    return list.map(function (g) {
      // 띄어쓰기를 무시하는 것은 띄어 쓴 열쇠말('홈 화면')만이다. 다 무시하면
      // '한글 자동화' 가 '글자' 에 걸린다(실측).
      var hits = g.keys.filter(function (k) {
        if (text.indexOf(k) !== -1) return true;
        return k.indexOf(" ") !== -1 && flat.indexOf(k.replace(/\s+/g, "")) !== -1; }).length;
      return { guide: g, hits: hits };
    }).filter(function (r) { return r.hits > 0; })
      .sort(function (a, b) { return b.hits - a.hits; })
      .map(function (r) { return r.guide; });
  }

  // 사용법을 묻는 말투. 이때는 안내를 주제보다 먼저 보인다.
  var HOWTO = /(어떻게|방법|하려면|하나요|싶어|싶은|어디서|되나요|돼요|되요|할 수|있어요\?)/;
  function isHowTo(q) { return HOWTO.test(String(q || "")); }

  /**
   * 검색창에 친 말을 주제로. 글자 그대로 찾아서 없을 때 timeline.js 가 부른다.
   * 말이 여럿이면 가장 많이 맞은 주제들만 남긴다 — '한글 자동화' 에 '자동화' 만
   * 맞은 주제 79개를 늘어놓으면 찾은 게 아니다(실측). 제목·태그·요약에 하나도 안
   * 맞으면 본문에서만 스친 주제를 준다(weak).
   * @returns {threads, terms, people, partial, weak}
   */
  function smartSearch(threads, q, names) {
    var people = namesIn(q, names);
    // 이름은 사람 거르기로 쓰고 찾을 말에서는 뺀다('김OO이' 의 '김OO').
    var terms = queryTerms(q).filter(function (w) {
      return !people.some(function (p) { return w.indexOf(p.toLowerCase()) === 0; }); });
    var rows = (terms.length || people.length) ? rankThreads(threads, terms, people) : [];
    var best = rows.reduce(function (m, r) { return Math.max(m, r.strong); }, 0);
    var picked = best > 0
      ? rows.filter(function (r) { return r.strong === best; }) : rows;
    return { threads: picked.map(function (r) { return r.thread; }), terms: terms,
             people: people, partial: best > 0 && best < terms.length, weak: best === 0 };
  }

  var api = { queryTerms: queryTerms, namesIn: namesIn, tagHits: tagHits, rankThreads: rankThreads,
              smartSearch: smartSearch, guides: guides, matchGuides: matchGuides,
              isHowTo: isHowTo, stem: stem };

  /* ---------- 도움말 화면 ----------
   * 사용법 안내를 한 화면에 모았다. 묻는 사람만 볼 수 있는 대화창 안에 두면 있는
   * 줄 몰라 안 쓴다. 안내가 가리키는 화면이 이 사람에게 없으면(로그인 안 한 사람의
   * '내 글 관리') 단추를 그리지 않는다. 단추에 data-view 를 쓰지 않는 것은 app.js 가
   * 그것을 탭으로 알고 '그 화면이 있다' 고 판단하기 때문이다(applyHash). */
  function ArchiveHelp(ctx) {
    var esc = ctx.esc, el = ctx.el;

    function viewExists(v) {
      return !!document.querySelector('#tabs [data-view="' + v + '"], #mobileNav [data-view="' +
        v + '"], #mobileMore [data-view="' + v + '"]');
    }

    function renderHelp(focusId) {
      var list = guides(ctx.TAG_PICK_MAX);
      el.view.innerHTML = '<section class="help">' +
        '<p class="eyebrow">도움말</p><h1 class="help-title">이 아카이브를 쓰는 법</h1>' +
        '<p class="help-lead">궁금한 것은 위쪽 검색창에 말로 쳐도 돼요. ' +
        '"한글 자동화 얘기 어디 있었지?" 처럼 쓰면 맞는 주제를 찾아 드려요.</p>' +
        '<div class="help-list">' + list.map(function (g) {
          return '<article class="help-item" id="help-' + esc(g.id) + '" tabindex="-1">' +
            "<h2>" + esc(g.q) + "</h2><p>" + esc(g.a) + "</p>" +
            (g.view && viewExists(g.view)
              ? '<button class="btn ghost" type="button" data-help-go="' + esc(g.view) + '">' +
                esc(g.go) + " →</button>" : "") +
            "</article>";
        }).join("") + "</div></section>";
      Array.prototype.forEach.call(el.view.querySelectorAll("[data-help-go]"), function (b) {
        b.onclick = function () { ctx.setView(b.getAttribute("data-help-go")); };
      });
      var target = focusId && document.getElementById("help-" + focusId);
      if (target) {
        target.classList.add("on");
        target.scrollIntoView({ block: "center" });
        target.focus({ preventScroll: true });
      }
    }

    /** 검색창에 친 말에 맞는 안내 — 타임라인 위에 띄울 쪽지 HTML. 없으면 "". */
    function hintHtml(q) {
      var found = matchGuides(q, guides(ctx.TAG_PICK_MAX)).slice(0, 2);
      if (!found.length) return "";
      return '<div class="help-hint"><span>사용법을 찾으셨나요?</span>' +
        found.map(function (g) {
          return '<button class="help-hint__go" type="button" data-help-id="' + esc(g.id) +
            '">' + esc(g.q) + " →</button>";
        }).join("") + "</div>";
    }

    return { renderHelp: renderHelp, hintHtml: hintHtml };
  }

  /* ---------- AI 에게 묻기 (검색 결과 위 칸) ----------
   * 검색창에 친 질문을 이 PC 의 claude -p 가 발행본 주제를 읽고 답한다
   * (scripts/ask_worker.js). 웹은 asks/{내 이메일} 에 질문을 쓰고 그 문서를 듣는다.
   * 누르기 전에는 묻지 않는다 — 검색할 때마다 부르면 글자를 칠 때마다 요금제를 쓴다.
   *
   * 답은 AI 가 쓴 글이라 글자로 그린다(esc 뒤 머리말·굵게·목록만 — answerHtml). 근거는 PC 가 후보 안에서만 고른
   * 주제이고, 눌러서 직접 확인하게 한다. 로그인 세션이 없는 로컬 미리보기에는
   * 칸 자체가 없다. */
  /** AI 답 → HTML. 먼저 글자를 모두 esc 하고, 그 위에서 정해 둔 것만 살린다:
   *  혼자 선 '**머리말**' 줄은 문단 머리말, 문장 속 '**말**' 은 굵게, '- ' 줄은 목록,
   *  혼자 선 '![[msg-…]]'·'![[link:msg-…]]' 줄은 빈 자리(타임라인과 같은 md-anchor).
   *  빈 자리는 화면이 발행본에서 사진·첨부·링크를 찾아 채운다(timeline.js
   *  fillAnswerAnchors) — 링크 주소가 AI 글에서 오는 길은 없다.
   *  나머지 마크다운(#·표·링크)은 글자로 남는다 — 태그가 새로 생길 길은 이것뿐이다. */
  function answerHtml(text, esc) {
    function inline(s) {
      return esc(s).replace(/\*\*([^*\n]{1,80}?)\*\*/g, "<strong>$1</strong>").replace(/\*\*/g, "")
        .replace(/`([^`\n]{1,60})`/g, "<code>$1</code>");   // 명령어(`claude -p`)
    }
    var html = String(text || "").split(/\n\s*\n/).map(function (block) {
      var out = [], para = [], list = [];
      function flushPara() { if (para.length) out.push("<p>" + para.join("<br>") + "</p>"); para = []; }
      function flushList() { if (list.length) out.push("<ul>" + list.join("") + "</ul>"); list = []; }
      block.split("\n").forEach(function (raw) {
        var line = raw.trim().replace(/^#{1,4}\s+(.+)$/, "**$1**");   // 제목으로 써도 머리말로
        if (!line) return;
        var head = /^\*\*([^*\n]{1,40})\*\*$/.exec(line);
        var item = /^[-•]\s+(.+)$/.exec(line);
        var spot = /^!\[\[(link:)?([A-Za-z0-9_-]+)\]\]$/.exec(line);
        if (spot) {
          flushPara(); flushList();
          out.push(spot[1]
            ? '<div class="md-link-anchor" data-link-anchor="' + esc(spot[2]) + '"></div>'
            : '<div class="md-anchor" data-anchor="' + esc(spot[2]) + '"></div>');
        } else if (head) { flushPara(); flushList(); out.push('<p class="ai-answer__sub">' + esc(head[1]) + "</p>"); }
        else if (item) { flushPara(); list.push("<li>" + inline(item[1]) + "</li>"); }
        else { flushList(); para.push(inline(line)); }
      });
      flushPara(); flushList();
      return out.join("");
    }).join("");
    return wrapCheck(html);
  }

  /* '확인할 점' 문단은 사람들의 대화가 아니라 검증 주석과 맞춰 본 결과다. 본문과
   * 한 흐름으로 읽히면 누구의 말인지 흐려지므로, 타임라인의 AI 검증 칸(.tc-ai)과 같은
   * 빛깔의 상자로 떼어 놓는다. 그 머리말부터 다음 머리말(없으면 끝)까지가 상자다. */
  var CHECK_HEAD = '<p class="ai-answer__sub">확인할 점</p>';
  /** '2026-08-27' → '8/27'. 근거 단추 안에 들어가니 짧게. */
  function shortDate(d) {
    var m = /^\d{4}-(\d{2})-(\d{2})/.exec(String(d || ""));
    return m ? (+m[1]) + "/" + (+m[2]) : String(d || "");
  }
  function wrapCheck(html) {
    var k = html.indexOf(CHECK_HEAD);
    if (k === -1) return html;
    var rest = html.slice(k + CHECK_HEAD.length);
    var nx = rest.indexOf('<p class="ai-answer__sub">');
    return html.slice(0, k) +
      '<div class="ai-answer__check"><p class="ai-answer__check-head">' +
      '<span class="tc-ai-badge">🔎 확인할 점</span>' +
      '<span class="ai-answer__check-note">대화를 검증 주석과 맞춰 본 것</span></p>' +
      (nx === -1 ? rest : rest.slice(0, nx)) + "</div>" + (nx === -1 ? "" : rest.slice(nx));
  }
  api.answerHtml = answerHtml;

  var ASK_MAX = 200;           // firestore.rules askWrite 의 상한과 같다
  var STALE_MS = 12 * 60 * 1000;   // 하트비트(5분)를 두 번 놓치면 꺼진 것으로 본다
  var WAIT_HINT_MS = 45 * 1000;

  function ArchiveAnswer(ctx) {
    var esc = ctx.esc, state = ctx.state;
    var doc = null, unsub = null, pcAsleep = false, waitTimer = null;

    function reqs() { return state.session && state.session.requests; }
    function enabled() { var r = reqs(); return !!(r && r.ask && r.watchAsk); }

    function watch() {
      if (unsub || !enabled()) return;
      unsub = reqs().watchAsk(function (d) { doc = d; paint(); });
    }

    function askButton(label) {
      return '<button class="btn" type="button" data-ai-ask>' + esc(label) + "</button>";
    }

    function inner(q) {
      var mine = doc && doc.question === q;
      if (!mine) {
        if (q.length > ASK_MAX) {
          return '<p class="ai-answer__note">AI에게는 ' + ASK_MAX + "자 이내로 물을 수 있어요.</p>";
        }
        return '<div class="ai-answer__ask">' + askButton("🤖 AI에게 물어보기") +
          '<p class="ai-answer__note">AI가 전체 기록에서 맞는 주제를 골라 읽고 자세히 답해요. ' +
          "하루 20번까지 물을 수 있고, 답은 틀릴 수 있으니 근거 주제를 꼭 확인해 주세요.</p></div>";
      }
      var st = doc.state;
      if (st === "queued" || st === "running") {
        return '<p class="ai-answer__wait"><span class="ai-answer__dot" aria-hidden="true"></span>' +
          (st === "running" ? "기록을 읽고 답을 쓰는 중이에요… 보통 20~40초 걸려요."
                            : "질문을 보냈어요. 답을 쓸 PC가 받으면 시작해요…") + "</p>" +
          (st === "queued" && pcAsleep
            ? '<p class="ai-answer__note">답을 쓰는 PC가 지금 꺼져 있는 것 같아요. 켜지면 답하고, 30분이 지나면 취소돼요.</p>'
            : "");
      }
      if (st === "done") {
        var cites = doc.cites || [];
        // 검증 주석이 있는 근거에는 확인한 날을 단다 — 누르면 그 주석이 펼쳐진 채로 간다.
        var checkedOf = ctx.checkedOf || function () { return null; };
        var anyChecked = false;
        return '<p class="ai-answer__label">🤖 AI 답변</p>' +
          '<div class="ai-answer__body">' + answerHtml(doc.answer, esc) + "</div>" +
          (cites.length
            ? '<p class="ai-answer__label">근거 주제</p><div class="ai-answer__cites">' +
              cites.map(function (c) {
                var chk = checkedOf(c.id);
                if (chk) anyChecked = true;
                return '<button class="ai-answer__cite" type="button" data-ai-jump="' +
                  esc(c.id) + '"' + (chk ? ' data-ai-open="1"' : "") + ">" + esc(c.title) +
                  ' <span>' + esc(c.date || "") + "</span>" +
                  (chk ? '<em class="ai-answer__cite-check" title="' + esc(chk) +
                    ' 에 웹 출처를 열어 확인한 AI 검증 보고서가 있어요">🔎 ' +
                    esc(shortDate(chk)) + " 검증</em>" : "") +
                  "</button>"; }).join("") + "</div>" +
              (anyChecked ? '<p class="ai-answer__note">🔎 표시가 있는 주제는 누르면 AI 검증 보고서가 함께 펼쳐져요.</p>' : "")
            : "") +
          '<p class="ai-answer__note">AI가 기록을 읽고 쓴 답이에요. 틀릴 수 있으니 근거 주제에서 확인해 주세요.</p>';
      }
      // failed · limited · expired — PC 가 적어 준 문장을 그대로 보인다.
      return '<p class="ai-answer__note ai-answer__note--warn">' +
        esc(doc.message || "답을 받지 못했어요.") + "</p>" +
        (st === "limited" ? "" : askButton("다시 물어보기"));
    }

    function boxHtml(q) {
      q = String(q || "").trim();
      if (!enabled() || q.length < 2) return "";
      watch();
      return '<section class="ai-answer" id="aiAnswer" aria-live="polite" data-q="' +
        esc(q) + '">' + inner(q) + "</section>";
    }

    /** 문서가 바뀌면 칸 안만 다시 그린다 — 타임라인 전체를 다시 그리면 읽던 자리를 잃는다. */
    function paint() {
      var box = document.getElementById("aiAnswer");
      if (!box) return;
      box.innerHTML = inner(box.getAttribute("data-q"));
      bind();
    }

    function bind() {
      var box = document.getElementById("aiAnswer");
      if (!box) return;
      if (ctx.fillMedia) ctx.fillMedia(box);   // 답 속 사진·첨부·링크 자리를 채운다
      var b = box.querySelector("[data-ai-ask]");
      if (b) b.onclick = function () {
        var q = box.getAttribute("data-q");
        b.disabled = true;
        pcAsleep = false;
        // 화면은 바로 '보냈어요' 로 — 스냅샷이 오기 전에도 누른 것이 먹었는지 보이게.
        doc = { question: q, state: "queued" };
        paint();
        reqs().ask(q).catch(function (e) {
          doc = { question: q, state: "failed",
                  message: "질문을 보내지 못했어요: " + (e && e.message ? e.message : e) };
          paint();
        });
        clearTimeout(waitTimer);
        waitTimer = setTimeout(checkPc, WAIT_HINT_MS);
      };
      Array.prototype.forEach.call(box.querySelectorAll("[data-ai-jump]"), function (c) {
        c.onclick = function () {
          ctx.jumpToTimeline("t-" + c.getAttribute("data-ai-jump"),
                             { ai: c.hasAttribute("data-ai-open") });
        };
      });
    }

    /** 한참 지나도 PC 가 안 받으면 하트비트를 본다. 꺼져 있으면 그렇다고 말한다. */
    function checkPc() {
      if (!doc || doc.state !== "queued" || !reqs().askSeenAt) return;
      reqs().askSeenAt().then(function (seen) {
        var t = seen ? Date.parse(seen) : NaN;
        pcAsleep = !(t > Date.now() - STALE_MS);
        paint();
      }, function () { /* 못 읽으면 말하지 않는다 */ });
    }

    return { boxHtml: boxHtml, bind: bind };
  }

  api.ArchiveHelp = ArchiveHelp;
  api.ArchiveAnswer = ArchiveAnswer;
  if (typeof window !== "undefined") window.ArchiveAsk = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
