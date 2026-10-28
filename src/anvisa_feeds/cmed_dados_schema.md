# Preços máximos da CMED por produto (`/cmed/dados/`)

Gerados a cada build a partir da lista de preços da CMED (Câmara de Regulação do Mercado de
Medicamentos) publicada pela ANVISA em dados.anvisa.gov.br. Só entram apresentações vendidas em
farmácia, ou seja, com preço máximo ao consumidor (PMC); as de uso hospitalar quase sempre não têm PMC
e ficam de fora. As poucas que a lista marca como de uso hospitalar e mesmo assim traz com PMC (7 na
lista de 09/10/2026) entram com `restricao_hospitalar: true`. A linha sem registro (`-` na lista) fica
de fora. Preços em **centavos**, como na lista: cada alíquota é uma coluna da própria CMED, nenhuma é
calculada aqui.

## `produtos.json`

`{stamp, publicado_em, produtos: [...]}`. `stamp` é o mês da lista (`AAAAMMDD`), `publicado_em` a data
de publicação da CMED. Cada item:

| campo | o que é |
|---|---|
| `registro_produto` | registro do produto na ANVISA, 9 dígitos (chave de tudo) |
| `produto`, `laboratorio`, `substancia` | nome comercial, laboratório e substância (o valor mais frequente entre as apresentações) |
| `tipo_produto` | Genérico, Similar, Novo, Específico, Biológico, Fitoterápico… |
| `apresentacoes` | quantas apresentações com PMC |
| `comercializado` | `true` se alguma apresentação teve comercialização informada no ano a que a lista se refere (`comercializacao_periodo` da apresentação) |

## `produto/<registro_produto>.json`

Os campos do índice, mais `cnpj`, `classe_terapeutica`, `tarja`, `stamp`, `publicado_em`,
`feed_substancia` (URL do feed Atom da substância, `cmed/substancia/<slug>.xml`, ou `null` sem
substância; use esta URL em vez de montar o slug), `situacao`, `medidas` e `apresentacoes`.

`situacao` e `medidas` vêm dos dados abertos da ANVISA convertidos pelo
[anvisa-api](https://vasfvitor.github.io/anvisa-api/) (tabelas `medicamentos_por_produto` e `medidas`),
pelo mesmo `registro_produto`. Os dois campos **ficam de fora** quando aquela fonte não pôde ser lida no
build; então não há como dizer nada sobre o registro.

| campo | o que é |
|---|---|
| `situacao` | `{ativo, vencimento}`: `ativo` é `true` quando o registro está Ativo na ANVISA (a ANVISA só publica Ativo e Inativo); `vencimento` é o mês em que o registro vence (`AAAA-MM`) ou `null`. `null` quando a ANVISA não traz o registro |
| `medidas` | medidas de fiscalização da ANVISA que citam o registro, da mais recente à mais antiga: `{data, acoes, atividades, processo}`. `data` é a última publicação (`AAAA-MM-DD`); `acoes` (Suspensão, Recolhimento, Proibição, Apreensão…) e `atividades` (Comercialização, Uso, Propaganda, Voluntário…) como a ANVISA escreve; `processo` é o da medida. A fonte não traz o lote: uma medida pode valer só para alguns lotes. Lista vazia quando não há nenhuma |

`apresentacoes` é uma lista de:

| campo | o que é |
|---|---|
| `ggrem` | código da apresentação na CMED (15 dígitos) |
| `apresentacao` | dose, forma e embalagem, como na lista |
| `eans` | códigos de barras |
| `regime_preco` | `Regulado` ou `Liberado` |
| `comercializado` | a empresa informou comercialização no ano `comercializacao_periodo`; `false` não quer dizer descontinuado, só que não houve venda informada naquele ano |
| `comercializacao_periodo` | o ano a que `comercializado` se refere, como no cabeçalho da lista (`"2025"` na lista de 09/10/2026) |
| `restricao_hospitalar` | a lista marca a apresentação como de uso hospitalar (a farmácia não vende) |
| `icms_0` | a lista marca o preço como isento de ICMS: vale a coluna `"0"`, e as outras alíquotas não se aplicam |
| `pmc` | preço máximo ao consumidor por alíquota de ICMS: `{"0": c, "12": c, "17": c, "17.5": c, …}` em centavos |
| `pmc_alc` | o mesmo para Áreas de Livre Comércio (sem a alíquota 0) |

## `todos.json`

`{stamp, publicado_em, produtos: [...]}`, em que cada item é exatamente o conteúdo do
`produto/<registro_produto>.json` correspondente, na ordem do índice. É para quem precisa de tudo de
uma vez (cerca de 13 MB, menos de 3 MB comprimido na entrega); para um remédio só, use o arquivo
individual.

A alíquota que vale depende do estado onde o remédio é vendido e, às vezes, do tipo de produto; a
lista da CMED não diz qual estado usa qual alíquota.
