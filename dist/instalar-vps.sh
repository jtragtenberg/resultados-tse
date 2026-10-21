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

say "5/5 Esperando o 1º ciclo de coleta (a 1ª passada baixa ~5.600 arquivos devagar, para o TSE não bloquear: ~3 a 5 min)"
for i in $(seq 1 200); do
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
7tpdu2t37a7d9atf/wd4qNd9AKAAAA==
