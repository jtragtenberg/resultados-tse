#!/usr/bin/env bash
# instalar-vps.sh — instala o coletor de apuração do TSE como serviço (systemd) e o expõe por HTTPS.
# Gerado por deploy/montar.py: o coletor (apuracao.py) e o verificador (verificar.py) vão embutidos no fim deste arquivo.
#
# Uso (como root ou com sudo):
#   bash instalar-vps.sh --tunel                      # HTTPS temporário sem domínio (Cloudflare quick tunnel)
#   bash instalar-vps.sh --dominio apuracao.seudominio.com   # HTTPS com Caddy; o DNS do domínio já deve apontar para este VPS
#   bash instalar-vps.sh --publico                    # só HTTP na porta 8000 (o site em https NÃO consegue ler: bloqueio de conteúdo misto)
# Opções: --eleicao 6258 (2º turno; 6257 = 1º turno, bom para testar) · --porta 8000 · --intervalo 30
#   bash instalar-vps.sh --desinstalar
#   bash instalar-vps.sh --so-extrair /tmp/x          # só extrai os arquivos (teste local, sem systemd)
set -euo pipefail

ELEICAO=6258; PORTA=8000; INTERVALO=60; DOMINIO=""; TUNEL=0; PUBLICO=0; DIR=/opt/resultados-tse; SO_EXTRAIR=""; DESINSTALAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --eleicao) ELEICAO="$2"; shift 2;; --porta) PORTA="$2"; shift 2;; --intervalo) INTERVALO="$2"; shift 2;;
    --dominio) DOMINIO="$2"; shift 2;; --tunel) TUNEL=1; shift;; --publico) PUBLICO=1; shift;;
    --dir) DIR="$2"; shift 2;; --so-extrair) SO_EXTRAIR="$2"; shift 2;; --desinstalar) DESINSTALAR=1; shift;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "opção desconhecida: $1"; exit 2;;
  esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
SELF="${BASH_SOURCE[0]}"

extrair() {  # $1 = pasta
  mkdir -p "$1"
  sed -n '/^__PAYLOAD__$/,$p' "$SELF" | tail -n +2 | base64 -d | tar xz -C "$1"
}

if [ -n "$SO_EXTRAIR" ]; then extrair "$SO_EXTRAIR"; echo "extraído em $SO_EXTRAIR"; ls -la "$SO_EXTRAIR"; exit 0; fi

if [ "$(id -u)" -ne 0 ]; then echo "Rode como root (ou: sudo bash $0 ...)"; exit 1; fi
command -v systemctl >/dev/null || { echo "systemd não encontrado: este instalador precisa de systemd."; exit 1; }

if [ "$DESINSTALAR" = 1 ]; then
  say "Removendo"
  systemctl disable --now resultados-tse cloudflared-resultados 2>/dev/null || true
  rm -f /etc/systemd/system/resultados-tse.service /etc/systemd/system/cloudflared-resultados.service
  systemctl daemon-reload; rm -rf "$DIR"; echo "removido (Caddy, se instalado, foi mantido)"; exit 0
fi

say "1/5 Python"
if ! command -v python3 >/dev/null; then
  command -v apt-get >/dev/null && { apt-get update -y && apt-get install -y python3 curl; } || { echo "instale python3 (>= 3.8) e rode de novo"; exit 1; }
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' || { echo "python3 >= 3.8 é necessário"; exit 1; }
command -v curl >/dev/null || { command -v apt-get >/dev/null && apt-get install -y curl; }

say "2/5 Arquivos em $DIR"
id resultados >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin resultados
extrair "$DIR"; mkdir -p "$DIR/dados"; chown -R resultados: "$DIR"

BIND=127.0.0.1; [ "$PUBLICO" = 1 ] && BIND=0.0.0.0
say "3/5 Serviço systemd (resultados-tse)"
cat > /etc/systemd/system/resultados-tse.service <<EOF
[Unit]
Description=Coletor de apuracao do TSE (eleicao $ELEICAO)
After=network-online.target
Wants=network-online.target

