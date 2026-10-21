#!/usr/bin/env python3
"""Reduz os Boletins de Urna do TSE a um "replay" da apuração de presidente, por município e por horário.

  python3 replay.py --ano 2022 --turno 1 [--pasta DIR] [--bin 5] [--manter]

Para cada UF: baixa bweb_<turno>t_<UF>_*.zip do Portal de Dados Abertos, lê o CSV em streaming,
guarda só as linhas de Presidente e, por seção, a hora em que o boletim chegou (DT_BU_RECEBIDO),
comparecimento, abstenção e votos (candidato 1, candidato 2, brancos, nulos). Agrega por município
e por faixa de tempo e grava dados/hist/<ano>-t<turno>-replay.json (poucos MB).

Formato do arquivo gerado:
  frames: [{"t": "2022-10-02 17:05", "p": 0.0123}, ...]   p = fração nacional de seções recebidas
  mun:    {"<ibge>|zz": {"u": "sp", "ts": seções, "e": [[frame, seç., comp., abst., v1, v2, brancos, nulos], ...]}}
          cada entrada é o ACUMULADO no frame; só há entradas nos frames em que o município mudou.
"""
import argparse, csv, datetime as dt, io, json, os, sys, urllib.request, zipfile
from concurrent.futures import ProcessPoolExecutor

RAIZ = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (replay)"}
API = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ano}-boletim-de-urna"
CM = "https://resultados.tse.jus.br/oficial/ele2026/6257/config/mun-e006257-cm.json"
V1, V2 = "13", "22"   # Lula, Jair Bolsonaro / Flávio Bolsonaro


