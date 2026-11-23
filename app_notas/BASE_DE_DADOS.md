# Base de dados (R1): o que foi decidido por vocês, e porquê

Este ramo foi preparado pelos formadores. Normalmente seriam vocês a decidir. Desta vez decidimos nós, porque todo o resto da semana depende disto: listar notas (R2), aprovar mudanças (R3), rever a semana (R5) e o resumo diário (R6) precisam de notas guardadas no servidor. Se esta decisão demorasse a segunda-feira inteira, nenhum outro ticket podia começar. Aqui fica o raciocínio, para o poderem contestar.

## O problema

Até sexta, as notas viviam no `localStorage` do navegador. Isso quer dizer que:

- só existiam naquele navegador: noutro telemóvel, ou no Claude Code, não havia notas;
- um agente nosso não as conseguia ler, porque estavam no browser e não no servidor;
- limpar os dados do navegador apagava tudo.

Na demo, os testers pediram para **listar as notas** e perguntar **"o que tenho para fazer?"**. Com `localStorage`, nada disso é possível.

## As restrições

1. **0 €.** Ninguém tem conta paga e não há cartão.
2. **Vercel serverless.** Cada pedido pode correr numa máquina nova, e o disco não sobrevive entre pedidos. Por isso **SQLite num ficheiro não serve em produção**: as notas desapareciam.
3. **SQL.** Já o aprenderam no módulo de bases de dados, e as perguntas do agente ("notas de agenda desta semana") são perguntas SQL.
4. **Ligar em minutos**, sem servidor nosso para manter.

## As opções que pesámos

| Opção | A favor | Contra |
|---|---|---|
| **Neon Postgres** (Vercel Marketplace) ✅ | Postgres a sério; plano gratuito; integração com o Vercel num clique; a ligação chega como variável de ambiente | Quando não há uso, a base "adormece" e o primeiro pedido demora mais (*cold start*); limites do plano gratuito |
| Supabase | Postgres, com autenticação incluída | Mais peças do que precisamos agora; projetos gratuitos pausam por inatividade |
| Turso (SQLite na cloud) | SQLite, que é simples | Outro driver, outro dialeto, e pouco do que aprenderam aplica-se diretamente |
| Upstash Redis / Vercel Blob | Muito simples | Não é uma base relacional: filtrar por categoria e data fica connosco |

**Decisão: Neon Postgres.** Os limites do plano gratuito que consultámos (outubro de 2026) foram 1 GB e 100 horas de computação por mês e por projeto ([neon.com/pricing](https://neon.com/pricing)). Uma nota tem menos de 1 KB, por isso cabe mais de um milhão.

## O que muda no código

- `db.py`: ligação à base de dados, uma por pedido (em serverless não há processo que fique vivo). Em produção usa Postgres através de `DATABASE_URL`. Em local e nos testes usa SQLite, sem configurar nada.
- `app.py`: as rotas novas `POST /api/notas`, `GET /api/notas?categoria=&q=`, `DELETE /api/notas/{id}` e `POST /api/notas/importar`. A rota `/api/classificar` continua igual, para os clientes que já a usam (a skill e o MCP).
- `public/index.html`: a página passa a usar a API. Na primeira visita, as notas antigas do `localStorage` passam para o servidor.
- `test_notas.py`: testes de criar, listar, apagar, importar e separar utilizadores. Correm em SQLite e foram corridos também num Postgres 16.

## O que **não** está feito (e é de propósito)

- **Não há contas.** Cada navegador gera um identificador (`X-Utilizador`). Isso separa as notas de cada pessoa, mas **não é autenticação**: quem souber o identificador lê as notas. Fica como ticket, porque escolher a forma de autenticação é uma decisão vossa.
- **Não há migrações.** A tabela é criada se não existir. Se mudarem colunas, precisam de uma estratégia de migrações.
- **A procura é `LIKE`**, não semântica. Os embeddings da semana 1 podem entrar aqui.

## Ligar em produção (quem é dono do projeto no Vercel)

1. Vercel → o projeto → **Storage** → **Create Database** → **Neon** (Marketplace) → plano **Free** → ligar a este projeto (todos os ambientes).
2. Em **Settings → Environment Variables**, confirmem que apareceu `DATABASE_URL` (ou `POSTGRES_URL`; o código aceita as duas).
3. Façam merge deste PR (ou **Redeploy**). A tabela é criada no primeiro pedido.
4. Testem no URL: adicionem uma nota, recarreguem a página, abram noutro navegador. Noutro navegador **não** devem ver as notas: o identificador é outro.

## Correr em local

```bash
cd app_notas
uv run --with-requirements requirements.txt --with httpx python test_notas.py
uvicorn app:app --reload        # usa notas.db (SQLite), ignorado pelo Git
```
