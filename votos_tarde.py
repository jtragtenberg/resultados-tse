#!/usr/bin/env python3
"""Conta, a partir dos logs das urnas (arquivos transmitidos para totalização do TSE), quantos votos para presidente
foram confirmados DEPOIS do horário de encerramento (17h de Brasília = fim do horário oficial da votação).

O log de cada urna registra "Voto confirmado para [Presidente]" com data e hora (segundos). NÃO registra em quem: o voto é secreto.

  python3 votos_tarde.py --ano 2026 --turno 1 [--ufs AC,AL] [--processos 4]

Lê cada .zip do TSE por HTTP Range (só os logs, sem gravar nada em disco) e grava dados/hist/<ano>-t<turno>-tarde.json.
O horário de abertura de cada urna ("Urna pronta para receber votos", 8h de Brasília no relógio local) serve de referência
para achar o horário de encerramento local (abertura + 9h), o que resolve os fusos (AC, AM, MT, Noronha, exterior...).
"""
import argparse, collections, concurrent.futures as cf, datetime as dt, io, json, os, re, struct, sys, time, urllib.request, zipfile, zlib

RAIZ = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (votos_tarde)"}
JANELA = (-60, 180)   # minutos em relação ao encerramento, em que se guarda o histograma por minuto
NOME = re.compile(r"^o(\d{5})([a-z]{2})(\d{5})(\d{4})(\d{4})-log\.(jez|logjez)$", re.I)


class HttpFile(io.RawIOBase):
    """Arquivo somente-leitura sobre HTTP (Range) com cache de blocos: abre um .zip enorme lendo só o que precisa."""
    def __init__(self, url, bloco=1 << 20):
        self.url, self.bloco, self.pos, self.cache, self.baixado = url, bloco, 0, {}, 0
        self.size = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=60).headers["Content-Length"])
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def _bloco(self, i):
        if i not in self.cache:
            a = i * self.bloco; b = min(self.size, a + self.bloco) - 1
            for tent in range(5):
                try:
                    self.cache[i] = urllib.request.urlopen(urllib.request.Request(self.url, headers=dict(UA, Range=f"bytes={a}-{b}")), timeout=120).read(); break
                except Exception:
                    if tent == 4: raise
                    time.sleep(2 * (tent + 1))
            self.baixado += len(self.cache[i])
            if len(self.cache) > 48: self.cache.pop(next(iter(self.cache)))
        return self.cache[i]
    def readinto(self, buf):
        n, want = 0, min(len(buf), self.size - self.pos)
        while n < want:
            i, off = divmod(self.pos, self.bloco); pedaco = self._bloco(i)[off:off + want - n]
            buf[n:n + len(pedaco)] = pedaco; n += len(pedaco); self.pos += len(pedaco)
        return n


def texto_do_log(dados):
    """.jez = zip com logd.dat; .logjez (2022) = 7z com logd.dat."""
    if dados[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(dados)); return z.read(z.namelist()[0])
    import py7zr   # só para 2022
    with py7zr.SevenZipFile(io.BytesIO(dados)) as s:
        return next(iter(s.readall().values())).read()


def seg(b, i=0):  # "dd/mm/aaaa hh:mm:ss" em bytes -> (dia como texto, segundos desde 00:00)
    return b[i:i + 10], int(b[i + 11:i + 13]) * 3600 + int(b[i + 14:i + 16]) * 60 + int(b[i + 17:i + 19])


def analisar_log(bruto, cargo=b"[Presidente]"):
    """Devolve (abertura_s, votos_s, dia, encerrou_s): horários locais, em segundos desde 0h, do dia da eleição."""
    alvo = b"Voto confirmado para " + cargo
    votos, prontas, enc = [], [], []
    for linha in bruto.split(b"\n"):
        if alvo in linha: votos.append(seg(linha))
        elif b"Urna pronta para receber votos" in linha: prontas.append(seg(linha))
        elif b"Operador selecionou: Encerrar vota" in linha: enc.append(seg(linha))
    if not votos: return None
    dia = collections.Counter(d for d, _ in votos).most_common(1)[0][0]
    ab = next((s for d, s in prontas if d == dia), None)
    return ab, [s for d, s in votos if d == dia], dia, next((s for d, s in enc if d == dia), None)


