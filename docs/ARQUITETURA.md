# Arquitetura · porquê um serviço, e os agentes como clientes

## A pergunta de quarta

*"O Hermes já faz canais, voz, lembretes e memória. O que é nosso?"*

A resposta que este esqueleto propõe (e que vocês podem rejeitar com evidência):

- **Nosso:** as categorias (incluindo Preocupações e Foco), o classificador, e **um número medido** sobre as nossas capturas.
- **Não é nosso:** Telegram, transcrição de voz, lembretes a uma hora, memória. Há agentes que já fazem isso bem.

Então o que é nosso fica num **serviço pequeno e independente**, e os agentes ligam-se a ele.

## As peças

| Peça | Corre onde | Precisa de estar sempre ligada? | Guarda estado? |
|---|---|---|---|
| Serviço `/classificar` | Free tier (Vercel) | Não: só responde a pedidos | Não (só logs) |
| Página web | Servida pelo serviço | Não | Só no browser de quem usa |
| Hermes + skill | Máquina de quem o usa | **Sim** (gateway, cron) | Sim (`~/.hermes`) |
| Claude + skill | App ou Claude Code de quem o usa | Não | — |

**Porque é que isto resolve o deploy a 0 €:** um serviço que só responde a pedidos cabe num free tier que adormece. O que tem de estar sempre ligado (o gateway do Hermes, os lembretes) é problema de quem corre o agente, não nosso. Se o Hermes fosse a nossa base, éramos nós a precisar de uma máquina sempre ligada, com disco que não se apaga. Isso não existe de graça.

## O que esta arquitetura custa

- **Perdemos o controlo da experiência dentro do agente.** O agente pode reescrever a captura, decidir não chamar o serviço, ou inventar uma categoria. Ensaio de 18 nov: com o pedido "Que categoria dás tu a: 'será que chove amanhã?'", o Hermes **não chamou o serviço** e respondeu "clima / previsão do tempo".
- **Voz:** na página, só no browser (Web Speech API, não funciona no Firefox). Por Telegram, só com um agente que transcreva (o Hermes faz).
- **Onde ficam as capturas?** Hoje, em lado nenhum (só a lista na página, no browser). Guardá-las é uma decisão: de quem são, onde vivem, quem as pode ver.

## Quando mudaríamos de ideia

- Se o número **através do agente** for muito pior do que o número **direto**, e não conseguirmos corrigir com a skill.
- Se o produto passar a ser os lembretes e a memória, e não a classificação.
- Se aparecer uma forma gratuita e fiável de correr um agente sempre ligado.
