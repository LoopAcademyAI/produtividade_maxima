"""Executa todos os scripts test_*.py, também os adicionados no futuro."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    tests = sorted(root.rglob("test_*.py"))
    tests = [
        path
        for path in tests
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    if not tests:
        print("Nenhum ficheiro test_*.py encontrado.", file=sys.stderr)
        return 1
    for test in tests:
        print(f"A executar {test.relative_to(root)}", flush=True)
        result = subprocess.run([sys.executable, str(test)], cwd=root, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
