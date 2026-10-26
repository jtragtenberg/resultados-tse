# Resultados TSE — apuração em tempo real e replay

Painel para ver como foi a apuração das eleições presidenciais de 2022 e 2026 (Lula x Bolsonaro) e comparar uma eleição com outra na mesma porcentagem de urnas apuradas. Também acompanha uma eleição em andamento, rodando o coletor.

Projeto independente, sem vínculo com a Justiça Eleitoral. Dados: [resultados.tse.jus.br](https://resultados.tse.jus.br/) e [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/).

**Versão publicada:** https://jtragtenberg.github.io/resultados-tse/ (GitHub Pages). É 100% estática: lê os arquivos de `dados/hist/` do próprio repositório e não depende de nenhum servidor. Eleições disponíveis: 2022 (1º e 2º turno) e 2026 (1º e 2º turno).

## Como usar

```bash
python3 apuracao.py                 # coleta uma eleição em andamento (padrão 6258) e serve em http://localhost:8000/web/
python3 apuracao.py --eleicao 6257  # 1º turno de 2026
python3 apuracao.py --simular       # dados fictícios, apuração aleatória por município
```

Só usa a biblioteca padrão do Python. O mapa usa d3 e as malhas do IBGE, carregados pela internet.

## O que tem

- **Mapa** por estado ou município, com zoom e a ilha fictícia "Exterior", nas visões: votos válidos (vermelho → roxo → azul), urnas apuradas, abstenção, brancos, nulos e **votos depois das 17h**.
- **Barras**, por estado ou pelos N municípios com maior valor, ordenadas da maior para a menor, que crescem conforme a apuração avança; em votos ou em %, e por candidato.
- **Linha do tempo de eleições** (2022 1º e 2º turno, 2026 1º e 2º turno) e **replay**: um slider com a porcentagem de urnas apuradas, que lembra a % ao trocar de eleição.
- **Comparar 1º e 2º turno de 2026** (outra aba): mudança de votos de cada candidato, de brancos, nulos e abstenção, e da vantagem de Lula, por estado e município, em mapa e em barras, com um resumo de "quem fez a diferença".
- **Votos depois das 17h**: quantos votos foram confirmados depois do encerramento (hora de cada voto, sem o candidato), por município e UF, com histograma por minuto.
- Tema claro e escuro. O guia visual está em [design.md](design.md).

## Dados e scripts

| Arquivo | O que faz |
|---|---|
| `apuracao.py` | coletor ao vivo (polling com ETag, histórico em SQLite) + servidor local; `--arquivar ID` grava uma eleição em `dados/hist/` |
| `historico2022.py` | gera os resultados finais de 2022 a partir do Portal de Dados Abertos |
| `replay.py` | reduz os Boletins de Urna (hora de chegada por seção) a quadros de 5 min por município, em `dados/hist/<ano>-t<turno>-replay.json` |
| `dados/hist/` | resultados finais e replays já gerados (cerca de 9 MB) |
| `replay_db.py` | gera o replay a partir do banco SQLite do coletor (usado no 2º turno de 2026, de que ainda não há boletins de urna) |
| `votos_apos17h.py` | lê os logs das urnas (centenas de GB no total, por HTTP Range) e conta votos confirmados depois do encerramento, por município |
| `web/index.html`, `web/comparar.js` | a página e a aba de comparação |

`dados/latest.json` e `dados/apuracao.db` são gerados pelo coletor e não são versionados.

## Rodar no VPS (apuração ao vivo para o site publicado)

```bash
python3 deploy/montar.py             # gera dist/instalar-vps.sh (coletor + verificador embutidos)
sudo bash dist/instalar-vps.sh --tunel --eleicao 6258     # HTTPS temporário (Cloudflare) · ou --dominio apuracao.seudominio.com
```

O instalador cria o serviço `resultados-tse` (systemd) e imprime a URL pública. Abra o site com `https://jtragtenberg.github.io/resultados-tse/?api=URL` (fica salvo no navegador) ou preencha `web/config.js`. O site lê `URL/latest.json` a cada 1 min e mostra "atualizado há N s".
Para checar se está funcionando: `python3 verificar.py [--url URL]` (no VPS: `python3 -I /opt/resultados-tse/verificar.py`) ou `python3 apuracao.py --teste` (uma coleta curta, sem servidor). O texto para mandar ao Hermes está em `deploy/mensagem-hermes.txt`.

**Limite do TSE:** requisições rápidas demais recebem erro 429 e bloqueiam o IP por vários minutos. O coletor limita a taxa (`--rps`, padrão 30), corta pela metade ao levar 429 e consulta só os municípios que ainda podem mudar.

## Replay de outras eleições

```bash
python3 replay.py --ano 2022 --turno 1     # baixa os boletins por UF (centenas de MB) e grava o replay
```

Depois, marque `replay:true` na eleição em `ELEICOES` no `web/index.html`.

Limites: o horário usado é `DT_BU_RECEBIDO` (chegada do boletim) e não foi confirmado o fuso. Horários fora da janela de 0,1% a 99,95% de chegada são limitados à borda do eixo.
