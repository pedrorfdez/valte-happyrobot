"""Builds the live dashboard into dist/ (served by the backend at /app/).

Each page = the design's CSS and runtime + a body from src/<Page>.body.html
(the design's own markup with its mock lists turned into loops) + the logic
in src/<Page>.logic.js (data from the API instead of hard-coded values).

  python3 frontend/extract_design.py   # once: assets + reference markup from the design export
  python3 frontend/build.py
"""

import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, DIST, ASSETS, DESIGN = HERE / "src", HERE / "dist", HERE / "assets", HERE / "design"

PAGES = {  # page -> (title, design page whose CSS it uses)
    "Main": ("Valte", "Main"),
    "NuevaEscenario": ("Nueva catástrofe", "NuevaEscenario"),
    "PanelCoordinacion": ("Panel · Coordinación", "PanelCoordinacion"),
    "PanelAutoridad": ("Panel · Autoridad", "PanelAutoridad"),
    "PanelRespuesta": ("Panel · Respuesta", "PanelRespuesta"),
    "Zonas": ("Zonas", "Zonas"),
    "Acciones": ("Acciones", "Acciones"),
    "Senales": ("Señales", "Senales"),
    "Recursos": ("Recursos", "Recursos"),
    "Contactos": ("Contactos", "Contactos"),
}

SHELL = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Valte</title>
<script src="assets/react.production.min.js"></script>
<script src="assets/react-dom.production.min.js"></script>
<script src="assets/dc-runtime.js"></script>
<link rel="stylesheet" href="assets/valte-tokens.css">
<link rel="stylesheet" href="assets/valte-ds.css">
<script src="assets/valte-ds.js"></script>
<script src="assets/valte-live.js"></script>
</head>
<body>
<x-dc><helmet>
<style>
{css}
</style>
</helmet>
{body}
</x-dc>
<script type="text/x-dc" data-dc-script="" data-props="{{&quot;$preview&quot;:{{&quot;width&quot;:1440,&quot;height&quot;:900}}}}">
{logic}
</script>
</body></html>
"""


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ASSETS, DIST / "assets")
    shutil.copy(SRC / "valte-live.js", DIST / "assets" / "valte-live.js")
    shutil.copy(SRC / "valte-map.js", DIST / "assets" / "valte-map.js")
    extra = (SRC / "extra.css").read_text(encoding="utf-8")
    built = []
    for page, (title, css_from) in PAGES.items():
        body_file, logic_file = SRC / f"{page}.body.html", SRC / f"{page}.logic.js"
        if not body_file.exists() or not logic_file.exists():
            continue
        body = re.sub(r"<!-- include: ([a-z_]+) -->", lambda m: (SRC / f"_{m.group(1)}.html").read_text(encoding="utf-8"),
                      body_file.read_text(encoding="utf-8"))
        css = (DESIGN / f"{css_from}.page.css").read_text(encoding="utf-8") + "\n" + extra
        page_css = SRC / f"{page}.css"
        if page_css.exists():
            css += "\n" + page_css.read_text(encoding="utf-8")
        html = SHELL.format(title=title, css=css, body=body, logic=logic_file.read_text(encoding="utf-8"))
        (DIST / f"{page}.dc.html").write_text(html, encoding="utf-8")
        built.append(page)
    (DIST / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=Main.dc.html"><a href="Main.dc.html">Valte</a>\n',
        encoding="utf-8")
    print("built:", ", ".join(built), "| missing:", ", ".join(p for p in PAGES if p not in built) or "none")


if __name__ == "__main__":
    main()
