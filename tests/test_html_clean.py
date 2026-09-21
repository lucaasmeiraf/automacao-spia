"""Testes da limpeza de HTML — garante paridade com o stripHtml do n8n."""
from app.processing.html_clean import limpar_campos, strip_html


def test_remove_tags():
    assert strip_html("<p>Olá <b>mundo</b></p>") == "Olá mundo"


def test_entidades_nomeadas():
    assert strip_html("Concep&ccedil;&atilde;o") == "Concepção"
    assert strip_html("&Aacute;rea &ndash; 10m&sup2;") == "Área – 10m²"


def test_nbsp_e_espacos():
    assert strip_html("a&nbsp;&nbsp;b   c") == "a b c"


def test_entidade_numerica():
    # html.unescape cobre entidades fora da tabela nomeada (ex.: &#233; = é)
    assert strip_html("caf&#233;") == "café"


def test_valor_nao_string_passa_direto():
    assert strip_html(123) == 123
    assert strip_html(None) is None


def test_limpar_campos_copia_e_limpa():
    registro = {"resumo": "<p>x</p>", "outro": "<b>y</b>"}
    limpo = limpar_campos(registro, ["resumo"])
    assert limpo["resumo"] == "x"
    assert limpo["outro"] == "<b>y</b>"   # não estava na lista → intacto
    assert registro["resumo"] == "<p>x</p>"  # original não foi mutado
