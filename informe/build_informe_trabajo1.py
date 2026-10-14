"""Integra la Parte 2 en el informe del equipo y regenera sus figuras desde datos locales.

Uso desde la raíz del repositorio:
    .venv\\Scripts\\python.exe informe\\build_informe_trabajo1.py

La plantilla es la copia del informe recibida del equipo. El script conserva la
Parte 1 y los anexos, sustituye los marcadores de Parte 2, renumera las secciones
comunes y genera un DOCX nuevo en docs/.
"""
from __future__ import annotations

import csv
import argparse
import gzip
import json
import math
from pathlib import Path
from statistics import median

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "informe" / "Informe_Trabajo1_base.docx"
OUT = ROOT / "docs" / "Informe_Trabajo1.docx"
FIG_DIR = ROOT / "informe" / "figures"
ECON = ROOT / "data" / "datasets" / "spain_tsp_economic_20261013"
RESULTS = ROOT / "results" / "tsp" / "model_a_experimental_aco_30_runs.json"
ECON_META = ECON / "metadata.json"
DATA = ROOT / "data" / "datasets" / "spain_tsp_2026"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def city_catalog():
    with (DATA / "cities.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {r["city_id"]: {**r, "latitude": float(r["latitude"]), "longitude": float(r["longitude"])} for r in rows}


def route_catalog():
    rows = {}
    for file in sorted((DATA / "routes" / "ors_enriched").glob("*.jsonl.gz")):
        with gzip.open(file, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                rows[(row["origin_id"], row["destination_id"])] = row
    return rows


def result_data():
    data = load_json(RESULTS)
    assert len(data["runs"]) == 90 and data["budget_each"] == 100
    assert all(s["runs"] == 30 and s["objective_budget_each"] == 100 for s in data["summaries"])
    return data


def draw_best_tour(data, cities, routes):
    runs = [r for r in data["runs"] if r["hour_value_eur_per_hour"] == 25]
    best = min(runs, key=lambda r: r["best_cost_eur"])
    order = list(best["tour_city_ids"])
    madrid = order.index("madrid")
    order = order[madrid:] + order[:madrid]
    best = {**best, "tour_city_ids": order}
    closed = order + [order[0]]
    W, H = 1900, 1210
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    title_font, subtitle_font = font(42, True), font(24)
    d.text((100, 45), "Mejor tour ACO del escenario experimental (v = 25 EUR/h)", fill="#17365D", font=title_font)
    d.text((100, 105), f"Semilla {best['seed']} · {best['best_cost_eur']:,.2f} EUR · 47 ciudades y retorno al origen", fill="#444444", font=subtitle_font)
    left, top, right, bottom = 105, 175, 1785, 1025
    lon_min, lon_max, lat_min, lat_max = -10.0, 4.4, 35.4, 44.3
    # Ajuste cosenoidal simple para que el eje longitudinal conserve proporción geográfica.
    coslat = math.cos(math.radians(40.0))
    def xy(lon, lat):
        x = left + ((lon - lon_min) * coslat) / ((lon_max - lon_min) * coslat) * (right - left)
        y = bottom - (lat - lat_min) / (lat_max - lat_min) * (bottom - top)
        return (int(x), int(y))
    for lon in range(-10, 5, 2):
        x, _ = xy(lon, lat_min)
        d.line((x, top, x, bottom), fill="#E7EDF2", width=1)
        d.text((x - 18, bottom + 12), f"{lon}°", fill="#62717D", font=font(18))
    for lat in range(36, 45, 2):
        _, y = xy(lon_min, lat)
        d.line((left, y, right, y), fill="#E7EDF2", width=1)
        d.text((left - 55, y - 10), f"{lat}°", fill="#62717D", font=font(18))
    d.rectangle((left, top, right, bottom), outline="#AAB7C4", width=2)

    # La figura usa exclusivamente geometrías Directions guardadas para los arcos del tour.
    for a, b in zip(closed[:-1], closed[1:]):
        route = routes.get((a, b))
        if not route:
            raise ValueError(f"Falta geometría publicada para el arco del tour {a}->{b}")
        coords = route["geometry"]["coordinates"]
        points = [xy(float(c[0]), float(c[1])) for c in coords]
        d.line(points, fill="#9FBAD0", width=3, joint="curve")
    for a, b in zip(closed[:-1], closed[1:]):
        route = routes[(a, b)]
        pts = [xy(float(c[0]), float(c[1])) for c in route["geometry"]["coordinates"]]
        d.line(pts, fill="#1464A5", width=5, joint="curve")

    # Marcas numeradas en cada capital; se rotulan seis referencias para conservar legibilidad.
    labels = {"madrid", "barcelona", "valencia", "sevilla", "bilbao", "a_coruna", "zaragoza"}
    for idx, city_id in enumerate(order, 1):
        city = cities[city_id]
        x, y = xy(city["longitude"], city["latitude"])
        r = 9
        is_start = city_id == order[0]
        color = "#B22222" if is_start else "#F3C969"
        d.ellipse((x-r, y-r, x+r, y+r), fill=color, outline="#17365D", width=2)
        d.text((x + 8, y - 23), str(idx), fill="#17365D", font=font(17, True))
        if city_id in labels:
            d.text((x + 14, y + 7), city["name"], fill="#17212B", font=font(19, True), stroke_width=2, stroke_fill="white")
    d.text((100, 1090), "Madrid es el inicio (marcador rojo); la numeración indica el orden. El ciclo vuelve a Madrid.", fill="#404B55", font=font(21))
    d.text((100, 1130), "Fuente: geometrías ORS de las rutas fastest; © openrouteservice by HeiGIT | Data from OpenStreetMap.", fill="#404B55", font=font(18))
    path = FIG_DIR / "tsp_best_tour_v25.png"
    im.save(path, dpi=(220, 220), optimize=True)
    return path, best


def draw_convergence(data):
    W, H = 1900, 1240
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((100, 32), "Convergencia de Ant System: mediana y rango intercuartílico", fill="#17365D", font=font(39, True))
    d.text((100, 84), "Mejor costo acumulado frente a evaluaciones de tours cerrados; n = 30 por escenario", fill="#444444", font=font(22))
    colors = {10: "#1769AA", 25: "#198754", 50: "#BD4A3A"}
    for panel, value in enumerate((10, 25, 50)):
        y0 = 150 + panel * 345
        x0, x1, y1 = 155, 1770, y0 + 270
        runs = [r for r in data["runs"] if r["hour_value_eur_per_hour"] == value]
        curves = []
        for run in runs:
            history = run["convergence"]
            j, current, curve = 0, history[0]["best_cost_eur"] if isinstance(history[0], dict) else history[0]["best_cost_eur"], []
            for ev in range(1, 101):
                while j + 1 < len(history) and history[j + 1]["evaluations"] <= ev:
                    j += 1
                    current = history[j]["best_cost_eur"]
                curve.append(float(current))
            curves.append(curve)
        finals = [r["best_cost_eur"] for r in runs]
        ymax = max(max(c[0] for c in curves), max(finals)) * 1.06
        ymin = min(finals) * 0.94
        d.rectangle((x0, y0, x1, y1), outline="#AAB7C4", width=2)
        d.text((x0, y0 - 34), f"v = {value} EUR/h", fill=colors[value], font=font(24, True))
        for fraction in (0.0, 0.5, 1.0):
            yy = int(y1 - fraction * (y1 - y0))
            d.line((x0, yy, x1, yy), fill="#E7EDF2", width=1)
            val = ymin + fraction * (ymax - ymin)
            d.text((x0 - 94, yy - 10), f"{val:,.0f}", fill="#62717D", font=font(16))
        d.text((x0, y1 + 7), "1", fill="#62717D", font=font(16))
        d.text((x1 - 34, y1 + 7), "100", fill="#62717D", font=font(16))
        low, mid, high = [], [], []
        for k in range(100):
            vals = sorted(c[k] for c in curves)
            low.append(vals[7])
            mid.append(vals[14])
            high.append(vals[22])
        def point(k, v):
            return (int(x0 + k * (x1 - x0) / 99), int(y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)))
        polygon = [point(k, high[k]) for k in range(100)] + [point(k, low[k]) for k in range(99, -1, -1)]
        d.polygon(polygon, fill="#D9E5F0")
        d.line([point(k, mid[k]) for k in range(100)], fill=colors[value], width=4)
    d.text((155, 1205), "Eje x: evaluaciones de tours cerrados; eje y: EUR. Banda: percentiles 25–75; línea: mediana. Mejor valor acumulado.", fill="#404B55", font=font(17))
    path = FIG_DIR / "tsp_aco_convergence_30_runs.png"
    im.save(path, dpi=(220, 220), optimize=True)
    return path


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def make_table(doc, headers, rows, widths):
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "A6A6A6")
        borders.append(element)
    tbl_pr.append(borders)
    set_repeat_table_header(table.rows[0])
    for idx, text in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = str(text)
        set_cell_shading(cell, "1F4E79")
    for row in rows:
        cells = table.add_row().cells
        for idx, text in enumerate(row):
            cells[idx].text = str(text)
    for row_idx, row in enumerate(table.rows):
        for idx, cell in enumerate(row.cells):
            cell.width = Inches(widths[idx])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for para in cell.paragraphs:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER if row_idx == 0 else WD_ALIGN_PARAGRAPH.LEFT
                para.paragraph_format.space_after = Pt(1)
                para.paragraph_format.line_spacing = 1.0
                for run in para.runs:
                    run.font.name = "Calibri"
                    run.font.size = Pt(8.5)
                    if row_idx == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))
    return table._tbl


