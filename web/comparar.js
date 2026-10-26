/* Aba "Comparar 1º x 2º turno de 2026": o que mudou entre os dois turnos, por estado e por município.
   Usa as funções e o estado da página principal (st, css, geo, tip, ...), que são globais; só define funções aqui. */

let CMP = null;   // { mun, ufs, cands } com os dois turnos lado a lado

async function cmpCarregar() {
  if (CMP) return CMP;
  const [a, b] = await Promise.all([buscar("2026-t1"), buscar("2026-t2")]);
  const pega = o => { const V = o.validos || (o.v1 + o.v2); return { L:o.v1, F:o.v2, V, B:o.brancos, N:o.nulos, C:o.comp || (V + o.brancos + o.nulos), A:o.abst, E:o.eleitores, S:o.st, T:o.ts }; };
  const reg = (x, y, extra) => ({ ...extra, a:pega(x), b:pega(y) });
  const mun = {}, ufs = {};
  for (const [k, m1] of Object.entries(a.mun)) { const m2 = b.mun[k]; if (m2) mun[k] = reg(m1, m2, { k, nm:m1.nm, uf:m1.uf }); }
  for (const [k, u1] of Object.entries(a.ufs)) { const u2 = b.ufs[k]; if (u2) ufs[k] = reg(u1, u2, { k, uf:k, nm:k === "br" ? "Brasil" : k === "zz" ? "Exterior" : k.toUpperCase() }); }
  CMP = { mun, ufs, cands: b.cands || a.cands };
  return CMP;
}

const cN1 = () => (CMP?.cands?.v1 || "Lula").split(" ")[0], cN2 = () => (CMP?.cands?.v2 || "Flávio").split(" ").slice(-1)[0];
const dv = (x, y) => y ? x / y : 0;
const CMP_MET = {
  margem:  { rot:"Mudança na vantagem de Lula (Lula − Flávio)", tipo:"div",
             abs:r => (r.b.L - r.b.F) - (r.a.L - r.a.F), pp:r => 100 * (dv(r.b.L - r.b.F, r.b.V) - dv(r.a.L - r.a.F, r.a.V)) },
  margem2: { rot:"Vantagem no 2º turno (Lula − Flávio)", tipo:"div", abs:r => r.b.L - r.b.F, pp:r => 100 * dv(r.b.L - r.b.F, r.b.V) },
  lula:    { rot:"Votos de Lula: mudança", tipo:"mud", cor:"--cand1", abs:r => r.b.L - r.a.L, pp:r => 100 * (dv(r.b.L, r.b.V) - dv(r.a.L, r.a.V)) },
  flavio:  { rot:"Votos de Flávio: mudança", tipo:"mud", cor:"--cand2", abs:r => r.b.F - r.a.F, pp:r => 100 * (dv(r.b.F, r.b.V) - dv(r.a.F, r.a.V)) },
  abst:    { rot:"Abstenção: mudança", tipo:"mud", cor:"#b8860b", abs:r => r.b.A - r.a.A, pp:r => 100 * (dv(r.b.A, r.b.E) - dv(r.a.A, r.a.E)) },
  brancos: { rot:"Votos brancos: mudança", tipo:"mud", cor:"#6d4fc2", abs:r => r.b.B - r.a.B, pp:r => 100 * (dv(r.b.B, r.b.C) - dv(r.a.B, r.a.C)) },
  nulos:   { rot:"Votos nulos: mudança", tipo:"mud", cor:"#d0489a", abs:r => r.b.N - r.a.N, pp:r => 100 * (dv(r.b.N, r.b.C) - dv(r.a.N, r.a.C)) },
  outros:  { rot:"Votos dos outros candidatos no 1º turno (os que passaram a ser disputados)", tipo:"seq", cor:"#2a7f9e",
             abs:r => r.a.V - r.a.L - r.a.F, pp:r => 100 * dv(r.a.V - r.a.L - r.a.F, r.a.V) },
};
const cmpVal = r => CMP_MET[st.cMet][st.cUnid](r);
const sinal = (v, casas = 0) => (v > 0 ? "+" : v < 0 ? "−" : "") + (casas ? Math.abs(v).toFixed(casas).replace(".", ",") : fmt.format(Math.abs(Math.round(v))));
const fmtVal = v => st.cUnid === "pp" ? sinal(v, 1) + " p.p." : sinal(v);
const compCurto = v => (v < 0 ? "−" : v > 0 && st.cMet !== "outros" ? "+" : "") + (Math.abs(v) >= 1e6 ? (Math.abs(v) / 1e6).toFixed(1).replace(".", ",") + "M" : Math.abs(v) >= 1e3 ? Math.round(Math.abs(v) / 1e3) + "k" : String(Math.round(Math.abs(v))));
const corDeMet = M => !M.cor ? null : M.cor.startsWith("--") ? css(M.cor) : M.cor;
const ZERO = () => escuroAgora() ? "#707070" : "#eeeeee", QUEDA = "#5b6b8a";

