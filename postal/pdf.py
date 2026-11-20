"""Exporta la evidencia visible de un informe sin interpretar HTML del usuario."""
from html import escape
from io import BytesIO
from math import isfinite
from pathlib import Path
import re
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, Table, TableStyle, CondPageBreak
from .labels import column_label
from .pdf_charts import BLUE, DAY_COLUMNS, chart_flowables
from .pdf_shipments import WEIGHT_COLUMNS, calendar_flowable, count_number, detail_columns, detail_value


METRIC_COLUMNS = {'total_envios', 'total_paquetes', 'cantidad', 'total', 'peso_total', 'total_peso', 'peso_promedio'}


def _is_record(panel):
    return not panel.get('chart') and len(panel.get('rows', [])) == 1 and len(panel.get('columns', [])) >= 3


def render_pdf(result):
    font = 'Helvetica'
    font_path = Path(__file__).resolve().parent.parent / 'static' / 'fonts' / 'geist-regular.ttf'
    if not font_path.exists():
        font_path = Path('C:/Windows/Fonts/arial.ttf')
    if font_path.exists():
        if 'PostalUnicode' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('PostalUnicode', str(font_path)))
        font = 'PostalUnicode'
    bold = 'Helvetica-Bold'
    bold_path = font_path.with_name('geist-bold.ttf')
    if bold_path.exists():
        if 'PostalUnicodeBold' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('PostalUnicodeBold', str(bold_path)))
        bold = 'PostalUnicodeBold'
    output = BytesIO()
    analysis = result.get('analysis') or {}
    explanation = result.get('is_explanation', analysis.get('presentation') == 'explanation' or (
        re.match(r'^explicaci[oó]n\b', result['title'], re.I) and (analysis.get('generated') or analysis.get('citations'))))
    panels = [] if explanation else result.get('panels') or [result]
    size = landscape(A4) if any(not _is_record(panel) and len(panel.get('columns', [])) > 5 for panel in panels) else A4
    doc = SimpleDocTemplate(output, pagesize=size, rightMargin=40, leftMargin=40, topMargin=78, bottomMargin=48,
                            title='Bolipost - ' + result['title'], author='Asistente Bolipost')
    normal = ParagraphStyle('postal', fontName=font, fontSize=9, leading=13, alignment=TA_LEFT, spaceAfter=7,
                            wordWrap='LTR', textColor=colors.HexColor('#1c3556'))
    heading = ParagraphStyle('heading', parent=normal, fontName=bold, fontSize=17, leading=23, spaceAfter=6, keepWithNext=True)
    section = ParagraphStyle('section', parent=normal, fontName=bold, fontSize=12, leading=16, spaceBefore=12, spaceAfter=8, keepWithNext=True)
    narrative = ParagraphStyle('narrative', parent=normal, fontSize=10.5, leading=17, spaceAfter=8)
    small = ParagraphStyle('small', parent=normal, fontSize=8, leading=12, textColor=colors.HexColor('#526984'))
    table_head = ParagraphStyle('table-head', parent=small, fontName=bold, fontSize=7, leading=10, textColor=colors.HexColor('#182a42'), spaceAfter=0)
    cell = ParagraphStyle('cell', parent=normal, fontSize=8, leading=11, spaceAfter=0)
    number_cell = ParagraphStyle('number-cell', parent=cell, alignment=TA_RIGHT)
    compact = ParagraphStyle('compact', parent=cell, fontSize=7.5, leading=10)
    calendar_label = ParagraphStyle('calendar-label', parent=small, alignment=TA_CENTER, leading=10, spaceAfter=0)
    calendar_count = ParagraphStyle('calendar-count', parent=calendar_label, fontName=bold, textColor=BLUE)
    field_label = ParagraphStyle('field-label', parent=small, spaceAfter=3)
    field_value = ParagraphStyle('field-value', parent=cell, fontName=bold, fontSize=9.5, leading=13)
    compact_field_value = ParagraphStyle('compact-field-value', parent=field_value, fontSize=7, leading=10)
    metric_value = ParagraphStyle('metric', parent=heading, fontSize=22, leading=28, keepWithNext=False,
                                  textColor=colors.HexColor('#20539a'))
    para = lambda text, style=normal: Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    story = [para(result['title'], heading)]
    exported = timezone.localtime().strftime('%d/%m/%Y %H:%M %Z')
    story.append(para(f'Exportado el {exported}', small))
    answer = '\n'.join(line for line in (result.get('answer') or '').splitlines()
                       if not re.match(r'^\s*fuentes?\s*:', line, re.I)).strip()
    error = (result.get('error') or {}).get('message')
    tracking_without_match = (result.get('filters') or {}).get('codigo') and result.get('status') not in (None, 'ok')
    if answer and not (tracking_without_match and not explanation) and not (result.get('status') == 'error' and answer == error):
        story.extend(para(paragraph, narrative) for paragraph in re.split(r'\n\s*\n', answer) if paragraph.strip())
    for key in ('note', 'warning'):
        note = result.get(key, analysis.get(key))
        if note:
            story.append(para(note, small))
    filters = result.get('filters') or {}
    if filters.get('choose_service') and len(panels) > 1:
        story.append(para(f"El código {filters.get('codigo', '')} tiene varios registros. "
                          "Elige un servicio para precisar su rastreo.", small))
    if result.get('demo'):
        story.append(para('DEMOSTRACIÓN: DATOS FICTICIOS. Este documento no acredita un envío real.', small))
    states = {'no_matches': 'No se encontraron coincidencias para estos filtros.',
              'empty_table': 'La tabla de origen está vacía.', 'cancelled': 'La consulta fue cancelada.',
              'error': error or 'No se pudo ejecutar la consulta.'}
    if result.get('status') in states:
        story.append(para(states[result['status']]))
    story.append(Spacer(1, 8))
    for panel in panels:
        columns = panel.get('columns', [])
        rows = panel.get('rows', [])
        if result.get('panels') and (len(panels) > 1 or panel.get('title') != result['title']):
            story.append(CondPageBreak(65 if rows else 40))
            story.append(para(panel.get('title', 'Resultado de la consulta'), section))
        if panel is not result:
            panel_error = (panel.get('error') or {}).get('message')
            if panel_error or panel.get('status') in states:
                story.append(para(panel_error or states[panel['status']]))
        chart = chart_flowables(panel, doc.width - 12, font, bold, para, small)
        if chart:
            story += [*chart, Spacer(1, 9)]
        if not rows or not columns:
            continue
        dimension, count_column = detail_columns(panel)
        daily = dimension in DAY_COLUMNS
        if daily:
            calendar = calendar_flowable(panel, dimension, count_column, doc.width, para, calendar_label,
                                         section, calendar_count)
            if calendar:
                story += [calendar, Spacer(1, 8)]
                continue
        if dimension:
            story.append(para('Detalle diario' if daily else 'Detalle por ciudad', section))
        maximum = max((count_number(row.get(count_column)) or 0 for row in rows), default=0) if count_column else 0
        if (not panel.get('chart') and panel.get('status') == 'ok' and not panel.get('has_more')
                and (panel.get('page') or 1) == 1 and panel.get('row_count') == len(rows) == 1
                and len(columns) == 1 and columns[0] in METRIC_COLUMNS):
            value = str(rows[0].get(columns[0]))
            if re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
                number = float(value)
                if isfinite(number) and abs(number) <= 2**53 - 1:
                    display = f'{int(number):,}'.replace(',', '.') if number.is_integer() else value
                    story += [para(column_label(columns[0]), small), para(display, metric_value)]
                    continue
        if _is_record(panel):
            value_style = compact_field_value if len(columns) >= 5 else field_value
            fields = [[para(column_label(column), field_label),
                       para('—' if rows[0].get(column) is None else rows[0][column], value_style)]
                      for column in columns]
            count = min(5, len(columns))
            grid = [fields[index:index + count] + [''] * (count - len(fields[index:index + count]))
                    for index in range(0, len(fields), count)]
            record = Table(grid, colWidths=[doc.width / count] * count, hAlign='LEFT', splitInRow=1)
            record.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                       ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                                       ('TOPPADDING', (0, 0), (-1, -1), 0),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
            story.append(record)
            continue
        # Repeat record keys so fields remain attributable across column groups.
        keys = [key for key in ('id', 'codigo') if key in columns] if len(columns) > 7 else []
        if len(columns) <= 7:
            groups = [columns] if columns else []
        elif keys:
            remaining = [column for column in columns if column not in keys]
            step = 7 - len(keys)
            groups = [keys + remaining[i:i + step] for i in range(0, len(remaining), step)]
        else:
            groups = [columns[i:i + 5] for i in range(0, len(columns), 5)]
        for group_index, group in enumerate(groups):
            if len(groups) > 1:
                story.append(CondPageBreak(75))
                story.append(para(f'Grupo de columnas {group_index + 1} de {len(groups)}', small))
            weights = [2 if dimension and c in (dimension, count_column) else
                       2.5 if c in ('nombre', 'nombre_completo', 'name') else
                       1.6 if c in ('codigo', 'created_at', 'updated_at', 'fecha_recojo') else
                       1.1 if c == 'id' or c.endswith('_id') or c.startswith('fk_') else
                       .7 if c in ('cantidad', 'peso', 'precio') else 1.2 for c in group]
            widths = [doc.width * weight / sum(weights) for weight in weights]
            content = [[para('Fecha' if daily and c == dimension else column_label(c), table_head) for c in group]]
            for row in rows:
                if dimension:
                    content.append([detail_value(row.get(c), c, dimension, count_column, maximum, width - 20,
                                                 font, para, number_cell if c == count_column or c in WEIGHT_COLUMNS else cell)
                                    for c, width in zip(group, widths)])
                else:
                    content.append([para('—' if row.get(c) is None else row[c], compact if len(rows) > 15 else cell)
                                    for c in group])
            table = LongTable(content, colWidths=widths, repeatRows=1, hAlign='LEFT', splitInRow=1, spaceAfter=12)
            padding = 4
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f5fc')),
                                      ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                      ('TOPPADDING', (0, 0), (-1, -1), padding), ('BOTTOMPADDING', (0, 0), (-1, -1), padding),
                                      ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                                      ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#dce3eb'))]))
            story.append(table)
    def footer(canvas, _doc):
        canvas.saveState()
        width, height = size
        canvas.setFillColor(colors.HexColor('#20539a'))
        canvas.rect(0, height - 8, width, 8, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#fecc36'))
        canvas.rect(40, height - 8, 68, 8, fill=1, stroke=0)
        canvas.setFont(bold, 11)
        canvas.setFillColor(colors.HexColor('#20539a'))
        canvas.drawString(40, height - 37, 'CORREOS DE BOLIVIA')
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#56667b'))
        canvas.drawString(40, height - 52, 'BOLIPOST · Informe de consulta')
        canvas.drawRightString(width - 40, height - 37, 'DEMOSTRACIÓN' if result.get('demo') else 'REPORTE POSTAL')
        canvas.setStrokeColor(colors.HexColor('#dce3eb'))
        canvas.line(40, height - 66, width - 40, height - 66)
        canvas.line(40, 36, width - 40, 36)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#667589'))
        canvas.drawString(40, 22, 'Respaldo histórico · Acceso de solo lectura')
        canvas.drawRightString(size[0] - 40, 22, f'Hoja {canvas.getPageNumber()}')
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
