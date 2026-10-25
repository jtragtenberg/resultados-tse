#!/usr/bin/env python3
"""Verifica se o coletor está funcionando e baixando dados. Só biblioteca padrão.

  python3 verificar.py                          # coletor em http://127.0.0.1:8000 (local ou, no VPS, a própria máquina)
  python3 verificar.py --url https://seu-tunel.trycloudflare.com    # de fora, pela URL pública
  python3 verificar.py --eleicao 6257           # 1º turno, para testar antes do dia 25/10
  python3 verificar.py --json                   # saída em JSON (para outro programa ler)

Saída: uma linha por checagem (OK / ATENÇÃO / FALHA) e um veredito final. Código de saída 0 = tudo certo.
Pensado para ser rodado pelo Hermes: a última linha é o veredito em uma frase.
"""
import argparse, gzip, json, sys, time, urllib.request, urllib.error

TSE = "https://resultados.tse.jus.br/oficial"
UA = {"User-Agent": "Mozilla/5.0 (verificar)", "Accept-Encoding": "gzip"}


milhar = lambda x: f"{x:,}".replace(",", ".")          # 1.234.567
pc = lambda x: f"{x * 100:.1f}".replace(".", ",") + "%"


def get(url, timeout=20):
    t0 = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        corpo = r.read()
        tam = len(corpo)
        if r.headers.get("Content-Encoding") == "gzip":
            corpo = gzip.decompress(corpo)
        return json.loads(corpo), tam, round(time.time() - t0, 2), dict(r.headers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--eleicao", default="6258")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-idade", type=int, default=240, help="segundos sem dado novo até virar ATENÇÃO")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    linhas, res = [], {"checagens": []}

    def ver(nivel, texto, **extra):
        linhas.append((nivel, texto)); res["checagens"].append(dict(nivel=nivel, texto=texto, **extra))

    # 1. o TSE responde?
    e6 = a.eleicao.zfill(6)
    try:
        d, tam, dt, _ = get(f"{TSE}/ele2026/{a.eleicao}/dados/br/br-c0001-e{e6}-u.json")
        s = d["s"]
        ver("OK", f"TSE respondendo ({dt}s, {tam/1e3:.1f} KB): Brasil {milhar(int(s['st']))} de {milhar(int(s['ts']))} seções apuradas, "
                  f"arquivo gerado em {d['dg']} {d['hg']}", apuradas=int(s["st"]), total=int(s["ts"]))
    except urllib.error.HTTPError as e:
        ver("FALHA", f"TSE respondeu {e.code} para a eleição {a.eleicao}" + (" — o arquivo ainda não foi publicado" if e.code in (403, 404) else ""))
    except Exception as e:
        ver("FALHA", f"não consegui falar com o TSE: {type(e).__name__} {e}")

    # 2. o coletor responde e está ciclando?
    st = None
    try:
        st, _, dt, _ = get(f"{url}/status", 10)
        u = st.get("ultimo_ciclo")
        if not u:
            ver("ATENÇÃO", f"coletor no ar ({url}) mas ainda sem ciclo concluído (rodando há {st['rodando_ha_s']}s) — o 1º ciclo leva ~1 min")
        else:
            nivel = "OK" if st["total"]["erros"] == 0 or st["total"]["erros"] < 0.01 * max(1, st["total"]["requisicoes"]) else "ATENÇÃO"
            ver(nivel, f"coletor ativo: {st['ciclos']} ciclos, último consultou {u['arquivos_consultados']} arquivos em {u['duracao_s']}s "
                       f"(novos {u['baixados']}, sem mudança {u['sem_mudanca']}, indisponíveis {u['indisponiveis']}, erros {u['erros']}, 429 {u.get('limitado', 0)}); "
                       f"total baixado {st['total']['bytes']/1e6:.1f} MB", ciclos=st["ciclos"])
            if u.get("limitado"):
                ver("ATENÇÃO", f"o TSE respondeu 429 (limite de requisições) {u['limitado']}x no último ciclo; o coletor reduziu para {st.get('rps_atual')} req/s "
                               f"(máx. {st.get('rps_max')}) e tenta de novo sozinho")
            if st.get("ultimo_erro"):
                ver("ATENÇÃO", f"último erro registrado: {st['ultimo_erro']}")
        b = st.get("brasil")
        if b:
            ver("OK", f"dado do coletor: {milhar(b['secoes_apuradas'])} de {milhar(b['secoes_total'])} seções ({pc(b['pct_apuradas'])}), "
                      f"Lula {milhar(b['v1'])} x {milhar(b['v2'])} Flávio")
    except Exception as e:
        ver("FALHA", f"coletor não responde em {url}/status: {type(e).__name__} {e} — o serviço está rodando? (systemctl status resultados-tse)")

    # 3. o latest.json está fresco?
    try:
        d, tam, dt, h = get(f"{url}/latest.json", 20)
        idade = round(time.time() - d["ts_epoch"]) if d.get("ts_epoch") else None
        nivel = "OK" if idade is not None and idade <= a.max_idade else "ATENÇÃO"
        ver(nivel, f"latest.json servido ({tam/1e3:.0f} KB na rede, {dt}s, {len(d.get('mun', {}))} municípios), gerado há "
                   f"{idade if idade is not None else '?'}s" + ("" if nivel == "OK" else f" — mais velho que {a.max_idade}s: o coletor pode ter travado"),
            idade_s=idade, cors=h.get("Access-Control-Allow-Origin"))
        if url.startswith("http") and "127.0.0.1" not in url and "localhost" not in url and h.get("Access-Control-Allow-Origin") != "*":
            ver("ATENÇÃO", "a resposta não tem CORS liberado: o site publicado não conseguirá ler")
    except urllib.error.HTTPError as e:
        ver("ATENÇÃO" if e.code == 503 else "FALHA", f"latest.json respondeu {e.code} (503 = coletor ainda no 1º ciclo)")
    except Exception as e:
        ver("FALHA", f"não consegui ler {url}/latest.json: {type(e).__name__} {e}")

    falhas = [t for n, t in linhas if n == "FALHA"]; avisos = [t for n, t in linhas if n == "ATENÇÃO"]
    veredito = ("FUNCIONANDO: o coletor está baixando dados do TSE e servindo o site." if not falhas and not avisos else
                "FUNCIONANDO COM RESSALVAS: " + "; ".join(avisos) if not falhas else
                "NÃO ESTÁ FUNCIONANDO: " + "; ".join(falhas))
    res["veredito"], res["ok"] = veredito, not falhas
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for n, t in linhas:
            print(f"[{n:7}] {t}")
        print("\nVEREDITO:", veredito)
    sys.exit(0 if not falhas else 1)


if __name__ == "__main__":
    main()
