const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, ImageRun, LevelFormat, PageBreak, TableOfContents,
  Footer, PageNumber,
} = require("docx");

// Genera el informe de la Parte 1 a partir de results/ y figures/.
// Uso (desde la raíz del repo): npm --prefix informe install   y luego   npm --prefix informe run parte1
// Los números de las tablas salen de los CSV; los del texto se revisan a mano si cambian los resultados.
const REPO = process.argv[2] || path.join(__dirname, "..");
const OUT = process.argv[3] || path.join(REPO, "docs", "Informe_Parte1.docx");
const fig = (p) => fs.readFileSync(path.join(REPO, p));

const FONT = "Calibri";
const W = 9026; // ancho útil A4 con márgenes de 1" (DXA)

// ---------- utilidades ----------
function runs(text, opts = {}) {
  // **negrita**, _cursiva_ y [[PENDIENTE]] resaltado
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|_[^_\s][^_]*_|\[\[[^\]]+\]\])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...opts }));
    const t = m[0];
    if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: "Consolas", ...opts, size: Math.min(opts.size || 20, 20) }));
    else if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...opts }));
    else if (t.startsWith("[[")) out.push(new TextRun({ text: "[" + t.slice(2, -2) + "]", highlight: "yellow", ...opts }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...opts }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...opts }));
  return out;
}
const P = (text, o = {}) => new Paragraph({ children: runs(text), spacing: { after: 120, line: 276 }, alignment: AlignmentType.JUSTIFIED, ...o });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const B = (text) => new Paragraph({ numbering: { reference: "vinetas", level: 0 }, children: runs(text), spacing: { after: 60 } });
const EQ = (text) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 120 }, children: [new TextRun({ text, italics: true, font: "Cambria Math" })] });
const CAP = (text) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: runs(text, { size: 18, italics: true, color: "444444" }) });
const IMG = (file, w, h) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120 }, children: [new ImageRun({ type: "png", data: fig(file), transformation: { width: w, height: h } })] });

const border = { style: BorderStyle.SINGLE, size: 4, color: "A6A6A6" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(headers, rows, widths, highlightRows = []) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (t, w, head, hl) => new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: head ? { fill: "1F4E79", type: ShadingType.CLEAR, color: "auto" } : hl ? { fill: "E2EFDA", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: runs(String(t), { size: 18, bold: head, color: head ? "FFFFFF" : undefined }) })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths, alignment: AlignmentType.CENTER,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map((r, j) => new TableRow({ children: r.map((c, i) => cell(c, widths[i], false, highlightRows.includes(j))) })),
    ],
  });
}

// ---------- datos (de results/gd/summary.csv y results/compare/summary.csv) ----------
function csv(p) {
  const [h, ...ls] = fs.readFileSync(path.join(REPO, p), "utf8").trim().split(/\r?\n/);
  const k = h.split(",");
  return ls.map((l) => Object.fromEntries(l.split(",").map((v, i) => [k[i], v])));
}
const gd = csv("results/gd/summary.csv");
const miles = (v) => String(Math.round(Number(v))).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00A0");
const num = (v, d = 3) => {
  const x = Number(v);
  if (x === 0) return "0";
  if (Math.abs(x) >= 1000) return miles(x);
  if (Math.abs(x) < 0.01) { const [m, e] = x.toExponential(1).split("e"); return m.replace(".", ",") + "·10" + e.replace("-", "⁻").replace(/\d/g, (c) => "⁰¹²³⁴⁵⁶⁷⁸⁹"[c]); }
  return x.toLocaleString("es-CO", { maximumSignificantDigits: d });
};
const pct = (v) => Math.round(Number(v) * 100) + " %";
const lr = (v) => Number(v).toExponential(0).replace("e-", "·10⁻").replace(/⁻(\d)$/, (_, d) => "⁻" + "⁰¹²³⁴⁵⁶⁷⁸⁹"[d]);

const sel = gd.filter((r) => r.seleccionada === "True");
const selRows = sel.map((r) => [r.funcion[0].toUpperCase() + r.funcion.slice(1), r.dim + "D", lr(r.lr), num(r.media), num(r.desv), num(r.mediana), num(r.mejor), pct(r["tasa_exito_0.0001"]), pct(r["tasa_exito_0.01"])]);

