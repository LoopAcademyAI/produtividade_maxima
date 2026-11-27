# R6.2 — Onde chega o resumo?

## Decisão

O resumo diário chega **à página principal da aplicação**, no topo, quando a pessoa
abre ou atualiza a página depois de o resumo ter sido gerado. Não será enviado por
email nem por notificação.

## Custo

**Custo adicional do canal de entrega: 0 €.** A página usa a aplicação, o endpoint e
a base de dados que já existem; não requer contratar ou configurar outro serviço.
Esta estimativa pressupõe que o uso continua dentro das quotas gratuitas da
infraestrutura atual. Não inclui o custo ou as quotas das chamadas ao modelo que
geram o resumo (R6.1), nem eventuais custos por exceder os limites dos fornecedores.

## Porquê

- **Sem serviço adicional:** a página já é o local onde a pessoa consulta as notas.
  Mostrar o resumo ali não exige fornecedor de email, serviço de push, novas
  credenciais ou subscrições do browser.
- **Privacidade:** o resumo fica na aplicação e não é copiado para uma caixa de
  email nem enviado a um serviço externo de notificações.
- **Experiência previsível:** o resumo fica disponível para consulta, sem interromper
  a pessoa com uma notificação. Como é diário, não é necessária entrega imediata.
- **Implementação mais simples:** o fluxo aproveita o armazenamento e a interface
  existentes, reduzindo configuração e pontos de falha.

## Alternativas consideradas

| Canal | Custo adicional de entrega | Motivo para não escolher |
|---|---|---|
| **Página da aplicação — escolhido** | **0 €**, usando a infraestrutura existente e dentro das quotas atuais | Requer abrir ou atualizar a página para ver o resumo, mas não acrescenta serviços nem expõe o conteúdo a um canal externo. |
| Email | Não garantido: pode ser 0 € dentro da quota gratuita de um fornecedor | Exige recolher e validar endereços, gerir credenciais e entregas; os limites gratuitos e a retenção de conteúdo dependem do fornecedor. |
| Notificação do browser | Potencialmente 0 €, dependendo dos serviços e limites usados | Exige permissões, subscrições, service worker e manutenção; é mais intrusiva e pode não chegar se o browser ou dispositivo não estiver disponível. |

## Limite da decisão

Esta decisão escolhe apenas o canal. A página continua a usar o identificador
`X-Utilizador` existente, que separa os dados mas não autentica a identidade da
pessoa; o canal não substitui a decisão de autenticação da R1.2. Este documento não
implementa nem altera a geração, a autenticação ou o envio de resumos.
