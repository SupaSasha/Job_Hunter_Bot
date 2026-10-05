"""ES Telegram interface catalog."""

ES = {
    "common.back": "← Volver",
    "common.cancel": "Cancelar",
    "common.add": "Agregar",
    "common.remove": "Quitar",
    "common.clear": "Borrar",
    "common.any": "Cualquiera",
    "common.none": "Ninguna",
    "common.yes": "Sí",
    "common.no": "No",
    "common.unknown": "Desconocido",
    "common.not_specified": "sin especificar",
    "common.enabled": "Activado",
    "common.disabled": "Desactivado",
    "common.current": "Actual",
    "language.title": "🌐 Idioma",
    "language.choose": "Choose your language / Elegí tu idioma",
    "language.menu": "🌐 Idioma\n\nActual: {name}",
    "language.updated": "Idioma cambiado a {name}.",
    "start.welcome": (
        "Job Hunter Bot\n\nBusco vacantes remotas, las filtro según tus "
        "preferencias, calculo su compatibilidad y te envío las mejores "
        "en un resumen diario de vacantes.\n\nUsá /help para ver los "
        "comandos disponibles."
    ),
    "help.public": (
        "Comandos disponibles\n\n/start - Información del bot\n/help - Ver "
        "comandos disponibles\n/status - Estado del bot\n/saved - Vacantes "
        "guardadas\n/filters - Filtros de búsqueda\n/settings - "
        "Configuración\n/cancel - Cancelar la entrada actual"
    ),
    "help.admin": (
        "\n\nComandos de administración:\n/collect - Ejecutar los "
        "recolectores ahora\n/digest - Obtener vacantes ahora\n/stats "
        "[24h|7d|30d] - Estadísticas del sistema"
    ),
    "command.unavailable": "Este comando no está disponible.",
    "command.unknown": (
        "Comando desconocido. Usá /help para ver los comandos disponibles."
    ),
    "input.cancelled": "Entrada cancelada.",
    "saved.empty": "Todavía no guardaste ninguna vacante.",
    "saved.title": "⭐ Vacantes guardadas:",
    "saved.continued": "Vacantes guardadas (continuación):",
    "status.never": "Nunca",
    "status.not_scheduled": "Sin programar",
    "status.today": "Hoy",
    "status.collector": (
        "{name}\nÚltima ejecución exitosa: {last_success}\nPróxima "
        "ejecución: {next_run}\nÚltimo estado: {status}"
    ),
    "status.body": (
        "🤖 Estado: en funcionamiento\n\n{collectors}\n\nVacantes en la base "
        "de datos: {count}\n\nResumen diario de vacantes:\nHora: {time}\nZona "
        "horaria: {timezone}\nÚltimo resumen: {last_digest}\nActivado: "
        "{enabled}\n\nHorarios en {zone}."
    ),
    "command.stats_usage": "Uso: /stats [24h|7d|30d]",
    "command.stats_unavailable": "Las estadísticas no están disponibles.",
    "command.stats_failed": "Las estadísticas no están disponibles por el momento.",
    "command.collect_started": "Recolección iniciada.",
    "command.collect_failed": "No se pudo iniciar la recolección.",
    "digest.queued": "🔎 Preparando tu resumen de vacantes…",
    "digest.failed": "No se pudo preparar tu resumen de vacantes.",
    "digest.already_sent": "Ya se envió tu resumen de vacantes de hoy.",
    "digest.in_progress": "Tu resumen de vacantes ya se está preparando.",
    "digest.attempted": "Ya se intentó enviar tu resumen de vacantes de hoy.",
    "digest.empty": "No hay nuevas vacantes que coincidan con tus filtros.",
    "digest.summary": (
        "🔥 {count} nuevas vacantes compatibles\n\nMejores coincidencias:\n" "{matches}"
    ),
    "settings.title": "⚙️ Configuración",
    "settings.timezone": "Zona horaria",
    "settings.digest_time": "Resumen diario",
    "settings.min_score": "Puntaje mínimo de compatibilidad",
    "settings.plan": "Plan",
    "settings.trial_ends": "Fin de la prueba",
    "settings.custom_time": "Horario personalizado del resumen 🔒",
    "settings.custom_score": "Puntaje mínimo personalizado 🔒",
    "settings.timezone_button": "🌎 Zona horaria",
    "settings.time_button": "🕐 Resumen diario",
    "settings.score_button": "🎯 Puntaje mínimo",
    "settings.unavailable": (
        "La configuración de notificaciones todavía no está disponible."
    ),
    "settings.invalid": "Configuración inválida.",
    "settings.not_available": "Esta opción no está disponible.",
    "settings.choose_timezone": "Elegí tu zona horaria.",
    "settings.choose_time": "Elegí el horario de tu resumen diario de vacantes.",
    "settings.choose_score": "Elegí el puntaje mínimo de compatibilidad.",
    "settings.timezone_updated": "Zona horaria cambiada a {value}.",
    "settings.time_updated": "Horario del resumen cambiado a {value}.",
    "settings.score_updated": "Puntaje mínimo cambiado a {value}%.",
    "settings.premium_required": "Esta opción requiere Prueba o Premium.",
    "settings.edit_failed": (
        "No se pudo actualizar el menú. Abrí /settings para revisar tu "
        "configuración."
    ),
    "settings.locked_time": (
        "El horario personalizado del resumen está disponible durante la "
        "prueba o con Premium.\n\nTu horario actual de envío es {value}."
    ),
    "settings.locked_score": (
        "El puntaje mínimo personalizado está disponible durante la "
        "prueba o con Premium.\n\nTu puntaje mínimo actual es {value}%."
    ),
    "filters.title": "🔎 Filtros de empleo",
    "filters.updated": "✅ Filtros de empleo actualizados.",
    "filters.unavailable": "Los filtros de empleo todavía no están disponibles.",
    "filters.not_available": "Este filtro no está disponible.",
    "filters.edit_failed": (
        "No se pudo actualizar el menú. Abrí /filters para revisar tus " "filtros."
    ),
    "filters.any_amount": "Cualquier monto",
    "filters.any_currency": "Cualquier moneda",
    "filters.tolerance": "Tolerancia horaria: ±{hours}h",
    "filters.any_selections": "Sin opciones seleccionadas se acepta cualquiera.",
    "filters.regions_help": (
        "Elegí las regiones permitidas. Sin regiones seleccionadas se "
        "excluyen las vacantes con una región indicada."
    ),
    "filters.source_minimum": "Debe quedar al menos una fuente activada.",
    "filters.salary_screen": (
        "Salario mínimo\n\nActual:\n{salary}\n\nNo se aplica conversión de " "monedas."
    ),
    "filters.set_amount": "Ingresar monto",
    "filters.currency": "Moneda",
    "filters.choose_currency": "Elegí la moneda del salario.",
    "filters.blacklist_title": "🚫 Lista de exclusión",
    "filters.words": "Palabras",
    "filters.companies": "Empresas",
    "filters.timezone_hint": "La zona horaria se configura en /settings.",
    "filters.reset": "Restablecer filtros",
    "filters.reset_confirm": "¿Restablecer todos los filtros?",
    "filters.reset_yes": "Sí, restablecer",
    "input.salary": "Enviá un número entero sin símbolos de moneda.\n\nEjemplo:\n2500",
    "input.add_keywords": "Enviá las palabras clave separadas por comas.",
    "input.remove_keywords": (
        "Enviá las palabras clave que querés quitar, separadas por comas."
    ),
    "input.add_tech": "Enviá una o más tecnologías separadas por comas.",
    "input.remove_tech": (
        "Enviá las tecnologías que querés quitar, separadas por comas."
    ),
    "input.add_words": "Enviá las palabras que querés excluir, separadas por comas.",
    "input.remove_words": (
        "Enviá las palabras excluidas que querés quitar, separadas por " "comas."
    ),
    "input.add_companies": (
        "Enviá las empresas que querés excluir, separadas por comas."
    ),
    "input.remove_companies": (
        "Enviá las empresas excluidas que querés quitar, separadas por " "comas."
    ),
    "input.keywords_example": "\n\nEjemplo:\npython, backend, api",
    "input.expiry": "\n\nUsá /cancel para cancelar. La entrada vence en 10 minutos.",
    "input.retry": "{error}\n\nIntentá de nuevo o usá /cancel.",
    "error.invalid_list": "Entrada de lista inválida.",
    "error.empty_list": "Enviá al menos un valor; separá varios valores con comas.",
    "error.list_size": "Usá hasta 50 valores de 100 caracteres como máximo cada uno.",
    "error.list_limit": "Usá hasta 50 valores.",
    "error.list_action": "Acción de lista inválida.",
    "error.tech_conflict": (
        "Primero quitá estas tecnologías de la lista de tecnologías " "excluidas."
    ),
    "error.filter_option": "Opción de filtro inválida.",
    "error.filter_screen": "Pantalla de filtros inválida.",
    "error.salary": (
        "Enviá un número entero entre 0 y 2147483647, sin símbolos de " "moneda."
    ),
    "error.currency": "Moneda inválida.",
    "error.tolerance": "La tolerancia horaria debe estar entre 0 y 4 horas.",
    "error.language": "Idioma inválido.",
    "error.timezone": "Zona horaria inválida",
    "error.digest_time": (
        "El horario del resumen debe ser una hora local con precisión de " "minutos"
    ),
    "error.score": "El puntaje mínimo debe ser un número entero entre 0 y 100",
    "job.match": "🔥 Compatibilidad: {score}%",
    "job.company": "Empresa",
    "job.company_missing": "Empresa no especificada",
    "job.salary": "Salario",
    "job.salary_missing": "Salario no especificado",
    "job.salary_from": "Desde {amount}",
    "job.salary_up_to": "Hasta {amount}",
    "job.remote": "Remoto",
    "job.region": "Región",
    "job.region_missing": "Región no especificada",
    "job.employment": "Tipo de empleo",
    "job.employment_missing": "Tipo de empleo no especificado",
    "job.technologies": "Tecnologías",
    "job.technologies_missing": "Tecnologías no especificadas",
    "job.experience": "Experiencia",
    "job.source": "Fuente",
    "job.matches": "Coincidencias",
    "job.penalties": "Penalizaciones",
    "job.warnings": "Avisos",
    "job.open": "Ver vacante",
    "job.save": "Guardar",
    "job.reject": "No me interesa",
    "feedback.invalid": "Acción inválida",
    "feedback.unregistered": "El usuario no está registrado",
    "feedback.inactive": "El usuario está inactivo",
    "feedback.not_found": "Vacante no encontrada",
    "feedback.saved": "Guardada.",
    "feedback.rejected": "Marcada como no adecuada.",
    "score.base": "Puntaje base: +50",
    "score.preferred": "Tecnología preferida {technology}: {points}",
    "score.keyword": "Palabra clave: {keyword}: +3",
    "score.region": "Región {region}: {points}",
    "score.timezone_compatible": "Zona horaria compatible: +10",
    "score.timezone_distance": "Diferencia horaria: {distance} h: {points}",
    "score.timezone_far": "Diferencia horaria: 5+ h: -20",
    "score.region_penalty": "Región no especificada: -2",
    "score.region_unknown": "Región remota desconocida",
    "score.timezone_penalty": "Zona horaria no especificada: -2",
    "score.timezone_missing": "Zona horaria no especificada",
    "score.experience_missing": "Nivel de experiencia no especificado",
    "score.level": "Nivel {level}: {points}",
    "score.title_seniority": "Nivel indicado en el título: {level}: {points}",
    "score.years": "Requiere {years}+ años de experiencia: {points}",
    "score.salary_penalty": "Salario no especificado: -2",
    "score.salary_missing": "Salario no especificado",
    "score.employment_missing": "Tipo de empleo no especificado",
    "score.full_time": "Tiempo completo: +3",
    "score.remote": "Remoto: +10",
    "label.keywords": "Palabras clave",
    "label.required_technologies": "Tecnologías requeridas",
    "label.preferred_technologies": "Tecnologías preferidas",
    "label.excluded_technologies": "Tecnologías excluidas",
    "label.blacklisted_words": "Palabras excluidas",
    "label.blacklisted_companies": "Empresas excluidas",
    "label.allowed_regions": "Regiones",
    "label.employment_types": "Tipo de empleo",
    "label.experience_levels": "Experiencia",
    "label.sources": "Fuentes",
    "label.remote_only": "Solo remoto",
    "label.exclude_us_only": "Excluir vacantes solo para EE. UU.",
    "label.full_time": "Tiempo completo",
    "label.part_time": "Medio tiempo",
    "label.contract": "Contrato",
    "label.freelance": "Freelance",
    "label.internship": "Pasantía",
    "label.junior": "Junior",
    "label.middle": "Intermedio",
    "label.senior": "Senior",
    "label.lead": "Lead",
    "label.staff": "Staff",
    "label.principal": "Principal",
    "label.architect": "Arquitecto",
    "label.engineering manager": "Gerente de ingeniería",
    "label.worldwide": "Todo el mundo",
    "label.latam": "Latinoamérica",
    "label.south_america": "Sudamérica",
    "label.uruguay": "Uruguay",
    "label.americas": "América",
    "label.north_america": "Norteamérica",
    "label.europe": "Europa",
    "label.eu": "Unión Europea",
    "label.emea": "EMEA",
    "label.apac": "APAC",
    "label.us_only": "Solo EE. UU.",
    "label.month": "mes",
    "label.year": "año",
    "label.hour": "hora",
    "label.Trial": "Prueba",
    "label.Free": "Gratis",
    "label.Premium": "Premium",
    "status.success": "éxito",
    "status.failed": "falló",
    "status.skipped": "omitido",
    "status.running": "en curso",
    "status.scheduled": "programado",
    "status.sent": "enviado",
    "status.pending": "pendiente",
    "status.empty": "sin coincidencias",
    "status.partial": "parcial",
    "status.abandoned": "abandonado",
    "status.unknown": "desconocido",
    "status.retryable": "pendiente de reintento",
    "status.active": "activo",
    "status.expired": "vencido",
    "status.trial": "prueba",
    "filters.button_keywords": "🔎 Palabras clave",
    "filters.button_reqtech": "🧰 Tecnologías requeridas",
    "filters.button_preftech": "⭐ Tecnologías preferidas",
    "filters.button_extech": "🚫 Tecnologías excluidas",
    "filters.button_regions": "🌎 Regiones",
    "filters.button_employment": "💼 Tipo de empleo",
    "filters.button_experience": "📈 Experiencia",
    "filters.button_salary": "💰 Salario",
    "filters.button_sources": "📡 Fuentes",
    "filters.button_blacklist": "🚫 Lista de exclusión",
    "filters.button_tz_tol": "🕐 Tolerancia horaria",
    "filters.button_reset": "Restablecer filtros",
    "filters.minimum_salary": "Salario mínimo",
}
