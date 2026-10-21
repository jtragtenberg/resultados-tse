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

ELEICAO=6258; PORTA=8000; INTERVALO=30; DOMINIO=""; TUNEL=0; PUBLICO=0; DIR=/opt/resultados-tse; SO_EXTRAIR=""; DESINSTALAR=0
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
