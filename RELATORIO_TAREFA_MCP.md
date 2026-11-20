# Tarefa do Grupo 4: o servidor MCP no ar

**Estado: concluída.** O MCP Inspector liga ao URL público e a tool devolve uma categoria.

- **URL público do servidor MCP:** `https://entrelinhas-lime.vercel.app/mcp`
- **Data:** 20/11/2026

---

## Enunciado

1. Criar a rota `/mcp` com o SDK oficial:
   - em Node, o `mcp-handler` da Vercel;
   - em Python, o `mcp` com `stateless_http=True`.
   - Cuidado com o `FastMCP` → `MCPServer` no `mcp` 2.x.
2. Criar a tool `classificar_nota(texto)` → categoria.
3. Validar a chave e rejeitar pedidos sem chave.
4. Guardar um log de cada chamada (tester, categoria, hora) na Upstash.
5. Fazer deploy e testar com o MCP Inspector (`npx @modelcontextprotocol/inspector`) contra o URL público.

**Pronto quando:** o MCP Inspector liga ao URL público e a tool devolve uma categoria.

---

## O que foi feito, ponto a ponto

### 1. ✅ Rota `/mcp` com o SDK oficial

- **Linguagem:** Python, porque a aplicação já era FastAPI. Usámos o SDK oficial `mcp` (versão 2.3.0).
- **Ficheiro:** `app_notas/mcp_server.py`.
- **Servidor:** criado com `MCPServer`, de `mcp.server.mcpserver`. No `mcp` 2.x, o `FastMCP` já não existe.
- **Transporte:** Streamable HTTP com `stateless_http=True`. Cada pedido é independente, o que é necessário em serverless, porque cada pedido pode cair numa instância diferente da Vercel.
- **Problemas resolvidos:**
  - **Parâmetros:** o `stateless_http` passa-se a `streamable_http_app()`, não ao construtor.
  - **Lifespan:** o FastAPI não corre o lifespan de sub-apps montadas, por isso o gestor de sessões MCP arranca no lifespan da app principal.
  - **Proteção contra DNS rebinding:** por defeito, o SDK só aceita `Host: localhost`, o que daria erro 421 na Vercel. Desligámos essa proteção, e o controlo de acesso passa a ser feito pela chave (ponto 3).

### 2. ✅ Tool `classificar_nota(texto)` → categoria

- **Ficheiro:** `app_notas/app.py`.
- **Lógica:** é a mesma da rota do site, `/api/classificar`, através da função partilhada `classificar_texto()`. Usa o modelo da NVIDIA.
- **Resposta:** `{"categoria": "..."}`. A categoria é sempre uma de: agenda, aprendizagem, foco, ideia, outros, pessoal, preocupações, social, tarefa, trabalho.
- **Erros:** um texto vazio, um texto demasiado longo ou uma resposta inválida do modelo dão um erro MCP (`isError: true`), não um crash.

### 3. ✅ Validar a chave e rejeitar pedidos sem chave

- **Onde:** um wrapper ASGI (`ExigirChave`) à volta de `/mcp`.
- **Cabeçalho:** o cliente envia `Authorization: Bearer <chave>`.
- **Uma chave por tester:** as chaves ficam na variável de ambiente `MCP_TESTERS`, no formato `{"nome": "chave"}`. As chaves com menos de 24 caracteres são ignoradas.
- **Respostas de erro:**
  - Sem chave, ou com uma chave inválida: **401**.
  - Sem testers configurados: **503**.
- **O site não muda:** os utilizadores do site (`/` e `/api/*`) continuam sem precisar de chave.

### 4. ✅ Log de cada chamada na Upstash

- **Base de dados:** Upstash Redis `entrelinhas-mcp` (plano free, região `us-east-1`).
- **Stream:** `entrelinhas:mcp:chamadas`, limitado a cerca de 10 000 entradas.
- **Campos de cada entrada:**
  - `tester`: o nome que corresponde à chave usada;
  - `categoria`;
  - `estado`: `ok` ou `erro`;
  - `hora`: em UTC.
