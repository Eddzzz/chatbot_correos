"""Vector charts for the printed version of the chat's report cards."""
from bisect import bisect_right
from datetime import date
from math import ceil, isfinite
import re

from reportlab.graphics.charts.utils import find_good_grid
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String, Wedge
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase.pdfmetrics import stringWidth


# Light theme from app.css and addChart in app.js, for legible printed reports.
BLUE = HexColor('#20539a')
INK = HexColor('#1c3556')
MUTED = HexColor('#526984')
BORDER = HexColor('#dbe4ef')
PALETTE = [BLUE, *(HexColor(color) for color in ('#3577b8', '#5498be', '#83b1c8', '#a5c9d8', '#657e9b'))]
MONTH = re.compile(r'(\d{4})-(0[1-9]|1[0-2])-01(?:[T ]00:00:00(?:\.0+)?(?:Z|[+-]00:00)?)?')
MONTHS = 'ene feb mar abr may jun jul ago sept oct nov dic'.split()
DAY_COLUMNS = {'dia', 'día', 'fecha', 'day', 'date'}
DAY = re.compile(r'(\d{4}-\d{2}-\d{2})(?:[T ]00:00:00(?:\.0+)?(?:Z|[+-]00:00)?)?')


def report_day(value):
    match = DAY.fullmatch(str(value))
    if match:
        try:
            return date.fromisoformat(match[1])
        except ValueError:
            pass


def _number(value, decimals=2):
    if abs(value) >= 10**12 or 0 < abs(value) < 10 ** -decimals:
        return f'{value:.2g}'.replace('.', ',')
    return f'{value:,.{decimals}f}'.rstrip('0').rstrip('.').translate(str.maketrans(',.', '.,'))


def _text(drawing, x, y, text, font, size=9, color=MUTED, anchor='start', width=None):
    text = str(text).replace('\n', ' ').replace('\r', ' ')
    if width is not None and stringWidth(text, font, size) > width:
        fit = bisect_right(range(len(text)), width, key=lambda end: stringWidth(text[:end] + '…', font, size))
        text = text[:max(0, fit - 1)] + '…'
    drawing.add(String(x, y, text, fontName=font, fontSize=size, fillColor=color, textAnchor=anchor))


def _caption(drawing, total, share, count, metric, partial, font, bold, continued=False):
    main = _number(total) if share else str(count)
    detail = f'{metric.lower()} · {count} categorías' if share else 'categorías'
    if partial:
        detail += ' · página visible'
    if continued:
        detail += ' · continuación'
    y = drawing.height - 19
    _text(drawing, 0, y, main, bold, 16, INK)
    x = stringWidth(main, bold, 16) + 5
    _text(drawing, x, y, detail, font, width=drawing.width - x)


def _legend(drawing, x, top, labels, values, colors, total, font, bold):
    for index, (label, value, color) in enumerate(zip(labels, values, colors)):
        y = top - index * 16
        drawing.add(Rect(x, y, 7, 7, rx=1.5, ry=1.5, fillColor=color, strokeColor=None))
        _text(drawing, x + 15, y, label, font, color=INK, width=drawing.width - x - 122)
        _text(drawing, drawing.width - 46, y, _number(value), bold, color=INK, anchor='end')
        _text(drawing, drawing.width - 2, y, _number(value / total * 100, 1) + '%', font, anchor='end')


def _ring(drawing, labels, values, colors, total, pie, font, bold):
    radius = min(77, drawing.width * .19)
    x, y = drawing.width * .23, (drawing.height - 26) / 2
    angle = 90
    for value, color in zip(values, colors):
        sweep = value / total * 360
        if sweep >= 360:
            drawing.add(Circle(x, y, radius, fillColor=color, strokeColor=None))
        elif sweep > 0:
            drawing.add(Wedge(x, y, radius, angle - sweep, angle, fillColor=color,
                              strokeColor=white, strokeWidth=1.5, degreedelta=2))
        angle -= sweep
    if not pie:
        drawing.add(Circle(x, y, radius * .76, fillColor=white, strokeColor=None))
        _text(drawing, x, y, _number(total), bold, 21, INK, 'middle', radius * 1.36)
        _text(drawing, x, y - 15, 'Total', font, 9, MUTED, 'middle')
    legend_x = drawing.width * .47
    _legend(drawing, legend_x, y + (len(labels) - 1) * 8 - 3, labels, values, colors, total, font, bold)


