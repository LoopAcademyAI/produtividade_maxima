"""As mesmas capturas, mas através de um agente com a skill instalada. O número mantém-se?

    uv run python eval/via_agente.py --cmd 'hermes -z {prompt}' --n 10
    uv run python eval/via_agente.py --cmd 'claude -p {prompt}' --n 10

O agente pode reescrever a captura, decidir não chamar o serviço, ou inventar uma categoria.
Tudo isso aparece aqui como erro. Para saber se o serviço foi mesmo chamado, comparem com os logs
do serviço (pedidos com "origem": "agente").
"""

import argparse
import pathlib
import shlex
import subprocess
import sys

AQUI = pathlib.Path(__file__).parent
sys.path.insert(0, str(AQUI.parent))

from captura.categorias import CATEGORIAS  # noqa: E402
from eval.score import carregar, score  # noqa: E402

PEDIDO = "Guarda esta captura: {texto}"


def via_agente(cmd, pedido, timeout):
    def classificar(texto):
        prompt = pedido.format(texto=texto)
        args = [a.replace("{prompt}", prompt) for a in shlex.split(cmd)]
        saida = subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
        ultima = saida.strip().lower()
        # Lemos as categorias que o agente disse. Se disser outra coisa ("clima"), não conta.
        return {c for c in CATEGORIAS if c in ultima}, 0

    return classificar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmd", required=True, help="comando do agente, com {prompt} no sítio da mensagem")
    ap.add_argument("--pedido", default=PEDIDO, help="como o utilizador fala com o agente ({texto} = a captura)")
    ap.add_argument("--n", type=int, default=10, help="quantas capturas (cada uma demora segundos)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--dados", default=str(AQUI.parent / "data" / "golden.csv"))
    args = ap.parse_args()

    dados = carregar(args.dados)[: args.n]
    nome = f"agente · {shlex.split(args.cmd)[0]} · \"{args.pedido}\""
    score(nome, via_agente(args.cmd, args.pedido, args.timeout), dados)
    print("\nOs tokens do agente não estão contados aqui (só os do serviço, nos logs). Quanto custa o agente?")


if __name__ == "__main__":
    main()
