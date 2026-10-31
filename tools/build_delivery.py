"""Genera reporte y dashboard reproducibles usando la corrida real del laboratorio."""
import base64
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from xml.sax.saxutils import escape

os.environ.setdefault("MPLCONFIGDIR", str(Path("tmp/pdfs/mpl").resolve()))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data"
OUT = ROOT / "output/entrega"
ASSETS = OUT / "assets"
OUT.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(exist_ok=True)
for evidence in (ROOT/"entrega/assets").glob("*.png"):
    shutil.copyfile(evidence, ASSETS/evidence.name)
rows = list(csv.DictReader((RUN / "requests.csv").open()))
summary = json.loads((RUN / "summary.json").read_text())
analysis = json.loads((RUN / "analysis.json").read_text())
assert len(rows) == len({r["request_id"] for r in rows}) == summary["completed"] == 6000
assert not any(r["transport_error"] for r in rows)
# La publicación conserva medidas reales y reemplaza las referencias de correlación.
for index, row in enumerate(rows, 1):
    row["request_id"] = f"solicitud-{index:06d}"
    row.pop("scheduled_at", None)
    row.pop("sent_at", None)
summary.pop("finished_at", None)
counts = {str(code): sum(r["status_code"] == str(code) for r in rows) for code in (200, 201, 400, 404, 409, 500)}
assert counts == summary["status_counts"]
lat = np.array([float(r["client_latency_ms"]) for r in rows])
bins = [[r for r in rows if min(59, int(float(r["sent_min"]))) == m] for m in range(60)]
stats = {
    "requests": len(rows), "duration_seconds": summary["elapsed_seconds"],
    "status_counts": counts, "success_pct": (counts["200"] + counts["201"]) / 60,
    "client_error_pct": sum(counts[c] for c in ("400", "404", "409")) / 60,
    "server_error_pct": counts["500"] / 60, "client_mean_ms": float(np.mean(lat)),
    "client_p50_ms": float(np.percentile(lat, 50)), "client_p95_ms": float(np.percentile(lat, 95)),
    "client_max_ms": float(max(lat)), "peak_minute": int(np.argmax([len(b) for b in bins])),
    "peak_requests_per_minute": max(len(b) for b in bins),
    "p95_schedule_lag_ms": float(np.percentile([float(r["schedule_lag_ms"]) for r in rows], 95)),
    "groups": analysis["groups"],
}
(OUT / "resultados.json").write_text(json.dumps(stats, indent=2) + "\n")

# Figuras reconstruidas a partir del CSV, separadas de las capturas nativas de GCP.
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.edgecolor": "#d4dce7", "axes.labelcolor": "#53647a", "xtick.color": "#53647a",
    "ytick.color": "#53647a", "figure.facecolor": "white", "axes.titleweight": "bold"})
fig, ax = plt.subplots(figsize=(9, 2.6), layout="constrained")
for prefix, color, label in [("2", "#275bc9", "Éxitos 2xx"), ("4", "#be781b", "Errores 4xx"), ("5", "#ce5062", "Errores 5xx")]:
    ax.plot(np.arange(60) + .5, [sum(r["status_code"].startswith(prefix) for r in b) / 60 for b in bins], color=color, linewidth=1.7, label=label)
ax.axvspan(35, 45, color="#8961c9", alpha=.09)
ax.set(xlim=(0, 60), ylim=(0, 5.1), xlabel="Minutos desde el inicio", ylabel="Solicitudes/s")
ax.grid(axis="y", color="#e3e8ef")
ax.legend(loc="upper left", frameon=False, ncol=3, fontsize=8)
fig.savefig(ASSETS / "trafico_csv.png", dpi=180)
plt.close(fig)
fig, ax = plt.subplots(figsize=(8.7, 2.7), layout="constrained")
group_map = {(g["category"], g["window"]): g for g in analysis["groups"]}
cats = ["electronics", "books", "clothing"]
for offset, window, color, label in [(-.18, "outside_35-45", "#9eabc0", "Fuera de 35–45"), (.18, "35-45", "#8961c9", "Minutos 35–45")]:
    values = [100 * group_map[c, window]["client_errors"] / group_map[c, window]["requests"] for c in cats]
    bars = ax.bar(np.arange(3) + offset, values, .34, color=color, label=label)
    ax.bar_label(bars, labels=[f"{v:.2f}%" for v in values], padding=4, fontsize=9)
