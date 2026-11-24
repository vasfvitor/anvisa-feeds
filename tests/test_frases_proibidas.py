"""The phrases of frases-proibidas.txt stay out of the public text: the string constants of the
package (docstrings and comments are not public) and the workflows' --notice strings."""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def padroes() -> list[tuple[str, re.Pattern]]:
    out = []
    for linha in (REPO / "frases-proibidas.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        expr = linha[3:] if linha.startswith("re:") else re.escape(linha)
        out.append((linha, re.compile(expr, re.I)))
    return out


def docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            corpo = node.body
            if (
                corpo
                and isinstance(corpo[0], ast.Expr)
                and isinstance(corpo[0].value, ast.Constant)
                and isinstance(corpo[0].value.value, str)
            ):
                ids.add(id(corpo[0].value))
    return ids


def textos_py(path: Path) -> list[tuple[int, str]]:
    """Each string constant with its line; an f-string as one text, `{…}` for each field."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pular = docstrings(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            partes = []
            for v in node.values:
                pular.add(id(v))
                partes.append(v.value if isinstance(v, ast.Constant) else "{…}")
            out.append((node.lineno, "".join(partes)))
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in pular
        ):
            out.append((node.lineno, node.value))
    return out


def textos_workflow(path: Path) -> list[tuple[int, str]]:
    out = []
    for n, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "--notice" in linha:
            out.append((n, linha.split("--notice", 1)[1]))
    return out


def test_no_banned_phrase_in_public_text():
    fontes = [(p, textos_py(p)) for p in sorted((REPO / "src").rglob("*.py"))]
    fontes += [(p, textos_workflow(p)) for p in sorted((REPO / ".github/workflows").glob("*.yml"))]
    achados = [
        f"{path.relative_to(REPO)}:{n}: {frase}"
        for path, textos in fontes
        for n, texto in textos
        for frase, padrao in padroes()
        if padrao.search(texto)
    ]
    assert not achados, "\n".join(achados)


def test_the_check_reads_strings_and_f_strings_not_comments_or_docstrings(tmp_path):
    fonte = tmp_path / "x.py"
    fonte.write_text(
        '"""Saiba mais."""\n# em tempo real\n'
        'x = f"Dados sem {y}, sem cadastro"\nz = "Lista atual"\n',
        encoding="utf-8",
    )
    achados = [
        (n, frase) for n, t in textos_py(fonte) for frase, padrao in padroes() if padrao.search(t)
    ]
    assert achados == [(3, r"re:\bsem [^\s,]+, sem [^\s,]+"), (4, "lista atual")]
