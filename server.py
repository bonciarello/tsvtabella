"""
TSV → Markdown Converter — Server Flask
Converte file TSV in tabelle Markdown con anteprima renderizzata.
"""

import os
import csv
import io
import re
import html as html_mod
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_tsv(content: str) -> tuple[list[str], list[list[str]]]:
    """
    Analizza il contenuto TSV e restituisce (headers, rows).
    Solleva ValueError con messaggio in italiano in caso di errore.
    """
    if not content.strip():
        raise ValueError("Il file è vuoto. Carica un file TSV con almeno una riga di intestazione.")

    reader = csv.reader(io.StringIO(content), delimiter="\t")
    rows = list(reader)

    # Filtra righe completamente vuote (ultima riga con solo newline)
    rows = [r for r in rows if any(cell.strip() for cell in r)]

    if not rows:
        raise ValueError("Nessun dato trovato nel file. Il file potrebbe contenere solo righe vuote.")

    headers = rows[0]
    if not headers or not any(h.strip() for h in headers):
        raise ValueError("La riga di intestazione è vuota o contiene solo spazi. Aggiungi nomi alle colonne.")

    # Verifica nomi duplicati (warning-level, ma accettiamo)
    stripped_headers = [h.strip() for h in headers]
    if len(set(stripped_headers)) != len(stripped_headers):
        # Non blocchiamo, ma puliamo: aggiungiamo suffisso ai duplicati
        seen: dict[str, int] = {}
        unique_headers = []
        for h in stripped_headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        headers = unique_headers
    else:
        headers = stripped_headers

    data_rows = rows[1:]

    if not data_rows:
        raise ValueError(
            "Il file contiene solo la riga di intestazione, nessun dato. "
            "Aggiungi almeno una riga di dati dopo l'intestazione."
        )

    # Controllo consistenza colonne
    expected = len(headers)
    for i, row in enumerate(data_rows):
        if len(row) != expected:
            raise ValueError(
                f"Numero di colonne inconsistente alla riga {i + 2}: "
                f"attese {expected}, trovate {len(row)}. "
                f"Verifica che tutte le righe abbiano lo stesso numero di campi separati da tab."
            )

    return headers, data_rows


# ── Rilevamento allineamento ─────────────────────────────────────────────────

_NUMERIC_RE = re.compile(r"^[-+]?\s*[\d.,]+\s*%?$")


def _is_numeric(value: str) -> bool:
    """Determina se una stringa rappresenta un valore numerico."""
    v = value.strip()
    if not v:
        return False  # cella vuota non forza allineamento
    return bool(_NUMERIC_RE.match(v))


def detect_alignment(headers: list[str], rows: list[list[str]]) -> list[str]:
    """
    Per ogni colonna: se tutti i valori non vuoti sono numerici → right,
    altrimenti → left.
    """
    alignments = []
    for col_idx in range(len(headers)):
        col_values = [row[col_idx] for row in rows]
        non_empty = [v for v in col_values if v.strip()]
        if non_empty and all(_is_numeric(v) for v in non_empty):
            alignments.append("right")
        else:
            alignments.append("left")
    return alignments


# ── Generazione Markdown ─────────────────────────────────────────────────────

_ALIGN_MAP = {"left": ":----", "right": "----:", "center": ":---:"}


def generate_markdown(headers: list[str], rows: list[list[str]], alignments: list[str]) -> str:
    """Genera la tabella in formato Markdown (pipe table)."""
    lines: list[str] = []

    # Riga intestazione
    lines.append("| " + " | ".join(headers) + " |")

    # Riga allineamento
    align_cells = [_ALIGN_MAP.get(a, ":----") for a in alignments]
    lines.append("|" + "|".join(align_cells) + "|")

    # Righe dati
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(padded[:len(headers)]) + " |")

    return "\n".join(lines)


# ── Anteprima HTML ───────────────────────────────────────────────────────────

def render_table_html(headers: list[str], rows: list[list[str]], alignments: list[str]) -> str:
    """Genera HTML per l'anteprima renderizzata della tabella."""
    align_css = {"left": "left", "right": "right", "center": "center"}
    parts = ['<table class="preview-table">', "<thead>", "<tr>"]

    for h, a in zip(headers, alignments):
        parts.append(f'<th style="text-align:{align_css[a]}">{html_mod.escape(h)}</th>')

    parts.extend(["</tr>", "</thead>", "<tbody>"])

    for row in rows:
        parts.append("<tr>")
        for i, cell in enumerate(row):
            a = alignments[i] if i < len(alignments) else "left"
            parts.append(f'<td style="text-align:{align_css[a]}">{html_mod.escape(cell)}</td>')
        parts.append("</tr>")

    parts.extend(["</tbody>", "</table>"])
    return "\n".join(parts)


# ── Route ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/convert", methods=["POST"])
def convert():
    # Validazione presenza file
    if "file" not in request.files:
        return jsonify({"error": "Nessun file caricato. Seleziona un file TSV e riprova."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nessun file selezionato. Scegli un file .tsv dal tuo computer."}), 400

    if not file.filename.lower().endswith(".tsv"):
        return jsonify({
            "error": f"Il file «{file.filename}» non ha estensione .tsv. "
                     f"Questo strumento accetta solo file TSV (Tab-Separated Values)."
        }), 400

    # Decodifica: prova UTF-8, poi latin-1
    raw = file.read()
    content = None
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            content = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        return jsonify({
            "error": "Impossibile decodificare il file. Assicurati che sia in formato "
                     "UTF-8 o Latin-1 e che non contenga byte corrotti."
        }), 400

    # Parsing & generazione
    try:
        headers, rows = parse_tsv(content)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    alignments = detect_alignment(headers, rows)
    markdown = generate_markdown(headers, rows, alignments)
    table_html = render_table_html(headers, rows, alignments)

    return jsonify({
        "markdown": markdown,
        "table_html": table_html,
        "headers": headers,
        "row_count": len(rows),
        "col_count": len(headers),
        "alignments": alignments,
    })


# ── Avvio ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4600))
    app.run(host="0.0.0.0", port=port, debug=False)