def add_paragraph(doc, text, style="Normal", bold_lead=None, small=False):
    p = doc.add_paragraph(style=style)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY if style == "Normal" else WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(6 if not small else 3)
    p.paragraph_format.line_spacing = 1.08
    if bold_lead and text.startswith(bold_lead):
        p.add_run(bold_lead).bold = True
        p.add_run(text[len(bold_lead):])
    else:
        p.add_run(text)
    if small:
        for r in p.runs:
            r.font.size = Pt(9)
    return p._p


def add_equation(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    r.italic = True
    r.font.name = "Cambria Math"
    r.font.size = Pt(11)
    return p._p


def add_caption(doc, label, title, note=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(label)
    r.bold = True
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(4)
    p2.add_run(title).italic = True
    nodes = [p._p, p2._p]
    if note:
        nodes.append(add_paragraph(doc, note, small=True))
    return nodes


def add_heading(doc, text, level=1):
    p = doc.add_paragraph(text, style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    return p._p


def add_figure(doc, path, width=6.35):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    p.add_run().add_picture(str(path), width=Inches(width))
    return p._p


def append_nodes_before(body, anchor, nodes):
    index = body.index(anchor)
    for offset, node in enumerate(nodes):
        body.insert(index + offset, node)


def main():
    global BASE, OUT, FIG_DIR, RESULTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=BASE)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--figure-dir", type=Path, default=FIG_DIR)
    args = parser.parse_args()
    BASE, RESULTS, OUT, FIG_DIR = args.template, args.results, args.output, args.figure_dir
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BASE, RESULTS, ECON_META):
        if not path.exists():
            raise FileNotFoundError(path)
    data = result_data()
    metadata = load_json(ECON_META)
    cities = city_catalog()
    routes = route_catalog()
    fig_map, best_v25 = draw_best_tour(data, cities, routes)
    fig_conv = draw_convergence(data)

    doc = Document(BASE)
    paragraphs = list(doc.paragraphs)
    def find_para(prefix):
        return next(p for p in paragraphs if p.text.strip().startswith(prefix))
    part2 = find_para("Parte 2. Problema del viajero")
    common = find_para("Secciones comunes")
    pending = [p for p in paragraphs if p.text.strip().startswith("[PENDIENTE") or p.text.strip().startswith("[Estructura sugerida")]
    for p in pending:
        if p._p.getparent() is not None and ("integrante 3" in p.text or "Estructura sugerida" in p.text):
            p._p.getparent().remove(p._p)
    # Reemplaza el marcador de conclusiones conjuntas; el detalle de Parte 2 está en 15.3.
    for p in paragraphs:
        if "conclusiones generales del trabajo" in p.text:
            p.text = "Conclusión general. En la primera parte observamos que el rendimiento depende de la geometría de la función y del presupuesto; en la segunda, mostramos que una metaheurística puede construir ciclos dirigidos sobre una red vial real. En ambos casos, la interpretación queda condicionada por el protocolo: los resultados del TSP aquí son de ACO y el componente de peajes es experimental, no una liquidación tarifaria."
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            break

    # Renumeración de los apartados comunes exigida por la estructura conjunta.
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("9. Uso de inteligencia artificial"):
            p.text = "16. Uso de inteligencia artificial"
        elif t.startswith("10. Cacería de la alucinación"):
            p.text = "17. Cacería de la alucinación"
        elif t.startswith("11. Reproducibilidad"):
            p.text = "18. Reproducibilidad"
    # Registra el apoyo editorial de esta iteración sin atribuir a Codex corridas ni datos.
    # Se inserta antes de la sección de impacto, si conserva el texto de la versión base.
    impact = next((p for p in doc.paragraphs if p.text.startswith("Impacto.")), None)
    if impact is not None:
        p = doc.add_paragraph(
            "En la preparación de esta versión, Codex también apoyó la redacción e integración editorial de la Parte 2 y la generación de sus figuras desde resultados y geometrías ya guardados. La revisión de cifras se realizó contra los archivos del repositorio; esta asistencia no ejecutó el GA ni generó adquisiciones externas.",
            style=impact.style,
        )
        p._p.getparent().remove(p._p)
        impact._p.addprevious(p._p)

    # Resumen y palabras clave: se conserva la Parte 1 y se añade el hallazgo de TSP con cautela.
    for p in doc.paragraphs:
        if p.text.startswith("Comparamos el descenso"):
            p.text = ("En la primera parte comparamos descenso por gradiente (GD), algoritmo evolutivo (EA), optimización por enjambre de partículas (PSO) y evolución diferencial (DE) en Rosenbrock y Rastrigin, en 2D y 3D, con 30 corridas por caso. GD no alcanzó el umbral de éxito y DE presentó la mayor confiabilidad en los cuatro casos. En la segunda parte construimos un TSP dirigido de 47 capitales peninsulares y 2.162 rutas viales. Ant System se ejecutó con 30 semillas y 100 evaluaciones por escenario. En el Modelo A experimental, las medias fueron 2.537,51, 4.485,19 y 7.897,95 EUR para 10, 25 y 50 EUR/h. Parte de los peajes son supuestos o proxies; no hay resultados GA comparables ni una matriz tarifaria oficial completa.")
        if p.text.startswith("Palabras clave:"):
            p.text = "Palabras clave: descenso por gradiente, evolución diferencial, colonia de hormigas, algoritmo genético, problema del viajero, peajes experimentales"

    # Los párrafos originales de índices y anexos se conservan; el campo TOC se actualiza al abrir en Word.
    body = doc._element.body
    # Captions/referencias a nuevas tablas y figuras.
    summaries = {float(s["hour_value_eur_per_hour"]): s for s in data["summaries"]}
    instances_rows = [
        ["47", "Capitales provinciales peninsulares; sin islas, Ceuta ni Melilla"],
        ["2.162", "47 × 46 arcos dirigidos entre ciudades distintas"],
        ["Grafo", "Completo y dirigido; no se sustituyen carreteras por distancias euclidianas"],
        ["Proveedor/perfil", "openrouteservice (ORS), driving-car"],
        ["Preferencia", "fastest para Directions"],
        ["Variables", "Distancia, duración, geometría, tollways y waycategory"],
        ["Cobertura", "2.162 de 2.162 rutas enriquecidas; 11 fragmentos comprimidos"],
        ["Dataset", "PR #8, fusionado en main; data/datasets/spain_tsp_2026/"],
    ]
    toll_status = metadata["toll_status_counts"]
    total = int(metadata["directed_arcs"])
    pct = lambda n: f"{100*int(n)/total:.2f} %".replace(".", ",")
    toll_rows = [
        ["Cero supuesto por ausencia de intervalos ORS", "1.020", pct(1020), "ZERO_ASSUMED_ORS; extras completos sin intervalo tollways; no es cero legal verificado."],
        ["Tarifa oficial aplicada por asociación inferida", "6", pct(6), "AP-68: 2 pares dirigidos; AP-9: 2 composiciones; C-32: 2 barreras. No se certifica el par exacto."],
        ["Proxy por km de segmento ORS", "1.136", pct(1136), "0,14145 EUR/km de longitud marcada; escenario no calibrado ni tarifa nacional."],
        ["Total con valor experimental finito", "2.162", "100,00 %", "Matriz numérica experimental completa; la salida estricta conserva UNKNOWN."],
        ["Peaje total oficialmente verificado", "0", "0,00 %", "Ningún arco tiene el costo completo verificado con entrada/salida y todos los eventos."],
    ]
    protocol_rows = [
        ["Instancia y objetivo", "47 ciudades; matriz dirigida EUR/arco; tour cerrado; Modelo A experimental"],
        ["Escenarios", "v = 10, 25 y 50 EUR/h; combustible BMW 120 F70, 5,4 L/100 km"],
        ["Corridas", "30 semillas por escenario: 20261014–20261043"],
        ["Presupuesto", "100 evaluaciones completas de tours por corrida"],
        ["ACO", "Ant System; 10 hormigas; α=1; β=2; ρ=0,5; Q=1; τ₀=1"],
        ["Métricas", "Mejor costo, media, desviación estándar muestral, tiempo medio y convergencia"],
        ["GA", "Sin implementación/resultados verificables en esta rama; comparación pendiente"],
    ]
    result_rows = []
    for value in (10.0, 25.0, 50.0):
        s = summaries[value]
        result_rows.append([
            f"{int(value)}", f"{s['runs']}", f"{s['objective_budget_each']}",
            f"{s['best_cost_min_eur']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            f"{s['best_cost_mean_eur']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            f"{s['best_cost_sample_std_eur']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        ])

    nodes = []
    def add(text, style="Normal", bold_lead=None, small=False):
        nodes.append(add_paragraph(doc, text, style, bold_lead, small))
    def h1(text): nodes.append(add_heading(doc, text, 1))
    def h2(text): nodes.append(add_heading(doc, text, 2))
    def eq(text): nodes.append(add_equation(doc, text))
    def table_block(number, title, headers, rows, widths, note):
        nodes.extend(add_caption(doc, f"Tabla {number}", title, note))
        nodes.append(make_table(doc, headers, rows, widths))
    def fig_block(number, title, path, note):
        nodes.extend(add_caption(doc, f"Figura {number}", title))
        nodes.append(add_figure(doc, path))
        nodes.append(add_paragraph(doc, note, small=True))

    h1("9. Introducción y pregunta guía")
    add("En la primera parte estudiamos funciones continuas sobre dominios numéricos; en esta abordamos una decisión discreta: ordenar visitas entre ciudades y cerrar el recorrido regresando al origen. El problema del viajero (TSP) busca una permutación de nodos que minimice la suma de los costos de sus arcos. Para n ciudades, fijado un origen, el número de órdenes candidatos crece como (n−1)!; por ello, incluso una instancia de 47 ciudades no se resuelve por enumeración directa. Esta estructura hace pertinente estudiar metaheurísticas, capaces de explorar espacios combinatorios grandes bajo presupuestos computacionales definidos (Dantzig, Fulkerson y Johnson, 1954).")
    add("La distancia recta no representa adecuadamente una movilidad condicionada por la red, sus sentidos, enlaces y accesos. Construimos por eso una instancia vial española. A la vez, minimizar kilómetros no equivale a minimizar gasto: una ruta más larga puede ahorrar tiempo, o una ruta rápida puede incorporar peajes. Nuestra pregunta guía es: ¿cómo se comporta Ant System al minimizar un costo económico experimental sobre la instancia dirigida y qué comparación con un algoritmo genético permite la evidencia actualmente disponible? La pregunta deja abierta la comparación GA porque en esta rama no localizamos una implementación ni resultados reproducibles del integrante responsable.")
    add("La contribución concreta es una instancia dirigida basada en rutas reales y una función que combina tiempo, combustible y un escenario explícito de peajes. Distinguimos el costo base sin peajes del Modelo A experimental y no presentamos los importes estimados como liquidaciones oficiales.")

    h1("10. Construcción de la instancia y fuentes de datos")
    h2("10.1. Selección de ciudades y representación del problema")
    add("La instancia comprende las 47 capitales provinciales de España peninsular; se excluyen las provincias insulares y las ciudades autónomas de Ceuta y Melilla. Cada capital es un nodo identificado de manera estable en el catálogo y el recorrido debe visitar cada nodo una sola vez antes de regresar al inicial. La representación es un grafo completo dirigido: para todo par distinto (i,j) se conserva un arco i→j. El conjunto contiene 47×46=2.162 arcos. Mantener la dirección es necesario porque los sentidos pueden tener tiempos y distancias distintos por accesos, trazado, circulación y elección de ruta.")
    add("No aproximamos los desplazamientos mediante distancias euclidianas. Para cada par utilizamos una ruta de carretera. Así, la matriz de costos no es necesariamente simétrica y las permutaciones inversas no tienen por qué costar lo mismo. El orden de las filas y columnas sigue el catálogo canónico publicado, lo que permite que ACO y cualquier implementación GA reciban la misma instancia.")
    h2("10.2. Obtención de rutas y construcción de matrices")
    add("Las rutas individuales se obtuvieron con la API Directions de openrouteservice, perfil driving-car y preferencia fastest. La respuesta incluye distancia en metros, duración en segundos y geometría; se solicitaron además tollways y waycategory para describir segmentos potencialmente tarifados y categorías de vía. Cada respuesta se relaciona con origen, destino, fecha, identificador y hashes. ORS documenta que tollways es una clasificación binaria por tramo dependiente del perfil y no devuelve el importe del peaje; waycategory utiliza valores que pueden combinar categorías mediante bits (HeiGIT, 2026).")
    add("El dataset vial base se adquirió mediante ORS Matrix el 12 de octubre de 2026; las geometrías Directions se incorporaron posteriormente como rutas individuales con preference=fastest. Matrix aporta distancia y duración por par, pero no geometría. Por ello, para el análisis económico de Modelo A se toman conjuntamente los componentes de cada ruta Directions y no se combina su duración con una geometría distinta.")
    add("A partir de los registros se conserva para cada arco la distancia y duración de su misma geometría; se convierten metros a kilómetros y segundos a horas. La matriz resultante tiene 47 filas y 47 columnas; en la diagonal se fija cero porque no representa desplazamientos entre ciudades distintas. Las tres matrices de combustible publicadas aplican la distancia de la matriz vial y el consumo adoptado. La matriz experimental de Parte 2 utiliza distancia y duración de Directions de una misma ruta para impedir una mezcla silenciosa de alternativas. La preferencia fastest es una regla de selección de ruta, no una afirmación de que se haya demostrado el mínimo global de tiempo en toda la red.")
    h2("10.3. Validación y publicación del conjunto de datos")
    add("El conjunto publicado registra 2.162 pares dirigidos únicos, geometrías completas, unidades originales y derivadas, orden estable, procedencia e integridad mediante hashes. Los controles comprueban que haya geometría válida, distancia y duración positivas, y extras solicitados para todas las rutas. Las geometrías enriquecidas se distribuyeron en once fragmentos comprimidos junto con las matrices base y la documentación en el PR #8, fusionado en main. La atribución indicada es «© openrouteservice by HeiGIT | Data from OpenStreetMap»; los resultados ORS están sujetos a los términos CC BY-SA 4.0 de la cuenta, mientras que los datos OSM se atribuyen bajo ODbL: son instrumentos de licencia distintos (HeiGIT, 2026; OpenStreetMap contributors, 2026). El paquete económico que acompaña este análisis es experimental y debe conservar su propia procedencia y advertencias.")
    table_block(13, "Caracterización de la instancia TSP", ["Atributo", "Descripción"], instances_rows, [1.45, 4.9], "Nota. Cobertura referida a rutas enriquecidas publicadas; la fuente es el manifiesto del dataset y la documentación del repositorio. La geometría describe rutas de carretera, no un mapa administrativo.")

    h1("11. Modelo de costo económico y tratamiento de peajes")
    h2("11.1. Función objetivo")
    add("Para un arco dirigido i→j definimos el costo generalizado en euros como la suma del costo del tiempo, el combustible y el peaje:")
    eq("Cᵢⱼ(v) = v · Tᵢⱼ + Fᵢⱼ + Pᵢⱼ")
    add("Tᵢⱼ se expresa en horas; v, en EUR/h; Fᵢⱼ y Pᵢⱼ, en EUR. El consumo de referencia del BMW 120 F70 es 5,4 L/100 km y el precio utilizado es 1,849098398 EUR/L. Por tanto, para la distancia Dᵢⱼ en kilómetros:")
    eq("Fᵢⱼ = (Dᵢⱼ / 100) · 5,4 · 1,849098398")
    add("Evaluamos v=10, 25 y 50 EUR/h. Estos tres escenarios examinan cómo cambia el peso económico del tiempo; no son estimaciones del valor social oficial del tiempo. Para un tour π, el costo suma los 46 arcos consecutivos y el retorno π₄₇→π₁. Cada una de las 47 ciudades aparece exactamente una vez. La matriz es dirigida y se utiliza sin simetrizarla.")
    eq("C(tour) = Σₖ₌₁⁴⁶ Cπₖ,πₖ₊₁(v) + Cπ₄₇,π₁(v)")
    add("En el Modelo A experimental, distancia, duración, combustible y peaje corresponden a la misma ruta Directions fastest. El baseline, por separado, calcula vT+F sin componente de peajes; por tanto, no representa que viajar por todas las conexiones sea gratuito.")
    h2("11.2. Identificación y estimación de peajes")
    add("ORS identifica segmentos que el perfil marca como tollways, pero esa clasificación no determina un precio, estación de entrada ni estación de salida. La cobertura del paquete económico vigente se reconstruyó desde metadata.json: 1.020 arcos tienen clasificación completa sin segmento tollways; seis reciben una tarifa oficial por asociación inferida con un recorrido nominal; los 1.136 arcos restantes con peaje potencial se valoran con un proxy. Ningún arco tiene un peaje total oficialmente verificado. Los seis casos de asociación inferida corresponden a AP-68 en ambos sentidos, dos composiciones de tramos AP-9 y dos asignaciones de barrera C-32. La vigencia y los importes de referencia provienen de tablas oficiales de 2026; lo incierto es si cada geometría atraviesa exactamente todos los pares o eventos de cobro considerados (Autopistas, 2026; Audasa, 2026; Generalitat de Catalunya, 2026).")
    add("Aplicamos tres tratamientos con distinto alcance. Primero, cuando una geometría es válida y los extras están completos pero no hay intervalo tollways, asignamos P=0 con el estado ZERO_ASSUMED_ORS. Es una hipótesis de modelo, no una certificación oficial de gratuidad. Segundo, en seis arcos aplicamos importes de tarifarios oficiales a una asociación de corredor plausible, conservando que el recorrido tarifario es inferido y no verificado. Tercero, para los demás segmentos potencialmente tarifados utilizamos 0,14145 EUR por kilómetro señalado por ORS. Este coeficiente es un proxy experimental no calibrado como promedio nacional ni como regla de cobro; el bundle mantiene sensibilidades al 50 % y al 150 % del valor central. No afirmamos que los sistemas cerrados cobren literalmente por kilómetro.")
    add("La tabla 14 presenta el estado por arco, no una medición de exactitud tarifaria. Los tres procedimientos cubren 2.162 celdas numéricas del Modelo A, pero la cobertura computacional del 100 % no es cobertura de tarifas oficialmente verificadas. La carpeta strict/ conserva UNKNOWN donde la evidencia no basta para asignar un importe.")
    table_block(14, "Cobertura de valoración de peajes", ["Procedimiento", "Arcos", "%", "Interpretación"], toll_rows, [1.55, 0.55, 0.55, 3.7], "Nota. Los importes oficiales son tarifas transcritas; su asignación a una geometría sigue siendo inferida. ZERO_ASSUMED_ORS y el proxy son supuestos del escenario; ninguno equivale a una liquidación de peaje observada. Conteos verificados en metadata.json del bundle económico local.")
    h2("11.3. Escenarios de valoración económica")
    add("El baseline sin peajes permite aislar la interacción de tiempo y combustible con la misma estructura de visita. El análisis principal, sin embargo, se refiere al Modelo A: conserva la ruta fastest de cada conexión e incorpora el peaje experimental descrito. No presentamos el Modelo B como una comparación implementada y validada entre ruta rápida y alternativa gratuita: en el paquete actual no hay alternativas avoid_tolls con extras completos aceptadas. Los archivos con elección FASTEST_ONLY no demuestran que se haya buscado o validado la mejor alternativa económica.")

    h1("12. Métodos de optimización: colonia de hormigas y algoritmo genético")
    h2("12.1. Optimización por colonia de hormigas (ACO)")
    add("Utilizamos Ant System, una formulación clásica de ACO en la que cada hormiga construye una permutación recorriendo arcos dirigidos. Cada hormiga elige una ciudad inicial de forma seudoaleatoria y, en cada paso, selecciona una ciudad no visitada. La probabilidad de escoger j desde i es proporcional a la feromona τᵢⱼ elevada a α y a la heurística ηᵢⱼ elevada a β; en esta implementación ηᵢⱼ=1/Cᵢⱼ. La probabilidad se normaliza entre las ciudades aún disponibles. Al completar el recorrido, la función objetivo lo cierra con el arco de regreso y calcula su costo total.")
    eq("pᵢⱼ = (τᵢⱼ^α ηᵢⱼ^β) / Σₗ∈Nᵢ (τᵢₗ^α ηᵢₗ^β),   ηᵢⱼ = 1/Cᵢⱼ")
    add("Después de cada colonia, el algoritmo evapora una fracción ρ de la feromona y deposita Q/Cₖ en los arcos dirigidos usados por cada tour k, incluido el cierre. Así, los recorridos de menor costo refuerzan más sus arcos, sin convertir la matriz en simétrica. La implementación verifica que la matriz sea finita, no negativa y de diagonal cero, y utiliza evaluaciones completas para hacer cumplir el presupuesto. El protocolo nacional fijó diez hormigas, α=1, β=2, ρ=0,5, Q=1 y feromona inicial τ₀=1. Se detuvo por presupuesto, no por una prueba de optimalidad (Dorigo, Maniezzo y Colorni, 1996).")
    h2("12.2. Algoritmo genético (GA)")
    add("Un GA para TSP suele representar un individuo mediante una permutación de ciudades y busca producir nuevas permutaciones a partir de selección, recombinación y mutación. Los operadores deben preservar la factibilidad —cada ciudad aparece una sola vez— y la función de aptitud debe evaluar el mismo ciclo dirigido, incluidos sus retornos. La literatura de computación evolutiva documenta familias de operadores y diseños, pero no basta con elegirlos conceptualmente para atribuirlos a una implementación concreta (Eiben y Smith, 2015).")
    add("En la rama auditada no encontramos el código del GA ni archivos de corridas correspondientes a esta instancia. Por ello no especificamos tamaño de población, selección, cruce, mutación, elitismo o parámetros; tampoco reportamos resultados GA. El contrato compartido TSPObjective y RunEvaluator ofrece una integración común: un GA compatible podría recibir la misma matriz dirigida y contabilizar tours completos con presupuesto explícito. La comparación se podrá realizar cuando el integrante responsable suministre su implementación y se igualen instancia, semillas y presupuesto de evaluaciones.")

    h1("13. Protocolo experimental")
    add("El experimento documentado usa la matriz dirigida Model A experimental de 47 capitales, tours cerrados y los escenarios v=10, 25 y 50 EUR/h. Para cada valor del tiempo ejecutamos 30 corridas independientes de Ant System con semillas consecutivas 20261014–20261043. Cada corrida dispone de un máximo de 100 evaluaciones completas de función objetivo. Los registros confirman que cada una consumió las 100. El presupuesto es deliberadamente preliminar y limitado; los resultados describen el comportamiento en ese protocolo, no convergencia al óptimo.")
    add("Conservamos para cada corrida el mejor costo y su desglose, la semilla, el tour abierto y cerrado, el número de evaluaciones, el tiempo de ejecución y los puntos de mejora acumulada. Resumimos el mejor resultado entre semillas, la media, la desviación estándar muestral y el tiempo medio. La tabla 15 recoge los parámetros que efectivamente aparecen en el artefacto de resultados. No afirmamos igualdad de presupuesto con GA porque no existen resultados de GA verificables.")
    table_block(15, "Protocolo experimental del TSP", ["Elemento", "Configuración ejecutada"], protocol_rows, [1.5, 4.85], "Nota. Valores verificados en model_a_experimental_aco_30_runs.json. El tiempo de ejecución depende del entorno y se reporta como media observada por corrida.")

    h1("14. Resultados y comparación")
    add("El archivo de resultados contiene 90 corridas: 30 para cada valor del tiempo, todas con presupuesto agotado. La tabla 16 resume los mínimos, medias y desviaciones estándar muestrales del costo final. El escenario v=25 ofrece un punto central para visualizar la solución; el mejor tour entre sus 30 semillas tuvo costo 4.120,15 EUR y semilla 20261019. La figura 8 dibuja la geometría Directions de los 47 arcos consecutivos de esa solución, incluido el regreso. La representación inicia en Madrid únicamente para facilitar la lectura: rotar un ciclo no modifica sus arcos ni su costo.")
    table_block(16, "Resultados de Ant System sobre el Modelo A experimental", ["v (EUR/h)", "Corridas", "Eval./corrida", "Mejor (EUR)", "Media (EUR)", "Desv. est. (EUR)"], result_rows, [0.8, 0.65, 0.8, 1.0, 1.05, 1.05], "Nota. Cada cifra procede de summaries en model_a_experimental_aco_30_runs.json. La variabilidad es entre 30 semillas ACO; no hay fila GA porque no se ejecutó.")
    add("La solución de menor costo de las 30 semillas con v=25 visita las 47 capitales una vez y cierra el tour en su origen. La visualización no usa líneas rectas entre ciudades: cada tramo dibujado es la geometría vial almacenada para el arco correspondiente. Su secuencia es: " + " → ".join(cities[c]["name"] for c in best_v25["tour_city_ids"]) + " → " + cities[best_v25["tour_city_ids"][0]]["name"] + ".", small=True)
    fig_block(8, "Mejor recorrido ACO entre 30 semillas, Modelo A experimental y v = 25 EUR/h", fig_map, "Nota. Se muestran las geometrías ORS Directions de los arcos elegidos y el cierre del tour. La selección de la mejor semilla es descriptiva y no constituye una prueba de optimalidad. Fuente de geometrías: dataset ORS enriquecido publicado; atribución © openrouteservice by HeiGIT | Data from OpenStreetMap.")
    add("La figura 9 agrega las historias de convergencia de cada escenario. Para cada número de evaluación se conserva el último mejor valor registrado por la corrida; se presenta la mediana y la banda intercuartílica entre semillas. El escalonamiento refleja que el historial registra mejoras y no cada evaluación sin cambio. Las curvas permiten describir el progreso bajo 100 tours evaluados, pero no comparar eficiencia frente a GA ni extrapolar comportamiento asintótico.")
    fig_block(9, "Convergencia ACO por valor del tiempo: mediana e intervalo intercuartílico", fig_conv, "Nota. n=30 semillas por panel. La historia se completa por arrastre del mejor costo conocido entre mejoras; la banda representa percentiles 25–75. Fuente: historial de convergencia del JSON de resultados.")
    add("Al aumentar v cambian los costos de la función objetivo porque el término vT recibe mayor peso; el aumento de los valores agregados no significa que el algoritmo haya empeorado. La desviación observada entre semillas muestra sensibilidad estocástica en este presupuesto corto. La matriz incorpora 1.136 proxies, seis asociaciones de tarifas por inferencia y 1.020 ceros supuestos; por ello los costos son reproducibles respecto de los archivos y parámetros, pero no equivalen al gasto real de un viaje ni permiten una evaluación predictiva de tarifas. No hay base para una prueba estadística de superioridad entre métodos, pues GA no fue ejecutado.")

    h1("15. Discusión, limitaciones y conclusiones")
    h2("15.1. Discusión y limitaciones")
    add("La instancia vial evita dos simplificaciones importantes: tratar las capitales como puntos unidos por distancias rectas y asumir simetría de los desplazamientos. La dirección permite representar que i→j y j→i recorren accesos o rutas distintas. Incluir el valor del tiempo y el combustible convierte la longitud en una decisión económica más interpretable, pero esa interpretación depende de parámetros fijados y de la calidad de cada componente monetario.")
    add("ACO produjo tours cerrados factibles y reproducibles en las 90 corridas registradas. El mejor tour hallado no se debe confundir con el óptimo global: 100 evaluaciones son un presupuesto preliminar pequeño frente al espacio de 46! órdenes. La dispersión de costos resume variación entre semillas, no incertidumbre estadística de precios. El Modelo A sirve para probar el flujo de evaluación y explorar sensibilidad bajo una especificación común, pero 52,54 % de sus arcos depende del proxy general, 47,18 % usa un cero supuesto y 0 % tiene tarifa total oficialmente verificada.")
    add("Persisten cinco límites sustantivos. ORS clasifica segmentos, pero no devuelve importes de peaje; el proxy de 0,14145 EUR/km no está calibrado ni validado como tarifa nacional. Los seis importes asociados a AP-68, AP-9 y C-32 son inferencias de recorrido completo, no comprobaciones de estaciones y todos los eventos tarifarios. Además, se fija una ruta fastest por par y no se modelan variaciones de hora de paso, descuentos ni tráfico dinámico. El Modelo B de rutas alternativas sin peaje no está validado porque no hay alternativas enriquecidas válidas; finalmente, la comparación con GA queda pendiente de implementación y corridas reproducibles del otro integrante.")
    h2("15.2. Conclusiones")
    add("Primero, construimos una instancia reproducible de TSP dirigido con 47 capitales y cobertura de 2.162 rutas viales enriquecidas. Segundo, Ant System generó soluciones cerradas factibles bajo 30 semillas por escenario y un presupuesto uniforme de 100 evaluaciones; las estadísticas describen resultados preliminares, no optimalidad. Tercero, las matrices del Modelo A son numéricamente completas gracias a supuestos visibles, pero no constituyen una matriz nacional de tarifas verificadas: la mayor parte de los peajes positivos usa un proxy y ningún arco tiene peaje total oficialmente verificado. Por tanto, el resultado defendible es una evaluación exploratoria del algoritmo sobre una función económica definida, con precisión tarifaria limitada; no una comparación ACO–GA ni una estimación certificada del costo real de recorrer España.")

    # Insertar todo antes de las secciones comunes y después del título Parte 2.
    append_nodes_before(body, common._p, nodes)
    # Secciones nuevas de referencias: se insertan ordenadas antes de Eiben, conservando las existentes.
    ref_anchor = next(p for p in doc.paragraphs if p.text.startswith("Eiben, A. E."))
    new_refs = [
        "Audasa. (2026). Tarifas de la autopista AP-9, vigentes desde el 1 de enero de 2026. https://www.audasa.es/wp-content/uploads/pdf/tarifas/2026/Tarifas-20260101.pdf",
        "Autopistas. (2026). Tarifas 2026: AP-68, Bilbao–Zaragoza. https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf",
        "Dantzig, G. B., Fulkerson, D. R., y Johnson, S. M. (1954). Solution of a large-scale traveling-salesman problem. Journal of the Operations Research Society of America, 2(4), 393–410. https://doi.org/10.1287/opre.2.4.393",
        "Dorigo, M., Maniezzo, V., y Colorni, A. (1996). Ant System: Optimization by a colony of cooperating agents. IEEE Transactions on Systems, Man, and Cybernetics—Part B: Cybernetics, 26(1), 29–41. https://doi.org/10.1109/3477.484436",
        "Generalitat de Catalunya. (2026). Tarifas de peajes y descuentos de la C-32. https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/peatges-tarifes-descomptes/tarifes-peatges/index.html",
        "HeiGIT. (2026). openrouteservice Directions API: Extra Info. Consultado el 13 de octubre de 2026. https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/",
        "HeiGIT. (2026). Términos de servicio de openrouteservice, sección Attribution and License. Consultados el 13 de octubre de 2026. https://account.heigit.org/info/tos",
        "OpenStreetMap contributors. (2026). Copyright and license (Open Database License, ODbL). Consultado el 13 de octubre de 2026. https://www.openstreetmap.org/copyright",
    ]
    for reference in new_refs:
        p = doc.add_paragraph(reference, style=ref_anchor.style)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(4)
        ref_anchor._p.addprevious(p._p)
    # Quitar el marcador de referencias de Parte 2, no las entradas existentes.
    for p in list(doc.paragraphs):
        if p.text.startswith("[PENDIENTE: referencias de la Parte 2"):
            p._p.getparent().remove(p._p)

    # Comandos TSP en la sección común de reproducibilidad.
    ref_heading = next(p for p in doc.paragraphs if p.text.strip() == "Referencias")
    repro_note = doc.add_paragraph(
        "Para regenerar este informe sin red, instale primero `pip install -r informe/requirements.txt`. La plantilla, el resumen ACO y los metadatos económicos usados se conservan en informe/. Con el dataset vial y sus geometrías disponibles, ejecute:",
        style="Normal",
    )
    ref_heading._p.addprevious(repro_note._p)
    commands = [
        r"python informe/build_informe_trabajo1.py",
    ]
    for command in commands:
        p = doc.add_paragraph(style="Normal")
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(command)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        ref_heading._p.addprevious(p._p)
    note = doc.add_paragraph(
        "La figura de convergencia y la tabla ACO se regeneran desde el resumen experimental conservado; las geometrías del mapa se leen del dataset vial. Para volver a ejecutar las 90 corridas ACO, se requiere además el bundle económico del proyecto y el comando `python -m experiments.run_tsp_economic_aco --bundle data/datasets/spain_tsp_economic_20261013 --dataset data/datasets/spain_tsp_2026 --output data/processed/tsp/model_a_experimental_aco_30_runs.json --budget 100`. Ninguna de estas operaciones llama a ORS.",
        style="Normal",
    )
    ref_heading._p.addprevious(note._p)

    # Actualización automática del índice y metadatos del documento.
    settings = doc.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")
    doc.core_properties.title = "Del gradiente a las hormigas: optimización numérica, metaheurística y combinatoria"
    doc.core_properties.subject = "Trabajo 1: Parte 1 y TSP de España peninsular"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(json.dumps({
        "output": str(OUT),
        "figures": [str(fig_map), str(fig_conv)],
        "runs": len(data["runs"]),
        "best_v25_seed": best_v25["seed"],
        "best_v25_eur": best_v25["best_cost_eur"],
        "economic_status_counts": metadata["toll_status_counts"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