function cmpEscala(regs) {   // amplitude para saturar a cor: percentil 85 nos estados e 95 nos municípios (poucos extremos, como SP, não apagam o resto)
  const v = regs.map(r => Math.abs(cmpVal(r))).sort((x, y) => x - y);
  return Math.max(v.length ? v[Math.floor((v.length - 1) * (regs.length > 60 ? 0.95 : 0.85))] : 1, 1e-9);
}
function cmpCor(r, mx) {
  if (!r) return css("--nada");
  const M = CMP_MET[st.cMet], t = Math.max(-1, Math.min(1, cmpVal(r) / mx));
  if (M.tipo === "div") return d3.interpolateRgb(css("--cand1"), css("--cand2"))((1 - t) / 2);   // vermelho (Lula ganhou) → roxo → azul (Flávio ganhou)
  return t >= 0 ? d3.interpolateRgb(ZERO(), corDeMet(M))(t) : d3.interpolateRgb(ZERO(), QUEDA)(-t);
}

/* ---------- blocos de texto ---------- */
function cmpTip(nome, r) {
  if (!r) return `<b>${nome}</b><div class="m">sem dados nos dois turnos</div>`;
  const lin = (rot, x, y, cls = "") => `<tr class="${cls}"><td>${rot}</td><td>${fmt.format(x)}</td><td>${fmt.format(y)}</td><td>${sinal(y - x)}</td></tr>`;
  return `<b>${nome}</b><table class="dtab"><tr><th></th><th>1º turno</th><th>2º turno</th><th>mudou</th></tr>
    ${lin(cN1(), r.a.L, r.b.L, "l")}${lin(cN2(), r.a.F, r.b.F, "f")}${lin("Outros cand.", r.a.V - r.a.L - r.a.F, 0)}${lin("Brancos", r.a.B, r.b.B)}${lin("Nulos", r.a.N, r.b.N)}${lin("Abstenção", r.a.A, r.b.A)}
    ${lin("Vantagem de " + cN1(), r.a.L - r.a.F, r.b.L - r.b.F)}</table>`;
}

function cmpDetalhe() {
  const r = st.pin ? (CMP.mun[st.pin.k] ?? CMP.ufs[st.pin.k]) : st.nivel === "uf" ? CMP.ufs[st.uf] : CMP.ufs.br;
  const nome = st.pin ? (r?.nm ?? st.pin.nome) + (r?.uf && CMP.mun[st.pin.k] ? " – " + r.uf.toUpperCase() : "") : st.nivel === "uf" ? st.uf.toUpperCase() : "Brasil";
  const el = document.getElementById("detalhe");
  if (!r) { el.innerHTML = `<div style="font-size:16px;font-weight:700">${nome}</div><div class="m">sem dados nos dois turnos</div>`; return; }
  const pp = (x, y) => sinal(100 * (y - x), 1) + " p.p.";
  const lin = (rot, x, y, base1, base2, cls = "") => `<tr class="${cls}"><td>${rot}</td><td>${fmt.format(x)}</td><td>${fmt.format(y)}</td><td><b>${sinal(y - x)}</b></td><td>${base1 ? pp(dv(x, base1), dv(y, base2)) : "–"}</td></tr>`;
  const o1 = r.a.V - r.a.L - r.a.F;
  el.innerHTML = `<div style="font-size:16px;font-weight:700;margin-bottom:6px">${nome}</div>
    <table class="dtab"><tr><th></th><th>1º turno</th><th>2º turno</th><th>mudou</th><th>p.p.</th></tr>
      ${lin(cN1(), r.a.L, r.b.L, r.a.V, r.b.V, "l")}${lin(cN2(), r.a.F, r.b.F, r.a.V, r.b.V, "f")}${lin("Outros candidatos", o1, 0, r.a.V, r.b.V)}
      ${lin("Brancos", r.a.B, r.b.B, r.a.C, r.b.C)}${lin("Nulos", r.a.N, r.b.N, r.a.C, r.b.C)}${lin("Abstenção", r.a.A, r.b.A, r.a.E, r.b.E)}
      ${lin("Vantagem de " + cN1(), r.a.L - r.a.F, r.b.L - r.b.F, r.a.V, r.b.V, "dest")}</table>
    <div class="m" style="margin-top:6px">p.p. = pontos percentuais: votos dos candidatos e "outros" sobre os votos válidos; brancos e nulos sobre o comparecimento; abstenção sobre os eleitores.
    "Outros candidatos" são os votos válidos que não eram de ${cN1()} nem de ${cN2()} no 1º turno.${st.pin ? ' · <a href="#" id="unpin">limpar seleção</a>' : "<br>clique numa região para fixar os detalhes"}</div>`;
  const u = document.getElementById("unpin"); if (u) u.onclick = e => { e.preventDefault(); st.pin = null; render(); };
}

