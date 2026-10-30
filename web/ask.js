/* ============ 물어보기 — 떠 있는 질문 단추 (web/ask.js) ============
 *
 * 오른쪽 아래 단추를 누르면 대화창 모양의 칸이 열린다. "한글 자동화 얘기 어디
 * 있었지?" 처럼 말로 물으면 주제 카드를 찾아 보여 주고, "내 글 내리려면?" 같은
 * 사용법 질문에는 정해 둔 안내를 보여 준다.
 *
 * AI 를 부르지 않는다(1단계). 이미 화면에 받아 둔 주제(ctx.data().THREADS)에서만
 * 찾으므로 새로 드러나는 자료가 없다 — 숨긴 주제·내려 달라고 한 글은 애초에 여기
 * 오지 않는다. 나중에 claude -p 로 답을 붙이면 이 칸이 그 앞단이 되고, 여기서 찾은
 * 주제가 그 답의 근거 후보가 된다.
 *
 * 위쪽 절반은 순수 함수(검사는 tests/ask.test.js), 아래 ArchiveAsk 는 화면이다.
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
  var ENDING = /(했던|했었지|했었|했지|했나|했어|하던|하나요|인가요|인가|인지|있었지|있었나|있었어|있나요|있어요|있나|있어|었지|았지|던가|나요|까요|세요|해줘|알려줘|찾아줘|보여줘|줘요|줘)$/;

  function cutOne(w, list) {
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      if (w.length - s.length >= 2 && w.slice(-s.length) === s) return w.slice(0, -s.length);
    }
    return w;
  }

  function stem(word) { return cutOne(cutOne(word, JOSA), VERB_END); }

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

  var api = { queryTerms: queryTerms, namesIn: namesIn, tagHits: tagHits, rankThreads: rankThreads,
              guides: guides, matchGuides: matchGuides, isHowTo: isHowTo, stem: stem };

  /* ---------- 화면 ---------- */

  var SHOW = 5;   // 한 번에 보여 줄 주제 수. 더 있으면 '모두 보기' 로 타임라인에 넘긴다.

  function ArchiveAsk(ctx) {
    var esc = ctx.esc, el = ctx.el;
    var ui = {}, mounted = false;

    function viewExists(v) {
      // 패널 안 단추는 data-view 를 쓰지 않는다 — app.js 가 그것을 탭으로 알고
      // 활성 표시를 붙이고, 없는 화면이 있는 것처럼 보이게 된다.
      return !!document.querySelector('#tabs [data-view="' + v + '"], #mobileNav [data-view="' + v + '"], #mobileMore [data-view="' + v + '"]');
    }

    function setOpen(open) {
      ui.panel.hidden = !open;
      ui.fab.hidden = open;
      ui.fab.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        if (!ui.log.childNodes.length) greet();
        ui.input.focus();
      } else {
        ui.fab.focus();
      }
    }

    function push(kind, html) {
      var div = document.createElement("div");
      div.className = "ask-msg ask-msg--" + kind;
      div.innerHTML = html;
      ui.log.appendChild(div);
      ui.log.scrollTop = ui.log.scrollHeight;
      return div;
    }

    function chip(text) {
      return '<button class="ask-chip" type="button" data-ask-q="' + esc(text) + '">' +
        esc(text) + "</button>";
    }

    function greet() {
      var d = ctx.data();
      var tags = ((d.TAGIDX && d.TAGIDX.tags) || []).slice(0, 2).map(function (r) {
        return r.tag + " 얘기 찾아줘"; });
      var how = ["내 글을 내리고 싶어요", "글자를 크게 하려면?"];
      push("bot", "<p>무엇이 궁금하세요? 대화에서 나온 주제를 찾아 드리거나, 사이트 쓰는 법을 알려 드려요.</p>" +
        '<div class="ask-chips">' + tags.concat(how).map(chip).join("") + "</div>");
    }

    function hitHtml(t, catLabel) {
      return '<li><button class="ask-hit" type="button" data-ask-jump="t-' + esc(t.id) + '">' +
        '<b class="ask-hit__title">' + esc(t.title) + "</b>" +
        '<span class="ask-hit__meta">' + esc(t.start_date || "") +
        (catLabel[t.category] ? " · " + esc(catLabel[t.category]) : "") + "</span>" +
        (t.summary ? '<span class="ask-hit__sum">' + esc(t.summary) + "</span>" : "") +
        "</button></li>";
    }

    function guideHtml(g) {
      return '<div class="ask-guide"><b>' + esc(g.q) + "</b><p>" + esc(g.a) + "</p>" +
        (g.view && viewExists(g.view)
          ? '<button class="ask-go" type="button" data-ask-view="' + esc(g.view) + '">' +
            esc(g.go) + " →</button>" : "") + "</div>";
    }

    // 답마다 '모두 보기' 에 넘길 주제 묶음을 둔다. 단추에는 번호만 단다.
    var moreSets = [];
    function moreButton(set, text) {
      moreSets.push(set);
      return '<button class="ask-go" type="button" data-ask-more="' + (moreSets.length - 1) +
        '">' + esc(text) + " →</button>";
    }

    function hitsHtml(rows, catLabel) {
      return '<ul class="ask-hits">' + rows.slice(0, SHOW).map(function (r) {
        return hitHtml(r.thread, catLabel); }).join("") + "</ul>";
    }

    function answer(q) {
      var d = ctx.data();
      var names = (d.STATS.participants || []).map(function (p) { return p.nickname; });
      var people = namesIn(q, names);
      // 이름은 사람 거르기로 쓰고 찾을 말에서는 뺀다('김OO이' 의 '김OO').
      var terms = queryTerms(q).filter(function (w) {
        return !people.some(function (p) { return w.indexOf(p.toLowerCase()) === 0; }); });
      var rows = (terms.length || people.length) ? rankThreads(d.THREADS, terms, people) : [];
      /* 말이 여럿이면 가장 많이 맞은 주제들만 남긴다. '한글 자동화' 에 '자동화' 만
       * 맞은 주제 79개를 세어 주면 찾은 게 아니다. 하나도 다 맞지 않으면 그렇다고
       * 말한다 — 뜻을 헤아려 고르는 것은 AI 를 붙이는 2단계의 몫이다. */
      var best = rows.reduce(function (m, r) { return Math.max(m, r.strong); }, 0);
      var strong = rows.filter(function (r) { return r.strong > 0 && r.strong === best; });
      var partial = best > 0 && best < terms.length;
      var found = matchGuides(q, guides(ctx.TAG_PICK_MAX)).slice(0, 2);
      // 사용법을 묻는 말투에 맞는 안내가 있으면 안내가 답이다. 본문에서만 스친
      // 주제까지 늘어놓으면 답이 묻힌다.
      var howFirst = found.length > 0 && (isHowTo(q) || !strong.length);
      var tagRows = people.length ? [] :
        tagHits(q, (d.TAGIDX && d.TAGIDX.tags) || [], ctx.tagFold).slice(0, 2);

      var parts = [];
      var guidesPart = found.map(guideHtml).join("");
      if (howFirst) parts.push(guidesPart);
      var shown = strong.length ? strong : (howFirst ? [] : rows);
      if (shown.length) {
        var who = people.length ? people.join("·") + "님이 참여한 " : "";
        var lead = !strong.length
          ? "제목·요약에는 없고 본문에서만 나온 주제 <b>" + shown.length + "개</b>예요"
          : partial
            ? "물으신 말이 모두 들어간 주제는 없어요. 일부만 맞는 " + esc(who) + "주제 <b>" +
              shown.length + "개</b>예요"
            : esc(who) + "주제 <b>" + shown.length + "개</b>를 찾았어요";
        parts.push("<p>" + lead +
          (shown.length > SHOW ? ". 가까운 것부터 " + SHOW + "개를 보여 드려요." : ".") + "</p>" +
          hitsHtml(shown, d.CAT_LABEL));
        if (shown.length > SHOW) {
          parts.push(moreButton({ ids: shown.map(function (r) { return r.thread.id; }),
                                  label: people.concat(terms).join(" "), kind: "subject" },
                                shown.length + "개 모두 타임라인에서 보기"));
        }
      }
      tagRows.forEach(function (r) {
        var ids = d.TAG_THREADS[ctx.tagFold(r.tag)] || [];
        if (ids.length) {
          parts.push(moreButton({ ids: ids, label: "#" + r.tag, kind: "tag" },
                                "#" + r.tag + " 태그가 붙은 주제 " + ids.length + "개 보기"));
        }
      });
      if (!howFirst && guidesPart) {
        parts.push('<p class="ask-aside">혹시 사용법을 찾으셨나요?</p>' + guidesPart);
      }
      if (!parts.length) {
        parts.push("<p>맞는 주제를 찾지 못했어요. 도구 이름이나 사람 이름처럼 대화에 나왔을 말로 다시 물어봐 주세요.</p>" +
          '<div class="ask-chips">' + chip("사진은 어디서 봐요?") + chip("태그로 모아 보려면?") + "</div>");
      }
      push("bot", parts.join(""));
    }

    function ask(q) {
      q = String(q || "").trim();
      if (!q) return;
      push("me", "<p>" + esc(q) + "</p>");
      answer(q);
    }

    function onLogClick(e) {
      var b = e.target.closest("button");
      if (!b || !ui.log.contains(b)) return;
      if (b.hasAttribute("data-ask-q")) { ask(b.getAttribute("data-ask-q")); return; }
      // 화면을 옮기는 단추는 칸을 닫고 간다. 대화는 남아 있어 다시 열면 이어진다.
      if (b.hasAttribute("data-ask-jump")) {
        setOpen(false); ctx.jumpToTimeline(b.getAttribute("data-ask-jump"));
      } else if (b.hasAttribute("data-ask-view")) {
        setOpen(false); ctx.setView(b.getAttribute("data-ask-view"));
      } else if (b.hasAttribute("data-ask-more")) {
        var set = moreSets[+b.getAttribute("data-ask-more")];
        if (set) { setOpen(false); ctx.pickThreads(set.ids, set.label, set.kind); }
      }
    }

    function mount() {
      if (mounted) return;
      ui = {
        fab: document.getElementById("askFab"),
        panel: document.getElementById("askPanel"),
        close: document.getElementById("askClose"),
        log: document.getElementById("askLog"),
        form: document.getElementById("askForm"),
        input: document.getElementById("askInput"),
      };
      if (!ui.fab || !ui.panel) return;
      mounted = true;
      ui.fab.addEventListener("click", function () { setOpen(true); });
      ui.close.addEventListener("click", function () { setOpen(false); });
      ui.log.addEventListener("click", onLogClick);
      ui.form.addEventListener("submit", function (e) {
        e.preventDefault();
        var q = ui.input.value;
        ui.input.value = "";
        ask(q);
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && !ui.panel.hidden && !el.lightbox.classList.contains("on")) {
          setOpen(false);
        }
      });
    }

    return { mount: mount, ask: ask };
  }

  api.ArchiveAsk = ArchiveAsk;
  if (typeof window !== "undefined") window.ArchiveAsk = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
