#!/usr/bin/env python3
"""Gera dist/instalar-vps.sh (instalador único com apuracao.py e verificar.py embutidos) e dist/mensagem-hermes.txt."""
import base64, io, os, tarfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVOS = ["apuracao.py", "verificar.py"]

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as t:
    for nome in ARQUIVOS:
        info = t.gettarinfo(os.path.join(RAIZ, nome), arcname=nome)
        info.uid = info.gid = 0; info.uname = info.gname = ""; info.mode = 0o755 if nome.endswith(".py") else 0o644
        with open(os.path.join(RAIZ, nome), "rb") as f:
            t.addfile(info, f)
b64 = base64.encodebytes(buf.getvalue()).decode()

with open(os.path.join(RAIZ, "deploy", "instalar-vps.sh.tpl")) as f:
    tpl = f.read()
os.makedirs(os.path.join(RAIZ, "dist"), exist_ok=True)
destino = os.path.join(RAIZ, "dist", "instalar-vps.sh")
with open(destino, "w") as f:
    f.write(tpl + b64)
os.chmod(destino, 0o755)
print(f"gerado {destino} ({os.path.getsize(destino)/1e3:.0f} KB)")
