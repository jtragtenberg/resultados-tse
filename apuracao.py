#!/usr/bin/env python3
"""Coletor + servidor local da apuração do 2º turno (Lula x Flávio Bolsonaro).

Uso:  python3 apuracao.py [--eleicao 6258] [--intervalo 60] [--porta 8000]
      (para testar com dados reais do 1º turno: --eleicao 6257)
      python3 apuracao.py --teste            # um ciclo curto: mostra se está baixando dados, sem subir servidor
      python3 apuracao.py --api --bind 127.0.0.1 --intervalo 30   # no VPS: só /latest.json, /status e /health, com CORS

Endpoints (no modo normal e no --api): /status (JSON com o andamento da coleta), /health.

A cada ciclo baixa os JSON do TSE (um por UF e um por município, com ETag para só
reprocessar o que mudou), grava o histórico em SQLite (dados/apuracao.db) e publica
dados/latest.json, que web/index.html lê para desenhar o mapa.
"""
import argparse, gzip, json, os, sqlite3, sys, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
RAIZ = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(RAIZ, "dados")
LULA, FLAVIO = "13", "22"
CANDS = {"v1": "Lula", "v2": "Flávio Bolsonaro"}
UA = {"User-Agent": "Mozilla/5.0 (apuracao-local)", "Accept-Encoding": "gzip"}

etags = {}      # url -> etag
cache = {}      # url -> último JSON parseado (para 304)
trava = threading.Lock()
STATUS = {"iniciado": time.time(), "eleicao": None, "ciclos": 0, "ultimo_ciclo": None, "total": {"requisicoes": 0, "baixados": 0, "bytes": 0, "sem_mudanca": 0, "indisponiveis": 0, "erros": 0, "limitado": 0},
          "ultimo_erro": None, "brasil": None, "latest_bytes": 0, "latest_gerado": None, "latest_epoch": None}
CONT = {"requisicoes": 0, "baixados": 0, "bytes": 0, "sem_mudanca": 0, "indisponiveis": 0, "erros": 0, "limitado": 0}   # contadores do ciclo em andamento
LATEST = {"raw": b"", "gz": b""}
CICLO_N = 0


class Limitado(Exception):
    """O TSE respondeu 429 (Too Many Requests)."""


class Limitador:
    """Controla a taxa de requisições ao TSE. Ao receber 429: pausa todas as conexões e corta a taxa pela metade;
    sem 429 por 30 s, a taxa sobe de novo aos poucos (+25%), até o máximo."""
    def __init__(self, rps):
        self.max = self.rps = float(rps); self.proximo = 0.0; self.pausa_ate = 0.0; self.limpo_desde = time.time(); self.lock = threading.Lock()

    def esperar(self):
        with self.lock:
            agora = time.time()
            quando = max(self.proximo, self.pausa_ate, agora)
            self.proximo = quando + 1.0 / self.rps
        if quando > agora:
            time.sleep(quando - agora)

    def bateu(self, retry_after=None):
        with self.lock:
            agora = time.time()
            if agora >= self.pausa_ate:          # várias conexões levam 429 juntas: corta a taxa uma vez só por pausa
                self.rps = max(3.0, self.rps / 2)
                self.pausa_ate = agora + (retry_after or 20)
            self.limpo_desde = agora

    def ok(self):
        with self.lock:
            if self.rps < self.max and time.time() - self.limpo_desde > 30:
                self.rps = min(self.max, self.rps * 1.25 + 1); self.limpo_desde = time.time()


LIM = Limitador(30)
ULT = {}   # url -> quando foi consultada pela última vez (para priorizar os municípios mais "velhos" e maiores)


def conta(chave, n=1):
    with trava:
        CONT[chave] += n