ax.set(xticks=np.arange(3), xticklabels=cats, ylabel="Respuestas 4xx (%)", ylim=(0, 20))
ax.grid(axis="y", color="#e8ecf1"); ax.set_axisbelow(True)
ax.legend(frameon=False, ncol=2, loc="upper right", fontsize=8)
fig.savefig(ASSETS / "escenario_csv.png", dpi=180)
plt.close(fig)

report_md = f"""# API serverless observable en Google Cloud

Andy  
30 de octubre de 2026

## Resumen

Desplegué una API HTTP de pedidos en Cloud Run functions mediante Terraform y ejecuté un simulador asíncrono durante una hora. Completé 6000 solicitudes en {summary['elapsed_seconds']:.3f} segundos, con 6000 identificadores únicos y sin errores de conexión. Registré 5381 respuestas exitosas, 497 errores 4xx y 122 errores 500. El escenario de electronics aumentó su tasa de errores 4xx de 8.82 % a 15.10 %.

## Implementación y metodología

Utilicé un proyecto de Google Cloud en la región us-central1, runtime Python 3.13 y función de entrada handle. Implementé crear, consultar y cancelar pedidos. Conservé el estado en Firestore orders-lab y utilicé una transacción para cancelar sin permitir una segunda cancelación. Configuré FAILURE_RATE=0.02 y EXTRA_LATENCY_MS=0. Mi simulador distribuyó los envíos según una normal N(30,10) en minutos, truncada por rechazo al intervalo de 0 a 60, con semilla 42 e invalid_share=0.08. Preparé 18 solicitudes de control antes de la hora medida y las guardé en preparation.csv, separado de requests.csv.

Ejecuté la corrida durante una hora el 30 de octubre de 2026. Envié X-Request-ID en cada llamada y emití logs JSON con endpoint, código, resultado, error, latencia y atributos de negocio. Creé la métrica basada en logs antes de generar el tráfico.

## Resultados generales

| HTTP | Cantidad | Porcentaje |
|---|---:|---:|
"""
for code, count in counts.items():
    report_md += f"| {code} | {count} | {count/60:.2f} % |\n"
report_md += f"""
La tasa media fue 1.67 solicitudes/s. El intervalo de mayor tráfico fue el minuto 33, con 274 solicitudes (4.57 solicitudes/s), coherente con la concentración alrededor de la media configurada de 30 minutos. La programación tuvo una demora p95 de {stats['p95_schedule_lag_ms']:.2f} ms. Esto indica que el simulador respetó de cerca su agenda en esta corrida.

## Tráfico y latencia

El dashboard mostró la misma subida y bajada del tráfico que el CSV. En la captura de la hora completa, el p95 nativo de GCP osciló aproximadamente entre 50 y 212 ms. La latencia del cliente fue {stats['client_mean_ms']:.2f} ms en promedio, {stats['client_p50_ms']:.2f} ms de mediana y {stats['client_p95_ms']:.2f} ms de p95. El máximo individual fue {stats['client_max_ms']:.2f} ms; este máximo no es un p95.

No identifiqué una subida sostenida del p95 nativo coincidente con el máximo de tráfico. En esta corrida, el mayor volumen no implicó por sí solo mayor latencia. Las variaciones también pueden depender del arranque, el estado de las instancias y las operaciones de Firestore; no realicé una prueba controlada para atribuirles una causa.

La gráfica SQL de latencia por operación mostró que cancelar pedidos tuvo mayor p95 de aplicación durante buena parte del periodo, con un pico cercano a 219 ms. Esto es compatible con que la cancelación realice una transacción y más trabajo de persistencia, pero no demuestra causalidad. La consulta y la creación tendieron a mostrar valores menores.

Distinguí tres mediciones: la latencia HTTP observada por Cloud Run, la latencia registrada dentro de handle y la latencia de extremo a extremo medida por el cliente. Sus percentiles no son intercambiables. No promedié los p95 por minuto para presentar un p95 global.

## Evaluación del escenario

Entre los minutos 35 y 45, dupliqué la probabilidad de eventos inválidos para electronics de 8 % a 16 %. FAILURE_RATE permaneció en 2 %. Comparé proporciones, porque los periodos y categorías tienen distintos volúmenes.

| Categoría | Periodo | Solicitudes | 4xx | Tasa 4xx |
|---|---|---:|---:|---:|
"""
for g in analysis["groups"]:
    report_md += f"| {g['category']} | {'Minutos 35 a 45' if g['window']=='35-45' else 'Fuera de 35 a 45'} | {g['requests']} | {g['client_errors']} | {g['client_errors']/g['requests']*100:.2f} % |\n"
