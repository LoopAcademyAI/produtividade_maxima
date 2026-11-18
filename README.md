# Captura

**Despeja um pensamento, e ele vai parar ao sítio certo.** O produto da equipa AI · Loop Future Academy 2026.

```
  página web (texto ou voz)  ─┐
  Hermes  + skill captura    ─┼──►  POST /classificar  ──►  as NOSSAS categorias + um número medido
  Claude  + skill captura    ─┤        (este serviço)
  eval/score.py (o marcador) ─┘
```

O que é nosso vive aqui: **as categorias, o classificador e o número**. Os agentes (Hermes, Claude, Pi, …) são clientes: dão-nos canais, voz e lembretes, mas a decisão sobre o que é cada captura é deste serviço. Ver [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Estado em 19 nov (o ponto de partida)

O classificador é o **zero-shot do spike de quarta**. Funciona, mas é fraco. Medido localmente sobre as 34 capturas do golden:

| sistema | accuracy | precision | recall | F1 | tokens/captura |
|---|---|---|---|---|---|
| zero-shot (base) | 0.03 | 0.39 | 0.88 | 0.55 | 82 |

Recall alto e precision baixa: **o modelo acrescenta categorias** a quase todas as capturas. A pergunta de quinta é vossa: **o que vai para dentro de `classificar()`, e porquê?**

## Correr localmente

```bash
uv sync
cp .env.example .env              # e ponham a NVIDIA_API_KEY e uma chave vossa em CAPTURA_KEYS
uv run uvicorn app:app --reload   # http://localhost:8000
uv run pytest                     # testes sem chamar a API
```

## Medir

```bash
uv run python eval/score.py --local --nome "a minha melhoria"           # o classificador, sem servidor
uv run python eval/score.py --url https://<url> --chave <chave>         # o deploy: é este que conta na sexta
uv run python eval/via_agente.py --cmd 'hermes -z {prompt}' --n 10      # através de um agente
```

**Regras do marcador (as de quarta):** o `score()` e o `data/golden.csv` não se mudam. Nada de regras à medida das 34 capturas: na sexta há capturas novas que nunca viram.

## A API

| Método | Caminho | Auth | O quê |
|---|---|---|---|
| GET | `/` | não | A página web (texto + ditado por voz no browser) |
| GET | `/saude` | não | `{"ok": true}` |
| GET | `/categorias` | não | As categorias |
| POST | `/classificar` | `Authorization: Bearer <chave>` | `{"texto": "...", "origem": "web"}` → `{"categorias": [...], "modelo", "tokens_prompt", "tokens_resposta", "segundos"}` |
| GET | `/docs` | não | Documentação automática do FastAPI |

Erros: `401` sem chave válida · `422` texto vazio ou com mais de 2000 caracteres · `429` limite de pedidos (20/min, 300/dia por pessoa) · `502` o modelo falhou.

Cada pedido escreve uma linha JSON nos logs (utilizador, origem, modelo, tokens, segundos). **O texto da captura não é registado.**

## Ligar um agente

A skill está em [`skill/captura/SKILL.md`](skill/captura/SKILL.md) (formato Agent Skills: funciona no Hermes, no Claude e noutros).

**Hermes:**
```bash
cp -r skill/captura ~/.hermes/skills/
echo "CAPTURA_URL=https://<url>" >> ~/.hermes/.env
echo "CAPTURA_KEY=<a-tua-chave>" >> ~/.hermes/.env
hermes -z "Guarda isto: tenho de devolver o carregador ao João"
```

**Claude Code:** `cp -r skill/captura ~/.claude/skills/` e as duas variáveis no ambiente.

## Pastas

| | |
|---|---|
| `app.py` | O serviço (FastAPI) |
| `captura/` | Categorias, classificador, chaves e limites |
| `static/index.html` | A página |
| `skill/captura/` | A skill para agentes |
| `eval/` | O marcador (direto, por URL, por agente) |
| `data/golden.csv` | As 34 capturas do quadro (não se mudam) |
| `docs/` | Arquitetura, deploy, decisões, desafios |
