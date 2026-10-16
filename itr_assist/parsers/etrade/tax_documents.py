"""E*TRADE / Morgan Stanley implementation of BaseTaxDocumentParser."""
from datetime import date
import re
from typing import Optional
from pypdf import PdfReader

from itr_assist.models import Form1042SData
from itr_assist.parsers.base import BaseTaxDocumentParser


class ETradeTaxDocumentParser(BaseTaxDocumentParser):
    """Parses Form 1042-S PDF for US gross income and federal tax withheld."""

    def parse(self, file_path: str, calendar_year_hint: Optional[int] = None) -> Optional[Form1042SData]:
        """Extract Form 1042-S fields from E*TRADE / Morgan Stanley PDF.

        calendar_year_hint is used only if the document's own "<year> Form 1042-S" header
        cannot be matched.
        """
        reader = PdfReader(file_path)

        full_text = ""
        for page in reader.pages:
            full_text += (page.extract_text() or "") + "\n"

        cal_year_m = re.search(r'(20\d\d)\s+Form 1042-S', full_text)
        fallback_year = calendar_year_hint if calendar_year_hint is not None else date.today().year
        cal_year = int(cal_year_m.group(1)) if cal_year_m else fallback_year

        gross_inc = 0.0
        tax_withheld = 0.0
        rate = 0.25

        row_m = re.search(r'06\s+Chap\.\s*3\s+\$([\d,]+\.\d+)\s+\S+\s+([\d\.]+)%\s+\S+\s+[\d\.]+%\s+\$([\d,]+\.\d+)', full_text)
        if row_m:
            gross_inc = float(row_m.group(1).replace(",", ""))
            rate = float(row_m.group(2)) / 100.0
            tax_withheld = float(row_m.group(3).replace(",", ""))
        else:
            gt_m = re.search(r'Grand Total\s+\$([\d,]+\.\d+)\s+\$([\d,]+\.\d+)', full_text)
            if gt_m:
                gross_inc = float(gt_m.group(1).replace(",", ""))
                tax_withheld = float(gt_m.group(2).replace(",", ""))

        pan_m = re.search(r'([A-Z]{5}\d{4}[A-Z])', full_text)
        pan = pan_m.group(1) if pan_m else ""

        acc_m = re.search(r'(\d{3}[ -]\d{6})', full_text)
        if acc_m:
            acc_num = re.sub(r'\s+', '-', acc_m.group(1).strip())
        else:
            acc_num = ""

        name = ""
        name_m = re.search(r'\d{3}\s+\d{6}\s*\n\s*([A-Z\s]+?)(?:\s+IN|\n)', full_text)
        if name_m:
            name = name_m.group(1).strip()
        else:
            # Fallback: Recipient name preceding TIN / PAN (Box 13a before Box 13i)
            name_pan_m = re.search(r'([A-Z\s]{3,35}?)\s*\n\s*[A-Z]{5}\d{4}[A-Z]', full_text)
            if name_pan_m:
                candidate = name_pan_m.group(1).strip().split('\n')[-1].strip()
                if candidate and not any(w in candidate for w in ["FORM", "PAGE", "CODE", "TOTAL"]):
                    name = candidate

        # Withholding agent (the custodian) address, box 12: printed as "US" (country) followed by
        # the street lines and a "CITY, ST 12345" line. Left empty when it cannot be read.
        agent_address = ""
        agent_zip = ""
        addr_m = re.search(
            r"\nUS\s*\n((?:[^\n]*\n){1,4}?)\s*([A-Z][A-Z .'-]+,\s*[A-Z]{2}\s+(\d{5})(?:-\d{4})?)\s*\n",
            full_text,
        )
        if addr_m:
            street = ", ".join(line.strip() for line in addr_m.group(1).splitlines() if line.strip())
            agent_address = ", ".join(part for part in (street, addr_m.group(2).strip()) if part)
            agent_zip = addr_m.group(3)

        full_text_upper = full_text.upper()
        if "MORGAN STANLEY" in full_text_upper:
            agent = "Morgan Stanley Smith Barney LLC"
        elif "E*TRADE" in full_text_upper or "ETRADE" in full_text_upper:
            agent = "E*TRADE Securities LLC"
        else:
            agent = "Withholding Agent"

        return Form1042SData(
            calendar_year=cal_year,
            recipient_name=name,
            recipient_tin=pan,
            gross_dividend_usd=gross_inc,
            tax_withheld_usd=tax_withheld,
            withholding_rate=rate,
            withholding_agent=agent,
            account_number=acc_num,
            withholding_agent_address=agent_address,
            withholding_agent_zip=agent_zip,
        )
