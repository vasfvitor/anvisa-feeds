"""The phrases of frases-proibidas.txt (the same list in the five health repos) stay out of the
public text. This file is the same, byte for byte, in ans and anvisa-feeds.

What is read:
- src/**/*.py: the string constants (docstrings and comments are not public), and the sentences
  built from several of them, each as one text: a `+` chain (an operand that is not a string
  becomes a space), the adjacent string elements of a list or tuple (joined with the separator of
  the `"sep".join(…)` they go to, else a space) and an f-string (each `{…}` becomes a space). HTML
  tags become spaces of the same length.
- .github/workflows/*.yml: every line but a YAML comment line, as one text (the `--notice` texts,
  the titles and bodies of issues), with shell variable names blanked; the rest of the shell is
  English and does not match.

A literal phrase matches with any run of whitespace between its words, ignoring case; a "re:" line
is used as written, with re.I. A hit is reported as `file:line: phrase`.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# an HTML tag: `<` right before a name, so "a < b" is left alone
TAG = re.compile(r"</?[A-Za-z][\w.:-]*(?:\s[^<>]*)?/?>")


def padroes(lista: str) -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for linha in lista.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("re:"):
            expr = linha[3:]
        else:
            expr = r"\s+".join(re.escape(p) for p in linha.split())
        out.append((linha, re.compile(expr, re.I)))
    return out


FRASES = padroes((REPO / "frases-proibidas.txt").read_text(encoding="utf-8"))

# one text: pieces of (line, text), in order
Pecas = list[tuple[int, str]]


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            primeiro = node.body[0] if node.body else None
            if (
                isinstance(primeiro, ast.Expr)
                and isinstance(primeiro.value, ast.Constant)
                and isinstance(primeiro.value.value, str)
            ):
                ids.add(id(primeiro.value))
    return ids


def _pecas(node: ast.AST, lidos: set[int]) -> Pecas | None:
    """The text of a string expression (constant, f-string, `+` chain), or None if it is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        lidos.add(id(node))
        return [(node.lineno, node.value)]
    if isinstance(node, ast.JoinedStr):
        lidos.add(id(node))
        out: Pecas = []
        for v in node.values:
            lidos.add(id(v))
            texto = v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else " "
            out.append((getattr(v, "lineno", node.lineno), texto))
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        esquerda = _pecas(node.left, lidos)
        direita = _pecas(node.right, lidos)
        if esquerda is None and direita is None:
            return None
        lidos.add(id(node))
        return (esquerda or [(node.lineno, " ")]) + (direita or [(node.lineno, " ")])
    return None


def _separadores(tree: ast.AST) -> dict[int, str]:
    """For each list or tuple passed to `"sep".join(…)`, its separator."""
    out = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)
            and len(node.args) == 1
            and isinstance(node.args[0], ast.List | ast.Tuple)
        ):
            out[id(node.args[0])] = node.func.value.value
    return out


def textos_py(fonte: str) -> list[Pecas]:
    """Every text of a module, outermost expression first, each string read once."""
    tree = ast.parse(fonte)
    lidos = _docstrings(tree)
    separadores = _separadores(tree)
    out: list[Pecas] = []
    for node in ast.walk(tree):
        if id(node) in lidos:
            continue
        if isinstance(node, ast.List | ast.Tuple):
            sep = separadores.get(id(node), " ")
            atual: Pecas = []
            for elt in [*node.elts, None]:
                pecas = _pecas(elt, lidos) if elt is not None and id(elt) not in lidos else None
                if pecas is None:
                    if atual:
                        out.append(atual[:-1])  # drop the separator after the last element
                    atual = []
                else:
                    atual += [*pecas, (pecas[-1][0], sep)]
        else:
            pecas = _pecas(node, lidos)
            if pecas:
                out.append(pecas)
    return out


# a shell variable (`$hoje`, `${hoje}`, `hoje=`): a name, not text
VARIAVEL = re.compile(r"\$\{?[A-Za-z_]\w*\}?|\b[A-Za-z_]\w*=")


def textos_workflow(fonte: str) -> list[Pecas]:
    """The workflow as one text, YAML comment lines left out and shell variable names blanked."""
    return [
        [
            (n, "" if re.match(r"\s*#", linha) else VARIAVEL.sub(" ", linha) + "\n")
            for n, linha in enumerate(fonte.splitlines(), 1)
        ]
    ]


def achados(arquivo: str, textos: list[Pecas]) -> list[str]:
    """`file:line: phrase` for each match, at the line of the piece where the match starts."""
    out = []
    for pecas in textos:
        inicios, pos = [], 0
        for _, texto in pecas:
            inicios.append(pos)
            pos += len(texto)
        junto = TAG.sub(lambda m: " " * len(m.group()), "".join(t for _, t in pecas))
        for frase, padrao in FRASES:
            for m in padrao.finditer(junto):
                i = max(k for k, inicio in enumerate(inicios) if inicio <= m.start())
                out.append((pecas[i][0], f"{arquivo}:{pecas[i][0]}: {frase}"))
    return [achado for _, achado in sorted(out, key=lambda a: a[0])]


def test_the_list_loads():
    assert len(FRASES) > 20
    assert r"re:\bsem\s+[^\s,]+,\s+sem\s+[^\s,]+" in [f for f, _ in FRASES]


def test_no_banned_phrase_in_public_text():
    hits = []
    for path in sorted((REPO / "src").rglob("*.py")):
        hits += achados(str(path.relative_to(REPO)), textos_py(path.read_text(encoding="utf-8")))
    for path in sorted((REPO / ".github/workflows").glob("*.yml")):
        texto = path.read_text(encoding="utf-8")
        hits += achados(str(path.relative_to(REPO)), textos_workflow(texto))
    assert not hits, "\n".join(hits)


def test_follows_a_sentence_across_plus_list_tag_and_f_string():
    fonte = (
        'a = "Arquivos republicados " + nome + " todo"\n'
        'b = ("Saiba "\n     + "mais")\n'
        'c = "".join(["Sem cadastro, ", "sem senha"])\n'
        'd = [\n    "clique",\n    "aqui",\n]\n'
        'e = "<p>só <b>fatos</b></p>"\n'
        'f = f"Dados de {dia}: sem alteração, {n} em tempo real"\n'
    )
    assert achados("x.py", textos_py(fonte)) == [
        "x.py:2: saiba mais",
        "x.py:4: re:\\bsem\\s+[^\\s,]+,\\s+sem\\s+[^\\s,]+",
        "x.py:6: clique aqui",
        "x.py:9: só fatos",
        "x.py:10: em tempo real",
        "x.py:10: sem alteração",
    ]


def test_docstrings_and_comments_are_not_read():
    fonte = (
        '"""Saiba mais."""\n# em tempo real\ndef f():\n    """Lista atual."""\n    return "ok"\n'
    )
    assert achados("x.py", textos_py(fonte)) == []


def test_a_workflow_issue_body_is_read_and_comments_are_not():
    fonte = (
        "# saiba mais\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - run: |\n"
        "          # clique aqui\n"
        '          hoje=$(date +%F); echo "${hoje}" "$hoje"\n'
        '          gh issue create --title "Coleta" --body "Os dados são republicados\n'
        '          diariamente."\n'
    )
    assert achados("w.yml", textos_workflow(fonte)) == [
        "w.yml:8: republicados diariamente",
        "w.yml:9: diariamente",
    ]