report_md += """
En electronics los 4xx aumentaron de 8.82 % a 15.10 %, una diferencia de 6.28 puntos porcentuales y aproximadamente 1.71 veces la tasa base observada. Al sumar 4xx y 5xx, sus errores pasaron de 10.65 % a 16.85 %. Books y clothing no mostraron el mismo incremento agregado durante la ventana. El resultado es consistente con el escenario configurado, aunque la tasa observada no se duplicó exactamente por la aleatoriedad y la mezcla de tipos de error.

En los extremos de la hora hubo pocos envíos. Por eso una tasa por minuto puede mostrar picos altos por unas pocas fallas; no interpreté esos picos aislados como una caída general del servicio.

## Dashboard y evidencias

Reuní en el dashboard Laboratorio - API observable las métricas nativas de tráfico y p95, una métrica de solicitudes por resultado y categoría basada en logs, un panel de logs y dos gráficas SQL: porcentaje de errores por categoría y latencia p95 por operación. Conservé capturas reales de sus seis paneles con el rango completo de la corrida. El dashboard HTML adjunto permite filtrar el CSV local sin conexión y complementa el panel de Cloud Monitoring.

## Conclusiones

Comprobé que la API procesa operaciones válidas y diferencia errores de entrada, recursos inexistentes, conflictos de estado y fallas internas. La trazabilidad por request_id me permitió relacionar las solicitudes del simulador con los logs de la aplicación. El tráfico reprodujo la concentración esperada y el escenario elevó de forma visible la proporción de errores de la categoría afectada. La combinación de métricas de plataforma, logs estructurados y SQL permitió analizar volumen, latencia y comportamiento de negocio en un mismo dashboard.

El 10.32 % de respuestas de error incluye fallas provocadas deliberadamente; no representa por sí solo disponibilidad de una API de producción. Las métricas del dashboard pueden incorporar llamadas adicionales dentro de su rango si no filtran el ID de esta corrida. Para los totales exactos utilicé las 6000 filas del CSV y, para las consultas SQL, el prefijo del run_id. La limpieza con terraform destroy queda para después de guardar y entregar las evidencias; no la presento como una acción ya ejecutada.

## Pasos para reproducir

1. Crear un proyecto propio y habilitar su facturación.
2. Configurar localmente las plantillas de Terraform, sin publicar la configuración real.
3. Ejecutar terraform init, terraform plan y terraform apply.
4. Configurar localmente la URL de la función y crear las métricas antes del tráfico.
5. Ejecutar el simulador durante una hora y conservar el CSV.
6. Agregar las gráficas SQL al dashboard de Cloud Monitoring y guardar evidencias.
7. Ejecutar terraform destroy después de conservar los resultados.

Para la publicación conservé las mediciones originales y reemplacé las referencias de solicitudes por valores anónimos. Excluí los identificadores de infraestructura, los enlaces privados y los archivos de autenticación.
"""
(OUT / "reporte_editable.md").write_text(report_md)

