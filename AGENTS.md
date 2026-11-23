# Instruções para agentes

Limita as alterações ao ticket, preserva o comportamento existente e segue `CONTRIBUTING.md`. Não incluas credenciais nem ambientes virtuais nos commits.

A partir de `app_notas/`, executa as mesmas verificações do CI:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python run_tests.py
uv export --locked --no-dev --no-hashes --no-emit-project --no-header --output-file /tmp/requirements-ci.txt
diff -u requirements.txt /tmp/requirements-ci.txt
```

Na raiz, verifica os commits da branch face à base atualizada: `python .github/scripts/check_commits.py origin/main`.

Uma alteração está pronta para revisão quando cumpre os critérios do ticket, as verificações locais e do CI passam, todos os `test_*.py` são executados, o lock e o ficheiro de deploy estão atualizados, a documentação necessária foi revista e o PR descreve as alterações e os testes. Pede revisão à outra equipa.