def _plot(drawing, labels, values, limits, view, font):
    horizontal = view == 'horizontal'
    low, high = limits
    magnitude = max(abs(low), abs(high))
    if 1e-9 <= magnitude <= 1e12:
        low, high, tick_step = find_good_grid(low, high, n=(4, 5))
        ticks = [index * tick_step for index in range(round(low / tick_step), round(high / tick_step) + 1)]
    else:
        ticks = [low * (1 - index / 4) + high * (index / 4) for index in range(5)]
    span = high / magnitude - low / magnitude
    width, height = drawing.width, drawing.height
    if horizontal:
        left = min(width * .40, max(stringWidth(label, font, 9) for label in labels) + 10)
        right, bottom = width - 69, 24
    else:
        left, right, bottom = min(74, max(stringWidth(_number(v), font, 8) for v in limits) + 9), width - 16, 25
    top = height - 34

    def position(value, start, end):
        return start + (value / magnitude - low / magnitude) / span * (end - start)

    for value in ticks:
        if horizontal:
            x = position(value, left, right)
            drawing.add(Line(x, bottom, x, top, strokeColor=BORDER, strokeWidth=.6))
            _text(drawing, x, 9, _number(value), font, 8, anchor='middle')
        else:
            y = position(value, bottom, top)
            drawing.add(Line(left, y, right, y, strokeColor=BORDER, strokeWidth=.6))
            _text(drawing, left - 6, y - 3, _number(value), font, 8, anchor='end')

    if horizontal:
        step = (top - bottom) / len(values)
        zero = position(0, left, right)
        for index, (label, value) in enumerate(zip(labels, values)):
            y = top - (index + .5) * step
            x = position(value, left, right)
            # A separate label gutter keeps negative values clear of the category names.
            _text(drawing, left - 8, y - 3, label, font, anchor='end', width=left - 8)
            if value:
                drawing.add(Rect(min(zero, x), y - 5, abs(x - zero), 10, rx=2, ry=2,
                                 fillColor=BLUE, strokeColor=None))
            _text(drawing, right + 8, y - 3, _number(value), font, color=INK)
        return

    step = (right - left) / len(values)
    points = [(left + (index + .5) * step, position(value, bottom, top)) for index, value in enumerate(values)]
    zero = position(0, bottom, top)
    if view == 'line':
        if len(points) > 1:
            area = [(points[0][0], zero), *points, (points[-1][0], zero)]
            drawing.add(Polygon([coordinate for point in area for coordinate in point],
                                fillColor=BLUE.clone(alpha=.09), strokeColor=None))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            drawing.add(Line(x1, y1, x2, y2, strokeColor=BLUE, strokeWidth=1.5))
        for x, y in points:
            drawing.add(Circle(x, y, 2, fillColor=BLUE, strokeColor=None))
    else:
        bar_width = min(24, step * .65)
        for x, y in points:
            if y != zero:
                drawing.add(Rect(x - bar_width / 2, min(y, zero), bar_width, abs(y - zero),
                                 rx=2, ry=2, fillColor=BLUE, strokeColor=None))
    stride = max(1, ceil(58 / step))
    for index in range(0, len(labels), stride):
        _text(drawing, points[index][0], 9, labels[index], font, 8, anchor='middle',
              width=min(step * stride - 3, 2 * min(points[index][0], width - points[index][0])))


def chart_flowables(panel, width, font, bold, para, small):
    chart = panel.get('chart')
    if not chart:
        return []
    labels, values = chart.get('labels'), chart.get('values')
    if (not isinstance(labels, list) or not isinstance(values, list) or not values or len(labels) != len(values)
            or not all(type(value) in (int, float) and isfinite(value) for value in values)):
        return []
    labels = ['—' if label is None else str(label) for label in labels]
    line = chart.get('kind') == 'line'
    months = [MONTH.fullmatch(label) for label in labels]
    missing = [label.lower() in ('', '—', 'sin dato', 'sin fecha') for label in labels]
    temporal = line and any(months) and all(month or absent for month, absent in zip(months, missing))
    story = []
    if temporal:
        if any(missing):
            undated = sum(value for value, absent in zip(values, missing) if absent)
            story.append(para(f'Sin fecha: {_number(undated)} · incluido en el detalle.', small))
        labels = [f'{MONTHS[int(month[2]) - 1]} {month[1]}' for month in months if month]
        values = [value for value, absent in zip(values, missing) if not absent]
    elif line and DAY_COLUMNS.intersection(panel.get('columns', [])):
        dates = [report_day(label) for label in labels]
        if all(dates):
            labels = [f'{day.day} {MONTHS[day.month - 1]}' for day in dates]

    metric = chart.get('label') or 'Total'
    if len(values) == 1 and not temporal:
        drawing = Drawing(width, 49)
        value = _number(values[0])
        _text(drawing, 0, 33, labels[0], font, 10, width=width)
        _text(drawing, 0, 8, value, bold, 22, BLUE)
        x = stringWidth(value, bold, 22) + 9
        _text(drawing, x, 9, metric, font, 10, width=width - x)
        drawing.add(Line(0, 0, width, 0, strokeColor=BORDER, strokeWidth=.6))
        return [drawing]

    total = sum(values)
    share = min(values) >= 0 and 0 < total and isfinite(total)
    partial = panel.get('has_more') or (panel.get('page') or 1) > 1
    requested = chart.get('view')
    if line:
        view = 'line'
    elif requested == 'bar':
        view = 'bar'
    elif share and not partial and requested == 'pie':
        view = 'pie'
    elif share and not partial and len(values) <= 5 and requested in (None, '', 'doughnut'):
        view = 'doughnut'
    else:
        view = 'horizontal'

    if view in ('pie', 'doughnut'):
        colors = [MUTED if label.lower() == 'sin departamento' else PALETTE[index % len(PALETTE)]
                  for index, label in enumerate(labels)]
        drawing = Drawing(width, 220)
        _caption(drawing, total, share, len(values), metric, partial, font, bold)
        _ring(drawing, labels[:12], values, colors, total, view == 'pie', font, bold)
        story.append(drawing)
        for start in range(12, len(values), 24):
            end = start + 24
            drawing = Drawing(width, 42 + 16 * len(labels[start:end]))
            _caption(drawing, total, share, len(values), metric, partial, font, bold, continued=True)
            _legend(drawing, 0, drawing.height - 40, labels[start:end], values[start:end], colors[start:end],
                    total, font, bold)
            story.append(drawing)
    else:
        limits = (min(0, min(values)), max(0, max(values))) if any(values) else (0, 1)
        chunk = 18 if view == 'horizontal' else len(values)
        for start in range(0, len(values), chunk):
            end = start + chunk
            height = max(145, 62 + 19 * len(values[start:end])) if view == 'horizontal' else 205
            drawing = Drawing(width, height)
            _caption(drawing, total, share, len(values), metric, partial, font, bold, continued=start > 0)
            _plot(drawing, labels[start:end], values[start:end], limits, view, font)
            story.append(drawing)
    return story
