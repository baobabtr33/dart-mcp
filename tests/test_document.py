import io
import zipfile

from dart_mcp.document import find_snippets, markup_to_text, parse_document_zip

MARKUP = """<DOCUMENT><BODY>
<SECTION-1><TITLE ATOC="Y">I. 회사의 개요</TITLE>
<P>당사는&nbsp;반도체를 제조합니다.</P>
<TABLE><TR><TH>구분</TH><TH>금액</TH></TR><TR><TD>매출액</TD><TD>1,000</TD></TR></TABLE>
</SECTION-1>
<SECTION-1><TITLE ATOC="Y">II. 사업의 내용</TITLE><P>메모리 사업</P></SECTION-1>
</BODY></DOCUMENT>"""


def test_markup_to_text():
    text = markup_to_text(MARKUP)
    assert "## I. 회사의 개요" in text
    assert "당사는 반도체를 제조합니다." in text
    assert "매출액 | 1,000" in text
    assert "<" not in text


def test_parse_zip_orders_main_file_and_builds_toc():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20240312000736_00760.xml", "<P>첨부 감사보고서</P>")
        zf.writestr("20240312000736.xml", MARKUP.encode("euc-kr"))
    doc = parse_document_zip("20240312000736", buf.getvalue())
    assert doc.text.startswith("## I. 회사의 개요")
    assert "# Attachment: 20240312000736_00760.xml" in doc.text
    assert [t["title"] for t in doc.toc] == ["I. 회사의 개요", "II. 사업의 내용"]
    assert doc.text[doc.toc[1]["offset"] :].startswith("## II.")


def test_find_snippets():
    hits = find_snippets("a" * 50 + "배당" + "b" * 50, "배당", radius=5)
    assert hits == [{"offset": 50, "snippet": "aaaaa배당bbbbb"}]
