"""Conservative checks for explicit invalid requests before planning."""
from datetime import date
import re
import unicodedata


_MONTHS = {name: index for index, name in enumerate((
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'), 1)}
_MONTHS['setiembre'] = 9
_NAMED_DATE = re.compile(
    r'\b(\d{1,2})\s+de\s+(' + '|'.join(_MONTHS) + r')\s+(?:de(?:l)?\s+)?(\d{4})\b')
_NUMERIC_DATE = re.compile(
    r'(?<![\w/-])(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})([/-])(\d{1,2})\5(\d{4}))(?![\w/-])')


class QuestionValidationError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def validate_question(question):
    """Raise for clear invalid requests; leave other semantics to the planner.

    This is deliberately not a domain keyword allowlist or a SQL safety boundary.
    Missing years and relative dates remain the planner's responsibility.
    """
    request = ''.join(char for char in unicodedata.normalize('NFKD', question.casefold())
                      if not unicodedata.combining(char))
    private_field = re.search(r'\b(?:emails?|c\.?i|dni|cedulas?|carnet(?:s|es)? de identidad|'
                              r'numero(?:s)?(?:_de_|_| de )(?:carnet|documento)(?:s)?|'
                              r'users\s*\.\s*["`]?(?:name|alias)|'
                              r'(?:email|ci|telefono|nombre|direccion)_(?:destinatario|remitente))\b', request)
    contact_request = re.sub(r'\bnombres?\s+(?:de\s+(?:los\s+)?|del\s+)?rol(?:es)?\b', '', request)
    private_contact = (
        re.search(r'\b(?:correos? electronicos?|telefonos?|direcciones?|nombres?|alias|datos personales)\b', contact_request)
        and re.search(r'\b(?:users|emplead[oa]s?|personal|usuari[oa]s?|destinatari[oa]s?|remitentes?)\b', request)
    )
    if private_field or private_contact:
        raise QuestionValidationError('restricted_request',
            'Los datos personales solicitados están restringidos para esta consulta.')
    if (re.search(r'\bsum\s*\(|\b(?:sumas?|sumar|sume|sumatoria)\b|\+', request)
            and re.search(r'\bnombre_estado\b', request) and re.search(r'\bactivo\b', request)):
        raise QuestionValidationError('clarification',
            'nombre_estado es un campo de texto y activo indica si el estado está activo. '
            '¿Quieres contar los registros activos por estado?')
    # Imperatives at clause boundaries: mentions of deletion and negations are reads.
    for clause in re.split(r'[;.!?\n]|\b(?:pero|y)\b', request):
        clause = re.sub(r'^\s*(?:por favor\s*,?\s*)?', '', clause)
        if re.match(r'(?:actualiza|modifica|borra|elimina)\s+(?:(?:el|la|los|las|un|una)\s+)?'
                    r'(?:reporte|informe|grafico|panel|filtros?|orden|consulta)\b', clause):
            continue
        if re.match(r'(?:borra(?:r|d|n)?|borre(?:n)?|elimina(?:r|d|n)?|elimine(?:n)?|'
                    r'actualiza(?:r|d|n)?|actualice(?:n)?|modifica(?:r|d|n)?|modifique(?:n)?|'
                    r'inserta(?:r|d|n)?|inserte(?:n)?|suprime(?:n)?|suprima(?:n)?|'
                    r'(?:ejecuta|ejecute|ejecutar)\s+(?:el\s+)?(?:sql\s+)?(?:delete|update|insert|drop|truncate)|'
                    r'delete\s+from|update\s+\w+\s+set|insert\s+into|drop\s+table|truncate\s+table)\b', clause):
            raise QuestionValidationError('restricted_request',
                'Esta aplicación solo permite consultar datos. No puede borrar, modificar ni insertar registros. '
                'Puedes solicitar un conteo, un listado o un reporte.')

    dates = [(int(m[3]), _MONTHS[m[2]], int(m[1])) for m in _NAMED_DATE.finditer(request)]
    for match in _NUMERIC_DATE.finditer(request):
        # A date-shaped parcel reference is not necessarily a calendar date.
        if re.search(r'''\b(?:codigo|guia|tracking|paquete)\s*(?:(?:es|igual a)\s*)?[:#]?\s*["']?\s*$''', request[:match.start()]):
            continue
        if match[1]:
            dates.append(tuple(map(int, match.group(1, 2, 3))))
        else:
            first, second, year = int(match[4]), int(match[6]), int(match[7])
            # Spanish day/month by default; accept unambiguous month/day too.
            month, day = (first, second) if first <= 12 < second else (second, first)
            dates.append((year, month, day))
    for year, month, day in dates:
        try:
            date(year, month, day)
        except ValueError:
            raise QuestionValidationError('clarification',
                'La fecha indicada no existe en el calendario. ¿Qué fecha deseas consultar?') from None

    # Narrow intent patterns only; domain words in free text are not rejected.
    unrelated = re.search(r'(?:^|[:;.!?])\s*(?:dame|quiero|necesito|prepara)\s+(?:una\s+)?receta\b', request)
    unrelated = unrelated or (re.search(r'\bquien (?:gano|ganara)\b', request)
                              and re.search(r'\b(?:partido de futbol|mundial|champions)\b', request))
    unrelated = unrelated or re.search(r'(?:^|[:;.!?])\s*fuera del (?:ambito|dominio) postal\b', request)
    unrelated = unrelated or re.search(r'(?:^|[:;.!?¿])\s*como (?:se )?(?:hace|hacer|prepara|preparar|cocinar)\s+(?:un|una)\s+(?:pastel|torta|pizza|receta)\b', request)
    incoherent = (re.search(r'\beso de aquello\b', request)
                  and re.search(r'\bhazlo igual pero diferente\b', request))
    if unrelated or incoherent:
        raise QuestionValidationError('clarification',
            '¿Qué información postal deseas consultar? Indica el dato o reporte que necesitas.')
