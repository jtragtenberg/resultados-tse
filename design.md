# Design — Apuração TSE

Guia visual para o painel de apuração, alinhado à identidade do TSE.

## Fonte das referências

`https://www.tse.jus.br/` responde **403 (Access Denied)** a acessos automatizados, inclusive com navegador headless, então a home institucional **não foi lida**. Este guia se baseia em duas propriedades oficiais do TSE que abrem normalmente, medidas por CSS e por captura de tela:

| Propriedade | O que se mediu |
|---|---|
| [resultados.tse.jus.br](https://resultados.tse.jus.br/) (app oficial de resultados, Angular/Ionic) | amarelo institucional, fundo cinza, cartões, Roboto |
| [dadosabertos.tse.jus.br](https://dadosabertos.tse.jus.br/) (CKAN + Bootstrap) | azul-petróleo, links, etiquetas, tabelas |

Para a marca (logotipo, áreas de proteção, Pantone/CMYK) vale o manual oficial: [Manual de identidade da Justiça Eleitoral](https://www.tse.jus.br/institucional/catalogo-de-publicacoes/arquivos/manual-de-identidade-da-justica-eleitoral). A campanha "Eleições 2022" usa a família Gotham; o app de resultados usa Roboto. Confirme o manual vigente antes de publicar com a marca.

Os valores abaixo marcados como **medido** vieram do CSS ou de pixels reais dessas páginas. Os marcados como **decisão** são escolhas deste projeto.

## Princípios

1. **Institucional e sóbrio:** fundo claro, muito branco, cor só onde há informação. Nada de decoração.
2. **Dados primeiro:** o mapa e os números são o conteúdo. A interface fica em cinza e branco.
3. **Neutralidade partidária:** as cores dos candidatos são só codificação de dados e nunca aparecem em elementos de interface (botões, links, cabeçalhos).
4. **Legível em tempo real:** o estado "sem dados", "apurando" e "final" precisa ser reconhecível de relance.
5. **Acessível:** contraste mínimo AA, informação nunca só por cor, modo escuro suportado.

## Cores

### Identidade (da interface)

| Token | Hex | Uso | Origem |
|---|---|---|---|
| `--tse-amarelo` | `#EBB400` | barra de topo, cartões de eleição, destaque de seleção | medido (resultados.tse.jus.br) |
| `--tse-cinza-fundo` | `#E8E8E8` | fundo da página | medido |
| `--tse-azul-ardosia` | `#6C7EA3` | cartões secundários (eleições suplementares) | medido |
| `--tse-azul-petroleo` | `#003445` | faixa superior escura, rodapés | medido (dadosabertos) |
| `--tse-azul-link` | `#206B82` | links, títulos de lista | medido (dadosabertos, `--bs-primary`) |
| `--tse-azul-claro` | `#C2D2E2` | fundo de bloco de busca/hero | medido |
| `--tse-azul-acao` | `#005CBB` | ação primária no app oficial | medido (CSS) |
| `--tse-texto` | `#1A1B1F` | texto principal | medido (CSS) |
| `--tse-texto-sec` | `#44474E` | texto secundário | medido (CSS) |
| `--tse-borda` | `#DEE2E6` | divisórias, bordas de tabela | medido (Bootstrap) |
| `--tse-erro` | `#BA1A1A` | erro | medido (CSS) |
| `--tse-sucesso` | `#3A833A` | confirmação, totalização final | medido (CSS) |

### Dados (codificação nos mapas)

Usadas só no mapa, na barra de placar e nos números dos candidatos. Já implementadas em [web/index.html](web/index.html).

| Token | Claro | Escuro | Significado |
|---|---|---|---|
| `--cand1` (hoje `--lula`) | `#C8102E` | `#E0405A` | candidato 1 na frente |
| `--cand2` (hoje `--flavio`) | `#1F5FBF` | `#5B97F0` | candidato 2 na frente |
| `--prog` | `#0F7B6C` | `#3FC0AA` | percentual de urnas apuradas |
| abstenção | `#B8860B` | — | escala sequencial |
| brancos | `#6D4FC2` | — | escala sequencial |
| nulos | `#D0489A` | — | escala sequencial |
| `--nada` | `#CFCFCF` | `#444444` | nenhuma urna apurada |

Regras:
- **Vantagem:** interpola de `#DDDDDD` (empate) até a cor do candidato, saturando em 40 pontos percentuais de diferença.
- **Confiança:** a opacidade vai de 35% a 100% conforme as urnas apuradas, então região pouco apurada parece "fraca".
- **Cinza** é exclusivo de "sem urnas apuradas". Nenhuma métrica usa cinza como cor de dado.
- **Amarelo institucional** não é cor de dado, para não confundir com abstenção (`#B8860B`). Use-o apenas em elementos de interface.

## Tipografia

- **Família:** Roboto, com fallback `"Helvetica Neue", Helvetica, Arial, sans-serif` (a mesma pilha do portal de dados abertos).
- **Corpo:** 14 px (0,875 rem) como no portal de dados. Auxiliar e legendas: 12 px.
- **Pesos:** 400 corpo, 500 rótulos e cabeçalhos de tabela, 700 números de destaque e títulos.
- **Números:** `font-variant-numeric: tabular-nums` em tabelas e placares. Formato brasileiro, milhar com ponto e decimal com vírgula (`Intl.NumberFormat("pt-BR")`), percentuais com uma casa (`49,1%`).
- **Hierarquia:** título da página 18 px/700, título de card 16 px/700, destaque numérico 26 px/700.

## Layout e espaçamento

- **Grade:** conteúdo em duas colunas, mapa fluido e painel lateral de 340 px, que passa a uma coluna abaixo de 900 px.
- **Espaçamento:** base de 4 px; gutters de 16 px; padding interno de cards de 12 px.
- **Largura máxima do mapa:** altura limitada a 76 vh para sempre caber na tela.
- **Cabeçalho:** título à esquerda, estado de dados (`eleição · coletado em ... · atualiza a cada 30 s`) à direita, em texto secundário.
- **Linha do tempo de eleições:** logo abaixo do cabeçalho, pontos conectados por uma linha. O ponto ativo é preenchido e em negrito, e o ponto "apurando" é vermelho para sinalizar ao vivo.

## Componentes

| Componente | Especificação |
|---|---|
| **Card** | fundo branco, borda 1 px `--tse-borda`, raio 8 px (o app oficial usa 8 a 12 px), sem sombra pesada |
| **Cartão de eleição** (oficial) | faixa lateral colorida com o ano + conteúdo branco; amarelo para eleição geral, ardósia para suplementares |
| **Botão segmentado** | borda 1 px, raio 6 px, item ativo invertido (fundo `--fg`, texto `--bg`) |
| **Botão** | raio 6 px, borda 1 px, sem cor de marca de partido |
| **Etiqueta (chip)** | raio 100 px, fundo branco, texto escuro (como as "Etiquetas mais recentes" do portal) |
| **Tabela** | cabeçalho em cinza secundário, 13 px, linhas com divisória, linha selecionada com fundo translúcido, ordenável com ▲ ▼ |
| **Barra de progresso** | 10 px, raio 5 px, trilho `--nada`, preenchimento `--prog` |
| **Barra de placar** | 18 px, duas cores lado a lado proporcionais ao voto |
| **Tooltip** | card pequeno, 12 px, segue o ponteiro |
| **Controles de zoom** | coluna de botões de 30 px no canto superior direito do mapa |

## Mapa

- Contornos de 0,4 px (municípios) e 1 px (estados), na cor do fundo, com `vector-effect: non-scaling-stroke` para não engrossar no zoom.
- A região fixada ganha contorno de 2 px na cor do texto.
- Legenda sempre visível, com degradê, valor máximo da escala e o significado do cinza.
- Estados são clicáveis (abrem o mapa por município). Municípios fixam os detalhes no painel.

## Modo escuro

O app já responde a `prefers-color-scheme: dark`. Em escuro, o fundo é `#161616`, o card `#222`, a borda `#383838`, e as cores de dado são clareadas para manter contraste. O amarelo institucional continua só em elementos de interface.

## Acessibilidade

- **Contraste:** texto sobre fundo com razão mínima de 4,5:1. O amarelo `#EBB400` não serve como cor de texto sobre branco (contraste de cerca de 1,9:1). Usá-lo só como fundo, com texto escuro `#1A1B1F`.
- **Não depender só de cor:** todo valor do mapa também aparece em número, no tooltip e no painel, e a tabela repete os percentuais.
- **Teclado:** setas ← e → percorrem a linha do tempo. Botões e linhas da tabela precisam de foco visível (a fazer).
- **Daltonismo:** vermelho × azul é distinguível pelos tipos comuns de daltonismo, e a intensidade e o valor numérico reforçam a leitura.
- **Movimento:** o zoom usa transições curtas de 200 a 250 ms. Respeitar `prefers-reduced-motion` (a fazer).

## O que mudar no código para seguir este guia

1. Trocar `--lula` e `--flavio` por `--cand1` e `--cand2` (os nomes atuais acoplam a interface a uma eleição).
2. Adotar Roboto e os tokens `--tse-*` em [web/index.html](web/index.html). Hoje a fonte é `system-ui` e o fundo é `#F6F5F2`, que não é do TSE.
3. Acrescentar a faixa superior amarela `#EBB400` com título "Apuração 2026" para ancorar a identidade, sem logotipo (o uso da marca depende do manual).
4. Foco visível e `prefers-reduced-motion`.
5. Rodapé com fonte dos dados: "Fonte: TSE — Divulgação de resultados", com horário de geração do arquivo.

## Limites deste documento

- **Home institucional não lida:** `www.tse.jus.br` bloqueou o acesso automático. Se quiser que eu a use como referência, salve a página (HTML e CSS) ou me passe capturas de tela, e eu ajusto os tokens.
- **Valores não verificados:** raios e espaçamentos do app oficial vêm de contagem de CSS, não de medição visual. A fonte do logotipo "Eleições 2026" (Gotham ou similar) não foi confirmada.
- **Marca:** este projeto é independente e não tem vínculo com a Justiça Eleitoral. Não reproduza o logotipo nem sugira chancela oficial.
