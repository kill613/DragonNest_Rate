/* 龙之谷金币查价器 · Web 前端
   渲染逻辑与桌面版 ui.py 一一对应；走势图按 chart.py 的绘图参数用 canvas 复刻。 */

(function () {
  "use strict";

  const C = {
    bg: "#0b1220",
    surface: "#121d31",
    card: "#15223a",
    borderSoft: "#1d2c45",
    text: "#e9f0ff",
    textSoft: "#c3d2ea",
    muted: "#8798b8",
    mutedDark: "#61718f",
    gold: "#f6c453",
    green: "#4ade80",
    red: "#fb7185",
    orange: "#fbbf24",
    tw: "#c084fc",
  };

  const NUM_FONT =
    '"Segoe UI Variable Display","Segoe UI","Bahnschrift","Helvetica Neue",Arial,sans-serif';
  const CJK_FONT =
    '"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif';

  const el = {
    statusText: document.getElementById("statusText"),
    dot: document.getElementById("dot"),
    fetchBtn: document.getElementById("fetchBtn"),
    cnPrice: document.getElementById("cnPrice"),
    twPrice: document.getElementById("twPrice"),
    cnPlatform: document.getElementById("cnPlatform"),
    twPlatform: document.getElementById("twPlatform"),
    bestBadge: document.getElementById("bestBadge"),
    calcCn: document.getElementById("calcCn"),
    calcTw: document.getElementById("calcTw"),
    calcHint: document.getElementById("calcHint"),
    cnDelta: document.getElementById("cnDelta"),
    twDelta: document.getElementById("twDelta"),
    cnMoney: document.getElementById("cnMoney"),
    twMoney: document.getElementById("twMoney"),
    amount: document.getElementById("amount"),
    cards: document.getElementById("cards"),
    conclusionText: document.getElementById("conclusionText"),
    lastUpdate: document.getElementById("lastUpdate"),
    autoChk: document.getElementById("autoChk"),
    autoLabel: document.getElementById("autoLabel"),
    disclaimer: document.getElementById("disclaimer"),
    version: document.getElementById("version"),
  };

  const app = {
    data: null,
    gold: 10000,
    auto: true,
    timer: null,
    amountTimer: null,
    fastPoll: null,
    fetching: false,
  };

  /* ----------------------------------------------------------- 格式化工具 */
  const fmtMoney = (v) =>
    "¥" +
    Number(v).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

  const fmtGold = (v) =>
    Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

  const fmtUnit = (v) => Number(v).toFixed(5);

  function blend(fg, bg, alpha) {
    const parse = (s) => {
      s = s.replace("#", "");
      return [
        parseInt(s.slice(0, 2), 16),
        parseInt(s.slice(2, 4), 16),
        parseInt(s.slice(4, 6), 16),
      ];
    };
    const [fr, fgc, fb] = parse(fg);
    const [br, bgc, bb] = parse(bg);
    const mix = (a, b) => Math.round(a * alpha + b * (1 - alpha));
    return `rgb(${mix(fr, br)},${mix(fgc, bgc)},${mix(fb, bb)})`;
  }

  /* --------------------------------------------------------------- 走势图 */
  function drawTrend(canvas, rawPoints, color, hoverIndex) {
    const width = canvas.clientWidth || canvas.parentNode.clientWidth || 240;
    const height = 62;
    const dpr = window.devicePixelRatio || 1;

    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const left = 18;
    const right = 18;
    const top = 8;
    const bottom = height - 15;
    const plotW = Math.max(1, width - left - right);
    const plotH = Math.max(1, bottom - top);

    // 7 天窗口：今天往前 6 天的 00:00 → 今天 23:59:59
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const start = new Date(today.getTime() - 6 * 86400000);
    const end = new Date(today.getTime() + 86399999);
    const total = Math.max(1, end.getTime() - start.getTime());

    // 横轴日期（每天中午定位，今天高亮）
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    for (let i = 0; i < 7; i++) {
      const day = new Date(start.getTime() + i * 86400000);
      const noon = day.getTime() + 12 * 3600000;
      const x = left + ((noon - start.getTime()) / total) * plotW;
      const isToday = day.toDateString() === today.toDateString();
      ctx.fillStyle = isToday ? C.gold : C.mutedDark;
      ctx.font = `9.5px ${NUM_FONT}`;
      ctx.fillText(
        `${String(day.getMonth() + 1).padStart(2, "0")}.${String(day.getDate()).padStart(2, "0")}`,
        x,
        height - 2
      );
    }

    // 三条水平网格虚线
    ctx.strokeStyle = C.borderSoft;
    ctx.setLineDash([2, 4]);
    ctx.lineWidth = 1;
    [0, 0.5, 1].forEach((fraction) => {
      const y = top + plotH * fraction;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - right, y);
      ctx.stroke();
    });
    ctx.setLineDash([]);

    const points = rawPoints
      .map((p) => ({ t: new Date(p.t).getTime(), p: Number(p.p) }))
      .filter((p) => p.t >= start.getTime() && p.t <= end.getTime() && p.p > 0);

    canvas._coords = [];
    canvas._points = points;

    if (!points.length) {
      ctx.fillStyle = C.muted;
      ctx.font = `11px ${CJK_FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("近7天暂无本地记录", width / 2, top + plotH / 2);
      return;
    }

    const values = points.map((p) => p.p);
    let vmin = Math.min.apply(null, values);
    let vmax = Math.max.apply(null, values);
    if (vmax <= vmin) {
      const pad = Math.max(vmin * 0.004, 0.0001);
      vmin -= pad;
      vmax += pad;
    } else {
      const pad = Math.max((vmax - vmin) * 0.15, 0.0001);
      vmin -= pad;
      vmax += pad;
    }
    const span = vmax - vmin || 1e-9;

    const xOf = (t) => left + ((t - start.getTime()) / total) * plotW;
    const yOf = (v) => top + ((vmax - v) / span) * plotH;
    const coords = points.map((p) => ({ x: xOf(p.t), y: yOf(p.p) }));

    // 曲线下浅色填充
    if (coords.length > 1) {
      ctx.beginPath();
      ctx.moveTo(coords[0].x, coords[0].y);
      coords.forEach((c) => ctx.lineTo(c.x, c.y));
      ctx.lineTo(coords[coords.length - 1].x, bottom);
      ctx.lineTo(coords[0].x, bottom);
      ctx.closePath();
      ctx.fillStyle = blend(color, C.card, 0.16);
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(coords[0].x, coords[0].y);
      coords.forEach((c) => ctx.lineTo(c.x, c.y));
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
    }

    // 数据点
    const showAll = coords.length <= 24;
    coords.forEach((c, index) => {
      canvas._coords.push({ index, x: c.x, y: c.y });
      const isLast = index === coords.length - 1;
      if (!showAll && !isLast) return;
      const radius = isLast ? 3.2 : 2.0;
      ctx.beginPath();
      ctx.arc(c.x, c.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = isLast ? C.gold : C.card;
      ctx.stroke();
    });

    // 悬停：竖虚线 + 大圈 + 右上角时间/价格
    if (hoverIndex != null && points[hoverIndex]) {
      const p = points[hoverIndex];
      const x = xOf(p.t);
      const y = yOf(p.p);
      ctx.strokeStyle = C.muted;
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.strokeStyle = C.gold;
      ctx.lineWidth = 1;
      ctx.stroke();

      const d = new Date(p.t);
      const label =
        `${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")} ` +
        `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}  ` +
        fmtUnit(p.p);
      ctx.font = `bold 9.5px ${NUM_FONT}`;
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      const textWidth = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(11,18,32,.86)";
      ctx.fillRect(width - right - textWidth - 4, 0, textWidth + 4, 13);
      ctx.fillStyle = C.text;
      ctx.fillText(label, width - right, 1);
    }
  }

  function attachTrendEvents(canvas) {
    const move = (event) => {
      if (!canvas._coords || !canvas._coords.length) return;
      const rect = canvas.getBoundingClientRect();
      const x = (event.touches ? event.touches[0].clientX : event.clientX) - rect.left;
      let nearest = null;
      let dist = 999;
      canvas._coords.forEach((c) => {
        const d = Math.abs(x - c.x);
        if (d < dist) {
          dist = d;
          nearest = c.index;
        }
      });
      const index = dist <= 14 ? nearest : null;
      if (index !== canvas._hover) {
        canvas._hover = index;
        drawTrend(canvas, canvas._points, canvas.dataset.color, index);
      }
    };
    const leave = () => {
      if (canvas._hover != null) {
        canvas._hover = null;
        drawTrend(canvas, canvas._points, canvas.dataset.color, null);
      }
    };
    canvas.addEventListener("mousemove", move);
    canvas.addEventListener("mouseleave", leave);
    canvas.addEventListener("touchmove", move, { passive: true });
    canvas.addEventListener("touchend", leave);

    if (window.ResizeObserver) {
      let last = 0;
      const ro = new ResizeObserver(() => {
        const w = canvas.clientWidth;
        if (w && Math.abs(w - last) > 2) {
          last = w;
          drawTrend(canvas, canvas._points || [], canvas.dataset.color, canvas._hover);
        }
      });
      ro.observe(canvas);
    }
  }

  /* ------------------------------------------------------------------ 渲染 */
  function setText(node, text, color) {
    node.textContent = text;
    if (color) node.style.color = color;
  }

  function renderSummary(data) {
    const s = data.summary;

    setText(el.cnPrice, s.cn.price, s.cn.price_color);
    setText(el.cnPlatform, s.cn.platform);
    setText(el.twPrice, s.tw.price, s.tw.price_color);
    setText(el.twPlatform, s.tw.platform);

    setText(el.cnDelta, s.cn.delta, s.cn.delta_color);
    setText(el.twDelta, s.tw.delta, s.tw.delta_color);
    setText(el.cnMoney, s.cn.money);
    setText(el.twMoney, s.tw.money);
  }

  function renderCard(card) {
    const root = document.createElement("div");
    root.className = "card";

    const bar = document.createElement("div");
    bar.className = "card-bar";
    bar.style.background = card.color;
    root.appendChild(bar);

    const body = document.createElement("div");
    body.className = "card-body";

    // 标题行
    const head = document.createElement("div");
    head.className = "card-head";
    const name = document.createElement("span");
    name.className = "card-name";
    name.textContent = card.name;
    head.appendChild(name);

    const tag = document.createElement("span");
    tag.className = "card-tag";
    tag.textContent = card.tag;
    tag.style.color = card.color;
    head.appendChild(tag);

    if (card.is_best) {
      const best = document.createElement("span");
      best.className = "card-best";
      best.textContent = "最高";
      head.appendChild(best);
    }
    body.appendChild(head);

    // 价格
    const priceRow = document.createElement("div");
    priceRow.className = "price-row";
    const price = document.createElement("span");
    price.className = "price";
    price.textContent = card.price;
    price.style.color = card.price_color;
    price.style.fontSize = Math.round(card.price_size * 1.33) + "px";
    price.dataset.role = "price";
    priceRow.appendChild(price);

    if (card.unit) {
      const unit = document.createElement("span");
      unit.className = "unit";
      unit.textContent = card.unit;
      priceRow.appendChild(unit);
    }
    body.appendChild(priceRow);

    const ratio = document.createElement("div");
    ratio.className = "ratio";
    ratio.textContent = card.ratio;
    body.appendChild(ratio);

    // 折算条
    const payout = document.createElement("div");
    payout.className = "payout";
    payout.textContent = card.payout;
    payout.style.color = card.payout_color;
    payout.dataset.role = "payout";
    body.appendChild(payout);

    // 走势
    const trendHead = document.createElement("div");
    trendHead.className = "trend-head";
    const trendTitle = document.createElement("span");
    trendTitle.textContent = "近7天走势";
    const trendRange = document.createElement("span");
    trendRange.className = "trend-range";
    trendRange.textContent = card.trend_range;
    trendRange.style.color = card.trend_range_color;
    trendHead.appendChild(trendTitle);
    trendHead.appendChild(trendRange);
    body.appendChild(trendHead);

    const trendBox = document.createElement("div");
    trendBox.className = "trend";
    const canvas = document.createElement("canvas");
    canvas.dataset.color = card.color;
    canvas.dataset.key = card.key;
    trendBox.appendChild(canvas);
    body.appendChild(trendBox);

    const hr = document.createElement("div");
    hr.className = "hr";
    body.appendChild(hr);

    // 三格
    const stats = document.createElement("div");
    stats.className = "stats";
    card.stats.forEach((s) => {
      const cell = document.createElement("div");
      const label = document.createElement("div");
      label.className = "stat-label";
      label.textContent = s.label;
      const value = document.createElement("div");
      value.className = "stat-value";
      value.textContent = s.value;
      value.title = s.value;
      cell.appendChild(label);
      cell.appendChild(value);
      stats.appendChild(cell);
    });
    body.appendChild(stats);

    // 交易方式
    if (card.tags && card.tags.length) {
      const tags = document.createElement("div");
      tags.className = "tags";
      card.tags.forEach((t) => {
        const item = document.createElement("span");
        item.className = "tag";
        item.textContent = t;
        tags.appendChild(item);
      });
      body.appendChild(tags);
    }

    // 备注
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = card.note;
    note.style.color = card.note_color;
    body.appendChild(note);

    // 其他商家
    if ((card.extra && card.extra.length) || card.extra_more) {
      const extra = document.createElement("div");
      extra.className = "extra";
      const title = document.createElement("div");
      title.className = "extra-title";
      title.textContent = "其他收货商家";
      extra.appendChild(title);
      (card.extra || []).forEach((line) => {
        const row = document.createElement("div");
        row.className = "extra-line";
        row.textContent = line;
        extra.appendChild(row);
      });
      if (card.extra_more) {
        const more = document.createElement("div");
        more.className = "extra-line";
        more.style.color = C.mutedDark;
        more.textContent = `另有 ${card.extra_more} 家未显示`;
        extra.appendChild(more);
      }
      body.appendChild(extra);
    }

    // 弹性空白
    const spacer = document.createElement("div");
    spacer.className = "spacer";
    body.appendChild(spacer);

    // 底部
    const foot = document.createElement("div");
    foot.className = "card-foot";
    const updated = document.createElement("span");
    updated.className = "updated";
    updated.textContent = card.updated;
    updated.style.color = card.updated_color;
    updated.dataset.role = "updated";
    foot.appendChild(updated);

    const links = document.createElement("span");
    links.className = "links";

    const src = document.createElement("a");
    src.className = "src-link";
    src.href = card.source_url;
    src.target = "_blank";
    src.rel = "noopener noreferrer";
    src.textContent = "打开来源 ↗";
    src.style.color = card.color;
    links.appendChild(src);

    const copy = document.createElement("span");
    copy.className = "copy-link";
    copy.textContent = "复制";
    copy.addEventListener("click", () => copyCard(card, copy));
    links.appendChild(copy);

    foot.appendChild(links);
    body.appendChild(foot);

    root.appendChild(body);

    // 走势数据
    requestAnimationFrame(() => {
      const pts = (app.data && app.data.history && app.data.history[card.key]) || [];
      drawTrend(canvas, pts, card.color, null);
      attachTrendEvents(canvas);
    });

    return root;
  }

  function render() {
    const data = app.data;
    if (!data) return;

    // 头部状态
    setText(el.statusText, data.status.text);
    el.dot.style.background = data.status.color;
    app.fetching = !!data.status.fetching;
    el.fetchBtn.disabled = app.fetching;
    el.fetchBtn.textContent = app.fetching ? "获取中…" : "获取最新价格";

    // 总结
    renderSummary(data);

    // 卡片
    el.cards.innerHTML = "";
    data.cards.forEach((card) => el.cards.appendChild(renderCard(card)));

    // 结论
    setText(el.conclusionText, data.conclusion.text, data.conclusion.color);

    // 页脚
    el.lastUpdate.textContent = `上次更新：${data.status.last_update}`;
    el.version.textContent = `v${data.app.version}`;
    el.disclaimer.textContent = data.app.disclaimer;
    el.autoLabel.textContent = `每 ${data.app.auto_seconds} 秒自动刷新`;

    recalc();
  }

  /* --------------------------------------------------------------- 折算计算 */
  function currentGold() {
    const raw = String(el.amount.value || "")
      .replace(/,/g, "")
      .replace(/，/g, "")
      .trim();
    if (!raw) return null;
    const value = Number(raw);
    if (!isFinite(value) || value <= 0) return null;
    return value;
  }

  function recalc() {
    const data = app.data;
    if (!data) return;
    const gold = currentGold();
    app.gold = gold;

    // 两组折算
    const cn = data.summary.cn.price_num;
    const tw = data.summary.tw.price_num;
    if (gold == null) {
      setText(el.calcCn, "≈ —", C.muted);
      setText(el.calcTw, "≈ —", C.muted);
      el.calcHint.textContent = "请输入大于 0 的金币数量";
    } else {
      setText(el.calcCn, cn ? `≈ ${fmtMoney(gold * cn)}` : "≈ —", cn ? C.green : C.muted);
      setText(el.calcTw, tw ? `≈ ${fmtMoney(gold * tw)}` : "≈ —", tw ? C.green : C.muted);
      el.calcHint.textContent = "分别按各组最高单价折算";
    }

    // 每张卡片的折算条
    const payoutNodes = el.cards.querySelectorAll('[data-role="payout"]');
    data.cards.forEach((card, index) => {
      const node = payoutNodes[index];
      if (!node) return;
      if (!card.price_num) {
        node.textContent = "暂无可用报价";
        return;
      }
      if (gold == null) {
        node.textContent = "输入金币数量查看折算";
        return;
      }
      node.textContent = `${fmtGold(gold)} 金 ≈ ${fmtMoney(gold * card.price_num)}`;
    });
  }

  /* ------------------------------------------------------------------ 交互 */
  async function poll() {
    try {
      const resp = await fetch("/api/state", { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      app.data = await resp.json();
      render();
    } catch (err) {
      setText(el.statusText, "与服务端连接失败", C.red);
      el.dot.style.background = C.red;
    }
  }

  async function refresh() {
    if (app.fetching) return;
    app.fetching = true;
    el.fetchBtn.disabled = true;
    el.fetchBtn.textContent = "获取中…";
    setText(el.statusText, "正在连接平台…", C.gold);
    el.dot.style.background = C.gold;

    try {
      await fetch("/api/refresh", { method: "POST", cache: "no-store" });
    } catch (err) {
      /* 交给轮询兜底 */
    }

    // 抓取期间每 2 秒跟进一次，直到服务端结束
    clearInterval(app.fastPoll);
    app.fastPoll = setInterval(async () => {
      await poll();
      if (!app.fetching) {
        clearInterval(app.fastPoll);
        app.fastPoll = null;
      }
    }, 2000);
  }

  function schedule() {
    clearInterval(app.timer);
    if (!app.auto) return;
    app.timer = setInterval(poll, 20000);
  }

  async function copyCard(card, node) {
    if (!card.copy_text) return;
    try {
      await navigator.clipboard.writeText(card.copy_text);
      flash(node, "已复制");
    } catch (err) {
      const area = document.createElement("textarea");
      area.value = card.copy_text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        flash(node, "已复制");
      } catch (e) {
        flash(node, "复制失败");
      }
      document.body.removeChild(area);
    }
  }

  function flash(node, text) {
    const original = node.textContent;
    node.textContent = text;
    node.style.color = C.green;
    setTimeout(() => {
      node.textContent = original;
      node.style.color = "";
    }, 1800);
  }

  /* ------------------------------------------------------------------ 启动 */
  el.fetchBtn.addEventListener("click", refresh);

  el.amount.addEventListener("input", () => {
    clearTimeout(app.amountTimer);
    app.amountTimer = setTimeout(recalc, 220);
  });

  el.amount.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(app.amountTimer);
      recalc();
    }
  });

  el.autoChk.addEventListener("change", () => {
    app.auto = el.autoChk.checked;
    if (app.auto) {
      setText(el.statusText, "已开启自动刷新", C.green);
      poll();
    } else {
      setText(el.statusText, "已关闭自动刷新", C.muted);
    }
    schedule();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "F5" || (event.key === "r" && event.ctrlKey)) {
      event.preventDefault();
      refresh();
    }
  });

  poll();
  schedule();
})();