def baixar_entrada(url, info, tam):
    """Uma requisição por urna: lê só os bytes do log dentro do .zip (cabeçalho local + dados)."""
    a = info.header_offset; b = min(tam, a + 30 + len(info.filename.encode()) + 512 + info.compress_size) - 1
    for tent in range(6):
        try:
            buf = urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, Range=f"bytes={a}-{b}")), timeout=120).read(); break
        except Exception:
            if tent == 5: raise
            time.sleep(2 * (tent + 1))
    n_len, e_len = struct.unpack("<HH", buf[26:30]); ini = 30 + n_len + e_len
    dados = buf[ini:ini + info.compress_size]
    return len(buf), (zlib.decompress(dados, -15) if info.compress_type == 8 else dados)


def processar_uf(args):
    url, uf, limite, fios = args
    f = HttpFile(url); z = zipfile.ZipFile(f)
    itens = [i for i in z.infolist() if NOME.match(i.filename)]
    if limite: itens = itens[:limite]
    lidos = f.baixado

    def uma(info):
        n, bruto = baixar_entrada(url, info, f.size)
        r = analisar_log(texto_do_log(bruto)); m = NOME.match(info.filename)
        if not r: return n, None
        ab, votos, dia, enc = r
        # guarda só o total e os votos a partir das 14h locais; o resto não interessa e pesaria na memória
        return n, (m.group(3), ab, len(votos), [s for s in votos if s >= 14 * 3600], enc)

    urnas = []
    with cf.ThreadPoolExecutor(fios) as ex:
        for n, u in ex.map(uma, itens):
            lidos += n
            if u: urnas.append(u)
    return uf, urnas, lidos