[Service]
User=resultados
WorkingDirectory=$DIR
ExecStart=$(command -v python3) -I $DIR/apuracao.py --api --bind $BIND --porta $PORTA --eleicao $ELEICAO --intervalo $INTERVALO
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl enable --now resultados-tse; systemctl restart resultados-tse

URL_PUBLICA=""
if [ -n "$DOMINIO" ]; then
  say "4/5 HTTPS com Caddy em https://$DOMINIO"
  if ! command -v caddy >/dev/null; then
    command -v apt-get >/dev/null || { echo "instalação automática do Caddy só no Debian/Ubuntu; instale o Caddy e aponte para 127.0.0.1:$PORTA"; exit 1; }
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y; apt-get install -y caddy
  fi
  printf '%s {\n  encode gzip\n  reverse_proxy 127.0.0.1:%s\n}\n' "$DOMINIO" "$PORTA" > /etc/caddy/Caddyfile
  systemctl enable --now caddy; systemctl reload caddy || systemctl restart caddy
  URL_PUBLICA="https://$DOMINIO"
elif [ "$TUNEL" = 1 ]; then
  say "4/5 HTTPS com Cloudflare quick tunnel"
  if ! command -v cloudflared >/dev/null; then
    case "$(uname -m)" in x86_64) A=amd64;; aarch64|arm64) A=arm64;; armv7l) A=arm;; *) echo "arquitetura $(uname -m) não suportada"; exit 1;; esac
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$A" -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
  fi
  cat > /etc/systemd/system/cloudflared-resultados.service <<EOF
[Unit]
Description=Tunel Cloudflare para o coletor de apuracao
After=network-online.target resultados-tse.service
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:$PORTA
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload; systemctl enable --now cloudflared-resultados; systemctl restart cloudflared-resultados
  for i in $(seq 1 30); do
    URL_PUBLICA=$(journalctl -u cloudflared-resultados -n 80 --no-pager 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
    [ -n "$URL_PUBLICA" ] && break; sleep 2
  done
  [ -n "$URL_PUBLICA" ] || echo "AVISO: não achei a URL do túnel ainda; veja: journalctl -u cloudflared-resultados | grep trycloudflare"
else
  say "4/5 Sem HTTPS (use --tunel ou --dominio para o site publicado conseguir ler)"
  IP=$(curl -fsS https://api.ipify.org 2>/dev/null || echo SEU_IP); URL_PUBLICA="http://$IP:$PORTA"
  [ "$PUBLICO" = 1 ] || echo "AVISO: o serviço escuta só em 127.0.0.1; use --publico, --tunel ou --dominio"
fi

say "5/5 Esperando o 1º ciclo de coleta (a 1ª passada baixa ~5.600 arquivos devagar, para o TSE não bloquear: ~8 a 10 min)"
for i in $(seq 1 450); do
  C=$(curl -fsS "http://127.0.0.1:$PORTA/status" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["ciclos"])' 2>/dev/null || echo 0)
  [ "${C:-0}" -ge 1 ] && break; sleep 2
done
python3 -I "$DIR/verificar.py" --url "http://127.0.0.1:$PORTA" --eleicao "$ELEICAO" || true

cat <<EOF

================ PRONTO ================
URL dos dados : ${URL_PUBLICA:-<ainda sem URL pública>}/latest.json
Status        : ${URL_PUBLICA:-http://127.0.0.1:$PORTA}/status
Abra o site com os dados deste servidor:
  https://jtragtenberg.github.io/resultados-tse/?api=${URL_PUBLICA:-URL}
Verificar a qualquer momento (peça ao Hermes para rodar):
  python3 -I $DIR/verificar.py
Ver os logs:  journalctl -u resultados-tse -f
Parar/iniciar: systemctl stop|start resultados-tse
========================================
EOF
exit 0
__PAYLOAD__
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
7bW9ttevfv0fF9wbtgCgAAA=
