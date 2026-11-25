"""Conversão local e conservadora de expressões temporais portuguesas para ISO."""

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Literal

DIAS_SEMANA = {
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
NUMEROS = {
    "uma": 1,
    "um": 1,
    "duas": 2,
    "dois": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
}
PERIODOS_IMPRECISOS = {
    "manha",
    "de manha",
    "tarde",
    "de tarde",
    "a tarde",
    "noite",
    "de noite",
    "a noite",
}


def sem_acentos(texto: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(c)
    )


def _referencia_data(referencia: date | datetime | str) -> date:
    if isinstance(referencia, datetime):
        return referencia.date()
    if isinstance(referencia, date):
        return referencia
    return datetime.fromisoformat(referencia).date()


def _parse_data(expressao: str, base: date) -> date | None:
    texto = sem_acentos(expressao).strip().strip(".,;: ")
    texto = re.sub(r"^(?:para|no|na|em|dia)\s+", "", texto)
    if not texto:
        return None

    relativas = re.findall(r"\bhoje\b|\bamanha\b", texto)
    if relativas:
        if len(relativas) != 1 or re.sub(r"\bhoje\b|\bamanha\b", "", texto).strip():
            return None
        return base + timedelta(days=1 if relativas[0] == "amanha" else 0)

    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", texto)
    if iso:
        try:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        except ValueError:
            return None

    numerica = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", texto)
    if numerica:
        dia, mes = int(numerica[1]), int(numerica[2])
        ano = int(numerica[3]) if numerica[3] else base.year
        try:
            resultado = date(ano, mes, dia)
        except ValueError:
            return None
        if not numerica[3] and resultado < base:
            try:
                resultado = date(ano + 1, mes, dia)
            except ValueError:
                return None
        return resultado

    nomes_meses = "|".join(MESES)
    por_extenso = re.fullmatch(
        rf"(?:dia\s+)?(\d{{1,2}})\s+de\s+({nomes_meses})(?:\s+de\s+(\d{{4}}))?",
        texto,
    )
    if por_extenso:
        dia, mes = int(por_extenso[1]), MESES[por_extenso[2]]
        ano = int(por_extenso[3]) if por_extenso[3] else base.year
        try:
            resultado = date(ano, mes, dia)
        except ValueError:
            return None
        if not por_extenso[3] and resultado < base:
            try:
                resultado = date(ano + 1, mes, dia)
            except ValueError:
                return None
        return resultado

    dia_semana = re.fullmatch(
        r"(?:proxima\s+|proximo\s+)?"
        r"(segunda|terca|quarta|quinta|sexta|sabado|sabadp|domingo)(?:-feira)?",
        texto,
    )
    if dia_semana:
        indice = DIAS_SEMANA[dia_semana[1]]
        deslocamento = (indice - base.weekday()) % 7
        if texto.startswith(("proxima ", "proximo ")) and deslocamento == 0:
            deslocamento = 7
        return base + timedelta(days=deslocamento)
    return None


def _parse_hora(expressao: str | None) -> time | None | Literal[False]:
    """None significa sem hora precisa; False significa hora explícita inválida."""
    if expressao is None or not expressao.strip():
        return None
    texto = sem_acentos(expressao).strip()
    if texto in PERIODOS_IMPRECISOS:
        return None

    candidatos: list[tuple[int, int]] = []
    for m in re.finditer(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", texto):
        candidatos.append((int(m[1]), int(m[2])))
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*h\s*(\d{2})?(?!\d)", texto):
        candidatos.append((int(m[1]), int(m[2] or 0)))
    for m in re.finditer(
        r"\b(?:as|a)\s+(\d{1,2})(?!\d|:|h\b|\s+h\b)"
        r"(?:\s+(?:horas?))?\s*(?:da\s+(manha|tarde|noite))?\b",
        texto,
    ):
        hora = int(m[1])
        periodo = m[2]
        if periodo in {"tarde", "noite"} and 1 <= hora <= 11:
            hora += 12
        candidatos.append((hora, 0))

    if re.search(r"\bmeia\s*[- ]\s*noite\b", texto):
        candidatos.append((0, 0))
    if re.search(r"\bmeio\s*[- ]\s*dia\b", texto):
        candidatos.append((12, 0))

    palavra_hora = re.search(
        r"\b(?:as|a)\s+(uma|um|duas|dois|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze)"
        r"(?:\s+e\s+(meia|um quarto))?",
        texto,
    )
    if palavra_hora:
        hora = NUMEROS[palavra_hora[1]]
        minuto = (
            30
            if palavra_hora[2] == "meia"
            else 15
            if palavra_hora[2] == "um quarto"
            else 0
        )
        resto = texto[palavra_hora.end() : palavra_hora.end() + 30]
        if ("da tarde" in resto or "da noite" in resto) and 1 <= hora <= 11:
            hora += 12
        candidatos.append((hora, minuto))

    if not candidatos:
        return None if any(p in texto for p in ("manha", "tarde", "noite")) else False
    if len(candidatos) != 1:
        return False
    try:
        return time(*candidatos[0])
    except ValueError:
        return False


def resolver_quando(
    expressao_data: str,
    expressao_hora: str | None,
    referencia: date | datetime | str,
) -> str | None:
    """Resolve expressões extraídas para ISO sem pedir ao LLM que calcule anos.

    Horas vagas ("de manhã", "à tarde") produzem apenas YYYY-MM-DD.
    Expressões desconhecidas, alternativas e datas inválidas produzem None.
    """
    base = _referencia_data(referencia)
    dia = _parse_data(expressao_data, base)
    if dia is None:
        return None
    hora = _parse_hora(expressao_hora)
    if hora is False:
        return None
    if hora is None:
        return dia.isoformat()
    return datetime.combine(dia, hora).isoformat()