- **Privacidade:** o texto da nota **nunca** é guardado.
- **Falhas da Upstash:** se a Upstash falhar, a tool responde na mesma e fica só um aviso no log.
- **Consultar o log:** `XREVRANGE entrelinhas:mcp:chamadas + - COUNT 20`, ou na consola da Upstash, em Data Browser.

### 5. ✅ Deploy e teste com o MCP Inspector

- **Deploy:**
  - Projeto Vercel `grupo4-68c4/entrelinhas`, com deploy feito pelo CLI.
  - As 4 variáveis de ambiente (`NVIDIA_API_KEY`, `MCP_TESTERS`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`) estão configuradas como Secret em Production.
- **Teste com o MCP Inspector (v2.16):**
  - Transporte Streamable HTTP, URL `https://entrelinhas-lime.vercel.app/mcp`.
  - Em Settings → Custom Headers: `Authorization: Bearer <chave>`.
  - Resultado: ligou ao servidor e a tool `classificar_nota` devolveu a categoria.

---

## Provas da verificação

| Teste | Resultado |
|---|---|
| `GET /api/health` (público) | 200 `{"status":"ok"}` |
| `POST /mcp` sem chave | 401 |
| `POST /mcp` com chave errada | 401 |
| `initialize` com chave | 200, servidor `entrelinhas` 1.0.0 |
| `tools/list` | expõe `classificar_nota` |
| `tools/call` "Reuniao com a equipa na sexta as 10h" | `{"categoria": "agenda"}` |
| `tools/call` "Comprar leite e pão amanhã" | `{"categoria": "tarefa"}` |
| MCP Inspector contra o URL público | ligado; a tool devolveu a categoria |
| Log na Upstash | chamadas registadas, incluindo as 3 feitas pelo Inspector (14:00 UTC) |
| Testes locais (`test_mcp.py`, `test_observabilidade.py`, `test_grafana.py`) | todos passam |

---

## Como um tester se liga

O tester recebe só duas coisas: o URL e a sua chave. Não precisa de acesso ao código nem à Vercel.

1. Correr `npx @modelcontextprotocol/inspector`.
2. Adicionar um servidor com o transporte **Streamable HTTP** e o URL `https://entrelinhas-lime.vercel.app/mcp`.
3. Em **Settings → Custom Headers**, adicionar o nome `Authorization` e o valor `Bearer <chave>`.
4. Ligar o servidor, abrir **Tools → classificar_nota**, escrever um texto e carregar em **Run Tool**.

---

## Melhorias feitas depois da tarefa (20/11/2026)

- **Token da Upstash rodado:** o antigo deixou de funcionar. O novo está no `.env` e na Vercel, e confirmámos que o log continua a ser escrito.
- **Uma chave por tester:**
  - 7 testers: jose, joao, marta, cunha, constanca, gabriel, ricardo.
  - As chaves estão em `app_notas/.env.testers.json`, um ficheiro local que fica fora do git e do deploy. Cada pessoa recebe só a sua chave.
  - O tester `local` saiu da produção (a chave dele agora dá 401) e ficou só no `.env`, para testes locais.
- **Gatilho de demonstração removido:** o texto `TESTE OBSERVABILIDADE E` já não provoca um erro 500. Os testes passaram a simular a falha com um mock e passam todos.
- **`.vercelignore` corrigido:** agora exclui `.env*`, e não só o `.env`.

## Pendente (opcional)

- [ ] Apagar do stream da Upstash as entradas de teste dos testers `local` e `jose`.
- [ ] Ligar o repositório GitHub ao projeto Vercel. Atenção: um deploy só é aceite se o autor do último commit pertencer à equipa Vercel `grupo4-68c4`. Até lá, fazer o deploy a partir de uma cópia de `app_notas` fora do repositório git (ver `PROGRESSO_MCP.md`).