const dMargem = r => (r.b.L - r.b.F) - (r.a.L - r.a.F);
function cmpResumo() {
  const br = CMP.ufs.br, m1 = br.a.L - br.a.F, m2 = br.b.L - br.b.F, virada = m2 - m1;
  const ufs = Object.values(CMP.ufs).filter(r => r.k !== "br"), tot = ufs.reduce((a, r) => a + dMargem(r), 0) || 1;
  const ord = [...ufs].sort((a, b) => dMargem(b) - dMargem(a));
  let acum = 0, n50 = 0; for (const r of ord) { acum += dMargem(r); n50++; if (acum >= tot / 2) break; }
  const lado = r => Math.sign(r.a.L - r.a.F) !== Math.sign(r.b.L - r.b.F) && r.a.L !== r.a.F;
  const trocaram = ufs.filter(lado).sort((a, b) => dMargem(b) - dMargem(a));
  const mu = Object.values(CMP.mun).sort((a, b) => dMargem(b) - dMargem(a)).slice(0, 5);
  const top = ord.slice(0, 6).map(r => `<tr><td>${r.nm}</td><td>${sinal(dMargem(r))}</td><td>${(100 * dMargem(r) / tot).toFixed(1).replace(".", ",")}%</td></tr>`).join("");
  document.getElementById("cmpResumo").innerHTML = `<div style="font-size:16px;font-weight:700;margin-bottom:4px">Quem fez a diferença</div>
    <div class="m">No 1º turno ${m1 < 0 ? cN2() + " tinha " + fmt.format(-m1) + " votos a mais que " + cN1() : cN1() + " tinha " + fmt.format(m1) + " votos a mais"}. No 2º, ${m2 >= 0 ? cN1() : cN2()} terminou ${fmt.format(Math.abs(m2))} votos à frente.
    A vantagem de ${cN1()} mudou <b>${sinal(virada)}</b> votos entre os turnos.</div>
    <div class="m" style="margin-top:6px">Votaram <b>${fmt.format(br.a.C)}</b> pessoas no 1º turno e <b>${fmt.format(br.b.C)}</b> no 2º (<b>${sinal(br.b.C - br.a.C)}</b>; a abstenção ${br.b.A < br.a.A ? "caiu" : "subiu"} ${fmt.format(Math.abs(br.b.A - br.a.A))}). A vantagem final de ${cN1()} (${fmt.format(Math.abs(m2))}) equivale a ${(100 * Math.abs(m2) / br.b.C).toFixed(1).replace(".", ",")}% de quem votou no 2º turno.</div>
    <div class="m" style="margin-top:6px"><b>${n50} estados</b> (${ord.slice(0, n50).map(r => r.nm).join(", ")}) respondem por metade dessa mudança.</div>
    <table class="dtab" style="margin-top:6px"><tr><th>Estado</th><th>mudança na vantagem</th><th>% do total</th></tr>${top}</table>
    <div class="m" style="margin-top:6px">${trocaram.length ? `Mudaram de lado: <b>${trocaram.map(r => r.nm).join(", ")}</b>.` : "Nenhum estado mudou de lado."}
    Maiores contribuições entre municípios: ${mu.map(r => `${r.nm}–${r.uf.toUpperCase()} (${sinal(dMargem(r))})`).join("; ")}.</div>`;
}

