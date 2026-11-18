# Decisões

Uma entrada por decisão. Curta. O que decidimos, com que evidência, e o que nos faria mudar de ideia.

---

## 001 · O que é nosso vive num serviço; os agentes são clientes

**Data:** 19 nov 2026 · **Quem:** proposta do formador (esqueleto). **A confirmar ou rejeitar pela equipa.**

**Decisão:** as categorias, o classificador e a medição vivem num serviço HTTP independente. O Hermes, o Claude ou outro agente ligam-se através de uma skill.

**Evidência:** ver [ARQUITETURA.md](ARQUITETURA.md). Um serviço sem estado cabe num free tier; um agente sempre ligado não.

**Mudaríamos de ideia se:** …

---

## 002 · O que vai para dentro de `classificar()`

**Data:** 19 nov 2026 · **Quem:** a equipa

**Opções que medimos** (marcador do spike, 34 capturas):

| sistema | accuracy | precision | recall | F1 | tokens/captura | seg/captura |
|---|---|---|---|---|---|---|
| zero-shot (base) | 0.03 | 0.39 | 0.88 | 0.55 | 82 | |
| | | | | | | |

**Decisão:** …

**Porquê:** …

**Mudaríamos de ideia se:** …
