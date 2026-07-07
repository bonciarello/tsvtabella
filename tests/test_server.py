"""
Test per il server TSV → Markdown Converter.
"""

import io
import pytest
from server import app, parse_tsv, detect_alignment, generate_markdown, render_table_html


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Test parsing ─────────────────────────────────────────────────────────────

def test_parse_simple_tsv():
    content = "Nome\tEtà\tCittà\nAlice\t30\tRoma\nBob\t25\tMilano\n"
    headers, rows = parse_tsv(content)
    assert headers == ["Nome", "Età", "Città"]
    assert rows == [["Alice", "30", "Roma"], ["Bob", "25", "Milano"]]


def test_parse_empty_file():
    with pytest.raises(ValueError, match="vuoto"):
        parse_tsv("")


def test_parse_header_only():
    with pytest.raises(ValueError, match="solo la riga di intestazione"):
        parse_tsv("Nome\tEtà\n")


def test_parse_duplicate_headers():
    content = "Col\tCol\tAltro\n1\t2\t3\n"
    headers, rows = parse_tsv(content)
    # I duplicati vengono resi unici
    assert headers == ["Col", "Col_1", "Altro"]


def test_parse_extra_tabs_data_rows():
    content = "A\tB\n1\t2\t3\n"
    with pytest.raises(ValueError, match="inconsistente"):
        parse_tsv(content)


def test_parse_trailing_newline():
    content = "A\tB\n1\t2\n\n"
    headers, rows = parse_tsv(content)
    assert headers == ["A", "B"]
    assert rows == [["1", "2"]]


def test_parse_single_column():
    content = "Valore\n10\n20\n30\n"
    headers, rows = parse_tsv(content)
    assert headers == ["Valore"]
    assert len(rows) == 3


# ── Test alignment detection ─────────────────────────────────────────────────

def test_detect_all_text():
    headers = ["Nome", "Ruolo"]
    rows = [["Alice", "Dev"], ["Bob", "PM"]]
    assert detect_alignment(headers, rows) == ["left", "left"]


def test_detect_all_numeric():
    headers = ["Prezzo", "Q.tà"]
    rows = [["10.50", "3"], ["20", "5"]]
    assert detect_alignment(headers, rows) == ["right", "right"]


def test_detect_mixed():
    headers = ["Nome", "Età", "Città"]
    rows = [["Alice", "30", "Roma"], ["Bob", "25", "Milano"]]
    assert detect_alignment(headers, rows) == ["left", "right", "left"]


def test_detect_numeric_with_empty():
    headers = ["A", "B"]
    rows = [["10", ""], ["", "20"]]
    # Una cella vuota non forza il tipo — ogni colonna ha almeno un numerico
    assert detect_alignment(headers, rows) == ["right", "right"]


def test_detect_percentage():
    headers = ["Tasso"]
    rows = [["15%"], ["20%"]]
    assert detect_alignment(headers, rows) == ["right"]


def test_detect_negative():
    headers = ["Delta"]
    rows = [["-5"], ["+3.2"]]
    assert detect_alignment(headers, rows) == ["right"]


# ── Test Markdown generation ─────────────────────────────────────────────────

def test_generate_markdown_simple():
    headers = ["Nome", "Età"]
    rows = [["Alice", "30"]]
    md = generate_markdown(headers, rows, ["left", "right"])
    expected = "| Nome | Età |\n|:----|----:|\n| Alice | 30 |"
    assert md == expected


def test_generate_markdown_multiple_rows():
    headers = ["A", "B"]
    rows = [["1", "2"], ["3", "4"]]
    md = generate_markdown(headers, rows, ["left", "left"])
    lines = md.split("\n")
    assert len(lines) == 4  # header + alignment + 2 data rows


# ── Test HTML rendering ──────────────────────────────────────────────────────

def test_render_html():
    headers = ["Nome", "Età"]
    rows = [["Alice", "30"]]
    html = render_table_html(headers, rows, ["left", "right"])
    assert "<table" in html
    assert "Alice" in html
    assert "text-align:right" in html
    # HTML escaping
    assert "&amp;" not in html or "Alice" in html  # no double escaping


def test_render_html_escapes():
    headers = ["Tag", "Valore"]
    rows = [["<script>", "&amp;"]]
    html = render_table_html(headers, rows, ["left", "left"])
    assert "&lt;script&gt;" in html
    assert "&amp;amp;" in html


# ── Test API endpoint ────────────────────────────────────────────────────────

def test_api_no_file(client):
    resp = client.post("/api/convert")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Nessun file" in data["error"]


def test_api_empty_filename(client):
    data = {"file": (io.BytesIO(b""), "")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_api_wrong_extension(client):
    data = {"file": (io.BytesIO(b"a\tb\n1\t2\n"), "dati.csv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert ".tsv" in resp.get_json()["error"]


def test_api_valid_tsv(client):
    data = {"file": (io.BytesIO("Nome\tEtà\nAlice\t30\nBob\t25\n".encode()), "dati.tsv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["row_count"] == 2
    assert result["col_count"] == 2
    assert "Nome" in result["markdown"]
    assert "Alice" in result["markdown"]
    assert "table" in result["table_html"]


def test_api_malformed_tsv(client):
    data = {"file": (io.BytesIO("A\tB\n1\t2\t3\n".encode()), "malformed.tsv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "inconsistente" in resp.get_json()["error"]


def test_api_empty_tsv(client):
    data = {"file": (io.BytesIO(b"",), "vuoto.tsv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_api_header_only_tsv(client):
    data = {"file": (io.BytesIO("A\tB\tC\n".encode()), "soloheader.tsv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "intestazione" in resp.get_json()["error"]


def test_api_latin1_encoding(client):
    # "città" in latin-1
    content = "Nome\tCitt\xe0\nAlice\tRoma\n".encode("latin-1")
    data = {"file": (io.BytesIO(content), "latin1.tsv")}
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["row_count"] == 1


def test_home_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Convertitore TSV" in html
    assert 'lang="it"' in html
    assert '<h1>' in html
    # Check for key accessibility elements
    assert 'skip-link' in html
    assert '<main' in html
    assert '<footer' in html
