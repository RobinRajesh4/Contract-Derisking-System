from conftest import fixture_text

from app.parser import (
    coverage_report,
    extract_labeled_facts,
    find_money_amounts,
    split_document,
)


def test_header_is_separated_from_clauses():
    header, clauses = split_document(fixture_text("julia_miller.txt"))
    assert header.startswith("HEALTH FINANCING AGREEMENT BORROWER: Julia Miller")
    assert header.endswith("FINANCED AMOUNT: $45,892.00.")
    assert len(clauses) == 8
    assert clauses[0].startswith("CLAUSE ONE")
    assert clauses[-1].startswith("CLAUSE EIGHT")
    assert all("FINANCED AMOUNT" not in c for c in clauses)


def test_single_line_pdf_text_is_split(  # Contract_1 was once stored as one giant clause
):
    header, clauses = split_document(fixture_text("contract_1.txt"))
    assert "FINANCED AMOUNT: $82,437.00." in header
    assert len(clauses) == 8
    assert all(len(c) < 300 for c in clauses)


def test_cents_are_not_cut_off_before_a_heading():
    header, _ = split_document("FINANCED AMOUNT: $45,892.00.\nCLAUSE ONE – PURPOSE: Financing for the asset described.")
    assert header == "FINANCED AMOUNT: $45,892.00."


def test_document_without_preamble_has_no_header():
    header, clauses = split_document(fixture_text("no_preamble.txt"))
    assert header is None
    assert len(clauses) == 8


def test_title_only_preamble_is_not_a_header():
    header, clauses = split_document(
        "AGREEMENT\nCLAUSE ONE – PURPOSE: This agreement aims to grant financing to the BORROWER.\n"
        "CLAUSE TWO – TERM: The financing period shall be up to 60 months."
    )
    assert header is None
    assert len(clauses) == 2


def test_coverage_is_complete_for_real_template():
    text = fixture_text("julia_miller.txt")
    header, clauses = split_document(text)
    assert coverage_report(text, header, clauses)["ok"]


def test_coverage_flags_dropped_content():
    text = fixture_text("julia_miller.txt")
    header, clauses = split_document(text)
    report = coverage_report(text, header, clauses[:3])
    assert not report["ok"]
    assert "jurisdiction" in report["missing_sample"] or report["ratio"] < 0.95


def test_labeled_facts_from_template():
    facts = extract_labeled_facts(fixture_text("julia_miller.txt"))
    assert facts["contract_value"] == 45892.0
    assert facts["currency"] == "USD"
    assert facts["contract_value_text"] == "$45,892.00"
    assert facts["lender_name"] == "FINANCIAL BANK OF AMERICA Inc"
    assert facts["customer_name"] == "Julia Miller"


def test_labeled_amount_without_cents():
    facts = extract_labeled_facts(fixture_text("carlos_brown_real_estate.txt"))
    assert facts["contract_value"] == 1203432.0
    assert facts["customer_name"] == "Carlos Brown"


def test_generic_party_labels_are_not_names():
    facts = extract_labeled_facts("Agreement between the BANK and the BORROWER. LENDER: the Bank, as defined.")
    assert "lender_name" not in facts


def test_money_amounts_in_several_formats():
    found = {(a["value"], a["currency"]) for a in find_money_amounts("INR 5,00,000 and 1200 USD and ₹1,20,000.50 and $9.99")}
    assert found == {(500000.0, "INR"), (1200.0, "USD"), (120000.5, "INR"), (9.99, "USD")}


# ---------------------------------------------------------- page furniture
from app.parser import strip_page_furniture  # noqa: E402