def resumir(uf, urnas):
    """Alinha cada urna ao seu horário local de encerramento (moda da abertura na UF/município + 9h)."""
    hora_ab = lambda ab: ab // 3600
    moda_uf = collections.Counter(hora_ab(u[1]) for u in urnas if u[1] is not None).most_common(1)[0][0]
    por_mun = collections.defaultdict(collections.Counter)
    for u in urnas:
        if u[1] is not None: por_mun[u[0]][hora_ab(u[1])] += 1
    out_mun, hist = {}, [0] * (JANELA[1] - JANELA[0] + 1)
    bins = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 120), (120, 10**9)]
    for cod, ab, total, tarde_cand, enc in urnas:
        # exterior: cada posto segue o horário local do seu município; Brasil: moda da UF, exceto município com fuso próprio (Noronha)
        mm = por_mun[cod]; h = mm.most_common(1)[0][0] if (uf == "ZZ" or (sum(mm.values()) >= 3 and mm.most_common(1)[0][0] != moda_uf)) else moda_uf
        corte = (h + 9) * 3600
        m = out_mun.setdefault(cod, {"urnas": 0, "votos": 0, "tarde": 0, "bins": [0] * len(bins), "ultimo_min": 0.0, "urnas_tarde": 0, "enc_atraso_min": 0.0})
        m["urnas"] += 1; m["votos"] += total
        apos = [s for s in tarde_cand if s > corte]
        if apos:
            m["tarde"] += len(apos); m["urnas_tarde"] += 1; m["ultimo_min"] = max(m["ultimo_min"], (max(apos) - corte) / 60)
            for s in apos:
                mi = (s - corte) / 60
                for k, (a, b) in enumerate(bins):
                    if a <= mi < b: m["bins"][k] += 1; break
        for s in tarde_cand:
            k = int((s - corte) // 60) - JANELA[0]
            if 0 <= k < len(hist): hist[k] += 1
        if enc is not None: m["enc_atraso_min"] += max(0, (enc - corte) / 60)
    return {"mun": out_mun, "hist_min": hist}


CM = "https://resultados.tse.jus.br/oficial/ele2026/6257/config/mun-e006257-cm.json"
SOMA = ("urnas", "votos", "tarde", "urnas_tarde", "enc_atraso_min")


def compactar(bruto):
    """Formato do site: municípios por código IBGE (o exterior fica só em ufs.zz), totais por UF e histograma por minuto."""
    cm = json.load(urllib.request.urlopen(urllib.request.Request(CM, headers=UA), timeout=60))
    ibge = {m["cd"]: m["cdi"] for ab in cm["abr"] for m in ab["mu"]}
    nova = lambda: {"urnas": 0, "votos": 0, "tarde": 0, "ut": 0, "enc": 0.0, "ult": 0.0, "b": [0] * 6}
    mun, ufs = {}, {}
    def somar(a, m):
        a["urnas"] += m["urnas"]; a["votos"] += m["votos"]; a["tarde"] += m["tarde"]; a["ut"] += m["urnas_tarde"]; a["enc"] += m["enc_atraso_min"]
        a["ult"] = max(a["ult"], m["ultimo_min"]); a["b"] = [x + y for x, y in zip(a["b"], m["bins"])]
    br = dict(nova(), h=None)
    for uf, d in bruto["uf"].items():
        u = ufs.setdefault(uf.lower(), dict(nova(), h=[0] * len(d["hist_min"])))
        u["h"] = [x + y for x, y in zip(u["h"], d["hist_min"])]
        br["h"] = [x + y for x, y in zip(br["h"] or [0] * len(d["hist_min"]), d["hist_min"])]
        for cod, m in d["mun"].items():
            somar(u, m); somar(br, m)
            if uf != "ZZ" and cod.zfill(5) in ibge:
                a = mun.setdefault(ibge[cod.zfill(5)], dict(nova(), u=uf.lower())); somar(a, m)
    ufs["br"] = br
    for a in list(mun.values()) + list(ufs.values()):
        a["enc"] = round(a["enc"] / a["urnas"], 1) if a["urnas"] else 0; a["ult"] = round(a["ult"], 1)
    return {"ano": bruto.get("ano"), "turno": bruto.get("turno"), "janela_min": bruto["janela_min"], "bins": bruto["bins"], "mun": mun, "ufs": ufs}


def recursos(ano):
    d = json.load(urllib.request.urlopen(urllib.request.Request(f"https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ano}-arquivos-transmitidos-para-totalizacao", headers=UA), timeout=60))["result"]
    return {(re.search(r"_(\d)t_([A-Z]{2})\.zip$", r["url"]).group(1), re.search(r"_(\d)t_([A-Z]{2})\.zip$", r["url"]).group(2)): r["url"]
            for r in d["resources"] if re.search(r"_(\d)t_([A-Z]{2})\.zip$", r["url"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2026"); ap.add_argument("--turno", default="1"); ap.add_argument("--ufs")
    ap.add_argument("--saida", help="arquivo de saída (padrão dados/hist/<ano>-t<turno>-tarde.json)"); ap.add_argument("--converter", metavar="ARQ", help="converte um resultado bruto antigo para o formato do site e sai"); ap.add_argument("--processos", type=int, default=4); ap.add_argument("--fios", type=int, default=6, help="requisições simultâneas por processo"); ap.add_argument("--limite", type=int, help="só N urnas por UF (teste)")
    a = ap.parse_args()
    if a.converter:
        d = json.load(open(a.converter))
        if "mun" in d: sys.exit("já está no formato do site")
        json.dump(compactar(d), open(a.converter, "w"), separators=(",", ":")); print("convertido", a.converter, f"{os.path.getsize(a.converter) / 1e6:.1f} MB"); return
    rec = {uf: u for (t, uf), u in recursos(a.ano).items() if t == a.turno}
    if a.ufs: rec = {k: v for k, v in rec.items() if k in a.ufs.upper().split(",")}
    if not rec: sys.exit("nenhum arquivo para esse ano/turno (o TSE ainda não publicou?)")
    print(len(rec), "UFs:", " ".join(sorted(rec)), flush=True)
    t0 = time.time(); res = {}; baixado = 0
    ordem = sorted(rec, key=lambda u: -1 if u == "SP" else 0)   # SP (o maior) primeiro, para não ficar sozinho no fim
    with cf.ProcessPoolExecutor(a.processos) as ex:
        futs = {ex.submit(processar_uf, (rec[uf], uf, a.limite, a.fios)): uf for uf in ordem}
        for fut in cf.as_completed(futs):
            uf, urnas, b = fut.result(); baixado += b
            res[uf] = resumir(uf, urnas)
            n = sum(m["votos"] for m in res[uf]["mun"].values()); t = sum(m["tarde"] for m in res[uf]["mun"].values())
            print(f"{uf}: {len(urnas)} urnas, {n:,} votos, {t:,} depois do encerramento ({t / max(n, 1):.2%}) · {b / 1e6:.0f} MB lidos · {time.time() - t0:.0f}s".replace(",", "."), flush=True)
    saida = a.saida or os.path.join(RAIZ, "dados", "hist", f"{a.ano}-t{a.turno}-tarde.json")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    json.dump(compactar({"ano": a.ano, "turno": a.turno, "janela_min": JANELA, "bins": ["0-5", "5-15", "15-30", "30-60", "60-120", "120+"], "uf": res}), open(saida, "w"), separators=(",", ":"))
    print("gravado", saida, f"{os.path.getsize(saida) / 1e6:.1f} MB · {baixado / 1e9:.1f} GB lidos em {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
