# Pacote para outro grupo — Entrelinhas

Este diretório contém uma aplicação FastAPI que recebe uma nota, chama o classificador NVIDIA e apresenta a categoria prevista. Inclui envio opcional de eventos técnicos para Grafana Cloud Loki.

## Segurança do pacote

Este pacote não inclui chaves, tokens, ficheiros `.env`, credenciais Vercel, diretórios `.vercel` ou ambientes virtuais. Antes de o partilhar, confirma o conteúdo com:

```bash
unzip -l entrelinhas-deploy-sem-credenciais.zip
```

O outro grupo deve criar as **suas próprias** credenciais. Nunca devem receber nem reutilizar as do grupo original.

## Executar localmente

```bash
cd app_notas
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env e inserir apenas a NVIDIA_API_KEY do próprio grupo
uvicorn app:app --reload
```

Abrir `http://127.0.0.1:8000`. Sem `NVIDIA_API_KEY`, a rota de classificação responde com erro controlado, mas `/api/health` continua disponível.

## Deploy na Vercel

1. Criar um repositório novo com o conteúdo recebido e ligá-lo a um projeto Vercel.
2. Definir `app_notas` como **Root Directory**. A Vercel reconhece a aplicação FastAPI através de `app.py`.
3. Em **Settings → Environment Variables**, criar `NVIDIA_API_KEY` como **Secret**, para Production (e Preview se pretendido).
4. Fazer deploy e testar `https://<dominio>/api/health`.
5. Inserir uma nota na página inicial e confirmar que a categoria devolvida pertence à lista prevista.

As notas são guardadas no `localStorage` do navegador neste protótipo. Não são uma base de dados partilhada entre utilizadores/dispositivos. O texto da nota é enviado à NVIDIA para a classificação.

## Grafana Cloud / Loki

1. Criar um stack Grafana Cloud próprio e abrir **Logs / Loki**.
2. Criar um token limitado a escrita de logs (`logs:write`). Guardar o URL Loki, o user/instance ID e o token.
3. Na Vercel, criar como **Secrets** de Production:

   - `LOKI_PUSH_URL` — termina em `/loki/api/v1/push`;
   - `LOKI_USER` — ID de instância Loki;
   - `LOKI_TOKEN` — token `logs:write`.

4. Fazer novo deploy. Importar `grafana/dashboard.json` no Grafana e escolher a fonte Loki do stack.
5. Em Explore, confirmar que aparecem eventos com:

```logql
{service_name="entrelinhas"} | json
```

Para erros:

```logql
{service_name="entrelinhas"} | json | nivel="error"
```

Os eventos enviados não incluem o texto da nota, o prompt ou credenciais. Os logs nativos da Vercel continuam a ser consultados na Vercel.

## Demonstração de erro

O gatilho de demonstração (o texto `TESTE OBSERVABILIDADE E`, que provocava um HTTP 500) foi removido a 20/11/2026. O erro `pedido_erro_inesperado` continua a ser verificado nos testes locais (`test_observabilidade.py` e `test_grafana.py`), que simulam a falha sem a expor em produção.

Testes locais:

```bash
cd app_notas
pip install httpx
python test_observabilidade.py
python test_grafana.py
```

## Como servir funcionários em segurança

Este protótipo não deve ser aberto diretamente a todos os funcionários sem estas evoluções:

1. Login da empresa via SSO/MFA e uma identidade por utilizador.
2. Base de dados com notas privadas por defeito e regras de acesso explícitas.
3. Chaves de modelos só no servidor; nunca em prompts, browsers, GPTs ou repositórios.
4. Deteção/redação de dados sensíveis antes de chamar modelos externos; retenção e eliminação definidas.
5. Auditoria técnica sem texto das notas e revisão de permissões/retenção com segurança e DPO.
6. Uma API central para a classificação; ChatGPT, Claude e outras interfaces apenas chamam esta API autenticada. Assim, a lógica e as categorias ficam controladas pela organização.

Para utilizar ChatGPT ou Claude, escolher planos empresariais/API e configurar SSO, grupos e políticas próprias. Contas pessoais não devem ser o canal aprovado para notas de trabalho ou dados sensíveis.
