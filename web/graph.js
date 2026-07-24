/* ============ 관계망 · SVG 힘-지향 그래프 (의존성 없음) ============ */
(function () {
  "use strict";
  var SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // opts: {nodes, edges, colorFor(catId), catLabel{}, onSelect(node, neighborIds)}
  function render(mount, opts) {
    mount.innerHTML = "";
    var nodes = opts.nodes.map(function (n) { return Object.assign({}, n); });
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var edges = opts.edges
      .filter(function (e) { return byId[e.source] && byId[e.target]; })
      .map(function (e) { return { s: byId[e.source], t: byId[e.target], type: e.type }; });

    // 인접
    var adj = {};
    nodes.forEach(function (n) { adj[n.id] = new Set(); });
    edges.forEach(function (e) { adj[e.s.id].add(e.t.id); adj[e.t.id].add(e.s.id); });

    // 카테고리 앵커(클러스터 중심)
    var cats = [];
    nodes.forEach(function (n) { if (cats.indexOf(n.category) < 0) cats.push(n.category); });
    var CR = 280, anchor = {};
    cats.forEach(function (c, i) {
      var a = (i / cats.length) * Math.PI * 2 - Math.PI / 2;
      anchor[c] = { x: Math.cos(a) * CR, y: Math.sin(a) * CR };
    });
    // 초기 위치: 앵커 주변 산포 (결정론적)
    var seed = 1;
    function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
    nodes.forEach(function (n) {
      var a = anchor[n.category];
      n.x = a.x + (rnd() - 0.5) * 120;
      n.y = a.y + (rnd() - 0.5) * 120;
      n.vx = 0; n.vy = 0;
      n.r = Math.max(5, n.value * 0.5 + 2.5);
    });

    // ── DOM ──
    var typeState = { topic: true, app: true, tool: true, person: true };
    var toolbar = document.createElement("div");
    toolbar.className = "graph-toolbar";
    var legend = document.createElement("div");
    legend.className = "legend";
    cats.forEach(function (c) {
      var s = document.createElement("span");
      s.innerHTML = '<i class="lg-mark" style="background:' + opts.colorFor(c) +
        ';border-radius:50%"></i>' + (opts.catLabel[c] || c);
      legend.appendChild(s);
    });
    toolbar.appendChild(legend);
    var spacer = document.createElement("div"); spacer.className = "spacer"; toolbar.appendChild(spacer);
    var TYPES = [["topic", "주제"], ["app", "앱"], ["tool", "도구"], ["person", "사람"]];
    TYPES.forEach(function (t) {
      var b = document.createElement("button");
      b.className = "on"; b.textContent = t[1];
      b.onclick = function () {
        typeState[t[0]] = !typeState[t[0]];
        b.classList.toggle("on", typeState[t[0]]);
        applyVisibility();
      };
      toolbar.appendChild(b);
    });
    var resetBtn = document.createElement("button");
    resetBtn.textContent = "⤢ 초기화";
    resetBtn.onclick = function () { view = { x: 0, y: 0, k: 1 }; applyView(); };
    toolbar.appendChild(resetBtn);
    mount.appendChild(toolbar);

    var s = svg("svg", { id: "graphSvg" });
    var vp = svg("g");
    var gEdges = svg("g"); var gNodes = svg("g");
    vp.appendChild(gEdges); vp.appendChild(gNodes);
    s.appendChild(vp);
    mount.appendChild(s);

    // 엣지 요소
    var edgeEls = edges.map(function (e) {
      var ln = svg("line", { class: "gedge" });
      ln._e = e; gEdges.appendChild(ln); return ln;
    });
    // 노드 요소
    nodes.forEach(function (n) {
      var g = svg("g", { class: "gnode" });
      var col = opts.colorFor(n.category);
      var shape;
      if (n.type === "tool") {
        shape = svg("rect", { x: -n.r, y: -n.r, width: n.r * 2, height: n.r * 2,
          transform: "rotate(45)", rx: 2, fill: col, stroke: "var(--surface)", "stroke-width": 1.5 });
      } else {
        shape = svg("circle", { r: n.r, fill: col,
          stroke: n.type === "topic" ? "var(--ink)" : "var(--surface)",
          "stroke-width": n.type === "topic" ? 2 : 1.5,
          "fill-opacity": n.type === "person" ? 0.7 : 1 });
      }
      g.appendChild(shape);
      if (n.type === "topic") {
        var tx = svg("text", { "text-anchor": "middle", y: -n.r - 4,
          style: "font-weight:700;font-size:11px" });
        tx.textContent = n.label; g.appendChild(tx);
      } else {
        var tx2 = svg("text", { "text-anchor": "middle", y: -n.r - 3, style: "display:none" });
        tx2.textContent = n.label; g.appendChild(tx2); n._label = tx2;
      }
      n._g = g; n._shape = shape;
      gNodes.appendChild(g);
      bindNode(n);
    });

    function applyVisibility() {
      nodes.forEach(function (n) { n._g.style.display = typeState[n.type] ? "" : "none"; });
      edgeEls.forEach(function (ln) {
        var e = ln._e;
        ln.style.display = (typeState[e.s.type] && typeState[e.t.type]) ? "" : "none";
      });
    }

    // ── 뷰(팬/줌) ──
    var view = { x: 0, y: 0, k: 1 };
    function applyView() {
      vp.setAttribute("transform",
        "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")");
    }
    function sizeView() {
      var w = s.clientWidth || 800, h = s.clientHeight || 500;
      s.setAttribute("viewBox", (-w / 2) + " " + (-h / 2) + " " + w + " " + h);
    }
    sizeView();
    window.addEventListener("resize", sizeView);

    s.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var f = ev.deltaY < 0 ? 1.12 : 0.89;
      var nk = Math.min(4, Math.max(0.3, view.k * f));
      view.x = view.x * (nk / view.k); view.y = view.y * (nk / view.k);
      view.k = nk; applyView();
    }, { passive: false });

    // 배경 드래그 = 팬, 노드 드래그 = 이동
    var drag = null;
    s.addEventListener("pointerdown", function (ev) {
      if (ev.target === s || ev.target === vp || ev.target.tagName === "line") {
        drag = { pan: true, x: ev.clientX, y: ev.clientY };
        s.classList.add("grabbing"); s.setPointerCapture(ev.pointerId);
      }
    });
    s.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      if (drag.pan) {
        view.x += ev.clientX - drag.x; view.y += ev.clientY - drag.y;
        drag.x = ev.clientX; drag.y = ev.clientY; applyView();
      } else if (drag.node) {
        var pt = toWorld(ev);
        drag.node.fx = pt.x; drag.node.fy = pt.y; alpha = Math.max(alpha, 0.3);
      }
    });
    s.addEventListener("pointerup", function (ev) {
      if (drag && drag.node) { drag.node.fx = null; drag.node.fy = null; }
      drag = null; s.classList.remove("grabbing");
    });
    function toWorld(ev) {
      var rect = s.getBoundingClientRect();
      var w = s.clientWidth, h = s.clientHeight;
      var sx = (ev.clientX - rect.left) / rect.width * w - w / 2;
      var sy = (ev.clientY - rect.top) / rect.height * h - h / 2;
      return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k };
    }

    var selectedId = null;
    function bindNode(n) {
      n._g.addEventListener("pointerdown", function (ev) {
        ev.stopPropagation();
        drag = { node: n }; s.setPointerCapture(ev.pointerId);
      });
      n._g.addEventListener("pointerenter", function () { if (!selectedId) highlight(n.id); });
      n._g.addEventListener("pointerleave", function () { if (!selectedId) highlight(null); });
      n._g.addEventListener("click", function (ev) {
        ev.stopPropagation();
        selectedId = (selectedId === n.id) ? null : n.id;
        highlight(selectedId);
        if (opts.onSelect) opts.onSelect(selectedId ? n : null, selectedId ? adj[n.id] : null);
      });
    }
    s.addEventListener("click", function (ev) {
      if (ev.target === s || ev.target === vp) {
        selectedId = null; highlight(null); if (opts.onSelect) opts.onSelect(null, null);
      }
    });

    function highlight(id) {
      if (!id) {
        nodes.forEach(function (n) {
          n._g.classList.remove("dim");
          if (n._label) n._label.style.display = "none";
        });
        edgeEls.forEach(function (ln) { ln.classList.remove("dim", "hl"); });
        return;
      }
      var keep = adj[id];
      nodes.forEach(function (n) {
        var on = n.id === id || keep.has(n.id);
        n._g.classList.toggle("dim", !on);
        if (n._label) n._label.style.display = on ? "" : "none";
      });
      edgeEls.forEach(function (ln) {
        var e = ln._e, touch = e.s.id === id || e.t.id === id;
        ln.classList.toggle("hl", touch);
        ln.classList.toggle("dim", !touch);
      });
    }

    // ── 시뮬레이션 ──
    var alpha = 1, REP = 2600, SPRING = 0.035, LEN = 46, CLUSTER = 0.02, CENTER = 0.006;
    function tick() {
      for (var i = 0; i < nodes.length; i++) {
        var a = nodes[i];
        for (var j = i + 1; j < nodes.length; j++) {
          var b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d2 = dx * dx + dy * dy + 0.01;
          var f = REP / d2;
          var d = Math.sqrt(d2);
          var fx = (dx / d) * f, fy = (dy / d) * f;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
      }
      edges.forEach(function (e) {
        var dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
        var d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        var f = (d - LEN) * SPRING;
        var fx = (dx / d) * f, fy = (dy / d) * f;
        e.s.vx += fx; e.s.vy += fy; e.t.vx -= fx; e.t.vy -= fy;
      });
      nodes.forEach(function (n) {
        var an = anchor[n.category];
        var kc = n.type === "topic" ? CLUSTER * 3 : CLUSTER;
        n.vx += (an.x - n.x) * kc + (0 - n.x) * CENTER;
        n.vy += (an.y - n.y) * kc + (0 - n.y) * CENTER;
        if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; return; }
        n.vx *= 0.82; n.vy *= 0.82;
        n.x += n.vx * alpha; n.y += n.vy * alpha;
      });
    }
    function draw() {
      nodes.forEach(function (n) { n._g.setAttribute("transform", "translate(" + n.x + "," + n.y + ")"); });
      edgeEls.forEach(function (ln) {
        var e = ln._e;
        ln.setAttribute("x1", e.s.x); ln.setAttribute("y1", e.s.y);
        ln.setAttribute("x2", e.t.x); ln.setAttribute("y2", e.t.y);
      });
    }
    var raf;
    function loop() {
      tick(); tick(); draw();
      alpha *= 0.99;
      if (alpha > 0.03 || drag) raf = requestAnimationFrame(loop);
    }
    applyView(); loop();

    return {
      focus: function (nodeId) {
        var n = byId[nodeId]; if (!n) return;
        selectedId = nodeId; highlight(nodeId);
        view.k = 1.4; view.x = -n.x * view.k; view.y = -n.y * view.k; applyView();
        if (opts.onSelect) opts.onSelect(n, adj[nodeId]);
      },
      search: function (q) {
        if (!q) return null;
        q = q.toLowerCase();
        var hit = nodes.filter(function (n) { return n.label.toLowerCase().indexOf(q) >= 0; });
        if (hit.length) { this.focus(hit[0].id); return hit[0]; }
        return null;
      },
      destroy: function () { cancelAnimationFrame(raf); window.removeEventListener("resize", sizeView); },
    };
  }

  window.KGraph = { render: render };
})();
