"""Pull the reusable parts out of the design export (`Valte · Pantallas.html`):
the dc-runtime, the Valte component bundle, React, fonts, the CSS, and each
screen's original markup (kept under design/ as the reference the live
screens in src/ were derived from). Run once; build.py does the rest.
"""

import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent / "Valte · Pantallas.html"
ASSETS = HERE / "assets"
DESIGN = HERE / "design"

FILES = {  # design title -> page file name used by the design's own links
    "Inicio · con catástrofes activas": "Main", "Inicio · sin catástrofes activas": "MainEmpty",
    "Alta · 01 Escenario": "NuevaEscenario", "Panel · Coordinación": "PanelCoordinacion",
    "Panel · Autoridad": "PanelAutoridad", "Panel · Respuesta": "PanelRespuesta", "Zonas": "Zonas",
    "Acciones": "Acciones", "Señales": "Senales", "Recursos": "Recursos", "Contactos": "Contactos",
}
JS_NAMES = {43272: "dc-runtime.js", 10181: "valte-ds.js", 10751: "react.production.min.js", 131835: "react-dom.production.min.js"}


def section(src: str, kind: str) -> str:
    m = re.search(r'<script type="__bundler/%s"[^>]*>' % kind, src)
    return src[m.end():src.index("</script>", m.end())]


def main() -> None:
    (ASSETS / "fonts").mkdir(parents=True, exist_ok=True)
    DESIGN.mkdir(exist_ok=True)
    outer = BUNDLE.read_text(encoding="utf-8")
    manifest = json.loads(section(outer, "manifest"))
    frames = re.findall(r'<iframe src="about:blank#([0-9a-f-]+)" title="([^"]+)"', json.loads(section(outer, "template")))
    css_written = False
    for uuid, title in frames:
        if title not in FILES:
            continue
        page = gzip.decompress(base64.b64decode(manifest[uuid]["data"])).decode("utf-8")
        inner = json.loads(section(page, "manifest"))
        tpl = json.loads(section(page, "template"))
        names: dict[str, str] = {}
        for rid, res in inner.items():
            data = base64.b64decode(res["data"])
            data = gzip.decompress(data) if res.get("compressed") else data
            if res.get("mime") == "text/javascript":
                names[rid] = JS_NAMES[len(data)]
                (ASSETS / names[rid]).write_bytes(data)
            elif res.get("mime") == "font/woff2":
                names[rid] = f"fonts/{hashlib.sha1(data).hexdigest()[:12]}.woff2"
                (ASSETS / names[rid]).write_bytes(data)
        for rid, name in names.items():
            tpl = tpl.replace(rid, f"assets/{name}")

        head_styles = re.findall(r"<style>(.*?)</style>", tpl[:tpl.index("<x-dc>")], flags=re.S)
        helmet = tpl[tpl.index("<helmet>"):tpl.index("</helmet>")]
        page_css = re.findall(r"<style>(.*?)</style>", helmet, flags=re.S)[-1]
        body = tpl[tpl.index("</helmet>") + len("</helmet>"):tpl.index('<script type="text/x-dc"')]
        body = body[:body.rindex("</x-dc>")]
        logic = re.search(r'<script type="text/x-dc"[^>]*>(.*?)</script>', tpl, flags=re.S).group(1)

        name = FILES[title]
        (DESIGN / f"{name}.body.html").write_text(body.strip() + "\n", encoding="utf-8")
        (DESIGN / f"{name}.page.css").write_text(page_css.strip() + "\n", encoding="utf-8")
        (DESIGN / f"{name}.mock.js").write_text(logic.strip() + "\n", encoding="utf-8")
        if not css_written:  # tokens + @font-face + the vt-* component CSS are identical on every screen
            (ASSETS / "valte-tokens.css").write_text(head_styles[0].strip() + "\n", encoding="utf-8")
            (ASSETS / "valte-ds.css").write_text(head_styles[1].replace("assets/fonts/", "fonts/").strip() + "\n", encoding="utf-8")
            css_written = True
        print(f"{name:20s} body={len(body):6d} css={len(page_css):5d}")
    fonts = list((ASSETS / "fonts").glob("*.woff2"))
    print(f"assets: {sorted(p.name for p in ASSETS.glob('*.*'))} + {len(fonts)} fonts")


if __name__ == "__main__":
    main()