function cmpTabela() {
  const esc = st.cTab === "mun";
  const regs = esc ? Object.values(CMP.mun) : Object.values(CMP.ufs).filter(r => r.k !== "br");
  const tot = Object.values(CMP.ufs).filter(r => r.k !== "br").reduce((a, r) => a + dMargem(r), 0) || 1;
  const ord = regs.sort((a, b) => dMargem(b) - dMargem(a));
  const lista = esc ? [...ord.slice(0, 25), { sep:true }, ...ord.slice(-10)] : ord;
  d3.select("#tab thead").html("<tr><th>Região</th><th>vantagem 1º</th><th>vantagem 2º</th><th>mudou</th><th>% da mudança</th></tr>");
  d3.select("#tab tbody").selectAll("tr").data(lista).join("tr").classed("sel", d => !d.sep && st.pin?.k === d.k)
    .on("click", (ev, d) => { if (d.sep) return; st.pin = st.pin?.k === d.k ? null : { k:d.k, nome:d.nm }; render(); })
    .html(d => d.sep ? `<td colspan="5" class="m">… maiores mudanças a favor de ${cN2()} abaixo …</td>`
      : `<td>${esc ? d.nm + " – " + d.uf.toUpperCase() : d.nm}</td><td>${sinal(d.a.L - d.a.F)}</td><td>${sinal(d.b.L - d.b.F)}</td><td><b>${sinal(dMargem(d))}</b></td><td>${(100 * dMargem(d) / tot).toFixed(2).replace(".", ",")}%</td>`);
}

/* ---------- mapa ---------- */
async function cmpMapa() {
  const q = "formato=application/vnd.geo+json&qualidade=minima";
  let url, chave, reg, nome;
  if (st.nivel === "estados") { url = `${IBGE}/paises/BR?${q}&intrarregiao=UF`; chave = f => UF_DE_COD[+f.properties.codarea]; reg = f => CMP.ufs[chave(f)]; nome = f => chave(f).toUpperCase(); }
  else if (st.nivel === "municipios") { url = `${IBGE}/paises/BR?${q}&intrarregiao=municipio`; chave = f => f.properties.codarea; reg = f => CMP.mun[chave(f)]; nome = f => { const r = reg(f); return r ? `${r.nm} – ${r.uf.toUpperCase()}` : chave(f); }; }
  else { url = `${IBGE}/estados/${COD[st.uf]}?${q}&intrarregiao=municipio`; chave = f => f.properties.codarea; reg = f => CMP.mun[chave(f)]; nome = f => reg(f)?.nm ?? chave(f); }
  const fc0 = await geo(url), comIlha = st.nivel !== "uf", ext = f => f.properties.ext;
  const c0 = chave, r0 = reg, n0 = nome;
  chave = f => ext(f) ? "zz" : c0(f); reg = f => ext(f) ? CMP.ufs.zz : r0(f); nome = f => ext(f) ? "Exterior (votos no exterior)" : n0(f);
  const fc = { type:"FeatureCollection", features: comIlha ? [...fc0.features, ilhaExterior()] : fc0.features };
  const escopo = st.nivel === "estados" ? Object.values(CMP.ufs).filter(r => r.k !== "br") : Object.values(CMP.mun).filter(r => st.nivel === "municipios" || r.uf === st.uf);
  const mx = cmpEscala(escopo);
  const W = 800, H = 720, box = d3.select("#svgbox"); box.selectAll("*").remove();
  const svg = box.append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const proj = d3.geoMercator().fitSize([W, H], fc), path = d3.geoPath(proj), g = svg.append("g");
  const nz = "cmp:" + st.nivel + ":" + st.uf;
  if (st.zk !== nz) { st.zk = nz; st.zt = d3.zoomIdentity; }
  zoom = d3.zoom().scaleExtent([1, 60]).translateExtent([[-W * 0.1, -H * 0.1], [W * 1.1, H * 1.1]]).on("zoom", ev => { st.zt = ev.transform; g.attr("transform", ev.transform); });
  svg.call(zoom).call(zoom.transform, st.zt).on("dblclick.zoom", null);
  g.selectAll("path").data(fc.features).join("path").attr("d", path).attr("class", f => ext(f) ? "ext" : st.nivel === "estados" ? "uf" : "")
    .attr("fill", f => cmpCor(reg(f), mx)).classed("pin", f => st.pin && st.pin.k === chave(f))
    .on("mousemove", (ev, f) => tip(ev, cmpTip(nome(f), reg(f)))).on("mouseleave", () => tip(null, null))
    .on("click", (ev, f) => {
      if (ext(f)) st.pin = st.pin?.k === "zz" ? null : { k:"zz", nome:"Exterior" };
      else if (st.nivel === "estados") { st.uf = chave(f); st.nivel = "uf"; st.pin = null; }
      else st.pin = { k:chave(f), nome:nome(f) };
      render();
    });
  if (comIlha) { const [x, y] = proj([ILHA.cx, ILHA.cy]); g.append("text").attr("class", "extl").attr("x", x).attr("y", y).attr("text-anchor", "middle").attr("dy", "0.35em").text("Exterior"); }
  cmpLegenda(mx, true);
}