def baixar(url, tentativa=1):
    """GET condicional. Devolve (json|None, mudou). Falhas de rede transitórias (reset de conexão, timeout) ganham 1 nova tentativa."""
    req = urllib.request.Request(url, headers=dict(UA, **({"If-None-Match": etags[url]} if url in etags else {})))
    LIM.esperar()
    conta("requisicoes")
    ULT[url] = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            LIM.ok()
            corpo = r.read()
            conta("bytes", len(corpo))
            if r.headers.get("Content-Encoding") == "gzip":
                corpo = gzip.decompress(corpo)
            etags[url] = r.headers.get("ETag", "")
            cache[url] = json.loads(corpo)
            conta("baixados")
            return cache[url], True
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try: espera = int(e.headers.get("Retry-After", "0")) or None
            except ValueError: espera = None
            LIM.bateu(espera); conta("limitado")
            raise Limitado(f"429 em {url.rsplit('/', 1)[-1]}")
        if e.code == 304:
            LIM.ok()
            conta("sem_mudanca")
            return cache.get(url), False
        if e.code in (403, 404):
            conta("indisponiveis")
            return None, False
        conta("erros")
        raise
    except Limitado:
        raise
    except Exception:
        if tentativa < 2:
            time.sleep(1.5)
            return baixar(url, tentativa + 1)
        conta("erros")
        raise


def resumo(d, cargo="1"):
    """Reduz o arquivo -u.json do TSE ao que o mapa precisa."""
    votos = {}
    for c in d["carg"]:
        if c["cd"] != cargo:
            continue
        for a in c["agr"]:
            for p in a["par"]:
                for cand in p["cand"]:
                    votos[cand["n"]] = int(cand.get("vap") or 0)
    s, e, v = d["s"], d["e"], d["v"]
    return {
        "ts": int(s["ts"]), "st": int(s["st"]),          # seções totais / totalizadas
        "eleitores": int(e["te"]),
        "v1": votos.get(LULA, 0), "v2": votos.get(FLAVIO, 0),
        "validos": int(v["vv"]), "total": int(v["tv"]), "comp": int(e["c"]), "abst": int(e["a"]), "brancos": int(v["vb"]), "nulos": int(v["tvn"]),
        "dg": d["dg"], "hg": d["hg"], "tf": d["tf"] == "s",
    }


