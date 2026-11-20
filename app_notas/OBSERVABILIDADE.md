# Spike — erros e observabilidade

## Objetivo

Provocar uma falha, perceber o seu efeito e descobrir como diagnosticar o problema com logs. Usámos capturas inventadas e não enviámos uma resposta inválida à aplicação de produção.

## 1. Erro inesperado reproduzido

No teste local foi criada uma rota temporária, apenas em memória, que simulou uma resposta `E` e tentou localizá-la na lista de categorias sem validação:

```python
resposta = 'E'
categoria = CATEGORIES[CATEGORIES.index(resposta)]
```

Como `E` não está na lista, `list.index` lançou `ValueError` e o pedido recebeu **HTTP 500 Internal Server Error**. Não houve pedido à NVIDIA. A rota temporária não foi incluída no código nem no deploy.

A aplicação real já validava respostas inválidas antes deste spike. A simulação mostra o que aconteceria se essa validação estivesse ausente; não era um bug comprovado na versão original.

## 2. Logs acrescentados

A aplicação regista eventos JSON em stdout/stderr. Cada pedido recebe um `request_id`; em respostas normais e erros HTTP controlados é devolvido no cabeçalho `X-Request-ID`. Os logs incluem rota, método, estado, duração e, conforme o evento, modelo, categoria válida ou tipo de exceção.

- `classificacao_concluida`: classificação válida.
- `categoria_invalida`: resposta não pertence às categorias; cliente recebe HTTP 502.
- `modelo_indisponivel`: erro na API NVIDIA; cliente recebe HTTP 502.
- `configuracao_em_falta`: chave não configurada; cliente recebe HTTP 503.
- `pedido_concluido`: rota, estado e duração do pedido.
- `pedido_erro_inesperado`: exceção inesperada, com tipo e identificador; a falha continua a produzir HTTP 500.

Erros vão para stderr para aparecerem como erro na Vercel; eventos informativos vão para stdout. Os logs da aplicação não incluem texto da nota, prompt, chave nem resposta livre do modelo. O próprio servidor ou bibliotecas podem produzir logs adicionais; rever sempre o destino e a política de privacidade ao configurar integrações externas.

Exemplo produzido com a resposta simulada `E`:

```json
{"event":"categoria_invalida","request_id":"304ea6d5326c47a0a540518d8bb1e670","modelo":"nvidia/nemotron-3-ultra-550b-a55b","tamanho_resposta":1,"duracao_ms":0}
```

A resposta `E` é simulada, sem chamada ao modelo. O valor da resposta livre não é registado, pois poderia conter informação da nota.

## 3. Reproduzir os testes locais

No terminal:

```bash
cd app_notas
source .venv/bin/activate
pip install httpx
python test_observabilidade.py
```

O teste simula uma resposta `E` e verifica HTTP 502 e o log `categoria_invalida`; simula uma exceção inesperada e verifica HTTP 500 e `pedido_erro_inesperado`; testa também uma resposta válida e que o texto e a chave de teste não aparecem nos logs. Não precisa de chamadas nem quota NVIDIA. O HTTP 500 é intencional no teste.

## 4. Consultar os logs reais

A versão com logs foi publicada em https://entrelinhas-notas.vercel.app. No teste real anterior ao último ajuste de nível, a nota inventada foi classificada como `tarefa` e consultámos os eventos `classificacao_concluida` e `pedido_concluido` na Vercel com o mesmo ID `9c41068e343a4b729a15910f324a08c3`. Foi um pedido bem-sucedido, não um erro 500 em produção.

1. Abrir [projeto Entrelinhas na Vercel](https://vercel.com/jcunha1/entrelinhas-notas).
2. Selecionar **Logs**; filtrar pela rota `/api/classificar`, nível **Error** ou procurar `categoria_invalida` / `pedido_erro_inesperado`.
3. Abrir um pedido para consultar a hora, estado HTTP, identificadores, duração e eventos. O `request_id` dentro do JSON é gerado pela aplicação; a Vercel também apresenta o seu próprio identificador, que é diferente.

No terminal autenticado:

```bash
npx vercel logs --since 1h
npx vercel logs --query 'level:error' --since 1h
```

A [documentação Vercel Runtime Logs](https://vercel.com/docs/logs/runtime) apresenta filtros e retenção por plano. No Hobby, a documentação indica retenção de uma hora; confirma no teu painel/plano.

## 5. Ferramenta de observabilidade: Vercel Logs e Grafana

A opção mais simples para esta aplicação já publicada é **Vercel Runtime Logs**: interface visual, filtros por rota, estado, ambiente e nível, e agrupamento por pedido. Está disponível sem integração adicional e foi efetivamente usado para ler o pedido real acima. Não é preciso instalar nada para este primeiro passo.

Para dashboards e retenção mais rica, o **Grafana com Loki** é uma opção. A arquitetura é:

`FastAPI → logs JSON na Vercel → Log Drain → Loki → Grafana Explore / dashboards`

A [documentação Grafana](https://grafana.com/docs/plugins/grafana-vercel-datasource/latest/) esclarece que o plugin Vercel, por si só, **não lê runtime logs**: é necessário encaminhá-los para Loki e adicionar Loki como fonte de dados. A [Vercel documenta Log Drains para planos Pro e Enterprise](https://vercel.com/docs/functions/logs); disponibilidade e custos devem ser confirmados para a conta antes de aderir. Não foram criadas contas, integrações ou recursos pagos, e Grafana/Loki não foram configurados neste spike.

**OpenTelemetry** é um conjunto de padrões e ferramentas para instrumentar e transportar telemetria (logs, métricas e traces); não é, por si só, um painel equivalente ao Grafana. Seria útil numa fase seguinte para ligar o pedido da aplicação à chamada NVIDIA através de traces, após decidir onde os dados serão recebidos.

## Conclusão

O HTTP 500 reproduzido mostra que uma resposta fora da lista pode causar uma falha inesperada se for usada sem validação. Com validação e logs, uma categoria inválida é identificada por `categoria_invalida`, devolve HTTP 502 e mantém os dados sensíveis fora dos nossos logs. A Vercel já fornece uma interface funcional para investigar pedidos; Grafana/Loki é uma evolução possível, ainda não implementada nem testada.
