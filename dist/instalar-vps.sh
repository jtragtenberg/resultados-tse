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
a3v96tf/AaCmfTIAoAAA
