#!/usr/bin/env python3
"""Gera dados/hist/<id>-replay.json a partir do banco SQLite do coletor (apuracao.db), em vez dos boletins de urna.

  python3 replay_db.py apuracao-eleicoes-6258.db 2026-t2 [--data 25/10/2026] [--bin 5]

O coletor guardou uma linha por município sempre que o arquivo do TSE mudou, com a hora em que o TSE o gerou (gerado_tse, horário
de Brasília). Cada linha é um estado acumulado do município, então dá para refazer a apuração minuto a minuto.
Diferenças em relação ao replay por boletim de urna (replay.py): o banco não tem comparecimento nem abstenção. O comparecimento
é válidos + brancos + nulos; a abstenção é ESTIMADA (eleitores do município x seções apuradas / total de seções - comparecimento).
"""
import argparse, datetime as dt, json, os, sqlite3

RAIZ = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("db"); ap.add_argument("id"); ap.add_argument("--data", default="25/10/2026"); ap.add_argument("--bin", type=int, default=5); ap.add_argument("--nota", default="", help="texto mostrado sob o slider"); ap.add_argument("--inicio", default="17:00", help="horário (Brasília) em que o eixo começa; versões anteriores (zeradas) caem no 1º quadro")
a = ap.parse_args()
final = json.load(open(os.path.join(RAIZ, "dados", "hist", a.id + ".json")))
c = sqlite3.connect(a.db)
linhas = c.execute("select uf, ibge, gerado_tse, secoes_total, secoes_apur, v1, v2, brancos, nulos, validos from snap "
                   "where gerado_tse like ? order by rowid", (a.data + "%",)).fetchall()
ev = {}   # chave (ibge ou 'zz') -> [(hora, st, ts, v1, v2, br, nu, validos)]
for uf, ibge, ger, ts, st, v1, v2, br, nu, val in linhas:
    if uf == "br" or (not ibge and uf != "zz"): continue    # linhas de UF (exceto zz) e do Brasil não entram
    ev.setdefault(ibge or "zz", []).append((dt.datetime.strptime(ger, "%d/%m/%Y %H:%M:%S"), uf, ts, st, v1, v2, br, nu, val))
t0 = min(e[0][0] for e in ev.values())
ini = dt.datetime.strptime(a.data + " " + a.inicio, "%d/%m/%Y %H:%M")
t0 = max(t0, ini).replace(second=0, microsecond=0); t0 -= dt.timedelta(minutes=t0.minute % a.bin)
passo = dt.timedelta(minutes=a.bin)
nf = int((max(e[-1][0] for e in ev.values()) - t0) / passo) + 2
mun, por_quadro, total = {}, [0] * nf, 0
for chave, lista in ev.items():
    lista.sort(key=lambda x: x[0])
    ts = max(x[2] for x in lista); total += ts
    ele = (final["ufs"]["zz"] if chave == "zz" else final["mun"].get(chave, {})).get("eleitores", 0)
    por_bin = {}
    for hora, uf, _, st, v1, v2, br, nu, val in lista:
        f = max(1, int((hora - t0) / passo) + 1); por_bin[f] = (st, v1, v2, br, nu, val)    # último estado de cada faixa
    entradas, ant = [], 0
    for f in sorted(por_bin):
        st, v1, v2, br, nu, val = por_bin[f]
        comp = val + br + nu; apt = round(ele * st / ts) if ts else 0
        entradas.append([f, st, comp, max(0, apt - comp), v1, v2, br, nu]); por_quadro[f] += st - ant; ant = st
    mun[chave] = {"u": lista[0][1].lower(), "ts": ts, "e": entradas}
frames, cum = [], 0
for f in range(nf):
    cum += por_quadro[f]; frames.append({"t": (t0 + f * passo).strftime("%Y-%m-%d %H:%M"), "p": round(cum / total, 5)})
out = {"bin": a.bin, "total": total, "frames": frames, "mun": mun, "fonte": "coletor", "abst_estimada": True, "nota": a.nota}
dest = os.path.join(RAIZ, "dados", "hist", a.id + "-replay.json")
json.dump(out, open(dest, "w"), separators=(",", ":"))
print(f"{len(mun)} municípios, {nf} quadros de {a.bin} min, de {frames[0]['t']} a {frames[-1]['t']}; p inicial {frames[0]['p']} final {frames[-1]['p']} -> {dest} ({os.path.getsize(dest)/1e6:.1f} MB)")
