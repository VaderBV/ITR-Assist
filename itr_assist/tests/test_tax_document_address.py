"""Form 1042-S: the withholding agent's address, read from the layout of a real form (fictional data)."""
from unittest.mock import MagicMock, patch

from itr_assist.parsers.etrade import ETradeTaxDocumentParser

# Real forms print the box-12 country ("US"), the street lines, then "CITY, ST ZIP", then the
# recipient's TIN. Each form is printed three times (copies B, C and D).
FORM = (
    "2025 Form 1042-S Recipient Summary Statements\n"
    "06 Chap. 3 $100.00 00 25.00% 15 0.00% $25.00\n"
    "3\n06 $100.00 00 15\n$25.00\n25.00% 0.00%\n$0.00\n$25.00\n15 01\n"
    "US\n1 TEST PLAZA\n7TH FLOOR\n \nNEW YORK, NY 10004\n"
    "ABCDE1234F\n16\n23\n100 123456 \nJOHN DOE IN\nSPRINGFIELD 12345\nINDIA\n"
    "Morgan Stanley Smith Barney, LLC\n"
)


def _parse(text):
    page = MagicMock()
    page.extract_text.return_value = text
    with patch("itr_assist.parsers.etrade.tax_documents.PdfReader") as reader:
        reader.return_value.pages = [page, page, page]
        return ETradeTaxDocumentParser().parse("form.pdf")


def test_withholding_agent_address_and_zip_are_read():
    data = _parse(FORM)
    assert data.withholding_agent_address == "1 TEST PLAZA, 7TH FLOOR, NEW YORK, NY 10004"
    assert data.withholding_agent_zip == "10004"
    assert data.gross_dividend_usd == 100.0 and data.tax_withheld_usd == 25.0


def test_zip_plus_four_keeps_the_five_digit_zip():
    data = _parse(FORM.replace("NEW YORK, NY 10004", "NEW YORK, NY 10004-1234"))
    assert data.withholding_agent_zip == "10004"


def test_unreadable_address_is_left_empty_not_guessed():
    data = _parse(FORM.replace("US\n1 TEST PLAZA\n7TH FLOOR\n \nNEW YORK, NY 10004\n", ""))
    assert data.withholding_agent_address == "" and data.withholding_agent_zip == ""