def ciclo(eleicao, db, estado, publicar=True, saida=None, limite=None, completo=False, orcamento=None):
    """Um ciclo de coleta. Em modo normal consulta o Brasil e as UFs (28 arquivos) e só uma parte dos municípios:
    pula os já totalizados, pula UFs cujo total já bate com a soma dos municípios em cache e prioriza os maiores e
    os há mais tempo sem consulta, respeitando um orçamento de requisições. `completo=True` baixa tudo (1ª vez, arquivar)."""
    global CICLO_N
    CICLO_N += 1
    inicio = time.time()
    with trava:
        for k in CONT: CONT[k] = 0
    e6 = eleicao.zfill(6)
    cfg, _ = baixar(f"{BASE}/{eleicao}/config/mun-e{e6}-cm.json")
    if not cfg:
        print("configuração ainda indisponível (o TSE ainda não publicou os arquivos desta eleição?)", flush=True); return
    fixas = [("br", None, None, None, f"{BASE}/{eleicao}/dados/br/br-c0001-e{e6}-u.json")]   # (uf, cod_tse, ibge, nome, url)
    por_uf = {}
    for abr in cfg["abr"]:
        uf = abr["cd"]
        fixas.append((uf, None, None, None, f"{BASE}/{eleicao}/dados/{uf}/{uf}-c0001-e{e6}-u.json"))
        if uf != "zz":
            por_uf[uf] = [(uf, m["cd"], m["cdi"], m["nm"], f"{BASE}/{eleicao}/dados/{uf}/{uf}{m['cd']}-c0001-e{e6}-u.json") for m in abr["mu"]]

    def trabalho(t):
        try:
            d, mudou = baixar(t[4])
            return t, d, mudou
        except Limitado:
            return t, None, False
        except Exception as ex:
            STATUS["ultimo_erro"] = f"{time.strftime('%H:%M:%S')} {t[4].rsplit('/', 1)[-1]}: {type(ex).__name__} {ex}"
            return t, None, False

    mudancas, agora = 0, time.strftime("%Y-%m-%d %H:%M:%S")
    consultados = 0

    def aplicar(lote):
        nonlocal mudancas, consultados
        consultados += len(lote)
        with ThreadPoolExecutor(8) as ex:
            for (uf, cod, ibge, nome, url), d, mudou in ex.map(trabalho, lote):
                if d is None:
                    continue
                r = resumo(d)
                if cod is None:
                    estado["ufs"][uf] = r
                else:
                    r["uf"], r["nm"] = uf, nome
                    estado["mun"][ibge] = r
                if mudou:
                    mudancas += 1
                    db.execute("INSERT INTO snap VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (agora, uf, ibge or "", r["dg"] + " " + r["hg"], r["ts"], r["st"],
                                r["v1"], r["v2"], r["brancos"], r["nulos"], r["validos"]))

    aplicar(fixas)                                   # 1) Brasil + UFs, sempre
    todos = [t for lista in por_uf.values() for t in lista]
    if limite:                                       # modo --teste
        sel = todos[:limite]
    elif completo or not estado["mun"]:
        sel = todos                                  # 1ª passada: precisa de todos
    else:
        sel, agora_t = [], time.time()
        for uf, lista in por_uf.items():
            u = estado["ufs"].get(uf)
            ms = [estado["mun"].get(t[2]) for t in lista]
            if CICLO_N % 10 and u and all(ms) and sum(m["st"] for m in ms) == u["st"] and sum(m["v1"] + m["v2"] for m in ms) == u["v1"] + u["v2"]:
                continue                             # o total da UF bate com a soma dos municípios em cache: nada mudou aqui
            for t, m in zip(lista, ms):
                if m and m["tf"] and CICLO_N % 10:
                    continue                         # município já totalizado: só reconsulta de 10 em 10 ciclos
                peso = 1 + (m["eleitores"] / 100000 if m else 0)   # cidades grandes valem mais atualização
                sel.append(((agora_t - ULT.get(t[4], 0)) * peso if m else 1e12, t))   # nunca obtido (falhou antes): vai primeiro
        sel.sort(key=lambda x: -x[0])
        sel = [t for _, t in sel[:orcamento or int(LIM.max * 30)]]
    aplicar(sel)                                     # 2) municípios escolhidos
    tarefas = fixas + sel
    db.commit()
    duracao = time.time() - inicio
    with trava:
        STATUS["ciclos"] += 1
        STATUS["ultimo_ciclo"] = dict(CONT, duracao_s=round(duracao, 1), em=agora, arquivos_consultados=len(tarefas))
        for k, v in CONT.items(): STATUS["total"][k] += v
    STATUS["eleicao"] = eleicao
    if estado["ufs"].get("br"):
        b = estado["ufs"]["br"]
        STATUS["brasil"] = {"secoes_apuradas": b["st"], "secoes_total": b["ts"], "pct_apuradas": round(b["st"] / b["ts"], 4) if b["ts"] else 0,
                            "v1": b["v1"], "v2": b["v2"], "arquivo_tse_gerado": f'{b["dg"]} {b["hg"]}'}
    if not publicar:
        return
    estado["gerado"] = agora
    estado["ts_epoch"] = round(time.time())
    estado["eleicao"] = eleicao
    estado["cands"] = CANDS
    destino = saida or os.path.join(DADOS, "latest.json")
    tmp = destino + ".tmp"
    bruto = json.dumps(estado, separators=(",", ":")).encode()
    with open(tmp, "wb") as f:
        f.write(bruto)
    os.replace(tmp, destino)
    LATEST["raw"], LATEST["gz"] = bruto, gzip.compress(bruto, 6)   # servido da memória pelo modo --api
    STATUS.update(latest_bytes=len(bruto), latest_gz_bytes=len(LATEST["gz"]), latest_gerado=agora, latest_epoch=estado["ts_epoch"])
    st = sum(u["st"] for k, u in estado["ufs"].items() if k != "br")
    print(f"{agora}  consultados {len(tarefas)}, novos {mudancas}, sem mudança {CONT['sem_mudanca']}, erros {CONT['erros']}, 429 {CONT['limitado']} ({LIM.rps:.0f} req/s)  "
          f"urnas totalizadas (soma UFs): {st}  [{duracao:.1f}s, {CONT['bytes']/1e6:.1f} MB]", flush=True)


