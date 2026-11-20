# Grupo 4 + Grupo 5 — contrato de integração MCP

Este documento explica o que o Grupo 5 preparou e como juntar o servidor MCP do Grupo 4. É um contrato para o piloto; não representa uma solução de autenticação empresarial.

## Estado atual

- Código base: repositório `josepedrocunhazzz/produtividade_maxima`, branch `main`.
- Alterações do Grupo 5: branch `grupo-5-acessos`, dentro de `app_notas/`.
- Vercel: projeto `entrelinhas-notas`, domínio `https://entrelinhas-notas.vercel.app`. O projeto existente não estava ligado automaticamente ao Git na última verificação.
- Redis Upstash: base `entrelinhas-redis`, Dublin, plano Free, ligada a Preview e Production. `PING` devolveu `PONG`; a aplicação e os scripts Lua ainda não foram testados contra a base real. Os dois ambientes partilham a mesma base.
- `/ligar`, `/uso` e `acesso.py` estão no código da branch do Grupo 5; ainda não estão publicados no domínio final. `/mcp` será entregue pelo Grupo 4.
- Os testes existentes do Grupo 5 passam com Redis simulado; isto não comprova acesso remoto, integração MCP nem teste externo.

## O que disponibilizamos

Dentro de `app_notas/acesso.py`:

```python
def verificar_chave(chave: str) -> str | None: ...
def registar_chamada(nome: str, categoria: str, ms: int) -> None: ...
```

`verificar_chave` devolve o nome para uma chave válida e `None` para ausente, inválida ou revogada. Pode levantar `acesso.RedisIndisponivel` quando a configuração ou a ligação falham; nesse caso não autorizar, devolver um erro de serviço e não registar dados sensíveis. As funções são síncronas: código assíncrono deve chamá-las num worker/thread. Os detalhes de Redis ficam no Grupo 5.

`registar_chamada` guarda nome, hora UTC, categoria e duração em milissegundos, apenas para uma classificação bem-sucedida. Não passar o texto da nota, prompt, chave ou URL. Se o registo falhar depois de a classificação ter terminado, tratar a falha sem voltar a executar automaticamente a tool; a contagem pode ficar incompleta. O limite atual é de 1000 eventos e a contagem da página reflete apenas os eventos conservados.

## O que o Grupo 4 deve implementar

1. Servidor MCP HTTP em `/mcp` e uma tool de classificação que use a lógica e categorias da aplicação existente.
2. Ler a chave de `https://entrelinhas-notas.vercel.app/mcp?key=<chave>` em cada pedido MCP relevante. Autenticar a inicialização, descoberta e chamadas consoante o transporte efetivamente usado; pedidos sem chave ou com chave inválida devem ser recusados com 401 antes da tool.
3. Chamar `verificar_chave` novamente nos pedidos relevantes, inclusive numa sessão já iniciada, para a revogação ter efeito. Nunca confiar num nome enviado pelo cliente: usar o nome devolvido pela verificação.
4. Medir a duração da tool, validar a categoria e chamar `registar_chamada(nome, categoria, ms)` uma vez por classificação concluída. Não contar handshake ou descoberta como chamadas da tool.
5. Não imprimir chave, URL com query string, texto da nota ou prompt nos logs. Inspecionar também os logs da infraestrutura: chaves em URLs podem ser registadas fora da aplicação.
6. Informar o Grupo 5 sobre nome da tool, parâmetros, formato de resposta, biblioteca MCP e ficheiros/dependências alterados. Testar HTTP MCP e ciclo de vida serverless na Vercel com um cliente real; não assumir que todos os clientes aceitam query string ou sessões de igual modo.

### Pseudocódigo de integração

O local concreto depende da implementação MCP; verificar a chave na fronteira dos pedidos, não apenas dentro da função da tool.

```text
pedido HTTP MCP chega com key
  nome = executar_em_thread(verificar_chave, key)
  se RedisIndisponivel: devolver 503
  se nome é None: devolver 401
  permitir protocolo MCP com identidade nome

quando a tool de classificação for chamada:
  iniciar cronómetro
  categoria = classificar(nota)
  validar categoria
  ms = duração da tool
  executar_em_thread(registar_chamada, nome, categoria, ms)
  devolver categoria
```

Definir em conjunto o tratamento de falha no registo e a propagação segura da identidade por pedido. Este exemplo não é um servidor MCP pronto a usar.

## Como juntar as branches

1. Cada grupo atualiza a sua branch a partir da base acordada. O Grupo 4 desenvolve na sua branch; não altera diretamente a branch `grupo-5-acessos` sem coordenação.
2. Criar pull requests ou outra revisão combinada. Rever conflitos especialmente em `app_notas/app.py`, `requirements.txt` e rotas. Preservar a app existente, `/ligar`, `/uso`, Grafana e `/mcp`.
3. Integrar numa branch comum de teste ou por PR para a branch acordada; correr `python -m unittest test_acesso test_paginas_acesso` em `app_notas/`, os testes do Grupo 4 e os testes anteriores de observabilidade. Estes incluem simulações, pelo que não substituem teste real.
4. O proprietário da Vercel configura `CODIGO_CONVITE` como segredo e `MCP_BASE_URL` com o domínio HTTPS do ambiente. `KV_REST_API_URL` e `KV_REST_API_TOKEN` já foram ligados ao projeto; verificar nomes/ambientes sem revelar valores. Após alterar variáveis é necessário um novo deployment.
5. Fazer deployment de teste no projeto correto. Verificar se Vercel Authentication permite ao cliente externo chegar a `/ligar` e `/mcp`, sem partilhar tokens de bypass. Preview e Production usam atualmente a mesma base: distinguir testes por nomes e evitar interferir com utilizadores reais.
6. Testar de ponta a ponta e só depois decidir publicação no domínio final. O projeto Vercel existente foi publicado pela CLI e não está automaticamente ligado ao Git; o responsável deve confirmar o procedimento de deploy e o rollback.

## Teste conjunto obrigatório

| Cenário | Esperado |
|---|---|
| Código de convite errado | Sem chave e sem dados de `/uso` |
| Chave em falta ou falsa | HTTP 401; tool não é executada |
| Criar chave em `/ligar` | URL pessoal emitido; não o incluir em prints ou relatórios |
| Ligar cliente real e classificar nota fictícia | Tool descoberta, categoria válida e evento em `/uso` |
| Verificação dos dados | Nome, hora, categoria e ms; sem conteúdo da nota |
| Revogar chave e repetir na mesma sessão | Acesso recusado |
| Redis indisponível | Acesso recusado; erro de serviço, nunca acesso permitido |
| Logs Vercel/Grafana | Verificar que não mostram nota, convite ou URL secreto |
| Teste externo | Pessoa fora dos grupos completa o percurso no seu computador sem ajuda |

Executar também uma escrita/leitura segura e os scripts Lua no Redis real antes da demonstração. Remover a falha intencional de observabilidade existente antes do piloto real. Registar a previsão em `docs/` antes do teste externo.

## Limitações do piloto

O convite é partilhado e o nome é autodeclarado: alguém com o convite pode declarar outro nome e substituir-lhe a chave. Os URLs contêm credenciais e podem surgir no histórico, configurações de cliente e logs. Não usar com notas sensíveis nem apresentar como SSO/segurança empresarial. Para produção, evoluir para autenticação individual OAuth/SSO, autorizações, expiração e proteção dos dados.
