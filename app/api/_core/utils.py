import html


def esc(valor):
    return html.escape(str(valor or ""))