# PDF con saltos intencionales y evidencias legibles.
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#17273d"), spaceAfter=13))
styles.add(ParagraphStyle(name="ReportH", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#17273d"), spaceBefore=13, spaceAfter=8))
styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=9, textColor=colors.HexColor("#24364b")))
styles.add(ParagraphStyle(name="ReportSmall", fontName="Helvetica", fontSize=8, leading=11, spaceAfter=7, textColor=colors.HexColor("#53647a")))
styles.add(ParagraphStyle(name="ReportCell", fontName="Helvetica", fontSize=9, leading=12))
styles.add(ParagraphStyle(name="ReportHeadCell", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white))
W, H = A4
width = W - 92
story = []
def p(text, style="ReportBody"):
    story.append(Paragraph(text, styles[style]))
def h(text): p(text, "ReportH")
def table(headers, data, widths):
    values = [[Paragraph(escape(str(x)), styles["ReportHeadCell"]) for x in headers]]
    values += [[Paragraph(escape(str(x)), styles["ReportCell"]) for x in row] for row in data]
    t=Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#233e60")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f2f5f9")]),
        ("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d9dfe7")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),9),
        ("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),7),
        ("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    story.extend([t, Spacer(1,9)])
def image(name, caption, max_h=140):
    path=ASSETS/name
    im=PILImage.open(path)
    scale=min(width/im.width,max_h/im.height)
    story.append(Image(str(path), width=im.width*scale,height=im.height*scale,hAlign="LEFT"))
    story.append(Spacer(1,5));p(caption,"ReportSmall")
def page(): story.append(PageBreak())

p("API serverless observable<br/>en Google Cloud", "ReportTitle")
p("Andy<br/>30 de octubre de 2026", "ReportSmall")
p("Desplegué una API de pedidos, generé una hora de tráfico y analicé sus métricas y logs. Completé <b>6000 solicitudes</b> sin errores de conexión. El escenario elevó los errores 4xx de electronics de <b>8.82 % a 15.10 %</b>.")
h("Implementación y metodología")
p("Implementé crear, consultar y cancelar pedidos en Cloud Run functions con Python 3.13 y entrada <b>handle</b>. Desplegué mediante Terraform en un proyecto de Google Cloud, región us-central1. Conservé el estado en Firestore orders-lab; la cancelación utiliza una transacción y rechaza cambios de estado imposibles.")
table(["Parámetro", "Valor utilizado"],[
    ["Distribución de envíos", "Normal N(30, 10) en minutos, truncada a [0, 60]"],
    ["Solicitudes y semilla", "6000 solicitudes; seed = 42"],
    ["Errores intencionales", "invalid_share = 0.08"],
    ["Fallas y demora", "FAILURE_RATE = 0.02; EXTRA_LATENCY_MS = 0"],
    ["Escenario", "electronics; minutos 35 a 45; double_errors"],
    ["Fecha de la corrida", "30 de octubre de 2026"],
    ["Duración medida", "3600.005 segundos"],
], [145,width-145])
p("Antes de iniciar preparé 18 solicitudes de control y creé la métrica basada en logs. La preparación quedó separada de las 6000 solicitudes medidas. Envié X-Request-ID y emití logs JSON con resultado, error, latencia y atributos de negocio.")
h("Resultados generales")
table(["Respuesta", "Cantidad", "Porcentaje"], [["Éxitos 200 y 201","5381","89.68 %"],["Errores 400, 404 y 409","497","8.28 %"],["Errores 500","122","2.03 %"],["Total","6000","100.00 %"]], [245,115,width-360])
p("Validé 6000 filas, 6000 IDs únicos y cero errores de transporte en el CSV. Los porcentajes mostrados están redondeados de forma independiente.","ReportSmall")
page()
h("Tráfico durante el experimento")
image("trafico_gcp.png","Figura 1. Tráfico nativo de Cloud Run separado por clase de respuesta. Captura real de GCP.")
image("trafico_csv.png","Figura 2. Tráfico reconstruido desde requests.csv; cada punto resume un minuto desde el inicio. La franja marca el escenario de electronics.",150)
p("Observé un aumento gradual del tráfico y una disminución posterior, coherentes con la normal configurada. En el CSV, el minuto 33 tuvo <b>274 solicitudes</b>, equivalentes a <b>4.57 solicitudes/s</b>. La tasa media de la hora fue 1.67 solicitudes/s. El pico de éxitos 2xx del panel nativo es menor que el pico total porque separa los códigos de respuesta.")
h("Relación entre tráfico y latencia")
image("latencia_nativa_gcp.png","Figura 3. Percentil 95 de latencia nativa de Cloud Run en la hora completa.")
p("El p95 nativo osciló aproximadamente entre <b>50 y 212 ms</b>. No observé una subida sostenida coincidente con el pico de tráfico. Esto describe esta corrida; no demuestra que la carga nunca afecte la latencia ni permite atribuir los picos a una causa específica.")
page()
h("Latencia por operación y observabilidad")
image("latencia_sql_gcp.png","Figura 4. Consulta SQL sobre latency_ms de los logs de aplicación, agrupada por minuto y endpoint.")
p("Cancelar pedidos mostró mayor p95 de aplicación durante buena parte del periodo, con un pico cercano a <b>219 ms</b>. La transacción y el trabajo adicional en Firestore son una explicación posible; no realicé un experimento separado que confirme esa causa.")
table(["Medición del cliente", "Resultado"], [["Latencia media",f"{stats['client_mean_ms']:.2f} ms"],["Mediana",f"{stats['client_p50_ms']:.2f} ms"],["p95 global",f"{stats['client_p95_ms']:.2f} ms"],["Máximo individual",f"{stats['client_max_ms']:.2f} ms"]], [290,width-290])
p("La latencia del cliente incluye red y respuesta HTTP; el log mide el tiempo dentro del manejador y Cloud Run mide la solicitud en la plataforma. No utilicé sus percentiles como valores intercambiables ni promedié p95 por minuto para calcular un p95 global.")
image("negocio_gcp.png","Figura 5. Métrica basada en logs por outcome y category, creada antes de la corrida.")
image("logs_gcp.png","Figura 6. Panel de logs de solicitudes dentro del mismo dashboard. Los registros conservan el request_id para correlacionarlos con el CSV.")
page()
h("Efecto del escenario en electronics")
p("Entre los minutos <b>35 y 45</b>, dupliqué la probabilidad de eventos inválidos de electronics de 8 % a 16 %. La probabilidad de fallas internas permaneció en 2 %. Comparé tasas para considerar las diferencias de volumen.")
data=[]
for g in analysis["groups"]:
    data.append([g["category"],"35 a 45" if g["window"]=="35-45" else "Fuera",g["requests"],g["client_errors"],f"{g['client_errors']/g['requests']*100:.2f} %"])
table(["Categoría", "Minutos", "Envíos", "4xx", "Tasa 4xx"],data,[119,84,84,70,width-357])
image("escenario_csv.png","Figura 7. Comparación de tasas 4xx calculada desde las filas de la corrida.",151)
p("La tasa 4xx de electronics pasó de <b>8.82 % a 15.10 %</b>: aumentó 6.28 puntos porcentuales, aproximadamente 1.71 veces. Sus errores totales, al sumar 4xx y 5xx, pasaron de 10.65 % a 16.85 %. Books y clothing no mostraron el mismo incremento agregado durante la ventana.")
image("errores_sql_gcp.png","Figura 8. Porcentaje de errores por categoría obtenido con SQL en Log Analytics.")
p("El aumento observado es consistente con el escenario. La tasa no tiene que duplicarse exactamente por la aleatoriedad y la mezcla de errores. Los picos al final de la gráfica corresponden a intervalos de pocos envíos y no deben interpretarse sin revisar su denominador.")
page()
h("Conclusiones y evidencias de entrega")
p("Comprobé que la API acepta solicitudes válidas y distingue errores de payload, recursos inexistentes, conflictos de estado y fallas internas. El tráfico se concentró cerca de la media configurada y el escenario elevó la proporción de errores de electronics. Utilicé métricas de plataforma, logs estructurados y SQL para analizar el comportamiento en un mismo dashboard.")
h("Dashboard del laboratorio")
image("dashboard_gcp.png","Figura 9. Dashboard único de Cloud Monitoring con sus seis paneles. Las figuras anteriores presentan cada panel con mayor detalle.",204)
p("Conservé los paneles nativos de tráfico y p95, la métrica basada en logs por resultado y categoría, el panel de logs y las dos gráficas SQL de errores y latencia por operación. El dashboard HTML adjunto complementa estas evidencias con filtros sobre el CSV y funciona sin conexión.")
h("Alcance de los resultados")
p("El <b>10.32 %</b> de respuestas de error incluye eventos provocados deliberadamente; no lo presento como una medida de disponibilidad de producción. Los totales exactos corresponden al CSV de la corrida. Las métricas nativas y basadas en logs pueden incluir otras llamadas en el mismo rango; las consultas SQL filtran el prefijo del run_id.")
p("No exporté las series numéricas nativas de GCP para calcular correlaciones o causas. Interpreto las capturas como evidencia visual y calculo los resultados exactos desde los archivos del simulador. La limpieza con terraform destroy queda para después de conservar y entregar las evidencias.")
h("Pasos para reproducir")
p("Crear un proyecto propio y habilitar facturación. Completar las plantillas locales, desplegar con Terraform y configurar la URL de la función. Crear las métricas antes de ejecutar el simulador durante una hora. Agregar las gráficas SQL al dashboard, guardar evidencias y eliminar los recursos al terminar.","ReportSmall")
p("Para la publicación conservé las mediciones originales y reemplacé las referencias de solicitudes por valores anónimos. Excluí identificadores de infraestructura, enlaces privados y archivos de autenticación.","ReportSmall")


def footer(canvas, doc):
    canvas.setTitle("API serverless observable en Google Cloud")
    canvas.setAuthor("Andy")
    canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor("#66768a"))
    canvas.drawString(46,27,"Laboratorio de observabilidad en GCP | 30 de octubre de 2026")
    canvas.drawRightString(W-46,27,str(doc.page))
pdf=OUT/"reporte_laboratorio_gcp.pdf"
SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=46,leftMargin=46,topMargin=40,bottomMargin=43).build(story,onFirstPage=footer,onLaterPages=footer)

