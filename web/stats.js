/* ============ 통계 화면 (web/stats.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02, admin.js 다음). 통계 화면과 '사람별 관심 주제',
 * 그리고 '내 글 관리' 가 빌려 쓰는 발자국·성향 보고(myFootprint·myTraitReport)가
 * 여기 있다. 약 560줄.
 *
 * 공유하는 것은 ctx 로 받는다. 데이터 전역(THREADS·MEDIA·STATS·KNOW·CAT_LABEL·A)은
 * app.js init() 에서 **다시 읽히므로** 값이 아니라 읽는 함수(ctx.data())로 받는다 —
 * 보호모드에서는 로드 시점에 전부 비어 있다. '내 글' 쪽 함수(mineKind·myNicknames)도
 * 순환이라 ctx.mine() 으로 늦게 받는다.
 *
 * 돌려주는 것: bar · card · mentions · myTraitReport · renderStats.
 * 순서: text.js → stats.js → mine.js → admin.js → app.js.
 */
(function () {
  "use strict";

  window.ArchiveStats = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, colorFor = ctx.colorFor,
        avatarStyle = ctx.avatarStyle, initial = ctx.initial, setView = ctx.setView;

    // ---------- 통계 ----------
    function bar(label, value, max, color) {
      var pct = max ? Math.round((value / max) * 100) : 0;
      return '<div class="bar-row"><span class="lab">' + esc(label) + '</span><span class="track">' +
        '<span class="fill" style="width:' + pct + "%" + (color ? ";--c:" + color : "") + '"></span></span>' +
        '<span class="val">' + value + "</span></div>";
    }
    function card(v, k) { return '<div class="stat-card"><div class="v">' + (v == null ? "-" : v) + '</div><div class="k">' + esc(k) + "</div></div>"; }
    /* ---------- 나의 기록 ----------
     *
     * 로그인한 본인이 이 방에 무엇을 남겼는지 정리해 보여 준다. 남의 것은
     * 보이지 않는다 — 참여자별 순위표를 없앤 것과 같은 이유다. 서로를 줄 세우면
     * 적게 쓴 사람이 위축된다. 대신 각자 자기 발자취를 본다.
     *
     * 발행본(threads·media)만으로 계산한다. 별도 조회가 없어 빠르고, 본인 원문을
     * 불러오지 않으므로 통계 탭에서 원문이 오갈 일도 없다.
     */
    function myFootprint() {
      var names = ctx.mine().myNicknames();
      if (!names.length) return null;
      var mine = function (n) { return names.indexOf(n) !== -1; };

      var joined = ctx.data().THREADS.filter(function (t) {
        return (t.participants || []).some(mine);
      });
      if (!joined.length) return null;

      var byCat = {}, mates = {}, first = null, last = null;
      joined.forEach(function (t) {
        byCat[t.category] = (byCat[t.category] || 0) + 1;
        (t.participants || []).forEach(function (p) { if (!mine(p)) mates[p] = 1; });
        if (!first || t.start_date < first) first = t.start_date;
        if (!last || t.end_date > last) last = t.end_date;
      });
      var cats = Object.keys(byCat)
        .map(function (c) { return { id: c, label: ctx.data().CAT_LABEL[c] || c, n: byCat[c] }; })
        .sort(function (a, b) { return b.n - a.n; });

      var links = 0;
      ctx.data().THREADS.forEach(function (t) {
        (t.links || []).forEach(function (l) { if (mine(l.nickname)) links++; });
      });
      /* 동영상을 파일로 세면 안 된다 — '올린 파일' 칸이 있지도 않은 첨부를
       * 세고 '올린 사진' 은 실제보다 적어진다. 셋을 갈라 센다. */
      var photos = 0, videos = 0, files = 0;
      ctx.data().MEDIA.forEach(function (m) {
        if (!mine(m.nickname)) return;
        if (m.kind === "image") photos += (m.images ? m.images.length : m.count || 1);
        else if (m.kind === "video") videos += (m.videos ? m.videos.length : m.count || 1);
        else files++;
      });

      var msgs = 0;
      (ctx.data().STATS.participants || []).forEach(function (p) {
        if (mine(p.nickname)) msgs += p.message_count;
      });

      return { names: names, msgs: msgs, joined: joined.length, total: ctx.data().THREADS.length,
               cats: cats, mates: Object.keys(mates).length,
               links: links, photos: photos, videos: videos, files: files,
               first: first, last: last };
    }

    /** 숫자에서 읽히는 것만 적는다. 근거 없는 칭찬은 넣지 않는다. */
    function myHighlights(f) {
      var out = [];
      var share = f.joined / Math.max(1, f.total);
      if (share >= 0.5) {
        out.push("이 방의 주제 <b>절반 이상</b>에 함께하셨습니다. 오간 이야기의 큰 줄기를 " +
          "곁에서 지켜본 셈입니다.");
      } else if (share >= 0.2) {
        out.push("전체 주제의 <b>" + Math.round(share * 100) + "%</b>에 함께하셨습니다.");
      }
      if (f.cats.length >= 5) {
        out.push("<b>" + f.cats.length + "개 분야</b>에 걸쳐 이야기하셨습니다. 한쪽에 머물지 " +
          "않고 폭넓게 오가셨습니다.");
      } else if (f.cats.length) {
        out.push("<b>" + f.cats[0].label + "</b>을(를) 중심으로 이야기하셨습니다.");
      }
      if (f.links >= 10) {
        out.push("자료 링크를 <b>" + f.links + "건</b> 나누셨습니다. 혼자 찾은 것을 " +
          "그때그때 꺼내 놓으신 기록입니다.");
      }
      if (f.photos + f.videos + f.files >= 10) {
        out.push("사진과 파일을 <b>" + (f.photos + f.videos + f.files) + "개</b> 올리셨습니다. " +
          "말로만 하지 않고 결과물을 보여 주셨습니다.");
      }
      if (f.mates >= 10) {
        out.push("<b>" + f.mates + "명</b>과 같은 자리에서 이야기하셨습니다.");
      }
      if (!out.length) {
        out.push("남기신 것이 이 방의 기록에 함께 담겨 있습니다.");
      }
      return out;
    }

    function myReport() {
      var f = myFootprint();
      if (!f) return "";
      var top = f.cats.slice(0, 4).map(function (c) {
        return '<span class="chip dot" style="--c:' + colorFor(c.id) + '">' +
          esc(c.label) + " " + c.n + "</span>";
      }).join("");
      return '<div class="panel mypanel">' +
        "<h3>나의 기록 — " + esc(f.names.join(", ")) + "</h3>" +
        '<p class="my-lead">' + esc(f.first) + " 부터 " + esc(f.last) + " 까지, " +
        "<b>" + f.joined + "개 주제</b>에 함께하며 <b>" + f.msgs + "건</b>을 남기셨습니다.</p>" +
        '<div class="my-nums">' +
        numCell(f.joined + " / " + f.total, "함께한 주제") +
        numCell(f.msgs, "남긴 메시지") +
        numCell(f.links, "나눈 링크") +
        numCell(f.photos, "올린 사진") +
        // 동영상 칸은 올린 사람에게만 뜬다. 대부분 0인 칸을 모두에게 두면
        // 숫자가 아니라 빈자리를 늘어놓는 것이 된다.
        (f.videos ? numCell(f.videos, "올린 동영상") : "") +
        numCell(f.files, "올린 파일") +
        numCell(f.mates, "함께한 사람") +
        "</div>" +
        (top ? '<div class="my-cats">' + top + "</div>" : "") +
        "<ul class='my-notes'>" +
        myHighlights(f).map(function (s) { return "<li>" + s + "</li>"; }).join("") +
        "</ul>" +
        /* 성향·관심 이야기는 본인 원문이 있어야 쓸 수 있다. 통계 탭에서 원문을
           부르지 않는다는 원칙은 그대로 두고, 그 글이 있는 자리로 보낸다. */
        '<p class="my-more"><button class="btn ghost" id="goMine">' +
        "기록에서 읽히는 것 — 성향·관심 보고서 보기 →</button></p>" +
        '<p class="hint" style="text-align:left;padding:6px 0 0;font-size:12px">' +
        "이 칸은 <b>본인에게만</b> 보입니다. 다른 사람의 기록은 볼 수 없습니다.</p></div>";
    }
    function numCell(v, k) {
      return '<div class="my-num"><div class="v">' + v + '</div><div class="k">' + esc(k) + "</div></div>";
    }

    /* ---------- 나의 성향·관심 보고서 ----------
     *
     * 숫자만 늘어놓으면 "378건"이 무엇을 뜻하는지 알 수 없다. 방장이 짚었다 —
     * "너무 산술적이야." 그래서 센 값을 문장으로 옮긴다.
     *
     * 다만 세지 않은 것은 쓰지 않는다. 성격을 지어내지 않고, 기록에서 실제로
     * 읽히는 것만 적는다 — 문장마다 뒤에 센 숫자가 붙어 있다. 근거가 모자라면
     * 그 문장을 통째로 뺀다(임계값). 남을 평가하지 않는 것과 같은 이유로,
     * 이 보고서는 본인 원문이 있는 '나의 기록' 탭에서만 그린다.
     */
    var MY_SLOTS = [
      { from: 0, to: 6, label: "새벽(0~6시)" },
      { from: 6, to: 9, label: "아침(6~9시)" },
      { from: 9, to: 12, label: "오전(9~12시)" },
      { from: 12, to: 18, label: "낮(12~18시)" },
      { from: 18, to: 22, label: "저녁(18~22시)" },
      { from: 22, to: 24, label: "밤(22~24시)" },
    ];
    var MY_PAT = {
      ask: /[?？]|나요|까요|는지요|은지요|으실지|을지요|궁금|여쭤|물어봐|알려주실/,
      warm: /감사|고맙|축하|응원|환영|반갑|수고|화이팅|축하|기대/,
      praise: /멋지|대단|훌륭|좋네|좋습니|최고|굿|잘하[셨시]/,
      laugh: /ㅎㅎ|ㅋㅋ|\^\^|ㅠㅠ|~~/,
      guide: /하시면|하세요|해보세요|해보셔|누르|설치|설정|방법은|이렇게 하/,
      mention: /@\S/,
    };
    var MY_DAYS = ["일", "월", "화", "수", "목", "금", "토"];

    /** 메시지 번호 → 주제. 주제는 메시지 번호의 연속 구간이라 범위로 찾는다. */
    function threadRanges() {
      if (state.tRanges) return state.tRanges;
      var num = function (id) { return parseInt(String(id || "").replace(/\D/g, ""), 10) || 0; };
      state.tRanges = ctx.data().THREADS.map(function (t) {
        return { from: num(t.start_msg), to: num(t.end_msg), cat: t.category };
      }).filter(function (r) { return r.from; })
        .sort(function (a, b) { return a.from - b.from; });
      return state.tRanges;
    }

    /** 지식 그래프의 도구·결과물 이름을 찾을 말로 바꾼다. 'A(B)' 는 A 와 B 둘 다. */
    function myTermList() {
      if (state.myTerms) return state.myTerms;
      var out = [];
      (ctx.data().KNOW.nodes || []).forEach(function (n) {
        if (n.type !== "tool" && n.type !== "app") return;
        var words = [];
        String(n.query || n.label).split(/[·,]/).forEach(function (part) {
          var m = /^(.*?)\((.+?)\)\s*$/.exec(part.trim());
          if (m) { words.push(m[1].trim()); words.push(m[2].trim()); }
          else if (part.trim()) words.push(part.trim());
        });
        words = words.filter(function (w) { return w.length >= 2; });
        if (words.length) out.push({ label: n.label, words: words });
      });
      state.myTerms = out;
      return out;
    }

    /** 한 글에 그 이름이 나오는가. 영문 낱말은 다른 낱말 안에 박힌 것을 세지 않는다. */
    function mentions(text, words) {
      for (var i = 0; i < words.length; i++) {
        var w = words[i];
        if (/^[\x20-\x7e]+$/.test(w)) {
          var re = new RegExp("(^|[^A-Za-z0-9])" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
            "([^A-Za-z0-9]|$)", "i");
          if (re.test(text)) return true;
        } else if (text.indexOf(w) !== -1) return true;
      }
      return false;
    }

    function myTraits(items) {
      var t = {
        total: items.length, text: 0, image: 0, video: 0, file: 0, urls: 0, chars: 0, shots: 0,
        long: 0, ask: 0, warm: 0, praise: 0, laugh: 0, guide: 0, mention: 0,
        weekend: 0, slots: [], months: {}, days: {}, cats: {}, terms: [],
        opened: 0, myIds: {},
      };
      MY_SLOTS.forEach(function () { t.slots.push(0); });
      var terms = myTermList().map(function (x) { return { label: x.label, words: x.words, n: 0 }; });
      var ranges = threadRanges();
      var num = function (id) { return parseInt(String(id || "").replace(/\D/g, ""), 10) || 0; };

      items.forEach(function (m) {
        t.myIds[m.id] = 1;
        var kind = ctx.mine().mineKind(m);
        t[kind]++;
        t.urls += (m.urls || []).length;
        // 사진은 글 수가 아니라 장 수로 센다 — 한 번에 여러 장을 올린 글이 많다
        if (kind === "image") t.shots += (m.image_count || 1);

        var body = String(m.text || "");
        if (kind === "text") {
          t.chars += body.length;
          if (body.length >= 200) t.long++;
          if (MY_PAT.ask.test(body)) t.ask++;
          if (MY_PAT.warm.test(body)) t.warm++;
          if (MY_PAT.praise.test(body)) t.praise++;
          if (MY_PAT.laugh.test(body)) t.laugh++;
          if (MY_PAT.guide.test(body)) t.guide++;
          if (MY_PAT.mention.test(body)) t.mention++;
          /* 이름 세기에서 주소는 뺀다. github.com 링크를 붙인 것을 'GitHub 를 말했다'로
             세면 링크 공유가 관심사로 둔갑한다. 링크는 이미 따로 세고 있다. */
          var plain = body.replace(/https?:\/\/\S+/g, " ");
          terms.forEach(function (x) { if (mentions(plain, x.words)) x.n++; });
        }

        var hh = parseInt(String(m.time || "").slice(0, 2), 10);
        if (!isNaN(hh)) {
          for (var i = 0; i < MY_SLOTS.length; i++) {
            if (hh >= MY_SLOTS[i].from && hh < MY_SLOTS[i].to) { t.slots[i]++; break; }
          }
        }
        var d = String(m.date || "");
        if (d) {
          t.days[d] = (t.days[d] || 0) + 1;
          t.months[d.slice(0, 7)] = (t.months[d.slice(0, 7)] || 0) + 1;
          var wd = new Date(d + "T00:00:00").getDay();
          if (wd === 0 || wd === 6) t.weekend++;
        }

        /* 발행본 메시지에는 분야가 붙어 있다. 없으면(옛 문서) 번호 구간으로 찾는다. */
        var cat = m.category;
        if (!cat) {
          var n = num(m.id);
          for (var j = 0; j < ranges.length; j++) {
            if (n >= ranges[j].from && n <= ranges[j].to) { cat = ranges[j].cat; break; }
          }
        }
        if (cat) t.cats[cat] = (t.cats[cat] || 0) + 1;
      });

      ctx.data().THREADS.forEach(function (th) { if (t.myIds[th.start_msg]) t.opened++; });

      // 많이 쓴 사람일수록 한두 번 스친 이름은 관심사가 아니다. 글 수에 맞춰 문턱을 올린다.
      var need = Math.max(2, Math.round(t.text / 60));
      t.terms = terms.filter(function (x) { return x.n >= need; })
        .sort(function (a, b) { return b.n - a.n; });
      return t;
    }

    /** 나와 같은 주제에 자주 있었던 사람. 발행본의 참여자 목록만 본다. */
    function myMates(limit) {
      var names = ctx.mine().myNicknames();
      var mine = function (n) { return names.indexOf(n) !== -1; };
      var by = {};
      ctx.data().THREADS.forEach(function (t) {
        var ps = t.participants || [];
        if (!ps.some(mine)) return;
        ps.forEach(function (p) { if (!mine(p)) by[p] = (by[p] || 0) + 1; });
      });
      return Object.keys(by).map(function (k) { return { name: k, n: by[k] }; })
        .sort(function (a, b) { return b.n - a.n; }).slice(0, limit);
    }

    function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
    function topKey(obj) {
      var best = null;
      Object.keys(obj).forEach(function (k) { if (!best || obj[k] > obj[best]) best = k; });
      return best;
    }
    function ymLabel(ym) {
      var p = String(ym).split("-");
      return p[0] + "년 " + parseInt(p[1], 10) + "월";
    }
    function dLabel(d) {
      var p = String(d).split("-");
      return parseInt(p[1], 10) + "월 " + parseInt(p[2], 10) + "일(" +
        MY_DAYS[new Date(d + "T00:00:00").getDay()] + ")";
    }

    /** 문장 목록 → 섹션. 문장이 하나도 없으면 섹션 자체를 그리지 않는다. */
    function mySection(title, lines) {
      var ok = lines.filter(Boolean);
      if (!ok.length) return "";
      return '<div class="my-story"><h4>' + title + "</h4>" +
        ok.map(function (s) { return "<p>" + s + "</p>"; }).join("") + "</div>";
    }

    function myTraitReport(items) {
      if (!items || items.length < 5) return "";
      var t = myTraits(items);
      var n = t.total, txt = t.text || 1;

      /* 언제 — 시간대는 가장 두드러진 하나만. 고르게 흩어져 있으면 그렇게 적는다. */
      var si = 0;
      t.slots.forEach(function (v, i) { if (v > t.slots[si]) si = i; });
      var slotShare = pct(t.slots[si], n);
      var topMonth = topKey(t.months), topDay = topKey(t.days);
      var when = mySection("언제 쓰셨나", [
        slotShare >= 25
          ? "글은 <b>" + MY_SLOTS[si].label + "</b>에 가장 많았습니다 — " + n + "건 가운데 " +
            t.slots[si] + "건(" + slotShare + "%)이 이 시간대입니다."
          : "쓰신 시각이 하루에 고르게 흩어져 있습니다. 가장 많은 때가 " +
            MY_SLOTS[si].label + "이고 그마저 " + slotShare + "%입니다.",
        t.weekend >= 5
          ? "주말에도 <b>" + t.weekend + "건</b>(" + pct(t.weekend, n) + "%)을 남기셨습니다."
          : "",
        topMonth
          ? "가장 말이 많았던 달은 <b>" + ymLabel(topMonth) + "</b>(" + t.months[topMonth] +
            "건)이고, 하루에 가장 많이 쓴 날은 <b>" + dLabel(topDay) + "</b>(" +
            t.days[topDay] + "건)입니다."
          : "",
      ]);

      /* 무엇 — 도구·결과물 이름과, 방 전체와 견준 분야 쏠림 */
      // 이름 하나가 두 번 나온 것으로 관심사를 말할 수는 없다
      var top5 = (t.terms.length >= 2 || (t.terms[0] && t.terms[0].n >= 3))
        ? t.terms.slice(0, 5).map(function (x) {
            return "<b>" + esc(x.label) + "</b>(" + x.n + "번)";
          }).join(", ")
        : "";
      var roomTotal = 0, roomBy = {};
      (ctx.data().STATS.categories || []).forEach(function (c) { roomTotal += c.messages; roomBy[c.id] = c.messages; });
      var myCatTotal = 0;
      Object.keys(t.cats).forEach(function (k) { myCatTotal += t.cats[k]; });
      var over = Object.keys(t.cats).map(function (k) {
        return { id: k, n: t.cats[k], mine: t.cats[k] / (myCatTotal || 1),
                 room: (roomBy[k] || 0) / (roomTotal || 1) };
      /* 비율만 보면 5%대 3% 같은 자잘한 차이가 1등으로 올라온다. 눈에 띄는 쏠림만
         말하려고 비(比)와 차(差)를 함께 걸고, 차이가 큰 것을 고른다. */
      }).filter(function (x) {
        return x.n >= 5 && x.room > 0 && x.mine / x.room >= 1.25 && x.mine - x.room >= 0.04;
      }).sort(function (a, b) { return (b.mine - b.room) - (a.mine - a.room); })[0];
      var myTop = Object.keys(t.cats).map(function (k) { return { id: k, n: t.cats[k] }; })
        .sort(function (a, b) { return b.n - a.n; });
      var what = mySection("무엇에 마음이 갔나", [
        top5 ? "글에 되풀이해 나온 이름은 " + top5 + "입니다." : "",
        myTop.length
          ? "가장 오래 머무신 자리는 <b>" + esc(ctx.data().CAT_LABEL[myTop[0].id] || myTop[0].id) +
            "</b>(" + myTop[0].n + "건, 내 글의 " + pct(myTop[0].n, myCatTotal) + "%)입니다."
          : "",
        over
          ? "이 방 전체와 견주면 <b>" + esc(ctx.data().CAT_LABEL[over.id] || over.id) +
            "</b> 쪽으로 더 기울어 있습니다 — 내 글의 " + Math.round(over.mine * 100) +
            "%, 방 전체는 " + Math.round(over.room * 100) + "%."
          : "",
      ]);

      /* 어떻게 — 묻는지 건네는지, 길게 쓰는지, 어떤 말씨인지 */
      var give = t.urls + t.shots + t.file;
      var gaveWhat = [[t.urls, "링크 %건"], [t.shots, "사진 %장"], [t.file, "첨부 %개"]]
        .filter(function (g) { return g[0]; })
        .map(function (g) { return g[1].replace("%", g[0]); }).join(", ");
      /* 적게 쓴 사람에게 "답하는 쪽"이라고 단정하면 근거 없는 성격 규정이 된다.
         판단은 글이 충분히 쌓였을 때만 하고, 아니면 아예 말하지 않는다. */
      var askLine = "";
      if (pct(t.ask, txt) >= 15) {
        askLine = "묻는 말이 <b>" + t.ask + "건</b>(글의 " + pct(t.ask, txt) +
          "%)입니다. 먼저 물어서 이야기를 끌어내는 편입니다.";
      } else if (txt >= 30 && pct(t.ask, txt) <= 8) {
        askLine = "묻기보다 <b>답하고 알려주는</b> 쪽이 많았습니다. 묻는 말은 " + t.ask +
          "건(" + pct(t.ask, txt) + "%)에 그칩니다.";
      }
      var how = mySection("어떻게 말하셨나", [
        askLine,
        give >= 10
          ? gaveWhat + " — <b>무언가를 건네는 글</b>이 " + give + "번입니다."
          : "",
        "한 번 쓸 때 평균 <b>" + Math.round(t.chars / txt) + "자</b>였고" +
          (t.long ? ", 200자가 넘는 긴 글도 <b>" + t.long + "건</b> 있습니다." : "입니다.") +
          (t.long >= txt * 0.1 ? " 필요할 때는 길게 정리해 두는 편입니다." : ""),
        t.guide >= txt * 0.15
          ? "'이렇게 하세요' 식으로 <b>방법을 일러 주는 글</b>이 " + t.guide + "건(" +
            pct(t.guide, txt) + "%)입니다."
          : "",
        (t.warm + t.praise) >= txt * 0.15
          ? "고맙다·반갑다·멋지다 같은 <b>호응하는 말</b>이 " + (t.warm + t.praise) +
            "건에서 보입니다."
          : "",
        t.laugh >= txt * 0.3
          ? "ㅎㅎ·^^ 같은 표시가 <b>" + t.laugh + "건</b>(" + pct(t.laugh, txt) +
            "%)에 붙어 있습니다. 딱딱하지 않게 말하시는 편입니다."
          : "",
        t.opened >= 3
          ? "<b>" + t.opened + "개 주제</b>의 첫 말을 남기셨습니다 — 이야기를 여는 자리에 " +
            "자주 서 계셨습니다."
          : "",
      ]);

      /* 누구와 — 줄 세우지 않되, 자주 겹친 자리는 알려 준다 */
      var mates = myMates(3);
      var who = mySection("누구와 있었나", [
        mates.length
          ? "같은 주제에 가장 자주 함께 계셨던 분은 " + mates.map(function (m) {
              return "<b>" + esc(m.name) + "</b>(" + m.n + "개 주제)";
            }).join(", ") + "입니다."
          : "",
        t.mention >= 5
          ? "이름을 불러(@) 말을 건넨 글이 " + t.mention + "건입니다."
          : "",
      ]);

      if (!(when + what + how + who)) return "";
      return '<div class="mine-card my-profile">' +
        "<h3>기록에서 읽히는 것</h3>" +
        '<p class="mine-note">아래는 남기신 글을 세어 본 것입니다. ' +
        "세어지지 않는 것은 적지 않았습니다. 본인에게만 보입니다.</p>" +
        when + what + how + who + "</div>";
    }

    /** 여러 색이 쌓인 막대. 한 달 안에서 어떤 주제가 오갔는지 색으로 보인다. */
    function stackBar(label, segs, total, max) {
      var pct = max ? (total / max) * 100 : 0;
      var inner = segs.map(function (s) {
        return '<span class="seg" style="width:' + (s.n / total * 100) + "%;background:" +
          colorFor(s.id) + '" title="' + esc(s.label + " " + s.n) + '"></span>';
      }).join("");
      return '<div class="bar-row"><span class="lab">' + esc(label) + "</span>" +
        '<span class="track"><span class="fill stack" style="width:' + pct + '%">' +
        inner + "</span></span>" +
        '<span class="val">' + total + "</span></div>";
    }

    /** 월별 × 주제별 집계. 스레드의 시작 달을 그 스레드의 달로 본다. */
    function monthlyByCategory() {
      var by = {};
      ctx.data().THREADS.forEach(function (t) {
        var m = (t.start_date || "").slice(0, 7);
        if (!m) return;
        (by[m] = by[m] || {})[t.category] = (by[m][t.category] || 0) + (t.count || 0);
      });
      return Object.keys(by).sort().map(function (m) {
        var segs = Object.keys(by[m])
          .map(function (c) { return { id: c, label: ctx.data().CAT_LABEL[c] || c, n: by[m][c] }; })
          .sort(function (a, b) { return b.n - a.n; });
        return { month: m, segs: segs,
                 total: segs.reduce(function (s, x) { return s + x.n; }, 0) };
      });
    }

    /* 사람별 관심 주제.
     *
     * 사람을 평가하는 화면처럼 읽힐 수 있어 조심해서 짰다. 셋을 지킨다.
     *   - 발언 수 순위를 매기지 않는다(누가 말이 많았나를 겨루는 판이 아니다).
     *   - '무엇에 관심'까지만 말하고 잘한다·못한다를 말하지 않는다.
     *   - 본인이 빠질 수 있다. 빠지면 발행 데이터 자체에 안 실린다.
     * 계산은 발행 단계에서 끝냈다(scripts/interests.py) — 참여한 주제의 분류를
     * 방 평균과 비교하고, 태그는 여러 사람이 쓴 것의 값을 깎는다. */
    function interestPanel() {
      var data = ctx.data().A.interests || { people: [] };
      var rows = data.people || [];
      if (!rows.length) return "";
      function person(p) {
        var fields = (p.fields || []).map(function (f) {
          return '<span class="int-field" style="--c:' + colorFor(f.category) + '">' +
            esc(f.label) + "</span>";
        }).join("");
        var topics = (p.topics || []).map(function (t) {
          return '<button class="tag-chip" data-int-nick="' + esc(p.nickname) +
            '" data-int-tag="' + esc(t.tag) + '">' + esc(t.tag) + "</button>";
        }).join("");
        return '<div class="int-row"><button class="int-name" data-nick="' + esc(p.nickname) +
          '"><span class="sidebar-avatar" style="' + avatarStyle(p.nickname) +
          '" aria-hidden="true">' + esc(initial(p.nickname)) + "</span>" + esc(p.nickname) +
          '<span class="int-n">주제 ' + p.thread_count + "개</span></button>" +
          (fields ? '<div class="int-fields">' + fields + "</div>" : "") +
          (topics ? '<div class="tag-cloud small">' + topics + "</div>" : "") + "</div>";
      }
      var top = rows.slice(0, 12), rest = rows.slice(12);
      var body = top.map(person).join("");
      if (rest.length) {
        body += '<details class="more-fold"><summary>' + rest.length +
          "명 더 보기</summary>" + rest.map(person).join("") + "</details>";
      }
      return '<div class="panel"><h3>사람별 관심 주제</h3>' +
        '<p class="doc-note">그 사람이 참여한 대화에서 뽑았습니다. 방 전체가 많이 ' +
        '이야기한 화제는 값을 낮춰, 그 사람에게 몰린 것만 남깁니다. 주제 ' +
        (data.min_threads || 3) + "개 미만 참여자는 내지 않습니다." +
        '<br>이 목록에서 빠지고 싶으면 <b>내 글 관리</b>에서 끄면 됩니다.</p>' +
        body + "</div>";
    }

    function bindInterests(scope) {
      Array.prototype.forEach.call(scope.querySelectorAll("[data-int-tag]"), function (b) {
        b.onclick = function (e) {
          e.stopPropagation();
          state.pick = null;
          state.nick = b.getAttribute("data-int-nick");
          state.q = b.getAttribute("data-int-tag");
          el.filter.value = state.nick; el.search.value = state.q;
          setView("timeline");
        };
      });
    }

    function renderStats() {
      var t = ctx.data().STATS.totals || {}, html = [];
      html.push('<div class="stat-cards">' + card(t.messages, "메시지") + card(t.participants, "참여자") +
        card((ctx.data().KNOW.nodes || []).length, "지식 노드") + card((ctx.data().KNOW.edges || []).length, "관계") +
        card(t.downloaded_images, "보관 사진") + card(t.urls, "링크") + "</div>");
      html.push('<p class="room-sub" style="margin:-6px 0 16px">기간 ' + esc(t.date_start || "") + " ~ " + esc(t.date_end || "") + "</p>");

      // 주제 분포를 먼저 — 이 방이 무엇을 이야기했는지가 먼저 보여야 한다
      var cs = (ctx.data().STATS.categories || []).slice().sort(function (a, b) { return b.messages - a.messages; });
      var maxC = cs.reduce(function (s, x) { return Math.max(s, x.messages); }, 1);
      html.push('<div class="panel"><h3>주제 분포</h3>' + cs.map(function (x) {
        return bar(x.label, x.messages, maxC, colorFor(x.id));
      }).join("") + "</div>");

      // 월별 활동은 주제 색을 쌓아 보여 준다. 그 달에 무엇이 오갔는지까지 읽힌다.
      var mc = monthlyByCategory();
      var maxM = mc.reduce(function (s, x) { return Math.max(s, x.total); }, 1);
      html.push('<div class="panel"><h3>월별 활동</h3>' +
        mc.map(function (x) { return stackBar(x.month, x.segs, x.total, maxM); }).join("") +
        '<p class="hint" style="padding:8px 0 0;text-align:left;font-size:12px">' +
        "막대의 색은 주제입니다. 마우스를 올리면 건수가 보입니다.</p></div>");

      html.push(interestPanel());
      html.push(myReport());
      el.view.innerHTML = html.join("");
      var go = document.getElementById("goMine");
      if (go) go.onclick = function () { setView("mine"); };
      bindInterests(el.view);
      Array.prototype.forEach.call(el.view.querySelectorAll("[data-nick]"), function (b) {
        b.onclick = function () {
          el.filter.value = b.getAttribute("data-nick");
          state.nick = el.filter.value; state.q = ""; state.pick = null;
          el.search.value = "";
          setView("timeline");
        };
      });
    }

    // ---------- 라이트박스 ----------

    return { bar: bar, card: card, mentions: mentions, myTraitReport: myTraitReport,
             renderStats: renderStats };
  };
})();
