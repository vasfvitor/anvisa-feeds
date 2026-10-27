# Preços máximos da CMED por produto (`/cmed/dados/`)

Gerados a cada build a partir da lista de preços da CMED (Câmara de Regulação do Mercado de
Medicamentos) publicada pela ANVISA em dados.anvisa.gov.br. Só entram apresentações vendidas em
farmácia, ou seja, com preço máximo ao consumidor (PMC); as de uso hospitalar não têm PMC e ficam de
fora. Preços em **centavos**, como na lista.

## `produtos.json`

`{stamp, publicado_em, produtos: [...]}`. `stamp` é o mês da lista (`AAAAMMDD`), `publicado_em` a data
de publicação da CMED. Cada item:

| campo | o que é |
|---|---|
| `registro_produto` | registro do produto na ANVISA, 9 dígitos (chave de tudo) |
| `produto`, `laboratorio`, `substancia` | nome comercial, laboratório e substância (o valor mais frequente entre as apresentações) |
| `tipo_produto` | Genérico, Similar, Novo, Específico, Biológico, Fitoterápico… |
| `apresentacoes` | quantas apresentações com PMC |
| `comercializado` | `true` se alguma apresentação foi comercializada no ano da lista |

## `produto/<registro_produto>.json`

Os campos do índice, mais `cnpj`, `classe_terapeutica`, `tarja`, `stamp`, `publicado_em` e
`apresentacoes`, uma lista de:

| campo | o que é |
|---|---|
| `ggrem` | código da apresentação na CMED (15 dígitos) |
| `apresentacao` | dose, forma e embalagem, como na lista |
| `eans` | códigos de barras |
| `regime_preco` | `Regulado` ou `Liberado` |
| `comercializado` | comercializada no ano da lista |
| `icms_0` | a lista marca o preço como isento de ICMS |
| `pmc` | preço máximo ao consumidor por alíquota de ICMS: `{"0": c, "12": c, "17": c, "17.5": c, …}` em centavos |
| `pmc_alc` | o mesmo para Áreas de Livre Comércio (sem a alíquota 0) |

## `todos.json`

`{stamp, publicado_em, produtos: [...]}`, em que cada item é exatamente o conteúdo do
`produto/<registro_produto>.json` correspondente, na ordem do índice. É para quem precisa de tudo de
uma vez (cerca de 13 MB, menos de 3 MB comprimido na entrega); para um remédio só, use o arquivo
individual.

A alíquota que vale depende do estado onde o remédio é vendido e, às vezes, do tipo de produto; a
lista da CMED não diz qual estado usa qual alíquota.