def test_page_numbers_and_running_header_are_removed():
    pages = [
        "Page 1\nCONFIDENTIAL - FINANCIAL BANK OF AMERICA Inc\nASSET FINANCING AGREEMENT\nCLAUSE ONE – PURPOSE: text\nmore text that ends here.",
        "Page 2\nCONFIDENTIAL - FINANCIAL BANK OF AMERICA Inc\nCLAUSE TWO – TERM: text\nmore text.",
        "Page 3\nCONFIDENTIAL - FINANCIAL BANK OF AMERICA Inc\nCLAUSE THREE – DEFAULT: text\nlast words.",
    ]
    cleaned = strip_page_furniture(pages)
    joined = "\n".join(cleaned)
    assert "Page 2" not in joined and "Page 3" not in joined
    # The running header survives once (first page), never mid-document.
    assert joined.count("CONFIDENTIAL") == 1 and "CONFIDENTIAL" in cleaned[0]
    assert "ASSET FINANCING AGREEMENT" in cleaned[0]
    assert cleaned[1].startswith("CLAUSE TWO") and cleaned[2].startswith("CLAUSE THREE")


def test_page_x_of_y_footers_are_removed():
    pages = [f"Body text of page {n} goes on.\nPage {n} of 3" for n in (1, 2, 3)]
    assert all("of 3" not in p for p in strip_page_furniture(pages))


def test_numbers_inside_the_body_are_kept():
    pages = ["LENDER: X\nSSN nº\n913053758\nmore\nbody\ntext\nhere\n2"]
    cleaned = strip_page_furniture(pages)[0]
    assert "913053758" in cleaned        # not at the page edge
    assert not cleaned.endswith("\n2")   # bare page number at the bottom


def test_reprinted_clauses_are_not_stripped():
    # Some generators reprint the whole clause list on every page; those
    # repeated lines are content, not furniture.
    page = "AGREEMENT\nCLAUSE ONE – PURPOSE: financing.\nCLAUSE TWO – TERM: 60 months.\nCLAUSE THREE – LAW: courts of New York."
    cleaned = strip_page_furniture([page, page, page])
    assert all("CLAUSE THREE – LAW: courts of New York." in p for p in cleaned)
    assert all("CLAUSE ONE" in p for p in cleaned)


def test_single_page_keeps_everything_but_page_number():
    cleaned = strip_page_furniture(["Page 1\nCONFIDENTIAL\nHEALTH FINANCING AGREEMENT\nBORROWER: Julia"])[0]
    assert cleaned == "CONFIDENTIAL\nHEALTH FINANCING AGREEMENT\nBORROWER: Julia"


def test_repeated_body_lines_in_different_positions_are_kept():
    # Identical boilerplate sentences that happen to fall near page edges
    # at different positions are body text, not a running header.
    body = "obligations set out herein and the BANK may, at its sole discretion, require additional"
    filler = [f"body line {n} of the page continues" for n in range(12)]

    def page(at):
        lines = list(filler)
        lines.insert(at, body)
        return "\n".join(lines)

    cleaned = strip_page_furniture([page(1), page(2), page(len(filler) - 1)])
    assert sum(body in p for p in cleaned) == 3


# ------------------------------------------------ labels with hard cases
import pytest  # noqa: E402


@pytest.mark.parametrize("text, key, expected", [
    ("BORROWER: Mr. John Smith, residing at 1 Road.", "customer_name", "Mr. John Smith"),
    ("LENDER: J.P. Morgan Chase Bank, registered in NY.", "lender_name", "J.P. Morgan Chase Bank"),
    ("LENDER: St. George Bank Ltd. CLAUSE ONE – PURPOSE: x", "lender_name", "St. George Bank Ltd"),
    ("BORROWER: Dr. Anna K. Silva (the Borrower) agrees", "customer_name", "Dr. Anna K. Silva"),
    ("BORROWER: Carlos Brown. LENDER: Bank X.", "customer_name", "Carlos Brown"),
    ("LENDER: FINANCIAL BANK OF AMERICA Inc., registered", "lender_name", "FINANCIAL BANK OF AMERICA Inc"),
])
def test_names_with_abbreviations_and_initials(text, key, expected):
    assert extract_labeled_facts(text)[key] == expected


