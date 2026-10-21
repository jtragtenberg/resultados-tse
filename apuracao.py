#!/usr/bin/env python3
"""Coletor + servidor local da apuração do 2º turno (Lula x Flávio Bolsonaro).

Uso:  python3 apuracao.py [--eleicao 6258] [--intervalo 60] [--porta 8000]
      (para testar com dados reais do 1º turno: --eleicao 6257)

A cada ciclo baixa os JSON do TSE (um por UF e um por município, com ETag para só
reprocessar o que mudou), grava o histórico em SQLite (dados/apuracao.db) e publica
dados/latest.json, que web/index.html lê para desenhar o mapa.
"""
import argparse, json, os, sqlite3, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
RAIZ = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(RAIZ, "dados")
LULA, FLAVIO = "13", "22"
CANDS = {"v1": "Lula", "v2": "Flávio Bolsonaro"}
UA = {"User-Agent": "Mozilla/5.0 (apuracao-local)"}

etags = {}      # url -> etag
cache = {}      # url -> último JSON parseado (para 304)


def baixar(url):
    """GET condicional. Devolve (json|None, mudou)."""
    req = urllib.request.Request(url, headers=dict(UA, **({"If-None-Match": etags[url]} if url in etags else {})))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            etags[url] = r.headers.get("ETag", "")
            cache[url] = json.loads(r.read())
            return cache[url], True
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return cache.get(url), False
        if e.code in (403, 404):
            return None, False
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


def ciclo(eleicao, db, estado, publicar=True, saida=None):
    e6 = eleicao.zfill(6)
    cfg, _ = baixar(f"{BASE}/{eleicao}/config/mun-e{e6}-cm.json")
    if not cfg:
        print("configuração ainda indisponível"); return
    tarefas = [("br", None, None, None, f"{BASE}/{eleicao}/dados/br/br-c0001-e{e6}-u.json")]   # (uf, cod_tse, ibge, nome, url)
    for abr in cfg["abr"]:
        uf = abr["cd"]
        tarefas.append((uf, None, None, None, f"{BASE}/{eleicao}/dados/{uf}/{uf}-c0001-e{e6}-u.json"))
        if uf == "zz":
            continue
        for m in abr["mu"]:
            tarefas.append((uf, m["cd"], m["cdi"], m["nm"],
                            f"{BASE}/{eleicao}/dados/{uf}/{uf}{m['cd']}-c0001-e{e6}-u.json"))

    def trabalho(t):
        try:
            d, mudou = baixar(t[4])
            return t, d, mudou
        except Exception as ex:
            return t, None, False

    mudancas, agora = 0, time.strftime("%Y-%m-%d %H:%M:%S")
    with ThreadPoolExecutor(24) as ex:
        for (uf, cod, ibge, nome, url), d, mudou in ex.map(trabalho, tarefas):
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
    db.commit()
    if not publicar:
        return
    estado["gerado"] = agora
    estado["eleicao"] = eleicao
    estado["cands"] = CANDS
    destino = saida or os.path.join(DADOS, "latest.json")
    tmp = destino + ".tmp"
    with open(tmp, "w") as f:
        json.dump(estado, f, separators=(",", ":"))
    os.replace(tmp, destino)
    st = sum(u["st"] for k, u in estado["ufs"].items() if k != "br")
    print(f"{agora}  arquivos novos: {mudancas}  urnas totalizadas (soma UFs): {st}", flush=True)


def coletor(eleicao, intervalo):
    os.makedirs(DADOS, exist_ok=True)
    db = sqlite3.connect(os.path.join(DADOS, "apuracao.db"), check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS snap (coletado TEXT, uf TEXT, ibge TEXT, gerado_tse TEXT,
                  secoes_total INT, secoes_apur INT, v1 INT, v2 INT, brancos INT, nulos INT, validos INT)""")
    estado = {"ufs": {}, "mun": {}}
    while True:
        try:
            ciclo(eleicao, db, estado)
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
    ciclo("6257", db, base, publicar=False)
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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=RAIZ, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eleicao", default="6258")
    ap.add_argument("--intervalo", type=int, default=60)
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--arquivar", metavar="ID", help="baixa a eleição uma vez e grava dados/hist/ID.json (ex.: --eleicao 6257 --arquivar 2026-t1)")
    ap.add_argument("--simular", action="store_true", help="dados fictícios: apuração aleatória por município")
    a = ap.parse_args()
    if a.arquivar:
        os.makedirs(os.path.join(DADOS, "hist"), exist_ok=True)
        _db = sqlite3.connect(":memory:"); _db.execute("CREATE TABLE snap (a,b,c,d,e,f,g,h,i,j,k)")
        ciclo(a.eleicao, _db, {"ufs": {}, "mun": {}}, saida=os.path.join(DADOS, "hist", a.arquivar + ".json"))
        raise SystemExit(0)
    if a.simular:
        threading.Thread(target=simulador, args=(min(a.intervalo, 5),), daemon=True).start()
    else:
        threading.Thread(target=coletor, args=(a.eleicao, a.intervalo), daemon=True).start()
    print(f"abra http://localhost:{a.porta}/web/")
    ThreadingHTTPServer(("127.0.0.1", a.porta), Handler).serve_forever()
