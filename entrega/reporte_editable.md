# API serverless observable en Google Cloud

Andy  
30 de octubre de 2026

## Resumen

Desplegué una API HTTP de pedidos en Cloud Run functions mediante Terraform y ejecuté un simulador asíncrono durante una hora. Completé 6000 solicitudes en 3600.005 segundos, con 6000 identificadores únicos y sin errores de conexión. Registré 5381 respuestas exitosas, 497 errores 4xx y 122 errores 500. El escenario de electronics aumentó su tasa de errores 4xx de 8.82 % a 15.10 %.

## Implementación y metodología

Utilicé un proyecto de Google Cloud en la región us-central1, runtime Python 3.13 y función de entrada handle. Implementé crear, consultar y cancelar pedidos. Conservé el estado en Firestore orders-lab y utilicé una transacción para cancelar sin permitir una segunda cancelación. Configuré FAILURE_RATE=0.02 y EXTRA_LATENCY_MS=0. Mi simulador distribuyó los envíos según una normal N(30,10) en minutos, truncada por rechazo al intervalo de 0 a 60, con semilla 42 e invalid_share=0.08. Preparé 18 solicitudes de control antes de la hora medida y las guardé en preparation.csv, separado de requests.csv.

Ejecuté la corrida durante una hora el 30 de octubre de 2026. Envié X-Request-ID en cada llamada y emití logs JSON con endpoint, código, resultado, error, latencia y atributos de negocio. Creé la métrica basada en logs antes de generar el tráfico.

## Resultados generales

| HTTP | Cantidad | Porcentaje |
|---|---:|---:|
| 200 | 3507 | 58.45 % |
| 201 | 1874 | 31.23 % |
| 400 | 170 | 2.83 % |
| 404 | 154 | 2.57 % |
| 409 | 173 | 2.88 % |
| 500 | 122 | 2.03 % |

La tasa media fue 1.67 solicitudes/s. El intervalo de mayor tráfico fue el minuto 33, con 274 solicitudes (4.57 solicitudes/s), coherente con la concentración alrededor de la media configurada de 30 minutos. La programación tuvo una demora p95 de 2.46 ms. Esto indica que el simulador respetó de cerca su agenda en esta corrida.

## Tráfico y latencia

El dashboard mostró la misma subida y bajada del tráfico que el CSV. En la captura de la hora completa, el p95 nativo de GCP osciló aproximadamente entre 50 y 212 ms. La latencia del cliente fue 144.82 ms en promedio, 131.71 ms de mediana y 236.93 ms de p95. El máximo individual fue 4350.61 ms; este máximo no es un p95.

No identifiqué una subida sostenida del p95 nativo coincidente con el máximo de tráfico. En esta corrida, el mayor volumen no implicó por sí solo mayor latencia. Las variaciones también pueden depender del arranque, el estado de las instancias y las operaciones de Firestore; no realicé una prueba controlada para atribuirles una causa.

La gráfica SQL de latencia por operación mostró que cancelar pedidos tuvo mayor p95 de aplicación durante buena parte del periodo, con un pico cercano a 219 ms. Esto es compatible con que la cancelación realice una transacción y más trabajo de persistencia, pero no demuestra causalidad. La consulta y la creación tendieron a mostrar valores menores.

Distinguí tres mediciones: la latencia HTTP observada por Cloud Run, la latencia registrada dentro de handle y la latencia de extremo a extremo medida por el cliente. Sus percentiles no son intercambiables. No promedié los p95 por minuto para presentar un p95 global.

## Evaluación del escenario

Entre los minutos 35 y 45, dupliqué la probabilidad de eventos inválidos para electronics de 8 % a 16 %. FAILURE_RATE permaneció en 2 %. Comparé proporciones, porque los periodos y categorías tienen distintos volúmenes.

| Categoría | Periodo | Solicitudes | 4xx | Tasa 4xx |
|---|---|---:|---:|---:|
| electronics | Fuera de 35 a 45 | 1531 | 135 | 8.82 % |
| electronics | Minutos 35 a 45 | 457 | 69 | 15.10 % |
| books | Fuera de 35 a 45 | 1527 | 120 | 7.86 % |
| books | Minutos 35 a 45 | 480 | 28 | 5.83 % |
| clothing | Fuera de 35 a 45 | 1529 | 113 | 7.39 % |
| clothing | Minutos 35 a 45 | 476 | 32 | 6.72 % |

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
