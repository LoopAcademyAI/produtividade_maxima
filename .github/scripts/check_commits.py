"""Valida os assuntos de todos os commits exclusivos da branch de um PR."""
import re
import subprocess
import sys

PATTERN = re.compile(r"^(feat|fix|test|docs|refactor|chore|style)(\([\w./-]+\))?!?: \S.*$")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python .github/scripts/check_commits.py <commit-base>", file=sys.stderr)
        return 2
    commits = git("rev-list", "--no-merges", f"{sys.argv[1]}..HEAD").splitlines()
    invalid = []
    for commit in commits:
        subject = git("show", "-s", "--format=%s", commit)
        if not PATTERN.fullmatch(subject):
            invalid.append((commit[:12], subject))
    if invalid:
        for commit, subject in invalid:
            print(f"Commit inválido {commit}: {subject}", file=sys.stderr)
        print("Formato esperado: feat|fix|test|docs|refactor|chore|style: descrição", file=sys.stderr)
        return 1
    print(f"Conventional Commits: {len(commits)} commit(s) válidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
