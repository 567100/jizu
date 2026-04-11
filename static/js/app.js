const byId = (id) => document.getElementById(id);

function showError(container, message) {
  container.textContent = `❌ 异常: ${message}`;
}

function updateClock() {
  const clock = byId("clock");
  if (!clock) return;
  const now = new Date();
  clock.textContent = now.toLocaleString("zh-CN", { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "未知错误");
  return data;
}

function formatCodes(codes) {
  return Object.entries(codes)
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}

const convertBtn = byId("convert-btn");
if (convertBtn) {
  convertBtn.addEventListener("click", async () => {
    const resultBox = byId("convert-result");
    try {
      const payload = {
        a: byId("a").value,
        b: byId("b").value,
        a_base: Number(byId("a-base").value),
        b_base: Number(byId("b-base").value),
        out_base: Number(byId("out-base").value),
        width: byId("width").value,
      };
      const data = await fetchJSON("/api/convert", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const r = data.result;
      resultBox.textContent = [
        `自动/指定位宽: ${r.width} 位`,
        `A(十进制)=${r.a_decimal}, B(十进制)=${r.b_decimal}`,
        `和=${r.sum}, 差=${r.difference}, 积=${r.product}`,
        "",
        "A 的编码:",
        formatCodes(r.codes_a),
        "",
        "B 的编码:",
        formatCodes(r.codes_b),
      ].join("\n");
      await Promise.all([refreshHistory(), refreshStats()]);
    } catch (err) {
      showError(resultBox, err.message);
    }
  });
}

for (const btn of document.querySelectorAll(".calc-btn")) {
  btn.addEventListener("click", async () => {
    const resultBox = byId("calc-result");
    const overflowBar = byId("overflow-bar");
    const claVisual = byId("cla-visual");
    try {
      const payload = {
        a: byId("calc-a").value,
        b: byId("calc-b").value,
        base: Number(byId("calc-base").value),
        width: Number(byId("calc-width").value),
        op: btn.dataset.op,
      };
      const data = await fetchJSON("/api/calc", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const r = data.result;
      resultBox.textContent = [
        `${r.a} ${r.op} ${r.b} = ${r.math_result}`,
        `位宽: ${r.width}, 合法范围: [${r.range[0]}, ${r.range[1]}]`,
        `溢出: ${r.overflow ? "是" : "否"}`,
        `截断二进制: ${r.wrapped_binary}`,
        `截断有符号值: ${r.wrapped_signed}`,
      ].join("\n");

      overflowBar.classList.toggle("danger", r.overflow);
      overflowBar.style.width = r.overflow ? "100%" : "55%";
      renderCla(r, payload.op, payload.width);

      await Promise.all([refreshHistory(), refreshStats()]);
    } catch (err) {
      showError(resultBox, err.message);
      overflowBar.classList.add("danger");
      overflowBar.style.width = "100%";
      if (claVisual) claVisual.classList.add("hidden");
    }
  });
}

function renderCla(result, op, width) {
  const panel = byId("cla-visual");
  const summary = byId("cla-summary");
  const chain = byId("cla-carry-chain");
  const tableBody = byId("cla-table-body");
  if (!panel || !summary || !chain || !tableBody) return;

  if (op !== "+" || !result.cla) {
    panel.classList.add("hidden");
    return;
  }

  panel.classList.remove("hidden");
  const cla = result.cla;
  summary.innerHTML = [
    `<span><strong>A</strong>=${cla.a_binary}</span>`,
    `<span><strong>B</strong>=${cla.b_binary}</span>`,
    `<span><strong>S</strong>=${cla.sum_binary}</span>`,
    `<span><strong>C${width}</strong>=${cla.carry_out}</span>`,
    `<span><strong>溢出(V)</strong>=C${width - 1}⊕C${width}=${cla.carry_in_msb}⊕${cla.carry_out}=${cla.overflow ? 1 : 0}</span>`,
  ].join("");

  chain.innerHTML = cla.carry_chain
    .map((carry, idx) => `<span class="carry-node">C${idx}=${carry}</span>`)
    .join('<span class="carry-arrow">→</span>');

  tableBody.innerHTML = "";
  for (const row of cla.bit_rows.slice().reverse()) {
    const tr = document.createElement("tr");
    const sBit = row.p ^ cla.carry_chain[row.index];
    tr.innerHTML = `
      <td>${row.index}</td>
      <td>${row.a}</td>
      <td>${row.b}</td>
      <td>${row.p}</td>
      <td>${row.g}</td>
      <td>${cla.carry_chain[row.index]}</td>
      <td>${sBit}</td>
    `;
    tableBody.appendChild(tr);
  }
}

async function refreshHistory() {
  const container = byId("history-list");
  if (!container) return;
  const data = await fetchJSON("/api/history");
  container.innerHTML = "";
  for (const item of data.items) {
    const div = document.createElement("div");
    div.className = "history-item";
    const time = new Date(item.time).toLocaleString("zh-CN", { hour12: false });
    div.innerHTML = `<strong>${item.label}</strong><br/><small>${item.detail}</small><br/><small>${time}</small>`;
    container.appendChild(div);
  }
}

let chart;
async function refreshStats() {
  const canvas = byId("stats-chart");
  if (!canvas) return;
  const data = await fetchJSON("/api/stats");
  const typeCounter = data.stats.type_counter || {};
  const baseCounter = data.stats.base_counter || {};

  const labels = ["转换操作", "算术操作", ...Object.keys(baseCounter).map((b) => `${b}进制输入`)];
  const values = [typeCounter.convert || 0, typeCounter.arithmetic || 0, ...Object.values(baseCounter)];

  if (chart) chart.destroy();
  chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "次数",
        data: values,
        backgroundColor: ["#4a67ff", "#00a9b7", "#ff9f40", "#7bc96f", "#c792ea", "#f45b69"],
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

Promise.all([refreshHistory(), refreshStats()]).catch((err) => {
  console.error("初始化失败", err);
});
