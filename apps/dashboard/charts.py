"""Chart geometry for server-drawn charts (no JS). The plot is an SVG stretched to its box
(viewBox 0 0 1000 100, preserveAspectRatio="none", strokes with vector-effect: non-scaling-stroke);
the axis labels and data dots are HTML placed by percentage, so text and circles stay sharp at any
width. Hover tooltips are SVG <title>s on one transparent column per data point."""
import math

W = 1000  # viewBox width; height is 100 so y values are percentages


def nice_scale(peak, ticks=4):
    """(top, [tick values]) with round steps (1, 2, 5 × 10ⁿ) covering 0..peak."""
    peak = max(peak, 1)
    raw = peak / ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    step = max(1, round(step))
    top = step * math.ceil(peak / step)
    return top, list(range(0, top + 1, step))


def _thin(n, most=8):
    step = max(1, math.ceil(n / most))
    return [i for i in range(n) if i % step == 0]


def _y(v, top):
    return round(100 - 100 * v / top, 2)


def line_chart(cur, prev=None, label=str, short_label=None):
    """cur/prev: [(bucket, count)]; the compare series is lined up by position (1st with 1st).
    label(bucket) is the tooltip text; short_label(bucket) the axis text."""
    short_label = short_label or label
    prev = prev or []
    n = max(len(cur), len(prev), 1)
    top, ticks = nice_scale(max([v for _, v in cur] + [v for _, v in prev] + [0]))

    def x(i):
        return round(W * i / (n - 1), 2) if n > 1 else W / 2

    def pts(series):
        return " ".join(f"{x(i)},{_y(v, top)}" for i, (_, v) in enumerate(series))

    slot = W / (n - 1) if n > 1 else W
    columns = []
    for i in range(n):
        parts = []
        if i < len(cur):
            parts.append(f"{label(cur[i][0])}: {cur[i][1]:,}")
        if i < len(prev):
            parts.append(f"{label(prev[i][0])}: {prev[i][1]:,} (compare)")
        left = max(0, x(i) - slot / 2)
        columns.append({"x": round(left, 2), "w": round(min(W, x(i) + slot / 2) - left, 2), "title": " · ".join(parts)})

    def dots(series):
        return [{"left": round(100 * x(i) / W, 2), "bottom": round(100 * v / top, 2)}
                for i, (_, v) in enumerate(series)] if n <= 45 else []

    area = f"{x(0)},100 {pts(cur)} {x(len(cur) - 1)},100" if cur else ""
    return {
        "cur": pts(cur), "prev": pts(prev), "area": area, "columns": columns,
        "dots": dots(cur), "prev_dots": dots(prev),
        "yticks": [{"bottom": round(100 * t / top, 2), "y": _y(t, top), "text": f"{t:,}"} for t in ticks],
        "xlabels": [{"left": round(100 * x(i) / W, 2), "text": short_label(cur[i][0] if i < len(cur) else prev[i][0]),
                     "edge": "start" if i == 0 and n > 1 else "", "alt": j % 2 == 1}
                    for j, i in enumerate(_thin(n))],
    }


def column_chart(rows, xlabel_every=1):
    """rows: breakdown rows (see stats.rows) in display order, drawn as columns; with a compare period
    each slot holds the current column and a lighter compare column side by side."""
    n = max(len(rows), 1)
    comparing = any(r["prev"] is not None for r in rows)
    top, ticks = nice_scale(max([r["n"] for r in rows] + [r["prev"] or 0 for r in rows] + [0]))
    slot = W / n
    gap = slot * 0.18
    width = (slot - gap) / (2 if comparing else 1)
    bars, prev_bars, columns = [], [], []
    for i, r in enumerate(rows):
        x0 = i * slot + gap / 2
        bars.append({"x": round(x0, 2), "y": _y(r["n"], top), "w": round(width, 2), "h": round(100 * r["n"] / top, 2)})
        if comparing:
            v = r["prev"] or 0
            prev_bars.append({"x": round(x0 + width, 2), "y": _y(v, top), "w": round(width, 2), "h": round(100 * v / top, 2)})
        title = f"{r['label']}: {r['n']:,}" + (f" · compare: {r['prev']:,}" if comparing else "")
        columns.append({"x": round(i * slot, 2), "w": round(slot, 2), "title": title})
    return {
        "bars": bars, "prev_bars": prev_bars, "columns": columns,
        "yticks": [{"bottom": round(100 * t / top, 2), "y": _y(t, top), "text": f"{t:,}"} for t in ticks],
        "xlabels": [{"left": round(100 * (i + 0.5) / n, 2), "text": r["label"]}
                    for i, r in enumerate(rows) if i % xlabel_every == 0],
    }
