"""Downloads use saved evidence only; no SQL is rerun against the postal source."""
import csv
import io
import json
import re
import sqlite3
from contextlib import closing
from tempfile import TemporaryFile

from django.http import FileResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from . import jobs
from .data import DataError
from .labels import COLUMN_LABELS


def csv_value(value):
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def saved_rows(job, panel):
    path = jobs.spool_path(job.id)
    if not path.exists():
        raise DataError('expired', 'Los datos guardados ya no están disponibles. Repita la consulta.')
    table = 'rows' if panel == 0 else f'rows_{panel}'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        try:
            cursor = connection.execute(f'SELECT value FROM {table} ORDER BY position')
            for row in cursor:
                yield json.loads(row[0])
        except sqlite3.Error as exc:
            raise DataError('expired', 'Los datos guardados no están disponibles. Repita la consulta.') from exc


def export_file(job, panels, extension, filename):
    output = TemporaryFile(mode='w+b')
    try:
        if extension == 'csv':
            text = io.TextIOWrapper(output, encoding='utf-8-sig', newline='')
            try:
                writer = csv.writer(text)
                panel = panels[0]
                writer.writerow([csv_value(COLUMN_LABELS.get(column, column)) for column in panel['columns']])
                for row in saved_rows(job, panel['index']):
                    values = [row.get(column) for column in panel['columns']]
                    writer.writerow([csv_value(value) for value in values])
                text.flush()
            finally:
                text.detach()
            mime = 'text/csv; charset=utf-8'
        else:
            if any(panel['row_count'] > 1048575 or len(panel['columns']) > 16384 for panel in panels):
                raise DataError('export_too_large', 'El resultado supera el límite de Excel. Exporte cada panel como CSV.')
            workbook = Workbook(write_only=True)
            try:
                for panel in panels:
                    name = re.sub(r'[\\/*?:\[\]]', '-', panel['title'])[:26]
                    sheet = workbook.create_sheet(f"{panel['index'] + 1} {name}")
                    sheet.freeze_panes = 'A2'
                    headers = [WriteOnlyCell(sheet, value=COLUMN_LABELS.get(column, column)) for column in panel['columns']]
                    for cell in headers:
                        cell.font = Font(bold=True)
                        cell.data_type = 's'
                    sheet.append(headers)
                    for row in saved_rows(job, panel['index']):
                        cells = []
                        for column in panel['columns']:
                            value = row.get(column)
                            if isinstance(value, str) and (len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value)):
                                raise DataError('invalid_excel_value', 'Una celda no es compatible con Excel. Use CSV para conservar el contenido completo.')
                            cell = WriteOnlyCell(sheet, value=value)
                            if isinstance(value, str):
                                cell.data_type = 's'
                            cells.append(cell)
                        sheet.append(cells)
                workbook.save(output)
            finally:
                for sheet in workbook.worksheets:
                    if not sheet.closed:
                        sheet.close()
                workbook.close()
            mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        output.seek(0)
        response = FileResponse(output, as_attachment=True, filename=filename, content_type=mime)
        response['Cache-Control'] = 'private, no-store'
        return response
    except BaseException:
        output.close()
        raise