const rosen = (d) => gd.filter((r) => r.funcion === "rosenbrock" && r.dim === String(d));
// fracción de corridas que quedan atrapadas contra el borde (best_f > 1000)
const div = {};
for (const r of csv("results/gd/runs.csv").filter((r) => r.funcion === "rosenbrock")) {
  const k = `${r.dim}|${Number(r.lr)}`;
  div[k] = div[k] || [0, 0];
  div[k][0] += Number(r.best_f) > 1000 ? 1 : 0;
  div[k][1] += 1;
}
const divFrac = (d, lr) => div[`${d}|${Number(lr)}`][0] / div[`${d}|${Number(lr)}`][1];
const sweepRows = (d) => rosen(d).map((r) => [lr(r.lr), num(r.mediana), num(r.media), num(r.mejor), pct(divFrac(d, r.lr)), pct(r["tasa_exito_0.0001"]), pct(r["tasa_exito_0.01"])]);
const sweepSel = (d) => rosen(d).map((r, i) => (r.seleccionada === "True" ? i : -1)).filter((i) => i >= 0);

// tabla de comparación: una fila por método registrado en results/compare; los que falten quedan pendientes
const comp = csv("results/compare/summary.csv");
const NOMBRES = { gd: "GD", ea: "EA", pso: "PSO", de: "DE" };
const compRows = comp.map((r) => [NOMBRES[r.metodo] || r.metodo, r.funcion[0].toUpperCase() + r.funcion.slice(1), r.dim + "D",
  num(r.mediana), pct(r["tasa_exito_0.0001"]), pct(r["tasa_exito_0.01"]), miles(r.evals_equiv_medias)]);
for (const m of ["ea", "pso", "de"]) {
  if (!comp.some((r) => r.metodo === m)) compRows.push([NOMBRES[m], "…", "…", "[[pend.]]", "[[pend.]]", "[[pend.]]", "[[pend.]]"]);
}

// ---------- documento ----------
const pend = (t) => P(`[[PENDIENTE: ${t}]]`);

