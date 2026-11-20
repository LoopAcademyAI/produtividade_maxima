# Servidor MCP — ponto de situação

Resumo para retomar o trabalho noutra sessão. Não contém segredos.

## Objetivo (5 passos)

1. ✅ Rota `/mcp` com o SDK oficial Python (`mcp` 2.x, `stateless_http=True`)
2. ✅ Tool `classificar_nota(texto) → categoria`
3. ✅ Validar a chave e rejeitar pedidos sem chave
4. ✅ Log de cada chamada (tester, categoria, hora) na Upstash
5. ✅ Deploy na Vercel (https://entrelinhas-lime.vercel.app/mcp) e teste com o MCP Inspector v2.16 (Settings → Custom Headers → `Authorization: Bearer <chave>`). Relatório: `RELATORIO_TAREFA_MCP.md`

## Onde está o código

- `app_notas/mcp_server.py`: cria o `MCPServer` e o sub-app Streamable HTTP. A classe `McpApp` cria um sub-app novo em cada arranque do lifespan.
- `app_notas/app.py`:
  - `classificar_texto()`: lógica partilhada pela rota `/api/classificar` e pela tool.
  - Tool `classificar_nota`: devolve `{"categoria": ...}` e, em caso de erro, `ToolError` (`isError: true`).
  - `ExigirChave`: wrapper ASGI à volta de `/mcp` (401 sem chave ou com chave inválida, 503 sem testers configurados).
  - `registar_chamada_mcp()`: `XADD` via REST para a Upstash.
  - `app.mount('/', ExigirChave(mcp_app))`: tem de ficar no **fim** do ficheiro.
- `app_notas/test_mcp.py`: testes da rota, das chaves e do log, com a NVIDIA e a Upstash simuladas.
- Os testes antigos (`test_observabilidade.py`, `test_grafana.py`) continuam a passar.

## Decisões tomadas

- **Python** (FastAPI já existente), não Node.
- **Quem usa o quê:**
  - Os utilizadores do site continuam sem chave: `/` e `/api/*` ficam abertos.
  - Os **testers** são pessoas com um cliente MCP (Inspector, Claude, Cursor). Recebem de nós só o URL `/mcp` e a sua chave, e nunca acedem ao backend.
- **Uma chave por tester:**
  - A variável de ambiente `MCP_TESTERS` tem o formato `{"nome": "chave", ...}`.
  - O cliente envia `Authorization: Bearer <chave>`.
  - As chaves com menos de 24 caracteres são ignoradas.
  - Gerar uma chave: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
  - O nome do tester vem da chave validada (fica em `scope['state']['tester']`) e a tool lê-o via `ctx.request_context.request.state`.
- **Log na Upstash:**
  - Stream `entrelinhas:mcp:chamadas`, com `XADD ... MAXLEN ~ 10000`.
  - Campos: `tester`, `categoria`, `estado` (`ok` ou `erro`) e `hora` (ISO, UTC). **Nunca o texto da nota.**
  - Se a Upstash falhar, a tool responde na mesma e fica só um aviso no log.
  - Só aceita URLs `https://*.upstash.io`.
  - Para consultar: `XREVRANGE entrelinhas:mcp:chamadas + - COUNT 20`, ou na consola em Data Browser.
- **Base de dados Upstash:** `entrelinhas-mcp`, plano free, região `us-east-1` (ao lado da região por defeito da Vercel, `iad1`).

## Armadilhas já resolvidas (não repetir)

- **mcp 2.x:** `FastMCP` foi removido. Usar `from mcp.server.mcpserver import MCPServer`.
  - O `stateless_http` passa-se a `streamable_http_app()`, não ao construtor.
  - Os tipos (por exemplo, `ToolAnnotations`) vêm de `mcp_types`.
- **Lifespan:** o FastAPI não corre o lifespan de sub-apps montadas. O `session_manager.run()` é chamado no lifespan do FastAPI, e só pode correr uma vez por instância (daí a `McpApp`).
- **DNS rebinding:** por defeito o SDK só aceita `Host: localhost`, o que daria 421 na Vercel. Está desligado explicitamente; o controlo de acesso é feito pela chave.
- **Windows Smart App Control:** bloqueia a DLL do `pydantic_core`. A app corre no **WSL (Ubuntu)** com o venv em `~/.venvs/entrelinhas`. Correr localmente:
  ```bash
  cd "/mnt/c/Users/HP/Desktop/Academia Loop/produtividade_maxima/app_notas"
  source ~/.venvs/entrelinhas/bin/activate
  uvicorn app:app --reload --port 8000
  python test_mcp.py && python test_observabilidade.py && python test_grafana.py
  ```
- **Node.js LTS** já está instalado no Windows (preciso para o `npx`).
- **MCP da Upstash** configurado no Claude Code (`~/.claude.json`), com autenticação OAuth.

## Deploy (feito a 2026-11-20)

- Projeto Vercel `grupo4-68c4/entrelinhas`, ligado a partir de `app_notas/` (`.vercel/project.json`). Deploy pelo CLI: `npx vercel deploy --prod --yes`. A ligação ao GitHub falhou, por isso não há deploy automático por push.
- URL de produção: `https://entrelinhas-lime.vercel.app`.
- As 4 variáveis estão em Production como Secret (`npx vercel env ls`).
- Testado com curl: `/api/health` dá 200; `/mcp` sem chave ou com chave errada dá 401; `initialize`, `tools/list` e `tools/call` funcionam; o log chega à Upstash.
- **O lifespan corre na Vercel**, por isso esse pendente fica fechado.
- No Windows, o `node`/`npx` não está no PATH das shells do Claude Code: usar `C:\Program Files\nodejs`.
- Para testar com curl no Git Bash com acentos, enviar o corpo com `--data-binary @ficheiro.json`, porque `-d '...'` estraga o UTF-8.

## Pendente

- [x] Rodar o token da Upstash: feito a 2026-11-20, atualizado no `.env` e na Vercel.
- [x] Chaves dos testers: estão em `app_notas/.env.testers.json`, que fica fora do git e do deploy. O tester `local` só existe no `.env` local.
- [x] Gatilho `TESTE OBSERVABILIDADE E` removido.
- [ ] Opcional: apagar as entradas de teste dos testers `local` e `jose` no stream.

## Como fazer o deploy agora

- O deploy a partir do repositório falha com "commit author doesn't have access to this team", porque o último commit é de um colega que não está na equipa Vercel.
- Alternativa: copiar `app_notas` (sem `.env*`, `.venv` e `__pycache__`, mas com o `.vercel/`) para uma pasta fora do git e correr lá `npx vercel deploy --prod --yes`.
- Para alterar variáveis: `npx vercel env add NOME --environment production --sensitive --force --yes`, com o valor enviado pelo stdin. O `env rm` exige aprovação humana.

## Forma de trabalhar

Um passo de cada vez, com revisão pelo utilizador entre passos. Respostas em português (PT).
