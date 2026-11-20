# Grafana Cloud + Loki para Entrelinhas

## Estado

A aplicação tem envio opcional de **eventos próprios** para Grafana Cloud Logs (Loki). A ligação real foi configurada em produção e verificada: o dashboard recebeu um erro HTTP 500 provocado e uma classificação de teste bem-sucedida. Não é necessário um Log Drain da Vercel. A integração não exporta automaticamente os logs da plataforma, de bibliotecas nem stack traces; estes continuam nos logs da Vercel.

O envio é síncrono, com timeout de 1,5 s por evento, e não impede a resposta se o Grafana falhar. Contudo, pode adicionar latência; numa função serverless, eventos podem perder-se em timeouts ou interrupções. É uma solução didática, não uma entrega garantida nem um pipeline de produção. A configuração incompleta desativa o envio. Os dados enviados são metadados da aplicação: identificador de pedido, rota, método, estado, categoria, modelo, duração e tipo de erro. Não enviamos texto de notas, respostas livres ou chaves nos eventos próprios.

## Preparar a conta

1. Criar conta em [Grafana Cloud](https://grafana.com/products/cloud/). Consultar os limites do plano escolhido antes de confirmar a adesão.
2. No portal Grafana Cloud, abrir o stack e as instruções para enviar logs para **Grafana Loki / Logs**. Obter o URL de ingestão Loki, o **user/instance ID** e criar um token com permissão de escrita de logs. A interface pode mudar; seguir as indicações do próprio stack. Usa o endpoint de push que termina em `/loki/api/v1/push`.
3. Não coloques o token no código, em ficheiros versionados ou no chat. O domínio de ingestão tem de terminar em `.grafana.net`, usar HTTPS e não ter query string.
4. Na Vercel, em **Entrelinhas → Settings → Environment Variables**, criar estas três variáveis para **Production** como **Secret**:

   - `LOKI_PUSH_URL`: URL completo, por exemplo `https://logs-xxx.grafana.net/loki/api/v1/push`.
   - `LOKI_USER`: ID de utilizador/instância Loki, que pode ser diferente do login Grafana.
   - `LOKI_TOKEN`: token de escrita de logs criado no Grafana Cloud.

5. Fazer um novo deploy de produção: as alterações de variáveis aplicam-se a novos deployments. Não partilhes estes valores no chat.

## Dashboard

1. No Grafana, verificar que a fonte de dados **Loki** do stack está disponível.
2. Criar ou importar dashboard, carregar [dashboard.json](dashboard.json) e selecionar a fonte Loki.
3. Em **Explore**, escolher Loki e experimentar:

```logql
{service_name="entrelinhas"} | json
```

Para encontrar erros:

```logql
{service_name="entrelinhas"} | json | nivel="error"
```

4. Para gerar o erro de demonstração já existente, escrever `TESTE OBSERVABILIDADE E` na aplicação. Deve ocorrer HTTP 500 e surgir `pedido_erro_inesperado` no Grafana. Usar também os logs Vercel para confirmar; se não aparecer no Grafana, procurar `grafana_envio_falhou` ou `grafana_configuracao_invalida` na Vercel.
5. O dashboard já foi importado no stack e confirmado com eventos reais de erro e sucesso.

A URL é validada para evitar envio acidental de credenciais a destinos fora de `*.grafana.net`. Se o teu stack usar domínio personalizado, é necessário adaptar a validação de forma explícita. A Vercel continua a manter os seus próprios logs. O botão de erro de teste continua ativo até o removermos depois da demonstração.

## Testar o código localmente

```bash
cd app_notas
source .venv/bin/activate
pip install httpx
python test_grafana.py
python test_observabilidade.py
```

O primeiro teste simula a API de ingestão e verifica o evento do erro, a falha de envio e o bloqueio de domínios inválidos. O segundo verifica os códigos HTTP e que a nota não é incluída nos logs. Não cria recursos Grafana nem envia dados reais.

Referências: [API de envio Loki](https://grafana.com/docs/loki/latest/reference/loki-http-api/#ingest-logs), [Logs no Grafana Cloud](https://grafana.com/docs/grafana-cloud/send-data/logs/), [Drains Vercel](https://vercel.com/docs/drains/using-drains).

## Partilha com outro grupo

Cada grupo deve criar o seu próprio stack, política `logs:write` e token no Grafana Cloud, e guardá-los como Secrets na sua Vercel. Não reutilizar stacks, URLs de dashboards, tokens ou outras credenciais de outro grupo. O erro `TESTE OBSERVABILIDADE E` permanece ativo apenas para demonstração e deve ser removido antes de disponibilizar a aplicação a utilizadores reais.