function cmpLegenda(mx, mapa) {
  const M = CMP_MET[st.cMet], un = st.cUnid === "pp" ? "p.p." : "votos", lim = st.cUnid === "pp" ? mx.toFixed(1).replace(".", ",") + " p.p." : fmt.format(Math.round(mx));
  const grad = M.tipo === "div" ? "linear-gradient(90deg,var(--cand1),var(--cand2))" : M.tipo === "seq" ? `linear-gradient(90deg,${ZERO()},${corDeMet(M)})` : `linear-gradient(90deg,${QUEDA},${ZERO()},${corDeMet(M)})`;
  const txt = M.tipo === "div" ? `vermelho = a vantagem de ${cN1()} aumentou · azul = a de ${cN2()} aumentou · roxo = quase não mudou · satura em ±${lim}`
    : M.tipo === "seq" ? `cor mais forte = mais votos de outros candidatos no 1º turno · satura em ${lim}`
    : `cor forte = aumentou · cinza-azulado = diminuiu · satura em ±${lim}`;
  document.getElementById("leg").innerHTML = `<i style="background:${grad}"></i><span><b>${M.rot}</b> (${un}) · ${txt}${mapa && st.nivel !== "uf" ? ' · a ilha "Exterior" é fictícia' : ""} · cinza = sem dados</span>`;
}

/* ---------- barras: estados ou municípios, da maior mudança (esquerda) à menor/queda (direita) ---------- */
function cmpBarras() {
  const mun = st.cEsc === "mun", M = CMP_MET[st.cMet];
  const base = mun ? Object.values(CMP.mun) : Object.values(CMP.ufs).filter(r => r.k !== "br");
  let rows = base.map(r => ({ k:r.k, r, v:cmpVal(r) })).sort((a, b) => b.v - a.v || String(a.k).localeCompare(String(b.k)));
  if (mun && rows.length > 2 * st.cN) rows = [...rows.slice(0, st.cN), { gap:true, k:"__gap", v:0 }, ...rows.slice(-st.cN)];
  const W = 900, H = mun ? 520 : 480, mg = { t:20, r:8, b:mun ? 92 : 34, l:62 }, iw = W - mg.l - mg.r, ih = H - mg.t - mg.b;
  const vs = rows.filter(d => !d.gap).map(d => d.v), y = d3.scaleLinear().domain([Math.min(0, ...vs), Math.max(0, ...vs, 1e-9)]).nice().range([ih, 0]);
  const x = d3.scaleBand(rows.map(d => d.k), [0, iw]).padding(0.14), box = d3.select("#barbox"); box.selectAll("*").remove();
  const svg = box.append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Gráfico de barras da comparação entre os turnos");
  const g = svg.append("g").attr("transform", `translate(${mg.l},${mg.t})`);
  const corPos = M.tipo === "div" ? css("--cand1") : corDeMet(M), corNeg = M.tipo === "div" ? css("--cand2") : QUEDA;
  const fy = st.cUnid === "pp" ? v => sinal(v, 1) : v => sinal(v).replace(/\d[\d.]*/, m => compCurto(+m.replace(/\./g, "")).replace(/^[+−]/, ""));
  g.selectAll(".gr").data(y.ticks(6)).join("g").attr("transform", d => `translate(0,${y(d)})`).each(function (d) {
    d3.select(this).append("line").attr("class", "gr").attr("x2", iw).style("stroke-width", d === 0 ? 1.6 : 1).style("stroke", d === 0 ? css("--mut") : null);
    d3.select(this).append("text").attr("class", "ax").attr("x", -8).attr("text-anchor", "end").attr("dy", "0.32em").text(st.cUnid === "pp" ? sinal(d, 1) : compCurto(d));
  });
  const rotulos = rows.length <= 32;
  const b = g.selectAll("g.b").data(rows.filter(d => !d.gap), d => d.k).join("g").attr("class", "b").attr("transform", d => `translate(${x(d.k)},0)`);
  b.append("rect").attr("x", 0).attr("width", x.bandwidth()).attr("y", d => d.v >= 0 ? y(d.v) : y(0)).attr("height", d => Math.abs(y(d.v) - y(0)))
    .attr("fill", d => d.v >= 0 ? corPos : corNeg).classed("sel", d => st.pin?.k === d.k)
    .on("mousemove", (ev, d) => tip(ev, cmpTip(mun ? `${d.r.nm} – ${d.r.uf.toUpperCase()}` : d.r.nm, d.r) + `<div class="m"><b>${fmtVal(d.v)}</b></div>`)).on("mouseleave", () => tip(null, null))
    .on("click", (ev, d) => { st.pin = st.pin?.k === d.k ? null : { k:d.k, nome:d.r.nm }; render(); });
  if (rotulos) b.append("text").attr("class", "vl").attr("text-anchor", "middle").attr("x", x.bandwidth() / 2).attr("y", d => (d.v >= 0 ? y(d.v) - 4 : y(d.v) + 11)).text(d => st.cUnid === "pp" ? sinal(d.v, 1) : compCurto(d.v));
  const nomeCurto = d => mun ? (d.r.nm.length > 14 ? d.r.nm.slice(0, 13) + "…" : d.r.nm) + " " + d.r.uf.toUpperCase() : (d.k === "zz" ? "EXT" : d.k.toUpperCase());
  const xl = b.append("text").attr("class", "xl").text(nomeCurto);
  if (mun) xl.attr("transform", `translate(${x.bandwidth() / 2},${ih + 8}) rotate(60)`).attr("text-anchor", "start").style("font-size", "9px");
  else xl.attr("x", x.bandwidth() / 2).attr("y", ih + 18).attr("text-anchor", "middle");
  if (rows.some(d => d.gap)) g.append("text").attr("class", "ax").attr("x", x("__gap") ?? iw / 2).attr("y", y(0) - 6).attr("text-anchor", "middle").text("…");
  cmpLegenda(Math.max(...vs.map(Math.abs)), false);
  document.getElementById("leg").insertAdjacentHTML("beforeend", `<span>· ${mun ? `os ${st.cN} municípios com maior aumento (esquerda) e os ${st.cN} com maior queda (direita)` : "estados do maior aumento (esquerda) ao maior queda (direita)"} · clique numa barra para ver os detalhes</span>`);
}

