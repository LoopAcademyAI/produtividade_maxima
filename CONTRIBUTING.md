# Contribuir

## Fluxo da semana 1

1. Atualiza a base: `git switch main`, `git fetch origin` e `git pull origin main`.
2. Cria uma branch por subticket: `<equipa>/<subticket>-<descricao>`.
3. Mantém as alterações e o PR pequenos e limitados ao subticket.
4. Escreve commits no formato Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:` ou `style:` seguidos de uma descrição. Um âmbito é opcional, por exemplo `fix(api): corrige resposta`.
5. Antes do PR, volta à `main` e executa `git pull origin main`; atualiza a tua branch com essa versão e resolve conflitos. Verifica novamente os comandos abaixo.
6. Abre o PR para `main`, preenche o modelo e pede revisão à outra equipa. Aguarda as verificações e a aprovação.

## Instalar e validar

Instala o [uv](https://docs.astral.sh/uv/getting-started/installation/) e, a partir da raiz do repositório:

```bash
cd app_notas
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python run_tests.py
```

Para atualizar as dependências, altera `pyproject.toml`, atualiza o lock com `uv lock` e regenera o ficheiro usado pelo deploy:

```bash
uv export --locked --no-dev --no-hashes --no-emit-project --no-header --output-file requirements.txt
```

O CI compara esse resultado com `requirements.txt`. Inclui o lock e o ficheiro gerado no mesmo PR. A verificação de commits do PR pode ser executada na raiz com `python .github/scripts/check_commits.py origin/main` depois de atualizar `origin/main`.
