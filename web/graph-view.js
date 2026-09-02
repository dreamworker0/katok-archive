/* ============ 관계망 화면 (web/graph-view.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). 그리기 자체는 web/graph.js(ArchiveGraph)가 하고,
 * 여기는 그것을 화면에 앉히고 노드 패널을 채우는 쪽이다. 이름이 graph.js 와 겹치지
 * 않게 -view 를 붙였다. 약 80줄.
 *
 * 떼어내는 방식은 admin.js·stats.js·mine.js 와 같다 — 팩토리 하나에 공유하는 것만
 * 넘긴다. init() 에서 다시 읽히는 데이터 전역은 값이 아니라 읽는 함수(ctx.data())로,
 * 다른 조각의 함수는 늦게 읽는 함수(ctx.stats())로 받는다.
 *
 * 돌려주는 것: renderGraph.
 */
(function () {
  "use strict";

  window.ArchiveGraphView = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, colorFor = ctx.colorFor,
        runSearch = ctx.runSearch, setView = ctx.setView, render = ctx.render;

    // ---------- 관계망 ----------
    function renderGraph() {
      el.view.innerHTML =
        '<div class="graph-wrap"><div id="gmount"></div>' +
        '<div class="node-panel" id="nodePanel"><button class="np-close" id="npClose">×</button>' +
        '<div id="npBody"></div></div></div>';
      var panel = document.getElementById("nodePanel");
      document.getElementById("npClose").onclick = function () { panel.classList.remove("on"); };

      state.graph = window.KGraph.render(document.getElementById("gmount"), {
        nodes: ctx.data().KNOW.nodes, edges: ctx.data().KNOW.edges, colorFor: colorFor, catLabel: ctx.data().CAT_LABEL,
        // 노드 종류 표는 발행본이 준다 — 원본은 scripts/ontology.py 다.
        nodeTypes: ctx.data().KNOW.node_types,
        onSelect: function (node) {
          if (!node) { panel.classList.remove("on"); return; }
          fillNodePanel(node);
          panel.classList.add("on");
        },
      });
    }

    function fillNodePanel(node) {
      var body = document.getElementById("npBody");
      /* 종류 이름은 발행본의 표에서 읽는다(원본은 scripts/ontology.py). 예전에는
       * 여기와 graph.js 에 따로 적혀 있어서 같은 종류가 '앱·결과물' 과 '앱' 으로
       * 갈렸다. 표가 없는 옛 캐시에서는 id 를 그대로 보여준다 — 빈칸보다 낫다. */
      var typeMap = {};
      (ctx.data().KNOW.node_types || []).forEach(function (t) { typeMap[t.id] = t.label || t.id; });
      var rows = "", actions = "";
      if (node.type === "person") {
        rows = '<div class="np-row">메시지 ' + (node.messages || 0) + "개 · 주로 <b>" +
          esc(ctx.data().CAT_LABEL[node.category] || "") + "</b></div>";
        actions = '<button class="btn" data-act="nick" data-v="' + esc(node.label) + '">이 사람만 보기</button>';
      } else if (node.type === "topic") {
        rows = '<div class="np-row">주제 클러스터의 중심</div>';
        actions = '<button class="btn" data-act="doc" data-v="' + esc(node.category) + '">지식 문서 보기</button>';
      } else if (node.type === "app") {
        rows = '<div class="np-row">만든이 <b>' + esc(node.maker || "-") + "</b><br>주제 " +
          esc(ctx.data().CAT_LABEL[node.category] || "") + "</div>";
        actions = '<button class="btn" data-act="q" data-v="' + esc(node.query || node.label) + '">타임라인에서 보기</button>';
      } else {
        rows = '<div class="np-row">주제 ' + esc(ctx.data().CAT_LABEL[node.category] || "") + "</div>";
        actions = '<button class="btn" data-act="q" data-v="' + esc(node.query || node.label) + '">타임라인에서 보기</button>';
      }
      /* 언제 오간 이야기인가. 관계망에는 시간이 없어서 작년에 한 번 스친 도구와
       * 어제까지 쓰는 도구가 나란히 떠 있었다. 흐리게 하거나 걸러내지는 않는다 —
       * 새 시각 언어를 만들기 전에 사실만 적어 둔다. 날짜가 없는 노드(원문에 이름이
       * 한 번도 안 나온 것)는 이 줄을 아예 내지 않는다. */
      var when = "";
      if (node.first_seen) {
        var span = node.first_seen === node.last_seen
          ? node.first_seen
          : node.first_seen + " ~ " + node.last_seen;
        when = '<div class="np-row np-when">' + esc(span) +
          (node.mentions ? " · " + node.mentions + "회 언급" : "") + "</div>";
      }
      body.innerHTML = '<h4>' + esc(node.label) + "</h4>" +
        '<div class="np-type">' + esc(typeMap[node.type] || node.type || "") + "</div>" + rows +
        when + '<div class="np-actions">' + actions + "</div>";
      Array.prototype.forEach.call(body.querySelectorAll("[data-act]"), function (b) {
        b.onclick = function () {
          var v = b.getAttribute("data-v");
          if (b.getAttribute("data-act") === "nick") { el.filter.value = v; state.nick = v; setView("timeline"); }
          else if (b.getAttribute("data-act") === "q") { runSearch(v); }
          else if (b.getAttribute("data-act") === "doc") {
            setView("summary");
            requestAnimationFrame(function () {
              var t = document.getElementById("doc-" + v);
              if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
            });
          }
        };
      });
    }

    return { renderGraph: renderGraph };
  };
})();
