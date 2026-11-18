---
name: captura
description: Classifica uma captura (um pensamento, tarefa, lembrete, ideia ou preocupação que o utilizador despeja) nas categorias do serviço Captura (agenda, aprendizagem, foco, ideia, outros, pessoal, preocupações, social, tarefa, trabalho). Usar sempre que o utilizador pedir para guardar, organizar ou classificar uma captura, ou mandar um pensamento solto para arrumar.
version: 0.1.0
author: Loop Future Academy · AI Track 2026
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  env_vars: [CAPTURA_URL, CAPTURA_KEY]
  commands: [curl]
metadata:
  hermes:
    tags: [Produtividade, Classificação, Loop Future Academy]
---

# Captura · classificar um pensamento solto

O serviço Captura recebe um texto e devolve as categorias certas. **As categorias são do serviço, não tuas:** não inventes categorias nem classifiques tu. Chama o serviço e usa a resposta.

## Como chamar

Envia o texto da captura **tal como o utilizador o escreveu ou disse**: sem resumir, corrigir ou traduzir. O serviço foi medido com capturas desarrumadas, e é assim que funciona melhor.

```bash
curl -sS -X POST "$CAPTURA_URL/classificar" \
  -H "Authorization: Bearer $CAPTURA_KEY" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"texto": sys.argv[1], "origem": "agente"}))' "TEXTO DA CAPTURA AQUI")"
```

Usa `python3` (ou `jq -Rs`) para construir o JSON: assim aspas, acentos e quebras de linha no texto não partem o pedido.

A resposta é assim:

```json
{"categorias": ["tarefa"], "modelo": "nvidia/nemotron-3.5-bolt-e4b", "tokens_prompt": 74, "tokens_resposta": 3, "segundos": 0.6}
```

## O que dizer ao utilizador

- Responde com as categorias, curto: `→ tarefa` (ou `→ agenda, trabalho` se vierem várias).
- Se `categorias` vier vazia: diz que o serviço não encontrou categoria e pergunta onde a pôr. Não escolhas tu.
- Se o utilizador mandar **várias capturas de uma vez**, chama o serviço uma vez por captura.

## Erros

| Código | Significa | O que fazer |
|---|---|---|
| 401 | Chave inválida ou em falta | Diz ao utilizador que falta configurar `CAPTURA_KEY`. Não tentes outra vez. |
| 429 | Limite de pedidos | Diz quanto falta esperar (vem em `detail`). Não insistas em ciclo. |
| 502 | O modelo do serviço falhou | Tenta **uma** vez mais. Se falhar, diz que falhou. |

## Configurar

```bash
# no Hermes: ${HERMES_HOME:-~/.hermes}/.env
CAPTURA_URL=https://<o-url-do-serviço>
CAPTURA_KEY=<a-tua-chave>
```

Nunca escrevas a chave na conversa nem em ficheiros do projeto.