# HTML autónomo con datos y capturas incrustados.
labels={"trafico_gcp":"Tráfico nativo de Cloud Run", "latencia_nativa_gcp":"Latencia p95 nativa", "negocio_gcp":"Solicitudes por resultado y categoría", "logs_gcp":"Panel de logs de aplicación", "latencia_sql_gcp":"SQL de latencia por operación", "errores_sql_gcp":"SQL de errores por categoría"}
evidence="".join(f'<figure><img alt="{label}" src="data:image/png;base64,{base64.b64encode((ASSETS/(file+".png")).read_bytes()).decode()}"><figcaption>{label} · captura real de GCP</figcaption></figure>' for file,label in labels.items())
fields=list(rows[0].keys())
dataset={"fields":fields,"rows":[[r[k] for k in fields] for r in rows],"groups":analysis["groups"]}
template=(ROOT/"tools/dashboard_template.html").read_text()
(OUT/"dashboard.html").write_text(template.replace("__EVIDENCE__",evidence).replace("__DATA__",json.dumps(dataset,separators=(",",":"),ensure_ascii=False).replace("</","<\\/")))
with (OUT/"requests.csv").open("w",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
(OUT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
for name in ["errors_by_minute.sql","latency_by_endpoint.sql"]:
    shutil.copyfile(ROOT/"lab/observability"/name,OUT/name)
(OUT/"LEEME.txt").write_text("ENTREGA PARA PUBLICACION\n\nReporte en primera persona, dashboard HTML sin conexion, CSV anonimizado y capturas de los paneles. Las mediciones se conservaron; las referencias de solicitudes son anonimas. No se incluyen configuraciones reales, identificadores de infraestructura ni credenciales.\n\nEl HTML complementa el dashboard de Cloud Monitoring. Antes de limpiar los recursos, conserva las evidencias.\n")

print(json.dumps({"pdf":str(pdf),"html":str(OUT/"dashboard.html"),"stats":stats},indent=2))