def get(url, destino=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        if destino is None:
            return r.read()
        with open(destino, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)


def hora(t):
    """2022: 02/10/2022 18:45:30 · 2026: 2026-10-04 18:16:01"""
    return dt.datetime.strptime(t, "%d/%m/%Y %H:%M:%S") if "/" in t else dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")


def processar(args):
    """Lê um zip de UF e devolve {(cod_municipio, uf): lista de (datetime, comp, abst, v1, v2, br, nu)}, uma por seção."""
    caminho, uf = args
    z = zipfile.ZipFile(caminho)
    nome = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    secoes = {}   # (mun, zona, secao) -> [hora, comp, abst, v1, v2, br, nu]
    with z.open(nome) as bruto:
        cab = bruto.readline().decode("latin-1").strip().split(";")
        ix = {c.strip('"'): i for i, c in enumerate(cab)}
        i_cargo, i_mun, i_zona, i_sec = ix["CD_CARGO_PERGUNTA"], ix["CD_MUNICIPIO"], ix["NR_ZONA"], ix["NR_SECAO"]
        i_hora, i_comp, i_abst = ix["DT_BU_RECEBIDO"], ix["QT_COMPARECIMENTO"], ix["QT_ABSTENCOES"]
        i_tv, i_nv, i_qt = ix["CD_TIPO_VOTAVEL"], ix["NR_VOTAVEL"], ix["QT_VOTOS"]
        marca = b';"Presidente";'   # 2022 traz aspas nos números, 2026 não
        for linha in bruto:
            if marca not in linha:   # descarta deputados e senador sem parsear
                continue
            c = next(csv.reader([linha.decode("latin-1")], delimiter=";"))
            if c[i_cargo] != "1":
                continue
            k = (c[i_mun], c[i_zona], c[i_sec])
            s = secoes.get(k)
            if s is None:
                s = secoes[k] = [hora(c[i_hora]),
                                 int(c[i_comp]), int(c[i_abst]), 0, 0, 0, 0]
            tv, nv, q = c[i_tv], c[i_nv], int(c[i_qt])
            if tv == "1":
                if nv == V1: s[3] += q
                elif nv == V2: s[4] += q
            elif tv == "2": s[5] += q
            elif tv == "3": s[6] += q
    saida = {}
    for (mun, _, _), s in secoes.items():
        saida.setdefault(mun.zfill(5), []).append(tuple(s))
    return uf, saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2022"); ap.add_argument("--turno", default="1")
    ap.add_argument("--pasta", default=os.path.join(RAIZ, "dados", "fonte-bu"))
    ap.add_argument("--bin", type=int, default=5, help="minutos por quadro")
    ap.add_argument("--janela", default="0.001,0.9995", help="quantis de chegada que delimitam o eixo de tempo; fora dele o horário é limitado à borda (descarta relógios errados e retardatários de dias depois)")
    ap.add_argument("--manter", action="store_true", help="não apagar os .zip depois de processar")
    ap.add_argument("--ufs", help="lista separada por vírgula (para testar)")
    a = ap.parse_args()
    pasta = os.path.join(a.pasta, f"{a.ano}-t{a.turno}"); os.makedirs(pasta, exist_ok=True)

    meta = json.loads(get(API.format(ano=a.ano)))["result"]["resources"]
    urls = {}
    for r in meta:
        u = r["url"]
        if u.endswith(".zip") and f"bweb_{a.turno}t_" in u:
            urls[u.split(f"bweb_{a.turno}t_")[1][:2]] = u
    if a.ufs:
        urls = {k: v for k, v in urls.items() if k in a.ufs.upper().split(",")}
    print(len(urls), "UFs:", " ".join(sorted(urls)), flush=True)

    cm = json.loads(get(CM))
    ibge = {m["cd"]: m["cdi"] for ab in cm["abr"] for m in ab["mu"]}

    def baixar(uf):
        destino = os.path.join(pasta, os.path.basename(urls[uf]))
        if not os.path.exists(destino):
            get(urls[uf], destino + ".part"); os.replace(destino + ".part", destino)
        return destino

    por_mun = {}   # chave -> {"u": uf, "s": [secoes...]}
    with ProcessPoolExecutor(min(6, os.cpu_count() or 2)) as ex:
        futs = []
        for uf in sorted(urls, key=lambda u: u == "SP"):   # SP por último pesa mais; deixa os pequenos andarem
            futs.append(ex.submit(processar, (baixar(uf), uf)))
            print("baixado", uf, flush=True)
        for f in futs:
            uf, saida = f.result()
            for cod, lista in saida.items():
                chave = "zz" if uf == "ZZ" else ibge.get(cod)
                if chave is None:
                    print("município sem código IBGE:", uf, cod); continue
                d = por_mun.setdefault(chave, {"u": uf.lower(), "s": []})
                d["s"].extend(lista)
            print("processado", uf, sum(len(v) for v in saida.values()), "seções", flush=True)
    if not a.manter:
        for n in os.listdir(pasta):
            if n.endswith(".zip"): os.remove(os.path.join(pasta, n))

    todas = sorted(s[0] for d in por_mun.values() for s in d["s"])
    q_lo, q_hi = (float(x) for x in a.janela.split(","))
    lo, hi = todas[int(q_lo * (len(todas) - 1))], todas[int(q_hi * (len(todas) - 1))]
    fora_ini, fora_fim = sum(h < lo for h in todas), sum(h > hi for h in todas)
    print(f"janela de tempo {lo} .. {hi}; {fora_ini} seções antes e {fora_fim} depois foram limitadas à borda "
          f"(chegada real de {todas[0]} a {todas[-1]})", flush=True)
    todas = [min(max(h, lo), hi) for h in todas]
    for d in por_mun.values():
        d["s"] = [(min(max(s[0], lo), hi),) + tuple(s[1:]) for s in d["s"]]
    t0 = min(todas).replace(second=0, microsecond=0)
    t0 = t0 - dt.timedelta(minutes=t0.minute % a.bin)
    passo = dt.timedelta(minutes=a.bin)
    nf = int((max(todas) - t0) / passo) + 2   # quadro 0 = antes de chegar qualquer boletim
    total = len(todas)
    print(f"{total} seções, de {min(todas)} a {max(todas)}, {nf} quadros de {a.bin} min", flush=True)

    por_quadro = [0] * nf
    mun_out = {}
    for chave, d in por_mun.items():
        buckets = {}
        for h, comp, abst, v1, v2, br, nu in d["s"]:
            f = int((h - t0) / passo) + 1
            b = buckets.setdefault(f, [0, 0, 0, 0, 0, 0, 0])
            b[0] += 1; b[1] += comp; b[2] += abst; b[3] += v1; b[4] += v2; b[5] += br; b[6] += nu
            por_quadro[f] += 1
        acum, entradas = [0] * 7, []
        for f in sorted(buckets):
            acum = [x + y for x, y in zip(acum, buckets[f])]
            entradas.append([f] + acum)
        mun_out[chave] = {"u": d["u"], "ts": len(d["s"]), "e": entradas}

    frames, cum = [], 0
    for f in range(nf):
        cum += por_quadro[f]
        frames.append({"t": (t0 + f * passo).strftime("%Y-%m-%d %H:%M"), "p": round(cum / total, 5)})   # estado ao fim da faixa
    saida = os.path.join(RAIZ, "dados", "hist", f"{a.ano}-t{a.turno}-replay.json")
    with open(saida, "w") as f:
        json.dump({"bin": a.bin, "total": total, "frames": frames, "mun": mun_out}, f, separators=(",", ":"))
    print("gravado", saida, f"{os.path.getsize(saida)/1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
