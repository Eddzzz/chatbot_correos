"""Definiciones iniciales y categorías de las skills predefinidas persistentes."""

POSTAL_ANALYSIS_PRESETS = (
    {
        'id': 'delays', 'name': 'Demoras y tiempos de tránsito', 'category': 'Operación postal', 'stage': 'both',
        'description': 'Duraciones verificadas y envíos pendientes con fechas de referencia explícitas.',
        'instructions': 'Para analizar demoras o tiempos de tránsito, identifica primero las fechas autorizadas de inicio y fin y su significado. La fecha de registro no implica admisión y el último evento no implica entrega. Usa un evento de entrega solo con equivalencia documentada y asociación inequívoca al envío y servicio. Agrega eventos antes de unir para no multiplicar envíos; no mezcles códigos repetidos entre servicios ni registros ambiguos. Calcula duraciones únicamente con fechas válidas, no nulas y ordenadas; informa excluidos y tamaño del conjunto. Para pendientes pide o declara la fecha de corte y distingue antigüedad de demora. Compara con un umbral solo si está documentado o lo proporciona el usuario; sin él presenta tiempos observados y pide el criterio de retraso. No inventes estados, tiempos, causas ni entregas.',
    },
    {
        'id': 'delivery-sla', 'name': 'Cumplimiento de plazos de entrega', 'category': 'Operación postal', 'stage': 'both',
        'description': 'Entregas dentro y fuera de plazo con reglas y denominadores verificables.',
        'instructions': 'Para evaluar cumplimiento de plazos o SLA, verifica el plazo aplicable por servicio, las fechas de inicio y entrega, la zona horaria y si se cuentan días calendario o hábiles. Si falta una regla esencial, solicita aclaración antes de clasificar; no supongas un SLA institucional ni un calendario de feriados. Solo identifica entregas mediante eventos o estados cuya equivalencia esté documentada. Consulta todo el conjunto filtrado, conserva una fila por envío y separa entregados dentro de plazo, fuera de plazo, pendientes y no evaluables. Declara el denominador de la tasa, el período, la fecha de corte, el criterio inclusivo del límite y las exclusiones. No incluyas pendientes como entregas tardías ni interpretes datos ausentes como cumplimiento. Los códigos duplicados sin relación verificable son no evaluables. Fundamenta cada conclusión en agregados consultados.',
    },
    {
        'id': 'period-comparison', 'name': 'Comparación entre períodos', 'category': 'Analítica', 'stage': 'both',
        'description': 'Cambios absolutos y porcentuales con períodos y cobertura comparables.',
        'instructions': 'Para comparar períodos, confirma dos intervalos explícitos y la fecha usada para asignar cada envío. Aplica la misma métrica, servicio, ubicación y filtros a ambos; usa inicio inclusivo y fin exclusivo para fechas con hora. Si solo se indica un mes sin año y el contexto no lo resuelve, pide el año. Consulta agregados del conjunto completo por período antes de calcular diferencias absolutas y porcentuales. La variación porcentual usa el período base como denominador; con base cero indica no calculable. Separa períodos parciales de completos, explica diferencias de duración y cobertura y usa promedios por día solo si tiene sentido y declaras el denominador. Distingue falta de datos de cero real y no atribuyas causalidad a la variación. Conserva las unidades y usa barras o líneas admitidas con valores verificados.',
    },
)

