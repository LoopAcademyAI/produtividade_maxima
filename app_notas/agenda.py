"""Parser antigo por regras, mantido como baseline de comparação offline."""

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DIAS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "sabadp": 5,
    "domingo": 6,
}
MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def extrair_quando(texto: str, referencia: datetime | None = None) -> str | None:
    """Retorna uma data ISO, ou data/hora local ISO, apenas quando reconhecida.

    `referencia` permite avaliações repetíveis; em produção usa Europe/Lisbon.
    """
    if referencia is None:
        referencia = datetime.now(ZoneInfo("Europe/Lisbon"))
    base = referencia.date()
    texto = "".join(
        c
        for c in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(c)
    )
    # Não interpretar frases negadas ou intervalos como um único compromisso.
    if re.search(r"\b(nao|sem|entre|ate|proximo|proxima|passado|passada)\b", texto):
        return None

    datas: list[date] = []
    invalida = False
    # Recolher ocorrências, mesmo repetidas, para recusar mais de uma data.
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", texto):
        try:
            datas.append(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            invalida = True
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])", texto):
        try:
            dia, mes = int(m[1]), int(m[2])
            ano = int(m[3]) if m[3] else base.year
            data = date(ano, mes, dia)
            if not m[3] and data < base:
                data = date(ano + 1, mes, dia)
            datas.append(data)
        except ValueError:
            invalida = True
    meses = "|".join(MESES)
    for m in re.finditer(
        rf"\b(\d{{1,2}})\s+de\s+({meses})(?:\s+de\s+(\d{{4}}))?\b", texto
    ):
        try:
            dia, mes = int(m[1]), MESES[m[2]]
            ano = int(m[3]) if m[3] else base.year
            data = date(ano, mes, dia)
            if not m[3] and data < base:
                data = date(ano + 1, mes, dia)
            datas.append(data)
        except ValueError:
            invalida = True
    for m in re.finditer(r"\b(hoje|amanha)\b", texto):
        datas.append(base + timedelta(days=(m[1] == "amanha")))
    # "quinta" pode ser uma propriedade e "sexta" um ordinal. Aceitamos
    # dias isolados no fim da frase ou acompanhados de uma indicação de hora.
    padrao_dia = (
        r"\b(" + "|".join(DIAS) + r")(?:-feira)?\b"
        r"(?=\s*(?:$|[,;.!?])|\s+(?:as|pelas)\b|\s+\d{1,2}[:h])"
    )
    for m in re.finditer(padrao_dia, texto):
        if m[1] in {"quinta", "sexta"} and not m[0].endswith("-feira"):
            continue
        datas.append(base + timedelta(days=(DIAS[m[1]] - base.weekday()) % 7))
    if invalida or len(datas) != 1:
        return None

    horas = list(re.finditer(r"(?<!\d)(\d{1,2})(?::(\d{2})|h(\d{2})?)(?!\d)", texto))
    if len(horas) > 1:
        return None
    if not horas:
        return datas[0].isoformat()
    match = horas[0]
    try:
        hora = time(int(match[1]), int(match[2] or match[3] or 0))
    except ValueError:
        return None
    return datetime.combine(datas[0], hora).isoformat()