def coletor(eleicao, intervalo):
    os.makedirs(DADOS, exist_ok=True)
    db = sqlite3.connect(os.path.join(DADOS, "apuracao.db"), check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS snap (coletado TEXT, uf TEXT, ibge TEXT, gerado_tse TEXT,
                  secoes_total INT, secoes_apur INT, v1 INT, v2 INT, brancos INT, nulos INT, validos INT)""")
    estado = {"ufs": {}, "mun": {}}
    while True:
        try:
            ciclo(eleicao, db, estado, orcamento=max(100, int(LIM.rps * intervalo)))
        except Exception as ex:
            print("erro no ciclo:", ex)
        time.sleep(intervalo)


def simulador(intervalo):
    """Modo --simular: usa os totais finais reais do 1º turno (6257) como base e faz cada município
    avançar numa velocidade aleatória própria, com ruído no voto, até 100%."""
    import random
    os.makedirs(DADOS, exist_ok=True)
    base = {"ufs": {}, "mun": {}}
    print("baixando base real do 1º turno (6257)...", flush=True)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE snap (a,b,c,d,e,f,g,h,i,j,k)")
    ciclo("6257", db, base, publicar=False, completo=True)
    ritmo = {k: random.uniform(0.02, 0.18) for k in base["mun"]}   # fração apurada por ciclo
    prog = {k: 0.0 for k in base["mun"]}
    ruido = {k: random.gauss(0, 0.06) for k in base["mun"]}         # viés de quem apura primeiro
    n = 0
    while True:
        n += 1
        mun, soma = {}, {}
        for k, m in base["mun"].items():
            if n > 1 and random.random() < 0.8:                      # nem todo município avança a cada ciclo
                prog[k] = min(1.0, prog[k] + ritmo[k] * random.uniform(0.3, 1.7))
            p = prog[k]
            st = round(m["ts"] * p)
            f = st / m["ts"] if m["ts"] else 0
            tot = m["v1"] + m["v2"]
            share = m["v1"] / tot if tot else 0.5
            if f < 1:
                share = min(0.99, max(0.01, share + ruido[k] * (1 - f)))
            nom = round(tot * f)
            r = dict(m, st=st, v1=round(nom * share), v2=nom - round(nom * share),
                     validos=round(m["validos"] * f), total=round(m["total"] * f),
                     comp=round(m["comp"] * f), abst=round(m["abst"] * f), brancos=round(m["brancos"] * f), nulos=round(m["nulos"] * f),
                     tf=st == m["ts"], dg=time.strftime("%d/%m/%Y"), hg=time.strftime("%H:%M:%S"))
            mun[k] = r
            for chave in (m["uf"], "br"):
                a = soma.setdefault(chave, {"ts": 0, "st": 0, "eleitores": 0, "v1": 0, "v2": 0, "validos": 0,
                                            "brancos": 0, "nulos": 0, "total": 0, "comp": 0, "abst": 0})
                for c in a:
                    a[c] += r[c] if c != "eleitores" else m["eleitores"]
        ufs = {}
        for k, a in soma.items():
            ufs[k] = dict(a, dg=time.strftime("%d/%m/%Y"), hg=time.strftime("%H:%M:%S"), tf=a["st"] == a["ts"])
        if "zz" in base["ufs"]:
            ufs["zz"] = dict(base["ufs"]["zz"], st=0, v1=0, v2=0, tf=False)
        agora = time.strftime("%Y-%m-%d %H:%M:%S")
        estado = {"ufs": ufs, "mun": mun, "gerado": agora, "eleicao": "SIMULAÇÃO (dados fictícios)", "cands": CANDS}
        tmp = os.path.join(DADOS, "latest.json.tmp")
        with open(tmp, "w") as f:
            json.dump(estado, f, separators=(",", ":"))
        os.replace(tmp, os.path.join(DADOS, "latest.json"))
        b = ufs["br"]
        print(f"{agora}  simulado: {b['st']}/{b['ts']} urnas ({b['st']/b['ts']:.1%})", flush=True)
        if b["st"] == b["ts"]:
            break
        time.sleep(intervalo)


def status_json():
    st = dict(STATUS)
    st["agora"] = round(time.time())
    st["segundos_desde_ultimo_dado"] = round(time.time() - st["latest_epoch"]) if st.get("latest_epoch") else None
    st["rps_atual"] = round(LIM.rps, 1); st["rps_max"] = LIM.max
    st["rodando_ha_s"] = round(time.time() - st["iniciado"])
    return json.dumps(st, ensure_ascii=False).encode()


def latest_bytes():
    if LATEST["raw"]:
        return LATEST["raw"], LATEST["gz"]
    try:
        with open(os.path.join(DADOS, "latest.json"), "rb") as f:
            bruto = f.read()
        return bruto, gzip.compress(bruto, 6)
    except OSError:
        return None, None


class Handler(SimpleHTTPRequestHandler):
    """Modo normal: serve o projeto (web/, dados/) e também /status e /health."""
    def __init__(self, *a, **k):
        super().__init__(*a, directory=RAIZ, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho in ("/status", "/health"):
            corpo = status_json() if caminho == "/status" else b'{"ok":true}'
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo))); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
            return self.wfile.write(corpo)
        super().do_GET()

    def log_message(self, *a):
        pass


class ApiHandler(BaseHTTPRequestHandler):
    """Modo --api (VPS): só /latest.json, /status e /health, com CORS aberto e gzip, para qualquer site ler."""
    def _enviar(self, codigo, corpo, tipo="application/json; charset=utf-8", extra=None, cabeca=False):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if not cabeca: self.wfile.write(corpo)

    def do_OPTIONS(self):
        self._enviar(204, b"")

    def do_HEAD(self):
        self.do_GET(cabeca=True)

    def do_GET(self, cabeca=False):
        caminho = self.path.split("?")[0].rstrip("/") or "/"
        if caminho == "/latest.json":
            bruto, gz = latest_bytes()
            if bruto is None:
                return self._enviar(503, b'{"erro":"ainda sem dados: o coletor nao terminou o primeiro ciclo"}', cabeca=cabeca)
            usa_gz = "gzip" in self.headers.get("Accept-Encoding", "")
            return self._enviar(200, gz if usa_gz else bruto, extra={"Cache-Control": "public, max-age=15", "Vary": "Accept-Encoding",
                                                                     **({"Content-Encoding": "gzip"} if usa_gz else {})}, cabeca=cabeca)
        if caminho == "/status":
            return self._enviar(200, status_json(), extra={"Cache-Control": "no-store"}, cabeca=cabeca)
        if caminho in ("/health", "/"):
            return self._enviar(200, b'{"ok":true}', extra={"Cache-Control": "no-store"}, cabeca=cabeca)
        self._enviar(404, b'{"erro":"nao encontrado"}', cabeca=cabeca)

    def log_message(self, *a):
        pass


def teste(eleicao):
    """--teste: baixa Brasil + UFs + 25 municípios, depois repete para provar que o ETag/304 funciona."""
    print(f"Teste de coleta — eleição {eleicao} ({BASE})", flush=True)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE snap (a,b,c,d,e,f,g,h,i,j,k)")
    estado = {"ufs": {}, "mun": {}}
    for rodada in (1, 2):
        ciclo(eleicao, db, estado, publicar=False, limite=25)
        u = STATUS["ultimo_ciclo"]
        print(f"  rodada {rodada}: {u['arquivos_consultados']} arquivos em {u['duracao_s']}s — baixados {u['baixados']} "
              f"({u['bytes']/1e3:.0f} KB), sem mudança (304) {u['sem_mudanca']}, indisponíveis {u['indisponiveis']}, erros {u['erros']}, limitado pelo TSE (429) {u['limitado']}")
    b = STATUS["brasil"]
    if b:
        n = lambda x: f"{x:,}".replace(",", ".")
        pct = str(round(b["pct_apuradas"] * 100, 1)).replace(".", ",")
        print(f"  Brasil: {n(b['secoes_apuradas'])} de {n(b['secoes_total'])} seções apuradas ({pct}%) · "
              f"{CANDS['v1']} {n(b['v1'])} x {n(b['v2'])} {CANDS['v2']} · arquivo do TSE gerado em {b['arquivo_tse_gerado']}")
        if b["secoes_apuradas"] == 0:
            print("  (0 seções apuradas é esperado antes do fim da votação: os arquivos já existem, mas ainda sem votos)")
    if STATUS["total"]["limitado"]:
        print("  ATENÇÃO: o TSE respondeu 429 (Too Many Requests): este IP está sendo limitado. Espere alguns minutos e tente de novo.")
    ok = STATUS["total"]["erros"] == 0 and STATUS["total"]["limitado"] == 0 and STATUS["total"]["baixados"] > 0
    print("RESULTADO:", "OK — o TSE está respondendo e o coletor está baixando." if ok else
          "PROBLEMA — nenhum arquivo baixado ou houve erros" + (f" (último erro: {STATUS['ultimo_erro']})" if STATUS["ultimo_erro"] else "")
          + ". Se for 404, o TSE ainda não publicou esta eleição.")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eleicao", default="6258")
    ap.add_argument("--intervalo", type=int, default=60)
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--bind", default="127.0.0.1", help="endereço de escuta (no VPS atrás de Caddy/túnel: 127.0.0.1)")
    ap.add_argument("--rps", type=float, default=30, help="máximo de requisições por segundo ao TSE (cai sozinho se o TSE responder 429)")
    ap.add_argument("--api", action="store_true", help="só /latest.json, /status e /health com CORS aberto (para o VPS)")
    ap.add_argument("--teste", action="store_true", help="um ciclo curto de coleta e sai, dizendo se está funcionando")
    ap.add_argument("--arquivar", metavar="ID", help="baixa a eleição uma vez e grava dados/hist/ID.json (ex.: --eleicao 6257 --arquivar 2026-t1)")
    ap.add_argument("--simular", action="store_true", help="dados fictícios: apuração aleatória por município")
    a = ap.parse_args()
    LIM.max = LIM.rps = a.rps
    if a.teste:
        raise SystemExit(teste(a.eleicao))
    if a.arquivar:
        os.makedirs(os.path.join(DADOS, "hist"), exist_ok=True)
        _db = sqlite3.connect(":memory:"); _db.execute("CREATE TABLE snap (a,b,c,d,e,f,g,h,i,j,k)")
        ciclo(a.eleicao, _db, {"ufs": {}, "mun": {}}, saida=os.path.join(DADOS, "hist", a.arquivar + ".json"), completo=True)
        raise SystemExit(0)
    if a.simular:
        threading.Thread(target=simulador, args=(min(a.intervalo, 5),), daemon=True).start()
    else:
        threading.Thread(target=coletor, args=(a.eleicao, a.intervalo), daemon=True).start()
    if a.api:
        print(f"API em http://{a.bind}:{a.porta}/latest.json  (/status, /health)", flush=True)
        ThreadingHTTPServer((a.bind, a.porta), ApiHandler).serve_forever()
    print(f"abra http://{a.bind if a.bind != '0.0.0.0' else 'localhost'}:{a.porta}/web/", flush=True)
    ThreadingHTTPServer((a.bind, a.porta), Handler).serve_forever()
