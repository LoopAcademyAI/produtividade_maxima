# Deploy a 0 €

O PDF *Deploy a 0 €* explica o porquê. Isto é o como.

## O que está no ar

- **Plataforma:** Vercel, plano Hobby (gratuito, sem cartão). O FastAPI corre como função serverless.
- **Segredos** (Settings → Environment Variables, nunca no repo): `NVIDIA_API_KEY`, `CAPTURA_KEYS`.
- **O que isto implica:**
  - **Cold start:** o primeiro pedido depois de uma pausa demora mais. Meçam-no.
  - **Sem disco:** nada do que o serviço escrever sobrevive. Por isso, por agora, não guardamos nada.
  - **O limite de pedidos vive na memória de cada instância.** Se a Vercel arrancar várias, cada uma conta à parte. Para um MVP chega; para produção, precisaria de um contador partilhado (Redis, base de dados).

## Fazer deploy

```bash
npm i -g vercel        # uma vez
vercel login
vercel link            # liga a pasta a um projeto
vercel env add NVIDIA_API_KEY production
vercel env add CAPTURA_KEYS production     # "nome:chave,nome:chave"
vercel --prod
```

Depois de cada deploy, **corram o marcador contra o URL**, e não contra o localhost:

```bash
uv run python eval/score.py --url https://<projeto>.vercel.app --chave <chave>
```

## Se quiserem outra plataforma

O serviço é um FastAPI normal: corre em qualquer sítio que corra Python. No **Render** (free web service), o comando de arranque é `uvicorn app:app --host 0.0.0.0 --port $PORT`; adormece ao fim de 15 minutos sem pedidos e demora cerca de um minuto a acordar. No **Hugging Face Spaces**, os Spaces Docker exigem um plano pago (verificado a 18 nov 2026). Comparem: cold start, limites, logs, onde ficam os segredos.

## Gerar chaves para pessoas novas

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(16))"
```

Acrescentem `nome:chave` ao `CAPTURA_KEYS` na Vercel e façam deploy outra vez (as variáveis só entram num deploy novo).
