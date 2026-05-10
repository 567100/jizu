const byId = (id) => document.getElementById(id);
const ADDRESS_DISPLAY_WIDTH = 4;

const FUNC_DESC = {
  0: "ADD（A + B + CIN）",
  1: "SUB（A - B，补码减法）",
  2: "AND（按位与）",
  3: "OR（按位或）",
  4: "XOR（按位异或）",
  5: "NOT A（按位取反）",
  6: "PASS A（直通 A）",
  7: "INC A（A + 1）",
};

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

const assembleBtn = byId("assemble-btn");
if (assembleBtn) {
  assembleBtn.addEventListener("click", async () => {
    const resultBox = byId("asm-result");
    try {
      const payload = { source: byId("asm-input").value };
      const data = await fetchJSON("/api/assemble", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const r = data.result;
      const labels = Object.entries(r.labels || {})
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      resultBox.textContent = [
        `机器字长: ${r.word_length} 位`,
        `指令条数: ${r.instruction_count}`,
        `标签数量: ${r.label_count}${labels ? ` (${labels})` : ""}`,
        "",
        "地址  十六进制  二进制               汇编",
        ...r.lines.map((line) => {
          const addr = String(line.address).padStart(ADDRESS_DISPLAY_WIDTH, "0");
          return `${addr}  ${line.hex}   ${line.binary}   ${line.source}`;
        }),
      ].join("\n");
      await Promise.all([refreshHistory(), refreshStats()]);
    } catch (err) {
      showError(resultBox, err.message);
    }
  });
}

const mergeSortBtn = byId("merge-sort-btn");
if (mergeSortBtn) {
  mergeSortBtn.addEventListener("click", async () => {
    const resultBox = byId("merge-result");
    const stepsBox = byId("merge-steps");
    try {
      const raw = byId("merge-input").value || "";
      const items = raw.split(/[,\n，\s]+/).map((s) => s.trim()).filter(Boolean);
      const payload = { items, base: Number(byId("merge-base").value) };
      const data = await fetchJSON("/api/merge-sort", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const r = data.result;
      resultBox.textContent = [
        `输入序列: [${r.input.join(", ")}]`,
        `最终结果: [${r.sorted.join(", ")}]`,
        `步骤总数: ${r.steps.length}`,
      ].join("\n");

      stepsBox.innerHTML = "";
      r.steps.forEach((step, idx) => {
        const line = document.createElement("div");
        line.className = `merge-step step-${step.phase}`;
        if (step.phase === "split") {
          line.textContent = `#${idx + 1} [深度${step.depth}] 拆分 ${JSON.stringify(step.source)} -> ${JSON.stringify(step.left)} | ${JSON.stringify(step.right)}`;
        } else if (step.phase === "merge") {
          line.textContent = `#${idx + 1} [深度${step.depth}] 归并 ${JSON.stringify(step.left)} + ${JSON.stringify(step.right)} => ${JSON.stringify(step.result)}`;
        } else {
          line.textContent = `#${idx + 1} [深度${step.depth}] 基线 ${JSON.stringify(step.segment)}`;
        }
        stepsBox.appendChild(line);
      });
      await Promise.all([refreshHistory(), refreshStats()]);
    } catch (err) {
      showError(resultBox, err.message);
      if (stepsBox) stepsBox.innerHTML = "";
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

let phase = 0;
function makeBitSwitches(containerId, count) {
  const container = byId(containerId);
  if (!container) return;
  container.innerHTML = "";
  for (let i = count - 1; i >= 0; i -= 1) {
    const btn = document.createElement("button");
    btn.className = "toggle-switch";
    btn.dataset.bit = String(i);
    btn.dataset.on = "0";
    btn.textContent = `${i}:0`;
    btn.addEventListener("click", () => {
      const on = btn.dataset.on === "1" ? "0" : "1";
      btn.dataset.on = on;
      btn.classList.toggle("on", on === "1");
      btn.textContent = `${i}:${on}`;
    });
    container.appendChild(btn);
  }
}

function readSwitchValue(containerId) {
  const container = byId(containerId);
  if (!container) return 0;
  let value = 0;
  for (const btn of container.querySelectorAll(".toggle-switch[data-bit]")) {
    const bit = Number(btn.dataset.bit);
    const on = btn.dataset.on === "1" ? 1 : 0;
    value |= (on << bit);
  }
  return value;
}


function updateFuncDesc() {
  const funcValue = readSwitchValue("switch-func");
  const desc = byId("func-desc");
  if (!desc) return;
  desc.textContent = `当前：${String(funcValue).padStart(3, "0")} = ${FUNC_DESC[funcValue]}`;
}


function initSimulator() {
  const simBtn = byId("simulate-btn");
  if (!simBtn) return;

  const widthSelect = byId("sim-width");
  const phaseLabel = byId("phase-label");

  const rebuild = () => {
    const width = Number(widthSelect.value);
    makeBitSwitches("switch-a", width);
    makeBitSwitches("switch-b", width);
    makeBitSwitches("switch-func", 3);

    for (const btn of document.querySelectorAll('#switch-func .toggle-switch')) {
      btn.addEventListener("click", updateFuncDesc);
    }
    updateFuncDesc();

  };
  rebuild();

  widthSelect.addEventListener("change", rebuild);

  const cinBtn = document.querySelector('[data-role="cin"]');
  cinBtn?.addEventListener("click", () => {
    const next = cinBtn.dataset.on === "1" ? "0" : "1";
    cinBtn.dataset.on = next;
    cinBtn.classList.toggle("on", next === "1");
    cinBtn.textContent = `CIN=${next}`;
  });

  for (const pbtn of document.querySelectorAll('[data-role="phase"]')) {
    pbtn.addEventListener("click", () => {
      phase += Number(pbtn.dataset.step || 0);
      if (phase < 0) phase = 0;
      if (phase > 3) phase = 3;
      phaseLabel.textContent = `当前阶段：T${phase}`;
    });
  }

  simBtn.addEventListener("click", async () => {
    const resultBox = byId("sim-result");
    try {
      const width = Number(widthSelect.value);
      const base = Number(byId("sim-base").value);
      const aVal = readSwitchValue("switch-a");
      const bVal = readSwitchValue("switch-b");
      const func = readSwitchValue("switch-func");
      const cin = document.querySelector('[data-role="cin"]')?.dataset.on === "1";

      const payload = {
        width,
        base,
        a: base === 2 ? aVal.toString(2) : base === 16 ? aVal.toString(16) : String(aVal),
        b: base === 2 ? bVal.toString(2) : base === 16 ? bVal.toString(16) : String(bVal),
        func,
        cin,
        phase,
      };

      const data = await fetchJSON("/api/simulate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const r = data.result;
      resultBox.textContent = [
        `操作: ${r.op_name} (F=${String(r.func).padStart(3, "0")})`,
        `时序: T${r.phase} - ${r.phase_desc}`,
        `控制字: ${r.control_word}`,
        `A=${r.a_binary} (${r.a_signed})`,
        `B=${r.b_binary} (${r.b_signed})`,
        `Y=${r.result_binary} (${r.result_signed})`,
        `标志位: C=${r.carry_out}, V=${r.overflow ? 1 : 0}, Z=${r.zero ? 1 : 0}, N=${r.negative ? 1 : 0}`,
      ].join("\n");
      await Promise.all([refreshHistory(), refreshStats()]);
    } catch (err) {
      showError(resultBox, err.message);
    }
  });
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

  const labels = ["转换操作", "算术操作", "运算器仿真", "指令汇编", "归并排序", ...Object.keys(baseCounter).map((b) => `${b}进制输入`)];
  const values = [
    typeCounter.convert || 0,
    typeCounter.arithmetic || 0,
    typeCounter.simulator || 0,
    typeCounter.instruction || 0,
    typeCounter.merge_sort || 0,
    ...Object.values(baseCounter),
  ];

  if (chart) chart.destroy();
  chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "次数",
        data: values,
        backgroundColor: ["#4a67ff", "#00a9b7", "#7f8cff", "#ff9f40", "#7bc96f", "#c792ea", "#f45b69"],
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

initSimulator();
Promise.all([refreshHistory(), refreshStats()]).catch((err) => {
  console.error("初始化失败", err);
});

function initCpuSimPage() {

  const loadAsmBtn = byId("cpu-load-asm");
  if (!loadAsmBtn) return;
  const asmFile = byId("cpu-asm-file");
  const memFile = byId("cpu-mem-file");

  const memInput = byId("cpu-mem-input");
  const asmInput = byId("cpu-asm-input");
  const machineBox = byId("cpu-machine");
  const memoryBox = byId("cpu-memory");
  const sortResultBox = byId("cpu-sort-result");

  const logBox = byId("cpu-exec-log");
  const pipelineBox = byId("cpu-pipeline");
  const regGeneral = byId("cpu-registers-general");
  const regSpecial = byId("cpu-registers-special");

  const regPreset = byId("cpu-reg-preset");

  const state = {
    g: {R0:0,R1:0,R2:0,R3:0,R4:0,R5:0,R6:0,R7:0},
    s: {PC:0,MAR:0,MDR:0,IR:0,SR:0,DR:0,PSW:0},
    mem: [], ins: [], timer: null, ip: 0, pass: 0, idx: 0, done: false, origin: [],
  };

  const render = () => {

    regGeneral.innerHTML = '<h5>通用寄存器组</h5>' + Object.entries(state.g).map(([k,v]) => `<label class="reg-item">${k}<input data-reg="${k}" type="number" value="${v}" /></label>`).join('');
    regSpecial.innerHTML = '<h5>专用寄存器组</h5>' + Object.entries(state.s).map(([k,v]) => `<label class="reg-item">${k}<input data-reg="${k}" type="number" value="${v}" /></label>`).join('');
    const mode = regPreset?.value || "all";
    regGeneral.style.display = mode === "special" ? "none" : "grid";
    regSpecial.style.display = mode === "general" ? "none" : "grid";
    memoryBox.textContent = state.mem.map((v,i)=>`[${String(i).padStart(3,'0')}] = ${v}`).join('\n') || '主存为空';

    sortResultBox.textContent = state.done
      ? `排序完成 ✅\n输入: [${state.origin.join(", ")}]\n输出: [${state.mem.join(", ")}]`
      : `排序进行中...\n当前主存: [${state.mem.join(", ")}]`;

    pipelineBox.innerHTML = ["IF取指","ID译码","OF取数","EX执行","WB回写"].map((x,i)=>`<span class="chip">T${i}: ${x}</span>`).join('');
    for (const input of document.querySelectorAll(".reg-item input")) {
      input.addEventListener("change", () => {
        const k = input.dataset.reg;
        if (k in state.g) state.g[k] = Number(input.value || 0);
        if (k in state.s) state.s[k] = Number(input.value || 0);
      });
    }

  };

  const loadAsm = () => {
    state.ins = asmInput.value.split(/\n+/).map(s=>s.trim()).filter(Boolean);

    machineBox.textContent = ["地址  汇编指令               机器码(hex/bin)", ...state.ins.map((line,i)=>`${String(i).padStart(4,'0')}  ${line.padEnd(18, ' ')}  0x${(0x8000+i).toString(16).toUpperCase()} / ${(0x8000+i).toString(2).padStart(16,'0')}`)].join('\n');
    state.ip = 0; state.s.PC = 0; state.done = false; render();
  };

  const step = () => {
    if (!state.ins.length || state.done) return;

    const line = state.ins[state.ip % state.ins.length];
    const a = state.ip % Math.max(1, state.mem.length);
    state.s.IR = 0x8000 + state.ip; state.s.PC = state.ip; state.s.MAR = a; state.s.MDR = state.mem[a] || 0; state.s.DR = state.s.MDR;
    state.g.R0 = (state.g.R0 + 1) & 0xFFFF;

    if (state.mem.length > 1) {
      const j = state.idx + 1;
      if (j < state.mem.length - state.pass && state.mem[state.idx] > state.mem[j]) {
        [state.mem[state.idx], state.mem[j]] = [state.mem[j], state.mem[state.idx]];
      }
      state.idx += 1;
      if (state.idx >= state.mem.length - 1 - state.pass) {
        state.idx = 0;
        state.pass += 1;
      }
      if (state.pass >= state.mem.length - 1) {
        state.done = true;
        if (state.timer) { clearInterval(state.timer); state.timer = null; }
      }

    }
    const item = document.createElement('div'); item.className = 'merge-step step-merge'; item.textContent = `#${state.ip+1} ${line} | PC=${state.s.PC} MAR=${state.s.MAR} MDR=${state.s.MDR}`;
    logBox.prepend(item);
    state.ip += 1; render();
  };

  loadAsmBtn.addEventListener('click', async () => {
    if (asmFile?.files?.[0]) asmInput.value = await asmFile.files[0].text();
    loadAsm();
  });
  byId('cpu-load-mem')?.addEventListener('click', async () => {

    const text = memFile?.files?.[0] ? await memFile.files[0].text() : (memInput?.value || '');
    state.mem = (text.match(/-?\d+/g) || []).map(Number);
    state.origin = state.mem.slice();
    state.pass = 0; state.idx = 0; state.done = false;

    if (memInput && !memFile?.files?.[0]) memInput.value = state.mem.join(",");
    render();
  });
  regPreset?.addEventListener("change", render);

  byId('cpu-step-btn')?.addEventListener('click', step);
  byId('cpu-auto-btn')?.addEventListener('click', ()=>{ if (state.timer || state.done) return; state.timer = setInterval(step, 500); });
  byId('cpu-stop-btn')?.addEventListener('click', ()=>{ if(state.timer){clearInterval(state.timer); state.timer=null;} });
  byId('cpu-reset-btn')?.addEventListener('click', ()=>{ if(state.timer){clearInterval(state.timer); state.timer=null;} state.g={R0:0,R1:0,R2:0,R3:0,R4:0,R5:0,R6:0,R7:0}; state.s={PC:0,MAR:0,MDR:0,IR:0,SR:0,DR:0,PSW:0}; state.mem=[]; state.ins=[]; state.ip=0; state.pass=0; state.idx=0; state.done=false; state.origin=[]; asmInput.value=''; memInput.value=''; machineBox.textContent=''; logBox.innerHTML=''; render();});
  state.mem = (memInput?.value.match(/-?\d+/g) || []).map(Number);
  loadAsm();

  render();
}

initCpuSimPage();
