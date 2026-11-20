# Grupo 5 — implementação e integração

## Estado

Código de acesso e páginas na branch `grupo-5-acessos`; o servidor MCP pertence ao Grupo 4. O Redis real e a integração com o servidor MCP têm de ser configurados e testados antes de anunciar o piloto como funcional.

## Configuração

Configurar `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN` (também são aceites `KV_REST_API_URL` e `KV_REST_API_TOKEN`), `CODIGO_CONVITE` e `MCP_BASE_URL` no ambiente de execução. Não partilhar valores. Criar e associar Redis Upstash à Vercel e fazer novo deployment. O código usa REST e scripts Lua, que devem ser validados no serviço efetivamente escolhido. Para execução local copiar `.env.example` para `.env` e preencher fora do Git.

## Funções para o Grupo 4

`acesso.verificar_chave(chave)` devolve nome ou None. `RedisIndisponivel` significa erro de serviço e não pode permitir acesso. `acesso.registar_chamada(nome, categoria, ms)` grava apenas nome, hora UTC, categoria e duração. Ambas são síncronas; num servidor assíncrono executar em worker/thread. Validar a chave em cada pedido aplicável, incluindo após revogação. O nome deve vir da verificação. O registo representa uma classificação bem-sucedida, não inicialização ou descoberta. Em falha de registo, comunicar erro operacional; as contagens podem ficar incompletas.

As chaves são armazenadas por hash SHA-256. Nome igual substitui o acesso anterior; nome autodeclarado não comprova identidade. Não usar nomes idênticos no piloto. O limite de 30 tentativas/minuto para convite é global: pode bloquear toda a equipa temporariamente. `/uso` mostra os últimos 1000 eventos, não uma contagem histórica integral. O convite é partilhado, não é autorização individual adequada a produção.

## Operação

- Página `/ligar`: gerar URL pessoal. URL inclui credencial; não publicar ou registar em logs.
- Página `/uso`: introduzir convite para consultar metadados.
- Plano B: `python gerar_acesso.py 'Nome'` mostra um URL secreto; entregar individualmente por canal privado.
- Revogação: `python revogar.py 'Nome'`; confirmar o nome exato. Ambos os scripts carregam `.env` do diretório corrente.
- Executar testes: `python -m unittest test_acesso test_paginas_acesso`; testes usam Redis simulado e não comprovam a ligação real.

## Verificações pendentes

1. Criar e configurar Redis real e convite, testar escrita/leitura e scripts Lua no deployment de teste.
2. Confirmar configuração de Vercel Authentication para acesso do cliente externo; não divulgar bypass.
3. Integrar servidor Grupo 4 e testar cliente MCP, revogação em sessão, `/uso`, disponibilidade e logs da Vercel/Grafana.
4. Verificar instruções e planos de cada cliente na versão efetivamente usada. O URL com chave pode ficar em logs e configurações de terceiros; inspecionar e documentar.
5. Remover a falha deliberada de observabilidade antes de piloto real, e executar teste independente e previsão antes da demonstração.

Não existe autenticação individual forte: um convite partilhado permite declarar qualquer nome e substituir o acesso associado. Não usar para dados sensíveis ou produção; evoluir para SSO/OAuth e autorização individual.
