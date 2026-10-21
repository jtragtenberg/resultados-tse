#!/usr/bin/env python3
"""Gera dados/hist/2022-t1.json e 2022-t2.json (presidente, Lula x Jair Bolsonaro) no mesmo formato do latest.json.

Fonte: Portal de Dados Abertos do TSE (resultados finais por município e zona).
  python3 historico2022.py [pasta_com_zips]     # baixa os .zip se não existirem (~585 MB)

Usa a configuração de municípios de 2026 só para converter o código TSE do município em código IBGE.
"""
import csv, io, json, os, sys, urllib.request, zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ZIPS = {"detalhe.zip": f"{CDN}/detalhe_votacao_munzona/detalhe_votacao_munzona_2022.zip",
        "cand.zip": f"{CDN}/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"}
CM = "https://resultados.tse.jus.br/oficial/ele2026/6257/config/mun-e006257-cm.json"
UA = {"User-Agent": "Mozilla/5.0 (historico2022)"}
V1, V2 = "13", "22"
CANDS = {"v1": "Lula", "v2": "Jair Bolsonaro"}


def get(url, destino=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        if destino is None:
            return r.read()
        with open(destino, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)


def linhas(z, nome):
    return csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";")


def vazio():
    return {"ts": 0, "st": 0, "eleitores": 0, "v1": 0, "v2": 0, "validos": 0, "total": 0,
            "comp": 0, "abst": 0, "brancos": 0, "nulos": 0}


def somar(a, b):
    for k in a:
        a[k] += b[k]


def main():
    pasta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "dados", "fonte2022")
    os.makedirs(pasta, exist_ok=True)
    for nome, url in ZIPS.items():
        if not os.path.exists(os.path.join(pasta, nome)):
            print("baixando", nome, "...", flush=True)
            get(url, os.path.join(pasta, nome))
    cm = json.loads(get(CM))
    ibge = {m["cd"]: (a["cd"], m["cdi"], m["nm"]) for a in cm["abr"] for m in a["mu"]}

    mun = {1: {}, 2: {}}   # turno -> cod_tse -> resumo
    z = zipfile.ZipFile(os.path.join(pasta, "detalhe.zip"))
    for r in linhas(z, "detalhe_votacao_munzona_2022_BR.csv"):
        if r["CD_CARGO"] != "1":
            continue
        t, cod = int(r["NR_TURNO"]), r["CD_MUNICIPIO"].zfill(5)
        m = mun[t].setdefault(cod, dict(vazio(), uf=r["SG_UF"].lower(), nm=r["NM_MUNICIPIO"], dg="", hg="", tf=True))
        n = int
        m["ts"] += n(r["QT_TOTAL_SECOES"]); m["st"] += n(r["QT_TOTAL_SECOES"])
        m["eleitores"] += n(r["QT_APTOS"]); m["comp"] += n(r["QT_COMPARECIMENTO"]); m["abst"] += n(r["QT_ABSTENCOES"])
        m["total"] += n(r["QT_VOTOS"]); m["validos"] += n(r["QT_TOTAL_VOTOS_VALIDOS"])
        m["brancos"] += n(r["QT_VOTOS_BRANCOS"]); m["nulos"] += n(r["QT_TOTAL_VOTOS_NULOS"])
        m["dg"], m["hg"] = r["DT_ULTIMA_TOTALIZACAO"], r["HH_ULTIMA_TOTALIZACAO"]
    z = zipfile.ZipFile(os.path.join(pasta, "cand.zip"))
    for r in linhas(z, "votacao_candidato_munzona_2022_BR.csv"):
        if r["CD_CARGO"] != "1" or r["NR_CANDIDATO"] not in (V1, V2):
            continue
        m = mun[int(r["NR_TURNO"])].get(r["CD_MUNICIPIO"].zfill(5))
        if m:
            m["v1" if r["NR_CANDIDATO"] == V1 else "v2"] += int(r["QT_VOTOS_NOMINAIS_VALIDOS"])

    os.makedirs(os.path.join(RAIZ, "dados", "hist"), exist_ok=True)
    for t in (1, 2):
        ufs, muni, sem = {}, {}, 0
        for cod, m in mun[t].items():
            ufs.setdefault(m["uf"], vazio()); ufs.setdefault("br", vazio())
            somar(ufs["br"], m)
            somar(ufs[m["uf"]], m)
            if m["uf"] == "zz":
                continue
            if cod not in ibge:
                sem += 1; continue
            muni[ibge[cod][1]] = m
        for k, u in ufs.items():
            u.update(dg=next(iter(mun[t].values()))["dg"], hg="", tf=True)
        out = {"ufs": ufs, "mun": muni, "gerado": "resultado final", "eleicao": f"2022 · {t}º turno", "cands": CANDS}
        destino = os.path.join(RAIZ, "dados", "hist", f"2022-t{t}.json")
        with open(destino, "w") as f:
            json.dump(out, f, separators=(",", ":"))
        b = ufs["br"]
        print(f"2022 {t}º turno: {len(muni)} municípios ({sem} sem código IBGE), Lula {b['v1']:,} x Bolsonaro {b['v2']:,}")


if __name__ == "__main__":
    main()