const children = [
  // Portada
  new Paragraph({ spacing: { before: 2400 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Trabajo 1 · Parte 1", size: 28, color: "1F4E79" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: "Optimización numérica: descenso por gradiente frente a métodos metaheurísticos", bold: true, size: 40 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [new TextRun({ text: "Funciones de Rosenbrock y Rastrigin en 2D y 3D", size: 26, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Redes Neuronales y Algoritmos Bioinspirados", size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [new TextRun({ text: "Universidad Nacional de Colombia · Facultad de Minas · 2026-02", size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Integrantes", bold: true, size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: runs("Leonard David Vivas Dallos", { size: 24 }) }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: runs("[[Integrante 2]]", { size: 24 }) }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: runs("[[Integrante 3]]", { size: 24 }) }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: runs("Borrador del 12 de octubre de 2026 · [[fecha de entrega por definir]]", { size: 20, color: "666666" }) }),
  new Paragraph({ children: [new PageBreak()] }),

  new Paragraph({ children: [new TextRun({ text: "Contenido", bold: true, size: 32, color: "1F4E79" })], spacing: { after: 200 } }),
  new TableOfContents("Contenido", { hyperlink: true, headingStyleRange: "1-2" }),
  P("_Nota: si el índice aparece vacío, en Word use clic derecho → «Actualizar campos». Lo resaltado en amarillo está pendiente._"),
  new Paragraph({ children: [new PageBreak()] }),

  // 1
  H1("1. Introducción"),
  P("La Parte 1 del trabajo compara un método clásico de optimización numérica, el **descenso por gradiente** con paso fijo, con tres métodos metaheurísticos poblacionales: **algoritmo evolutivo (EA)**, **optimización por enjambre de partículas (PSO)** y **evolución diferencial (DE)**. Los cuatro métodos se aplican a dos funciones de prueba con propiedades opuestas, Rosenbrock y Rastrigin, en dimensión 2 y 3."),
  P("Para que la comparación sea justa, todos los métodos usan el mismo protocolo: las mismas 30 semillas, el mismo dominio, el mismo presupuesto de evaluaciones de la función objetivo y el mismo criterio de éxito. Cada resultado de este informe se regenera con un solo comando desde el repositorio (sección 8)."),
  P("Este borrador contiene completos el protocolo común y el análisis del descenso por gradiente. Las secciones de EA, PSO y DE y la comparación final quedan con la estructura lista para completar cuando estén los resultados de esos métodos."),

  // 2
  H1("2. Funciones de prueba"),
  P("Se eligieron dos funciones que ponen a prueba debilidades distintas de los métodos: una con un único mínimo pero mal condicionada, y otra con muchísimos mínimos locales."),
  H2("2.1 Rosenbrock"),
  EQ("f(x) = Σᵢ₌₁ⁿ⁻¹ [ 100 (xᵢ₊₁ − xᵢ²)² + (1 − xᵢ)² ]"),
  P("Dominio: xᵢ ∈ [−5, 10]. Mínimo global único en x* = (1, …, 1) con f(x*) = 0. El mínimo está en el fondo de un valle largo, estrecho y curvo: encontrar el valle es fácil, pero avanzar por él es difícil porque la curvatura en la dirección transversal es mucho mayor que en la dirección del valle (función mal condicionada). Es una prueba exigente para el descenso por gradiente con paso fijo."),
  P("Su gradiente analítico, obtenido con la regla de la cadena (con u = xᵢ₊₁ − xᵢ²), es:"),
  EQ("∂f/∂xᵢ = −400 xᵢ (xᵢ₊₁ − xᵢ²) − 2 (1 − xᵢ) + 200 (xᵢ − xᵢ₋₁²)"),
  P("donde el primer par de términos aparece para i ≤ n − 1 y el último para i ≥ 2. En 2D se reduce a ∂f/∂x₁ = −400 x₁ (x₂ − x₁²) − 2 (1 − x₁) y ∂f/∂x₂ = 200 (x₂ − x₁²). La implementación (`Rosenbrock.grad` en `src/functions.py`) se verificó contra esta derivación hecha a mano y con pruebas unitarias contra diferencias finitas."),
  H2("2.2 Rastrigin"),
  EQ("f(x) = 10 n + Σᵢ₌₁ⁿ [ xᵢ² − 10 cos(2π xᵢ) ]"),
  P("Dominio: xᵢ ∈ [−5,12; 5,12]. Mínimo global único en x* = 0 con f(x*) = 0. El término coseno crea una malla regular de mínimos locales (cerca de cada punto con coordenadas enteras), de modo que un método local queda atrapado en el mínimo de la cuenca donde arranca. Es la prueba natural para los métodos poblacionales."),
  EQ("∂f/∂xᵢ = 2 xᵢ + 20π sen(2π xᵢ)"),
  P("La curvatura en el óptimo es f''(0) = 2 + 40π² ≈ 396,8. Para un paso fijo η, el descenso por gradiente es estable cerca de un mínimo solo si η < 2 / f'' ≈ 0,005; por eso las tasas probadas en Rastrigin son menores que ese valor."),

  // 3
  H1("3. Protocolo experimental común"),
  P("Estas decisiones son comunes a los cuatro métodos y están registradas en `docs/decisiones.md` (12 de octubre de 2026)."),
  B("**Corridas independientes:** 30 por combinación de método, función y dimensión, con semillas fijas 0 a 29 (`src/seeds.py`). La semilla determina el punto o la población inicial, que se muestrea de forma uniforme en el dominio."),
  B("**Presupuesto:** 20 000 evaluaciones equivalentes de f en 2D y 40 000 en 3D, igual para todos los métodos. [[Provisional hasta tener los resultados de los métodos poblacionales.]]"),
  B("**Conteo de evaluaciones:** el envoltorio `CountedProblem` (`src/counter.py`) cuenta por separado las evaluaciones de f y de ∇f. Una evaluación del gradiente analítico cuesta 1 evaluación equivalente; si el gradiente se calculara por diferencias centrales costaría 2n. Para el descenso por gradiente se reportan ambos totales (`equiv_evals` y `equiv_evals_2n`); el que se compara con el presupuesto es el primero."),
  B("**Criterio de éxito:** una corrida es exitosa si f − f* ≤ 10⁻⁴ (umbral principal). También se reporta el umbral secundario f − f* ≤ 10⁻²."),
  B("**Métricas:** por cada configuración se reportan media, desviación estándar, mediana, mejor y peor valor final de f − f*, evaluaciones usadas y tasa de éxito con ambos umbrales."),
  B("**Dominio:** todos los métodos trabajan dentro de la caja del dominio; los puntos que salen se proyectan al borde (recorte). [[Confirmar con el integrante 2 que EA, PSO y DE usan el mismo manejo del borde.]]"),
  P("Para la comparación todos los métodos comparten una misma interfaz, `metodo(problem, seed, budget, grad_cost, **hiperparámetros) → RunResult` (`src/result.py`), y el mismo script (`experiments/compare.py`) los corre con idénticas semillas y presupuesto."),

  // 4
  H1("4. Descenso por gradiente"),
  H2("4.1 Algoritmo"),
  P("Se implementó el descenso por gradiente con paso fijo y proyección al dominio:"),
  EQ("x₍ₖ₊₁₎ = recorte( x₍ₖ₎ − η ∇f(x₍ₖ₎) )"),
  P("Cada iteración evalúa una vez el gradiente analítico y una vez f (para llevar el mejor valor encontrado), así que cuesta 2 evaluaciones equivalentes. La corrida se detiene al agotar el presupuesto o cuando ‖∇f‖ < 10⁻¹² (el método ya no se mueve). Se reporta el mejor valor de f visto en la trayectoria."),
  H2("4.2 Selección de la tasa de aprendizaje"),
  P("La tasa η es el único hiperparámetro. Se hizo un barrido con 30 corridas por tasa: 8 valores entre 10⁻⁵ y 10⁻³ en Rosenbrock y 3 valores (10⁻⁴, 10⁻³ y 3·10⁻³) en Rastrigin. Para cada función y dimensión se eligió la tasa con **menor mediana** de f − f* final (redondeada a 4 cifras significativas); en caso de empate, la que gasta menos evaluaciones y luego la menor tasa. Se usa la mediana y no la media porque con tasas grandes algunas corridas divergen y la media queda dominada por esos casos."),

  // 5
  H1("5. Resultados del descenso por gradiente"),
  H2("5.1 Resumen con la tasa elegida"),
  table(["Función", "Dim.", "η", "Media", "Desv.", "Mediana", "Mejor", "Éxito 10⁻⁴", "Éxito 10⁻²"], selRows, [1150, 650, 950, 1000, 1000, 1000, 1076, 1100, 1100]),
  CAP("Tabla 1. Descenso por gradiente con la tasa elegida: f − f* final en 30 corridas (fuente: results/gd/summary.csv)."),
  P("Con el umbral principal (10⁻⁴) el descenso por gradiente **no logra ninguna corrida exitosa** en ninguno de los cuatro casos con la tasa elegida. Con el umbral secundario solo hay éxitos en Rosenbrock: 7 % en 2D y 57 % en 3D. En Rastrigin la tasa de éxito es 0 % con ambos umbrales."),

  H2("5.2 Rosenbrock: compromiso entre estabilidad y velocidad"),
  table(["η", "Mediana", "Media", "Mejor", "Atrapadas en el borde", "Éxito 10⁻⁴", "Éxito 10⁻²"], sweepRows(2), [1000, 1300, 1300, 1300, 1726, 1200, 1200], sweepSel(2)),
  CAP("Tabla 2. Barrido de η en Rosenbrock 2D (20 000 evaluaciones). En verde, la tasa elegida. «Atrapadas en el borde»: corridas que terminan con f > 1000."),
  table(["η", "Mediana", "Media", "Mejor", "Atrapadas en el borde", "Éxito 10⁻⁴", "Éxito 10⁻²"], sweepRows(3), [1000, 1300, 1300, 1300, 1726, 1200, 1200], sweepSel(3)),
  CAP("Tabla 3. Barrido de η en Rosenbrock 3D (40 000 evaluaciones). En verde, la tasa elegida."),
  P("El barrido muestra dos regímenes:"),
  B("**Tasas pequeñas (η ≤ 2·10⁻⁴):** ninguna corrida diverge, pero el avance por el valle es lento y el presupuesto se agota antes de llegar al mínimo. Mientras más pequeña la tasa, más lejos queda del óptimo: la mediana con η = 10⁻⁵ es 1,27 en 2D frente a 0,96 con η = 2·10⁻⁴."),
  B("**Tasas grandes (η ≥ 4·10⁻⁴ en 2D, η ≥ 3·10⁻⁴ en 3D):** las corridas que arrancan cerca del valle avanzan rápido y logran los mejores valores individuales (hasta 1,1·10⁻⁸ en 3D con η = 10⁻³), pero las que arrancan lejos, donde el gradiente es enorme (del orden de 4·10⁵ cerca de x₁ = 10), dan saltos que las llevan contra el borde del dominio y quedan atrapadas allí. Con η = 10⁻³ eso le pasa al 77 % de las corridas en 2D y al 97 % en 3D."),
  P("La tasa elegida, η = 2·10⁻⁴, es la mayor que nunca diverge en ninguna de las dos dimensiones. El costo de esa robustez es la precisión: en 2D la mediana final es 0,96, muy lejos del umbral de éxito. En 3D la mediana es mucho menor (4,8·10⁻³) porque el presupuesto es el doble y el método alcanza a hacer 20 000 iteraciones en lugar de 10 000; la figura 1 muestra que en ambos casos la curva sigue bajando al agotar el presupuesto."),
  P("Las tasas grandes logran éxitos con el umbral principal (13 % en 2D con η = 10⁻³, 17 % en 3D con η = 4·10⁻⁴ y 7·10⁻⁴), cosa que la tasa elegida no consigue. Es decir, con paso fijo no existe una tasa que sirva para todos los puntos iniciales: la que es estable lejos del óptimo es demasiado lenta cerca de él, y viceversa. Este es el comportamiento esperado en una función mal condicionada y motiva variantes con paso adaptativo o búsqueda lineal."),

  IMG("figures/gd/gd_convergencia.png", 600, 400),
  CAP("Figura 1. Convergencia del descenso por gradiente: mediana de f − f* de las 30 corridas frente a evaluaciones equivalentes, una curva por tasa. La banda muestra los cuartiles de la tasa elegida (fuente: figures/gd/gd_convergencia.png)."),
  IMG("figures/gd/gd_cajas.png", 600, 400),
  CAP("Figura 2. Distribución de f − f* final en las 30 corridas para cada tasa (fuente: figures/gd/gd_cajas.png)."),

  H2("5.3 Rastrigin: atrapado en el mínimo local más cercano"),
  P("En Rastrigin el resultado no depende de la tasa: las tres tasas producen exactamente la misma media (16,78 en 2D y 25,50 en 3D), la misma mediana y el mismo mejor valor. La razón es que las tres son menores que el límite de estabilidad 2 / f'' ≈ 0,005, así que el método converge siempre al **mínimo local de la cuenca donde arranca**; la tasa solo cambia cuánto tarda en llegar. Con η = 3·10⁻³ la corrida se detiene por gradiente nulo tras unas 21 iteraciones (≈ 42 evaluaciones de las 20 000 disponibles); con η = 10⁻⁴ casi todas las corridas agotan el presupuesto antes de que el gradiente se anule del todo, pero el valor final es el mismo."),
  P("Ninguna corrida llega al mínimo global. El mejor resultado (f ≈ 1,99 en 2D, f ≈ 4,97 en 3D) corresponde a corridas que arrancaron en cuencas vecinas al origen. La figura 3 lo muestra: cada trayectoria se mueve solo una distancia corta hasta el centro de la cuenca local donde empezó."),
  P("Como el método se detiene después de menos del 1 % del presupuesto, el resto de las evaluaciones se desperdicia. Esto deja planteada una mejora natural, no implementada aquí: reiniciar el descenso desde puntos aleatorios hasta agotar el presupuesto (multiarranque)."),
  IMG("figures/gd/gd_rastrigin_niveles.png", 420, 350),
  CAP("Figura 3. Curvas de nivel de Rastrigin 2D y trayectorias del descenso con η = 3·10⁻³ para las semillas 0, 1 y 2 (fuente: figures/gd/gd_rastrigin_niveles.png)."),
  IMG("figures/gd/gd_rosenbrock_niveles.png", 420, 350),
  CAP("Figura 4. Curvas de nivel de Rosenbrock 2D y trayectorias del descenso con η = 2·10⁻⁴: la semilla 0 da un primer salto grande por el gradiente alto lejos del valle, y luego todas avanzan despacio por el fondo del valle hacia (1, 1) (fuente: figures/gd/gd_rosenbrock_niveles.png). El repositorio incluye además animaciones GIF de ambas trayectorias en figures/gd/."),

  // 6
  H1("6. Métodos metaheurísticos"),
  pend("esta sección la completa el integrante 2 con EA, PSO y DE implementados sobre el formato común de src/result.py."),
  H2("6.1 Algoritmo evolutivo (EA)"),
  pend("representación, selección, cruce, mutación, reemplazo, tamaño de población, hiperparámetros elegidos y cómo se eligieron."),
  H2("6.2 Optimización por enjambre de partículas (PSO)"),
  pend("ecuaciones de velocidad y posición, inercia w, coeficientes c₁ y c₂, tamaño del enjambre, manejo del borde, hiperparámetros elegidos."),
  H2("6.3 Evolución diferencial (DE)"),
  pend("estrategia (p. ej. DE/rand/1/bin), F, CR, tamaño de población, manejo del borde, hiperparámetros elegidos."),
  P("Para cada método se recomienda reportar lo mismo que en la sección 5: tabla de resultados con los hiperparámetros elegidos, figura de convergencia y figura de cajas, y animación GIF en 2D."),

  // 7
  H1("7. Comparación de los métodos"),
  P("La comparación se genera con `python -m experiments.compare --config configs/compare.yaml`, que corre todos los métodos registrados en `src/methods.py` con el mismo presupuesto, semillas y umbrales. Por ahora solo está registrado el descenso por gradiente."),
  table(["Método", "Función", "Dim.", "Mediana f − f*", "Éxito 10⁻⁴", "Éxito 10⁻²", "Evals. medias"],
    compRows, [900, 1400, 800, 1626, 1400, 1400, 1500]),
  CAP("Tabla 4. Comparación con el mismo presupuesto y semillas (fuente: results/compare/summary.csv)."),
  pend("insertar figures/compare/compare_convergencia.png y figures/compare/compare_cajas.png regeneradas con los cuatro métodos, y analizar: ¿qué método gana en cada función?, ¿cuántas evaluaciones necesita cada uno para llegar al umbral?, ¿la diferencia es significativa (p. ej. prueba de Wilcoxon sobre las 30 corridas)?"),
  P("Hipótesis a contrastar con los resultados: el descenso por gradiente debería ser competitivo en Rosenbrock si se le da una buena tasa, porque usa información de la pendiente, mientras que en Rastrigin los métodos poblacionales deberían superarlo con claridad porque exploran varias cuencas a la vez."),

  // 8
  H1("8. Conclusiones preliminares"),
  B("El descenso por gradiente con paso fijo es muy sensible a la tasa en una función mal condicionada como Rosenbrock: la tasa estable para todos los puntos iniciales (2·10⁻⁴) es demasiado lenta para alcanzar 10⁻⁴ con el presupuesto dado, y las tasas más rápidas hacen que una parte de las corridas quede atrapada contra el borde."),
  B("En Rastrigin la tasa es irrelevante para el resultado final: el método siempre termina en el mínimo local de la cuenca inicial y usa menos del 1 % del presupuesto. Ninguna de las 120 corridas encontró el mínimo global."),
  B("Contar por separado evaluaciones de f y de ∇f, y reportar el total con gradiente analítico (costo 1) y numérico (costo 2n), deja explícito cuánto le favorece al descenso por gradiente disponer del gradiente exacto."),
  pend("conclusiones de la comparación con EA, PSO y DE."),

  // 9
  H1("9. Uso de inteligencia artificial"),
  P("Según la regla del equipo, todo uso de IA para algo verificable se registra en `docs/alucinaciones.md` con el prompt y la respuesta literales antes de verificarlo."),
  B("**H-04 · Gradiente analítico de Rosenbrock (2D)** (matemáticas): se consultó el gradiente a Gemini y se contrastó con la derivación propia de la sección 2.1, que coincide con la implementación. [[Estado: por verificar; falta pegar en la bitácora el prompt y la respuesta literales.]]"),
  pend("resumen de los demás hallazgos (meta: al menos 5 hallazgos en al menos 3 categorías)."),

  // 10
  H1("10. Reproducibilidad"),
  P("Todo el código está en el repositorio del equipo. Después de `pip install -r requirements.txt`:"),
  B("`python -m experiments.gd_experiment --config configs/gd.yaml`: barrido completo del descenso por gradiente (≈ 3,5 min). Escribe `results/gd/` y `figures/gd/`."),
  B("`python -m experiments.compare --config configs/compare.yaml`: comparación de métodos (≈ 25 s). Escribe `results/compare/` y `figures/compare/`."),
  B("`pytest`: pruebas unitarias de funciones, gradientes, contador, semillas y formato común."),
  P("Cualquier parámetro se puede cambiar sin editar archivos con `--set clave=valor`, por ejemplo `--set metodos.gd.rosenbrock.lr=0.0003`."),

  H1("Referencias"),
  P("[[Verificar cada referencia en la fuente original antes de entregar.]]"),
  P("Nocedal, J. y Wright, S. J. (2006). _Numerical Optimization_ (2.ª ed.). Springer."),
  P("Rosenbrock, H. H. (1960). An automatic method for finding the greatest or least value of a function. _The Computer Journal_, 3(3), 175–184."),
  P("Rastrigin, L. A. (1974). _Systems of Extremal Control_. Nauka, Moscú."),
];

const doc = new Document({
  creator: "Equipo Trabajo 1",
  title: "Trabajo 1 · Parte 1",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, color: "1F4E79" }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 25, bold: true, color: "2E75B6" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "vinetas", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  features: { updateFields: true },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "666666" })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log("ok", OUT); });
