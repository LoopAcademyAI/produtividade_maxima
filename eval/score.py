"""O marcador do spike de quarta, agora contra o serviço a sério.

    uv run python eval/score.py --url https://<o-vosso-url> --chave <chave>   # o deploy (o que conta na sexta)
    uv run python eval/score.py --local                                      # o classificador, sem servidor

As métricas são as de quarta, sem mudanças: accuracy (exata), precision, recall e F1 no geral,
tokens e segundos por captura. Grava cada previsão em eval/resultados/ para poderem ler os erros.
"""

import argparse
import csv
import datetime
import json
import pathlib
import sys
import time

AQUI = pathlib.Path(__file__).parent
sys.path.insert(0, str(AQUI.parent))


def carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        return [{"texto": r["texto"], "categorias": {c.strip() for c in r["categorias"].split(",") if c.strip()}}
                for r in csv.DictReader(f)]


def via_url(url, chave):
    import httpx

    cliente = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {chave}"}, timeout=60)

    def classificar(texto):
        for tentativa in range(6):
            r = cliente.post("/classificar", json={"texto": texto, "origem": "score"})
            if r.status_code == 429:  # o nosso próprio limite por minuto: esperamos e tentamos outra vez
                print(f"  … 429 ({r.json().get('detail')}), à espera 15 s")
                time.sleep(15)
                continue
            r.raise_for_status()
            d = r.json()
            return set(d["categorias"]), d["tokens_prompt"] + d["tokens_resposta"]
        r.raise_for_status()

    return classificar


def via_local():
    from captura.classificador import classificar as c

    def classificar(texto):
        r = c(texto)
        return r.categorias, r.tokens_prompt + r.tokens_resposta

    return classificar


def score(nome, classificar, dados, mostrar_erros=8):
    tp = fp = fn = exatas = tokens = 0
    linhas, inicio = [], time.time()
    for g in dados:
        t0 = time.time()
        try:
            prev, tok = classificar(g["texto"])
        except Exception as erro:  # uma falha conta como "não previu nada", e fica registada
            prev, tok = set(), 0
            print(f"  ! falhou: {g['texto'][:50]!r} ({type(erro).__name__}: {erro})")
        certas = g["categorias"]
        tp += len(prev & certas); fp += len(prev - certas); fn += len(certas - prev)
        exatas += prev == certas
        tokens += tok
        linhas.append({"texto": g["texto"], "certas": sorted(certas), "previstas": sorted(prev),
                       "certo": prev == certas, "segundos": round(time.time() - t0, 2)})
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    n = len(dados)
    linha = {"sistema": nome, "capturas": n, "accuracy": round(exatas / n, 2), "precision": round(p, 2),
             "recall": round(r, 2), "f1": round(f1, 2), "tokens/captura": round(tokens / n),
             "seg/captura": round((time.time() - inicio) / n, 2)}
    print(json.dumps(linha, ensure_ascii=False))
    erros = [l for l in linhas if not l["certo"]]
    print(f"\n{len(erros)} erros. Alguns (texto · certas → previstas):")
    for e in erros[:mostrar_erros]:
        print(f"   {e['texto'][:70]!r} · {e['certas']} → {e['previstas']}")
    return linha, linhas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    onde = ap.add_mutually_exclusive_group(required=True)
    onde.add_argument("--url", help="URL do serviço deployed")
    onde.add_argument("--local", action="store_true", help="chama o classificador diretamente")
    ap.add_argument("--chave", help="a vossa chave (ou CAPTURA_KEY no ambiente)")
    ap.add_argument("--dados", default=str(AQUI.parent / "data" / "golden.csv"))
    ap.add_argument("--nome", help="nome no marcador (ex.: 'few-shot 2 por categoria')")
    args = ap.parse_args()

    dados = carregar(args.dados)
    if args.url:
        import os
        chave = args.chave or os.environ.get("CAPTURA_KEY")
        if not chave:
            ap.error("falta --chave (ou CAPTURA_KEY)")
        classificar, nome = via_url(args.url, chave), args.nome or f"url · {args.url}"
    else:
        classificar, nome = via_local(), args.nome or "local"

    linha, linhas = score(nome, classificar, dados)
    pasta = AQUI / "resultados"
    pasta.mkdir(exist_ok=True)
    ficheiro = pasta / f"{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    ficheiro.write_text(json.dumps({"resumo": linha, "capturas": linhas}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nGravado em {ficheiro.relative_to(AQUI.parent)}")


if __name__ == "__main__":
    main()