@pytest.mark.parametrize("text, value, currency", [
    ("FINANCED AMOUNT: Forty-five thousand eight hundred ninety-two dollars ($45,892.00).", 45892, "USD"),
    ("FINANCED AMOUNT: EUR 45.892,00.", 45892, "EUR"),
    ("FINANCED AMOUNT: R$ 45.892,00.", 45892, "BRL"),
    ("FINANCED AMOUNT: 45 892,00 €.", 45892, "EUR"),
    ("FINANCED AMOUNT: CAD 50,000.", 50000, "CAD"),
    ("FINANCED AMOUNT: ₹4,58,920.00.", 458920, "INR"),
    ("FINANCED AMOUNT: $1,203,432. CLAUSE ONE", 1203432, "USD"),
])
def test_amounts_in_words_and_local_formats(text, value, currency):
    facts = extract_labeled_facts(text)
    assert (facts["contract_value"], facts["currency"]) == (value, currency)


# ------------------------------------------------------------------ OCR
import shutil  # noqa: E402

import app.parser as parser_module  # noqa: E402


def _scanned_pdf(pages_text, footer="Scanned with CamScanner", typed_cover=None):
    """A PDF whose pages are images of text (like a scan) with a small
    real-text footer, optionally preceded by a typed cover page."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    if typed_cover:
        c.setFont("Helvetica", 12)
        for i, line in enumerate(typed_cover):
            c.drawString(60, 780 - 18 * i, line)
        c.showPage()
    for text in pages_text:
        img = Image.new("RGB", (1654, 2339), "white")
        draw = ImageDraw.Draw(img)
        y = 120
        for line in text:
            draw.text((110, y), line, fill="black", font=font)
            y += 60
        c.drawImage(ImageReader(img), 0, 0, width=A4[0], height=A4[1])
        c.setFont("Helvetica", 7)
        c.drawString(40, 15, footer)
        c.showPage()
    c.save()
    return buf.getvalue()


SCANNED_PAGES = [
    ["HEALTH FINANCING AGREEMENT", "BORROWER: Julia Miller, residing in Chicago.",
     "FINANCED AMOUNT: $45,892.00.", "CLAUSE ONE - PURPOSE: Financing of the asset."],
    ["CLAUSE TWO - TERM: The financing period is 60 months.",
     "CLAUSE THREE - PAYMENT: Interest of 1.2% per month."],
]


def test_scanned_pages_with_a_text_footer_are_ocrd(monkeypatch):
    done = []
    monkeypatch.setattr(parser_module, "_ocr_pdf_pages",
                        lambda content, pages: done.extend(pages) or {n: f"OCR TEXT OF PAGE {n} " * 10 for n in pages})
    pytest.importorskip("reportlab")
    text, info, pages = parser_module.extract_text_from_file("scan.pdf", _scanned_pdf(SCANNED_PAGES))
    assert done == [1, 2]
    assert info["used"] and info["pages"] == 2
    assert "OCR TEXT OF PAGE 2" in pages[1]


def test_typed_cover_page_does_not_block_ocr_of_scanned_pages(monkeypatch):
    done = []
    monkeypatch.setattr(parser_module, "_ocr_pdf_pages",
                        lambda content, pages: done.extend(pages) or {n: f"OCR TEXT OF PAGE {n} " * 10 for n in pages})
    pytest.importorskip("reportlab")
    cover = ["LOAN AGREEMENT - COVER PAGE", "Prepared for FINANCIAL BANK OF AMERICA Inc.",
             "This agreement consists of the pages that follow and is binding on both parties once signed."]
    parser_module.extract_text_from_file("scan.pdf", _scanned_pdf(SCANNED_PAGES, typed_cover=cover))
    assert done == [2, 3]


@pytest.mark.skipif(not (shutil.which("tesseract") and shutil.which("pdftoppm")), reason="needs Tesseract + Poppler")
def test_real_ocr_of_a_scanned_contract():
    pytest.importorskip("reportlab")
    text, info, pages = parser_module.extract_text_from_file("scan.pdf", _scanned_pdf(SCANNED_PAGES))
    assert info["used"] and info["pages"] == 2
    assert "Julia Miller" in text and "45,892" in text and "60 months" in text
    assert extract_labeled_facts(text)["contract_value"] == 45892



def test_label_values_stop_at_the_next_label_of_any_case():
    header = ("LOAN AGREEMENT\nBorrower: John Smith\nAddress: 12 Elm Road, Springfield\n"
              "Lender: First Capital Bank\nAmount Financed: $45,892 over 360 monthly payments.\n")
    facts = extract_labeled_facts(header)
    assert facts["customer_name"] == "John Smith"
    assert facts["lender_name"] == "First Capital Bank"
    assert facts["contract_value"] == 45892


@pytest.mark.parametrize("text, value", [
    ("FINANCED AMOUNT: $45,892 360 monthly", 45892),
    ("FINANCED AMOUNT: USD 150,000 180 months", 150000),
])
def test_amount_is_not_joined_with_the_next_number(text, value):
    assert extract_labeled_facts(text)["contract_value"] == value


def test_schedule_rows_and_repeated_heading_survive():
    pages, n = [], 1
    for p in range(4):
        rows = []
        for _ in range(5):
            rows.append(f"{n}  {n:02d}/2025  1,250.00")
            n += 1
        body = "\n".join(f"body line {i} of page text" for i in range(8))
        pages.append("REPAYMENT SCHEDULE (continued)\n" + "\n".join(rows[:2]) + "\n" + body + "\n"
                     + "\n".join(rows[2:]) + f"\nPage {p + 1} of 4")
    out = strip_page_furniture(pages)
    assert [sum("/2025" in line for line in o.split("\n")) for o in out] == [5, 5, 5, 5]
    assert "REPAYMENT SCHEDULE" in out[0]
    assert all("of 4" not in o for o in out)


def test_bare_number_in_the_body_is_not_a_page_number():
    assert "1250" in strip_page_furniture(["installment is\n1250\ndollars and more text here"])[0]


# ------------------------------------------ signed contracts, busy page edges

SIGNED = """CAR FINANCING AGREEMENT
BORROWER: Daniel Okafor, residing at 2147 Maplewood Lane, Westerville, OH.
LENDER: HARBORLINE CREDIT UNION, headquartered at 88 Riverside Drive, Columbus, OH.
FINANCED AMOUNT: $38,750.00.
CLAUSE ONE – PURPOSE: This agreement grants the BORROWER financing for the Vehicle.
CLAUSE TWO – PAYMENT: The BORROWER shall pay into account no. ______________ each month
by direct debit, with interest of 0.79% per month.
CLAUSE THREE – JURISDICTION: The parties elect the Courts of Franklin County, Ohio, to settle
any disputes arising from this agreement.
Signed in two counterparts at Columbus, Ohio, on March 14, 2026.
______________________________ ______________________________
Daniel Okafor, Borrower Authorized officer
"""


def test_signature_block_does_not_delete_the_last_clause():
    _, clauses = split_document(SIGNED)
    assert len(clauses) == 3
    assert clauses[-1].startswith("CLAUSE THREE – JURISDICTION")
    assert clauses[-1].endswith("arising from this agreement.")
    assert "Signed in two counterparts" not in clauses[-1]


def test_clause_with_a_fill_in_blank_is_kept():
    _, clauses = split_document(SIGNED)
    assert "account no. ______________ each month" in clauses[1]


def test_page_number_behind_header_and_footer_lines_is_removed():
    # Some PDF generators write header and footer first: four furniture
    # lines before the body, the page number fourth.
    def page(n, body):
        return f"Agreement No. HCU-AUTO-17\nConfidential\nInitials: Borrower ____ Lender ____\nPage {n}\n{body}"
    pages = [page(1, "CAR FINANCING AGREEMENT\nCLAUSE ONE – PURPOSE: financing of the vehicle."),
             page(2, "CLAUSE TWO – TERM: sixty months."),
             page(3, "CLAUSE THREE – LAW: courts of Ohio.")]
    cleaned = strip_page_furniture(pages)
    assert cleaned[1] == "CLAUSE TWO – TERM: sixty months."
    assert cleaned[2] == "CLAUSE THREE – LAW: courts of Ohio."
    assert "Page 1" not in cleaned[0]


def test_table_rows_at_the_page_edge_are_not_peeled_away():
    rows = [f"Installment {n} due on the fourteenth" for n in range(1, 6)]
    pages = ["\n".join(["Loan schedule"] + rows) for _ in range(3)]
    cleaned = strip_page_furniture(pages)
    assert all(sum(r in p for r in rows) >= 4 for p in cleaned)


def test_sentence_starting_with_signed_is_not_a_signature_block():
    text = SIGNED.replace(
        "CLAUSE THREE – JURISDICTION: The parties elect the Courts of Franklin County, Ohio, to settle\n",
        "CLAUSE THREE – JURISDICTION: The parties elect the Courts of Franklin County, Ohio. Notices go by post.\n"
        "Signed copies of every notice must be kept by both parties. The courts settle\n",
    )
    _, clauses = split_document(text)
    assert "Signed copies of every notice must be kept" in clauses[-1]
    assert "Signed in two counterparts" not in clauses[-1]


def test_heading_split_by_the_pdf_text_layer_is_still_a_heading():
    # pypdf gave "5. L IABILITY": the clause was merged into clause 4.
    text = ("SERVICE AGREEMENT between AlphaTech Solutions and Beta Retail, dated 1 November 2025.\n"
            "4. CONFIDENTIALITY Both parties agree to keep shared information confidential. "
            "5. L IABILITY The Service Provider's liability shall not exceed the fees paid in 6 months. "
            "6. GOVERNING LAW This Agreement is governed by the laws of India.")
    _, clauses = split_document(text)
    assert [c.split(" ")[0] for c in clauses] == ["4.", "5.", "6."]
    assert clauses[1].startswith("5. L IABILITY")


def test_in_witness_whereof_mid_line_ends_the_last_clause():
    text = ("SERVICE AGREEMENT between AlphaTech Solutions and Beta Retail, dated 1 November 2025.\n"
            "1. SERVICES The provider maintains the website for the client as agreed. "
            "2. GOVERNING LAW This Agreement is governed by the laws of India, courts in Bengaluru. "
            "IN WITNESS WHEREOF, the parties have executed this Agreement.\n_________ ______ Authorized Signatory")
    _, clauses = split_document(text)
    assert len(clauses) == 2
    assert clauses[-1].endswith("courts in Bengaluru.")


def test_numbered_list_word_starting_with_a_single_capital_is_not_a_heading():
    _, clauses = split_document(
        "LOAN AGREEMENT between the parties below, for a car purchase.\n"
        "CLAUSE ONE – PAYMENT: The borrower pays in 12 installments. A Borrower who pays late owes a fee of 2%."
    )
    assert len(clauses) == 1


FLAWED = (
    "SERVICE AGREEMENT (FLAWED VERSION)\n"
    'This Agreement is made between XYZ Corp ("Provider") and ABC Ltd ("Client").\n'
    "1. Services: Provider agrees to offer consulting services but the exact scope will be determined later.\n"
    "2. Payment: Client shall pay Provider $10,000. Payment schedule will be discussed after completion of\nservices.\n"
    "6. Governing Law: This agreement shall be governed by whichever jurisdiction the Provider deems fit.\n"
    "7. Signatures: Digital or verbal consent is acceptable; signatures are optional.\n"
    "Signed by:\nXYZ Corp Representative: ____________________\n"
)


def test_numbered_headings_in_ordinary_capitals_with_a_colon():
    # "1. Services: ..." used to give no clauses at all.
    header, clauses = split_document(FLAWED)
    assert [c.split(":")[0] for c in clauses] == ["1. Services", "2. Payment", "6. Governing Law", "7. Signatures"]
    assert "made between XYZ Corp" in header
    assert clauses[-1].endswith("signatures are optional.")


def test_numbered_sentences_and_cross_references_are_not_headings():
    _, clauses = split_document(
        "LOAN AGREEMENT between the parties below, for the purchase of a vehicle.\n"
        "CLAUSE ONE – PAYMENT: The borrower pays monthly as per clause 2. Payment: see the schedule. "
        "The steps are:\n2. The borrower shall notify the bank of any change of address within 10 days."
    )
    assert len(clauses) == 1
