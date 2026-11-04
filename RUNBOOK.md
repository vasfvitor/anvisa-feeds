# RUNBOOK do anvisa-feeds

O que fazer quando um workflow deste repo fica vermelho. Comece pelo
[RUNBOOK do anvisa-hub](https://github.com/vasfvitor/anvisa-hub/blob/main/RUNBOOK.md): lá estão o mapa
dos seis repos, a rotina e o que vale para todos (rodar de novo, run cinza, lockfile, Pages).

As mensagens aparecem aqui como o log mostra, em inglês. Procure com Ctrl+F um trecho da mensagem que
você viu. `<subfila>`, `N` e afins marcam a parte que muda.

Quem cria ou muda um alarme ou uma mensagem de erro atualiza este arquivo no mesmo commit.

## Índice

| Workflow / job | Trecho da mensagem | Entrada |
|---|---|---|
| crawl / crawl | issue "Coleta incompleta" | [Coleta incompleta](#coleta-incompleta) |
| crawl / crawl | `"subfilas_crawled": 0`, `from Cloudflare`, `token request failed` | [Nenhuma subfila respondeu](#nenhuma-subfila-respondeu) |
| crawl / crawl | `no ANVISA credentials` | [Credenciais ausentes](#credenciais-ausentes) |
| crawl / crawl | `Traceback`, `ValidationError` | [Coleta parou no meio](#coleta-parou-no-meio) |
| crawl / crawl | `git push`, `CONFLICT` | [Commit do snapshot falhou](#commit-do-snapshot-falhou) |
| crawl / cmed | `rows against`, `refusing it` | [Lista da CMED encolheu](#lista-da-cmed-encolheu) |
| crawl / cmed | `update anvisa/dados/cmed.py`, `ALIQUOTAS` | [Formato da CMED mudou](#formato-da-cmed-mudou) |
| crawl / cmed | `HTTP`, `no Last-Modified header` | [Download da CMED falhou](#download-da-cmed-falhou) |
| crawl / cmed | `gh release create` | [Release da CMED falhou](#release-da-cmed-falhou) |
| crawl / deploy | issue "O cmed/dados saiu sem os dados do anvisa-api" | [anvisa-api não foi lido](#anvisa-api-não-foi-lido) |
| crawl / deploy | issue "Lista da CMED com N dias", `the CMED list is missing` | [Lista da CMED velha](#lista-da-cmed-velha) |
| crawl / build, deploy | `no snapshots to build from`, `Traceback`, deploy | [Build ou deploy falhou](#build-ou-deploy-falhou) |
| ci | ruff, pytest, build | [Lint, formato ou testes](#lint-formato-ou-testes) |

## crawl

Roda todo dia às 09:00 UTC (06:00 em Brasília). Também roda, só com build, quando um push muda `src/`,
`pyproject.toml`, `uv.lock` ou o próprio workflow. Tem quatro jobs:

1. **crawl:** pede a fila de cada subfila à API da ANVISA e faz commit do snapshot do dia.
2. **cmed:** duas consultas condicionais à lista da CMED. Só faz commit quando a lista mudou.
3. **build:** monta o site a partir dos snapshots. Roda mesmo quando a coleta falhou.
4. **deploy:** publica no Pages e, depois, confere as fontes vindas do anvisa-api e a idade da lista da
   CMED.

Uma falha num job não apaga o trabalho dos outros. Quando a coleta falha, o site é montado com o último
snapshot bom e um aviso em todas as páginas.

Três causas de fora do código não deixam o run vermelho: abrem uma issue com o label `alerta`, que fecha
sozinha quando a situação normaliza (ver o RUNBOOK do hub, "Issues de alerta"). São elas: coleta
incompleta, `cmed/dados` sem os dados do anvisa-api e lista da CMED com mais de 45 dias. O run fica verde,
com um aviso amarelo.

**Para rodar de novo:** Actions → crawl → "Run workflow" no `main`. Não use "Re-run jobs": ele parte do
commit antigo e o `git pull --rebase` do snapshot do dia entra em conflito. Com `build_only` marcado, ele
só remonta o site, sem fazer nenhuma requisição à ANVISA.

### Coleta incompleta

- **Onde aparece:** a issue "Coleta incompleta: N de M subfilas não responderam", aberta pelo job crawl
  (passo "Alarm issue for an incomplete crawl"). O run fica verde.
- **Mensagem:** a issue lista as subfilas, com o erro de cada uma, como no passo Crawl:
  `subfila <id>: <Erro>: <mensagem>`. Por exemplo,
  `RateLimitError: HTTP 429: rate limit exceeded (25 burst, 1 request/s)`, ou `ReadTimeout` depois de
  `retry 2/2`.
- **O que quer dizer:** mais de 10% das subfilas não responderam. O snapshot parcial já foi commitado e
  publicado.
- **O site foi afetado?** Saiu parcial. As subfilas que falharam mostram a última fila coletada, com
  "não coletada em <dia>", e todas as páginas têm o aviso "A coleta de hoje ficou incompleta".
- **Agir ou esperar:** esperar. A API da ANVISA estava instável ou o limite de requisições foi atingido.
  A issue fecha sozinha na primeira coleta com 10% de falhas ou menos.
- **Pedir ajuda quando:** a issue ficar aberta vários dias seguidos.

### Nenhuma subfila respondeu

- **Onde aparece:** job crawl, passo Crawl.
- **Mensagens:** o JSON da coleta com `"subfilas_crawled": 0`, e o processo termina com código 1. Antes
  dele, uma destas:
  - `HTTP 403 from Cloudflare: the request was blocked before reaching ANVISA. ...`
  - `token request failed: HTTP <código>`
  - a mesma linha `subfila <id>: ...` repetida em todas as subfilas.
- **O que quer dizer:** a coleta inteira falhou. Pode ser o portal de APIs fora do ar, o token negado ou
  um bloqueio do Cloudflare.
- **O site foi afetado?** Nada foi commitado. O site é montado com o último snapshot bom e o aviso "A
  coleta de hoje falhou; estes dados são da última coleta bem-sucedida."
- **Agir ou esperar:** esperar um dia.
- **O que fazer se repetir:**
  - **`token request failed`:** entrar em https://api.anvisa.gov.br/ com a conta gov.br e conferir se
    as credenciais ainda valem. Se forem novas, atualizar os secrets `ANVISA_CLIENT_ID` e
    `ANVISA_CLIENT_SECRET` (Settings → Secrets and variables → Actions).
  - **403 do Cloudflare:** a ANVISA bloqueou o acesso. Não contornar. Pedir ajuda.

### Credenciais ausentes

- **Onde aparece:** job crawl, passo Crawl.
- **Mensagem:** `error: no ANVISA credentials: set ANVISA_CLIENT_ID and ANVISA_CLIENT_SECRET, ...`
- **O que quer dizer:** os secrets do repo não chegaram ao workflow.
- **O que fazer:** em Settings → Secrets and variables → Actions, conferir se `ANVISA_CLIENT_ID` e
  `ANVISA_CLIENT_SECRET` existem. As credenciais vêm de https://api.anvisa.gov.br/ (login gov.br).

### Coleta parou no meio

- **Onde aparece:** job crawl, passo Crawl, com um `Traceback` do Python. Por exemplo, um
  `ValidationError` ou um erro de conexão durante a leitura do catálogo, que é refeita às segundas.
- **O que quer dizer:** a ANVISA mudou o formato de uma resposta, ou a leitura do catálogo caiu. A
  leitura do catálogo não tem nova tentativa.
- **O site foi afetado?** O dia não foi coletado. O site segue com o último snapshot bom e o aviso.
- **O que fazer:** rodar de novo uma vez ("Run workflow").
- **Pedir ajuda quando:** repetir.

### Commit do snapshot falhou

- **Onde aparece:** job crawl, passo "Commit and push the snapshot", com uma saída do `git` (por exemplo,
  `CONFLICT`).
- **O que quer dizer:** o snapshot foi coletado, mas não chegou ao `main`.
- **O site foi afetado?** O build roda, mas não encontra o snapshot do dia. Por isso o aviso diz que a
  coleta falhou, mesmo ela tendo funcionado.
- **O que fazer:** o snapshot fica guardado 90 dias como artifact `snapshot-<dia>` na página do run.
  1. Baixar o artifact (página do run → Artifacts).
  2. Extrair os arquivos dentro de `snapshots/`.
  3. Commit e push.
- **Pedir ajuda quando:** não tiver certeza do que ficou no `main`.

## crawl / job cmed

A lista de preços da CMED muda uma vez por mês. Quando ela muda, o job cria uma Release `cmed-<data>`
com os dois CSVs e faz commit do snapshot em `snapshots/cmed/`. Em qualquer falha deste job, o build
segue e as páginas da CMED ficam com o mês anterior, sem aviso. O job fica vermelho de novo todo dia até
a causa ser resolvida.

### Lista da CMED encolheu

- **Mensagem:** `snapshot <data>: N rows against M in <anterior>; refusing it (rerun with a lower --min-rows-ratio if the list really shrank)`
- **O que quer dizer:** a lista nova tem menos de 95% das linhas da anterior. O job recusa, para não
  publicar uma lista cortada.
- **Agir ou esperar:** esperar um dia. Se a CMED publicou um arquivo incompleto, ela costuma corrigir.
- **Se a lista encolheu de verdade** (a CMED tirou produtos), aceite a lista nova uma vez:
  1. confira na página da CMED que a lista nova está certa;
  2. Actions → crawl → "Run workflow", com `cmed_min_rows_ratio` menor que a proporção da mensagem (N
     dividido por M). Por exemplo, 24.000 contra 26.000 dá 0,92: use `0.9`;
  3. o run seguinte, agendado, volta ao padrão (0.95).
- **Pedir ajuda quando:** não tiver certeza de que a lista nova está certa.

### Formato da CMED mudou

- **Mensagens** (vêm da biblioteca `anvisa`):
  - `TA_PRECO_MEDICAMENTO.csv: price column '<coluna>' (<nome>) is not in COLUMNS; add the rate to ALIQUOTAS in anvisa/dados/cmed.py`
  - `...: unknown column '<coluna>'; update anvisa/dados/cmed.py`
  - `...: missing columns [...]; update anvisa/dados/cmed.py`
- **O que quer dizer:** a CMED mudou as colunas da lista. A mais provável é uma alíquota nova de ICMS,
  quando um estado muda a lei.
- **Agir ou esperar:** agir, em três repos:
  1. corrigir o leitor no anvisa-api (ver o
     [RUNBOOK do anvisa-api](https://github.com/vasfvitor/anvisa-api/blob/main/RUNBOOK.md#cmed-mudou-ou-a-cópia-da-dcb-está-errada));
  2. lançar uma versão nova no PyPI;
  3. subir a versão em `pyproject.toml` e no `uv.lock` deste repo.

  O portal também precisa saber da alíquota nova (`icms.ts`). Pedir ajuda.

### Download da CMED falhou

- **Mensagens:**
  - `HTTP <código> for <url>`;
  - `<url>: got N of M bytes (truncated)`;
  - `<url>: <erro> (after 3 attempts)`;
  - `TA_PRECO_MEDICAMENTO.csv: no Last-Modified header, cannot name the month`.
- **O que quer dizer:** o servidor da ANVISA não entregou a lista, ou entregou sem a data.
- **Agir ou esperar:** esperar. O run do dia seguinte tenta de novo.
- **Pedir ajuda quando:** passar de uma semana.

### Release da CMED falhou

- **Onde aparece:** passo "Keep the month's raw files in a Release".
- **O que quer dizer:** quase sempre, a Release `cmed-<data>` já existe. Isso acontece quando o mesmo mês
  é coletado duas vezes, por exemplo depois de um run que criou a Release e falhou no push.
- **O site foi afetado?** O mês novo não entra; as páginas ficam com o anterior.
- **Agir ou esperar:** pedir ajuda. É um problema conhecido: este passo não aceita rodar duas vezes.

## crawl / jobs build e deploy

### anvisa-api não foi lido

- **Onde aparece:** a issue "O cmed/dados saiu sem os dados do anvisa-api", aberta pelo job deploy depois
  do deploy. O run fica verde.
- **Mensagens**, no log do passo "Check the anvisa-api sources and the CMED list's age":
  - `cmed/dados went out without the registration status and measures (anvisa-api could not be read)`
  - `cmed/dados went out without the official names (anvisa-api could not be read)`
  - No log do job build: `situação dos registros: fonte indisponível (...)` e
    `nomes oficiais (DCB): fonte indisponível (...)`.
- **O que quer dizer:** o build não conseguiu ler as tabelas do anvisa-api. São elas que dizem se cada
  registro está ativo, as medidas da ANVISA e os nomes oficiais (DCB).
- **O site foi afetado?** Saiu sem essas informações. O portal mostra "Nesta atualização do site não foi
  possível conferir na ANVISA se o registro está ativo nem se há medidas sobre este remédio." Preços e
  feeds saíram normais.
- **O que fazer:**
  1. Abrir o [RUNBOOK do anvisa-api](https://github.com/vasfvitor/anvisa-api/blob/main/RUNBOOK.md) e ver
     se o `dados` de lá está vermelho.
  2. Se a mensagem do build disser `schema_version`, o contrato do anvisa-api mudou. Pedir ajuda.
  3. Senão, esperar. O próximo run lê de novo, e a issue fecha sozinha quando o build voltar a ler o
     anvisa-api.

### Lista da CMED velha

- **Onde aparece:** a issue "Lista da CMED com N dias", aberta pelo job deploy. O run fica verde.
- **O que quer dizer:** a lista da CMED publicada tem mais de 45 dias. A CMED publica uma por mês. A lista
  atual é de 09/10/2026, então a issue pode abrir por volta de 24/11/2026.
- **O site foi afetado?** As páginas mostram a lista antiga. Os preços continuam valendo até a CMED
  publicar outra.
- **Agir ou esperar:** esperar. Se quiser conferir, a página da CMED é
  https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos.
- **Pedir ajuda quando:** a CMED publicou uma lista nova e o job cmed não a pegou (ver as entradas
  acima).
- **Vermelho, com `::error::the CMED list is missing`:** o site saiu sem lista da CMED nenhuma. Isso não
  é atraso da CMED, é um problema no build. Pedir ajuda.

### Build ou deploy falhou

- **Mensagens:** `no snapshots to build from`, um `Traceback` no passo "Build the site", ou um erro do
  `deploy-pages`.
- **O site foi afetado?** O deploy anterior continua no ar.
- **O que fazer:** rodar de novo com `build_only` marcado. Se for o deploy, ver o RUNBOOK do hub, "Deploy
  do Pages falhou".
- **Pedir ajuda quando:** o build repetir o erro.

## ci

Roda em push e em pull request: `uv sync --locked`, `ruff`, `pytest` e um build a partir dos snapshots
commitados. Não publica nada. O deploy vem do workflow crawl.

### Lint, formato ou testes

- **O que fazer**, na máquina:

  ```bash
  uv sync
  uv run ruff check . && uv run ruff format .
  uv run pytest
  ```

- Os testes usam só fixtures. Se começarem a falhar depois de subir a versão da biblioteca `anvisa`, a
  mudança veio de lá.

## Problemas conhecidos

Achados em 2026-11-03, ainda sem correção.

- **404 em tudo vira filas "esvaziadas".** A ANVISA responde 404 para uma subfila vazia. Se ela passar a
  responder 404 para todas, cada fila sai como esvaziada, com o run verde e muitos eventos de saída nos
  feeds e no ritmo. Fase 3.
- **Subfila removida parece vazia.** O catálogo só é relido às segundas. Até lá, uma subfila que a
  ANVISA tirou aparece como vazia.
- **Sem alarme de idade da fila.** Se o cron parar, nada fica vermelho. Só a linha "Última coleta
  bem-sucedida" nas páginas mostra. Fase 2.
- **A Release da CMED não pode rodar duas vezes.** Ver
  [Release da CMED falhou](#release-da-cmed-falhou). Fase 3.
- **Situação e medidas são tão velhas quanto o anvisa-api.** Nada aqui confere a idade delas. Desde
  13/10/2026 a ANVISA não atualiza os arquivos de registro, e o alarme disso fica no anvisa-api.
- **Coleta incompleta de até 10% passa sem vermelho.** Só aparece no rodapé ("N subfilas falharam") e no
  índice ("não coletada hoje").