/* ---------- orquestração ---------- */
async function renderComparar() {
  try { await cmpCarregar(); } catch { document.getElementById("meta").textContent = "não consegui carregar os dois turnos de 2026"; return; }
  tip(null, null);
  const barras = st.vista === "barras", M = st.cMet;
  seg("segCVista", [["mapa", "Mapa"], ["barras", "Barras"]], "vista");
  if (barras) seg("segCEsc", [["uf", "Por estado"], ["mun", "Por município"]], "cEsc");
  else seg("segCEsc", [["estados", "Estados"], ["municipios", "Municípios do Brasil"]], "nivel");
  if (!barras && st.nivel === "uf") document.querySelectorAll("#segCEsc button").forEach(b => b.className = "");
  seg("segCMet", [["margem", "Mudança da vantagem"], ["margem2", "Vantagem no 2º turno"], ["lula", cN1()], ["flavio", cN2()], ["abst", "Abstenção"], ["brancos", "Brancos"], ["nulos", "Nulos"], ["outros", "Outros candidatos"]], "cMet");
  seg("segCUnid", [["abs", "Votos"], ["pp", "Pontos percentuais"]], "cUnid");
  seg("segCN", [[15, "15"], [25, "25"], [50, "50"]], "cN");
  seg("segCTab", [["uf", "Estados"], ["mun", "Municípios"]], "cTab");
  document.getElementById("segCN").hidden = !(barras && st.cEsc === "mun");
  document.getElementById("segCUnid").hidden = M === "outros" && false;
  document.getElementById("voltar").hidden = barras || st.nivel !== "uf";
  document.getElementById("titulo").textContent = barras ? "" : st.nivel === "uf" ? st.uf.toUpperCase() + " por município" : "";
  document.getElementById("svgwrap").hidden = barras; document.getElementById("barbox").hidden = !barras;
  document.getElementById("meta").textContent = "2026 · comparação entre o 1º e o 2º turno (resultados finais)";
  document.getElementById("fonte").textContent = "TSE — resultados finais do 1º e do 2º turno de 2026";
  cmpResumo(); cmpDetalhe(); cmpTabela();
  if (barras) cmpBarras(); else await cmpMapa();
}
