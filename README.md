# Resultados TSE — apuração em tempo real e replay

Painel local para acompanhar a apuração do 2º turno de 2026 (Lula x Flávio Bolsonaro) e comparar com a apuração de eleições passadas na mesma porcentagem de urnas apuradas.

Projeto independente, sem vínculo com a Justiça Eleitoral. Dados: [resultados.tse.jus.br](https://resultados.tse.jus.br/) e [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/).

**Versão publicada:** https://jtragtenberg.github.io/resultados-tse/ (GitHub Pages). Sem coletor, mostra só as eleições arquivadas (2022 e 2026 1º turno) com replay; o modo ao vivo exige rodar o coletor localmente.

## Como usar

```bash
python3 apuracao.py                 # coleta o 2º turno de 2026 (eleição 6258) e serve em http://localhost:8000/web/
python3 apuracao.py --eleicao 6257  # 1º turno de 2026
python3 apuracao.py --simular       # dados fictícios, apuração aleatória por município
```

Só usa a biblioteca padrão do Python. O mapa usa d3 e as malhas do IBGE, carregados pela internet.

## O que tem

- **Mapa** por estado ou município, com zoom, nas visões: votos válidos (vermelho → roxo → azul), urnas apuradas, abstenção, brancos e nulos.
- **Barras por estado**, ordenadas da maior para a menor, que crescem conforme a apuração avança.
- **Linha do tempo de eleições** (2022 1º e 2º turno, 2026 1º turno, 2026 2º turno ao vivo) e **replay**: um slider com a porcentagem de urnas apuradas, que lembra a % ao trocar de eleição.
- Tema claro e escuro. O guia visual está em [design.md](design.md).

## Dados e scripts

| Arquivo | O que faz |
|---|---|
| `apuracao.py` | coletor ao vivo (polling com ETag, histórico em SQLite) + servidor local; `--arquivar ID` grava uma eleição em `dados/hist/` |
| `historico2022.py` | gera os resultados finais de 2022 a partir do Portal de Dados Abertos |
| `replay.py` | reduz os Boletins de Urna (hora de chegada por seção) a quadros de 5 min por município, em `dados/hist/<ano>-t<turno>-replay.json` |
| `dados/hist/` | resultados finais e replays já gerados (cerca de 9 MB) |
| `web/index.html` | a página |

`dados/latest.json` e `dados/apuracao.db` são gerados pelo coletor e não são versionados.

## Replay de outras eleições

```bash
python3 replay.py --ano 2022 --turno 1     # baixa os boletins por UF (centenas de MB) e grava o replay
```

Depois, marque `replay:true` na eleição em `ELEICOES` no `web/index.html`.

Limites: o horário usado é `DT_BU_RECEBIDO` (chegada do boletim) e não foi confirmado o fuso. Horários fora da janela de 0,1% a 99,95% de chegada são limitados à borda do eixo.
