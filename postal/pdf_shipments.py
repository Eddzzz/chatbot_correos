"""Print equivalents of the chat's calendar and shipment detail."""
from calendar import Calendar, monthrange
from decimal import Decimal
import re

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib.colors import HexColor
from reportlab.platypus import KeepTogether, Table, TableStyle

from .labels import column_label
from .pdf_charts import BLUE, BORDER, DAY_COLUMNS, INK, MONTHS, report_day


COUNT_COLUMNS = {'total_envios', 'total_paquetes', 'cantidad', 'total'}
CITY_COLUMNS = {'ciudad', 'ciudad_destino', 'city'}
WEIGHT_COLUMNS = {'peso_total', 'total_peso'}
MONTH_NAMES = 'enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'.split()
WEEKDAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
NUMBER = re.compile(r'-?[0-9]+(?:\.[0-9]+)?')


def metric_number(value):
    text = str(value)
    return Decimal(text) if NUMBER.fullmatch(text) else None


def localized(number, digits=0):
    return f'{number:,.{digits}f}'.translate(str.maketrans(',.', '.,'))


def count_number(value):
    number = metric_number(value)
    if number is not None and abs(number) <= 2**53 - 1 and number == number.to_integral_value():
        return int(number)


def detail_columns(panel):
    kind = (panel.get('chart') or {}).get('kind')
    columns = panel.get('columns', [])
    dimensions = DAY_COLUMNS if kind == 'line' else CITY_COLUMNS if kind == 'bar' else set()
    dimension = next((column for column in columns if column in dimensions), None)
    count = next((column for column in columns if column in COUNT_COLUMNS), None)
    return (dimension, count) if dimension and count else (None, None)


def calendar_flowable(panel, day, count, width, para, small, section, number_style):
    rows = panel['rows']
    if (len(panel['columns']) != 2 or len(rows) < 2 or panel.get('row_count') != len(rows)
            or panel.get('has_more') or (panel.get('page') or 1) != 1):
        return None
    first = report_day(rows[0].get(day))
    if first is None:
        return None
    counts = {}
    for row in rows:
        date = report_day(row.get(day))
        value = count_number(row.get(count))
        if (date is None or date.year != first.year or date.month != first.month
                or date.day in counts or value is None or value < 0):
            return None
        counts[date.day] = value
    cells = [[para(label, small) for label in WEEKDAYS]]
    for week in Calendar().monthdayscalendar(first.year, first.month):
        cells.append([
            [para(number, small), para(localized(counts[number]), number_style) if number in counts else para('—', small)]
            if number else '' for number in week
        ])
    calendar = Table(cells, colWidths=[width / 7] * 7, rowHeights=[18] + [27] * (len(cells) - 1), hAlign='LEFT')
    calendar.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), HexColor('#f0f5fc')),
                                  ('INNERGRID', (0, 0), (-1, -1), .45, BORDER),
                                  ('BOX', (0, 0), (-1, -1), .45, BORDER),
                                  ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('TOPPADDING', (0, 0), (-1, -1), 2),
                                  ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    title = f'{MONTH_NAMES[first.month - 1].capitalize()} de {first.year} · {column_label(count).lower()}'
    flowables = [para(title, section), calendar]
    if len(counts) < monthrange(first.year, first.month)[1]:
        flowables.append(para('— Sin dato en el reporte', small))
    return KeepTogether(flowables)


def detail_value(value, column, dimension, count, maximum, width, font, para, style):
    if column == dimension and dimension in DAY_COLUMNS:
        date = report_day(value)
        if date:
            return para(f'{WEEKDAYS[date.weekday()].lower()} {date.day} {MONTHS[date.month - 1]} {date.year}', style)
    if column == count:
        number = count_number(value)
        if number is not None:
            drawing = Drawing(width, 11)
            track = width - 48
            if maximum > 0 and number >= 0 and track > 0:
                drawing.add(Rect(0, 4, track, 3, rx=1, ry=1, fillColor=BORDER, strokeColor=None))
                if number:
                    drawing.add(Rect(0, 4, track * number / maximum, 3, rx=1, ry=1, fillColor=BLUE, strokeColor=None))
            drawing.add(String(width, 2, localized(number), fontName=font, fontSize=8, fillColor=INK, textAnchor='end'))
            return drawing
    if column in WEIGHT_COLUMNS:
        number = metric_number(value)
        if number is not None:
            digits = max(3, -number.as_tuple().exponent)
            if digits <= 20:
                return para(localized(number, digits), style)
    return para('—' if value is None else value, style)