SKILL_PRESETS = (
    {
        'id': 'statistics', 'name': 'Estadística descriptiva', 'category': 'Estadísticas', 'stage': 'both',
        'description': 'Totales, promedios y dispersión con contexto y unidades.',
        'instructions': 'Cuando se solicite un análisis estadístico, consulta agregados del conjunto completo con los filtros de la pregunta. Incluye conteo, suma y promedio solo para métricas numéricas pertinentes; añade mínimo, máximo y dispersión si la fuente y el motor lo permiten. Distingue registros, envíos y eventos para evitar dobles conteos por uniones. Indica período, unidad, tamaño del conjunto y tratamiento de valores nulos. No interpretes códigos o identificadores como cantidades. Explica los resultados con cifras verificadas, sin extrapolar una muestra al total ni inventar estadísticas ausentes.',
    },
    {
        'id': 'trends', 'name': 'Tendencias en el tiempo', 'category': 'Analítica', 'stage': 'both',
        'description': 'Evolución diaria, semanal o mensual y cambios entre períodos.',
        'instructions': 'Para preguntas de evolución temporal, agrupa la métrica solicitada por una granularidad adecuada al período: día, semana o mes. Mantén el mismo alcance y los mismos filtros en toda la serie, ordena cronológicamente y distingue períodos completos de parciales. Calcula cambios absolutos y porcentuales solo entre períodos comparables; si la base es cero, no informes una tasa porcentual indefinida. Usa una gráfica de líneas con agregados verificados cuando proceda. Distingue ausencia de datos de un cero real y no atribuyas causas ni hagas pronósticos sin evidencia.',
    },
    {
        'id': 'comparisons', 'name': 'Comparaciones por sucursal y servicio', 'category': 'Analítica', 'stage': 'both',
        'description': 'Diferencias entre sucursales, servicios o períodos comparables.',
        'instructions': 'Cuando se pida comparar sucursales, servicios o períodos, consulta cada grupo con la misma definición de métrica y filtros comparables. Conserva la identidad de las sucursales y muestra sus nombres municipales, sin fusionar sucursales distintas. Presenta totales, diferencias absolutas y, cuando exista una base distinta de cero, variación porcentual. Declara el denominador de las tasas y el alcance geográfico y temporal. Usa barras para categorías cuando ayuden a comparar. Señala limitaciones de cobertura y no equipares volumen con calidad de servicio ni atribuyas causalidad.',
    },
    {
        'id': 'rankings', 'name': 'Rankings y concentración', 'category': 'Analítica', 'stage': 'both',
        'description': 'Principales sucursales o servicios y su peso en el total.',
        'instructions': 'Para consultas de principales sucursales, servicios u otras categorías, agrega primero todo el conjunto filtrado y luego ordena por la métrica solicitada. Aplica el número de posiciones pedido y un criterio de desempate estable. Si muestras participación, calcula el denominador sobre el total filtrado, antes de limitar el ranking; no uses la suma del top como si fuera el total. Distingue ranking completo y selección parcial, informa empates relevantes y utiliza gráficas de barras para comparar magnitudes. No completes categorías ni cifras que no estén en los resultados.',
    },
    {
        'id': 'percentages', 'name': 'Distribuciones y porcentajes', 'category': 'Estadísticas', 'stage': 'both',
        'description': 'Participación por categoría con denominadores explícitos.',
        'instructions': 'Para preguntas de distribución o participación, calcula conteos y porcentajes por la categoría solicitada usando el conjunto completo con los mismos filtros. Explica cuál es el denominador y cómo se tratan nulos o categorías sin información. Solo afirma que los porcentajes suman 100 % cuando las categorías son mutuamente excluyentes y exhaustivas; aclara diferencias por redondeo. Para eventos o estados repetidos, evita contar un envío varias veces salvo que la pregunta trate de eventos. Usa barras si corresponde y conserva unidades y etiquetas legibles.',
    },
    {
        'id': 'charts', 'name': 'Gráficas de barras y líneas', 'category': 'Gráficas', 'stage': 'planner',
        'description': 'Barras para comparar categorías; líneas para series temporales.',
        'instructions': 'Cuando la pregunta solicite una gráfica o un dashboard, elige barras para comparar categorías y líneas para la evolución temporal. Usa únicamente el contrato gráfico admitido: chart con kind bar o line, label_column y value_column existentes en el resultado agregado, y label con la métrica y su unidad. Consulta agregados del conjunto completo, nunca presentes una muestra como total. Ordena las fechas cronológicamente y las categorías según la comparación pedida. Mantén nombres de sucursales legibles y conserva su identidad. No inventes puntos, series o valores ni solicites tipos de gráfica no admitidos. Si faltan datos, explica la limitación en lugar de fabricar una gráfica.',
    },
    {
        'id': 'outliers', 'name': 'Variaciones y valores atípicos', 'category': 'Estadísticas', 'stage': 'both',
        'description': 'Cambios inusuales con una referencia y un criterio explícitos.',
        'instructions': 'Si se solicitan anomalías o variaciones inusuales, compara métricas verificadas entre grupos o períodos equivalentes y explica el criterio usado. Calcula medidas de dispersión o umbrales solo cuando el motor, la fuente y el tamaño del conjunto lo permitan. Separa casos extremos observados de anomalías estadísticamente justificadas. No declares significancia, fraude ni causas a partir de una diferencia aislada. Indica limitaciones por grupos pequeños, valores ausentes, períodos incompletos o cambios de cobertura y utiliza únicamente resultados consultados.',
    },
    {
        'id': 'data-quality', 'name': 'Calidad y cobertura de datos', 'category': 'Analítica', 'stage': 'both',
        'description': 'Nulos, duplicados y cobertura antes de interpretar resultados.',
        'instructions': 'Cuando se pida revisar la calidad o interpretar estadísticas, verifica la cobertura temporal, campos necesarios ausentes y duplicados relevantes mediante consultas de solo lectura. Define la clave de duplicado según la entidad y distingue eventos legítimamente repetidos de envíos duplicados. Presenta conteos y proporciones con denominadores explícitos y explica cómo afectan a las conclusiones. No modifiques registros ni consultes tablas no habilitadas. No asumas que los datos ausentes valen cero ni que una falta de cobertura representa ausencia de actividad.',
    },
) + POSTAL_ANALYSIS_PRESETS + (
    {
        'id': 'extended-statistics', 'name': 'Estadísticas ampliadas', 'category': 'Estadísticas', 'stage': 'both',
        'description': 'Rango, promedios, cobertura y variaciones sobre el conjunto completo.',
        'instructions': 'Cuando se pidan más estadísticas, consulta COUNT, SUM, AVG, MIN y MAX de peso, precio u otras medidas pertinentes del conjunto completo filtrado. Incluye conteo de valores válidos y nulos, rango MAX menos MIN y promedios por grupo cuando correspondan. Usa solo expresiones SQL autorizadas; no solicites funciones de mediana, percentiles o desviación no admitidas por el motor. No promedies códigos, identificadores ni promedios de grupos sin ponderar. Conserva unidades documentadas, período y filtros; no supongas moneda ni unidad de peso. Para porcentajes y variaciones declara denominador y trata base cero como no calculable. Presenta solo medidas consultadas, sin extrapolar filas visibles ni confundir registros con envíos.',
    },
    {
        'id': 'evidence-advice', 'name': 'Consejos basados en evidencia', 'category': 'Respuestas', 'stage': 'analyst',
        'description': 'Un siguiente paso breve vinculado a las cifras consultadas.',
        'instructions': 'Incluye consejos únicamente cuando el usuario los pida expresamente; pedir una explicación o interpretar datos no equivale a pedir consejos. Cuando los solicite, incluye como máximo un hallazgo kind advice con referencias a celdas relevantes de una misma fila. Diferencia una recomendación de un hecho observado. No atribuyas causas, incumplimientos, calidad de servicio o necesidades de personal a un volumen aislado; no inventes acciones, metas, plazos ni medidas institucionales. Conserva las referencias y el esquema JSON. Mantén el consejo breve y, si pide desarrollarlo, usa únicamente evidencia verificada del mismo contexto.',
    },
    {
        'id': 'statistical-reporter', 'name': 'Reportero estadístico y PDF', 'category': 'Informes', 'stage': 'both',
        'description': 'Informes con indicadores, comparaciones y consejos exportables a PDF.',
        'instructions': 'Si se solicita un reporte o informe estadístico, usa intent report y hasta seis consultas autorizadas: indicadores globales, distribución por la categoría pedida, evolución temporal y comparación cuando los datos lo permitan. Incluye solo secciones pertinentes y conserva el mismo período, servicio y ubicación. Usa barras o líneas admitidas sobre agregados completos; no inventes datos faltantes. El analista organiza primero los principales indicadores, después comparaciones verificadas y un consejo breve si procede. Amplía cuando el usuario lo pida. La respuesta verificada y las tablas de las páginas seleccionadas se incluyen en la exportación PDF existente; no afirmes que un archivo fue creado o descargado por emitir una respuesta. No prometas que el PDF contiene todas las filas si solo se exportan páginas seleccionadas.',
    },
)
