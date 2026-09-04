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
        runSearch = ctx.runSearch, setView = ctx.setView, render = ctx.render,
        pickThreads = ctx.pickThreads;

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

    /** 이 노드의 관계와 그 **근거**.
     *
     *  관계망은 이 아카이브에서 유일하게 되짚을 수 없는 층이었다 — 엣지를 봐도
     *  왜 그렇게 아는지 갈 곳이 없었다. 발행본의 엣지에는 근거가 된 주제가
     *  실려 있으므로(`build_site.publish_edges`), 여기서 그 주제로 보내 준다.
     *
     *  근거가 없는 관계는 **단추를 내지 않는다.** 눌러서 빈 목록이 나오면 고장으로
     *  보인다 — 요지 태그를 화면에서 뺀 것과 같은 판단이다. 대신 관계 자체는
     *  보여 준다: 관계가 있다는 것과 근거를 못 찾았다는 것은 다른 말이고, 그
     *  차이가 보여야 사람이 무엇을 볼지 안다.
     */
    function relationRows(node) {
      var K = ctx.data().KNOW;
      var byId = {};
      (K.nodes || []).forEach(function (n) { byId[n.id] = n; });
      var etype = {};
      (K.edge_types || []).forEach(function (t) { etype[t.id] = t.label || t.id; });

      var rows = (K.edges || []).map(function (e) {
        var mine = e.source === node.id, other = byId[mine ? e.target : e.source];
        if ((!mine && e.target !== node.id) || !other) return null;
        var ids = e.evidence_threads || [];
        return {
          label: other.label, dir: mine ? "→" : "←",
          rel: etype[e.type] || e.type, ids: ids, by: e.by || "",
        };
      }).filter(Boolean);
      if (!rows.length) return "";

      // 근거가 있는 것을 먼저, 그 안에서 근거가 많은 것을 먼저. 되짚을 수 있는
      // 관계가 위에 오는 것이 이 절의 뜻이다.
      rows.sort(function (a, b) {
        return (b.ids.length - a.ids.length) || a.label.localeCompare(b.label);
      });
      var withEv = rows.filter(function (r) { return r.ids.length; }).length;

      return '<div class="np-rel"><h5>관계 ' + rows.length + "개 · 근거 있는 것 " +
        withEv + "개</h5>" +
        rows.map(function (r) {
          var head = '<span class="np-rel-dir">' + r.dir + "</span>" +
            '<b>' + esc(r.label) + "</b>" +
            '<span class="np-rel-kind">' + esc(r.rel) + "</span>";
          if (!r.ids.length) {
            return '<div class="np-rel-row np-rel-none">' + head +
              '<span class="np-rel-no">근거 없음</span></div>';
          }
          return '<div class="np-rel-row">' + head +
            '<button class="np-rel-go" data-ev="' + esc(r.ids.join(",")) +
            '" data-label="' + esc(node.label + " " + r.dir + " " + r.label) +
            '" title="근거가 된 대화 주제를 봅니다' +
            (r.by ? " (" + esc(r.by) + ")" : "") + '">근거 ' + r.ids.length +
            "</button></div>";
        }).join("") + "</div>";
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
        when + '<div class="np-actions">' + actions + "</div>" + relationRows(node);
      Array.prototype.forEach.call(body.querySelectorAll("[data-ev]"), function (b) {
        b.onclick = function () {
          var ids = (b.getAttribute("data-ev") || "").split(",").filter(Boolean);
          if (ids.length) pickThreads(ids, b.getAttribute("data-label"), "subject");
        };
      });
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
