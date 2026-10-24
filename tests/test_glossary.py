from dart_mcp.glossary import account_label, lookup_terms, translate_report_name


def test_periodic_report_with_period():
    assert translate_report_name("사업보고서 (2024.12)") == "Annual Report (period ending 2024-12)"


def test_amended_prefix_and_spacing():
    assert translate_report_name("[기재정정]  유상증자 결정") == (
        "[Amended] Paid-in Capital Increase (Rights Offering / Placement) Decision"
    )


def test_longest_match_wins():
    assert translate_report_name("연결재무제표기준영업(잠정)실적(공정공시)") == (
        "Preliminary Consolidated Earnings (Fair Disclosure)"
    )


def test_voluntary_flag():
    assert translate_report_name("단일판매ㆍ공급계약체결(자율공시)") == "Single Large Sales/Supply Contract [voluntary]"


def test_unknown_title_returns_none():
    assert translate_report_name("완전히 새로운 공시") is None


def test_account_label_prefers_glossary():
    assert account_label("ifrs-full_Revenue", "매출액") == "Revenue"


def test_account_label_humanizes_xbrl_id():
    assert account_label("ifrs-full_ProfitLossAttributableToOwnersOfParent", "기타") == (
        "Profit loss attributable to owners of parent"
    )


def test_account_label_entity_specific_id_is_none():
    assert account_label("entity00126380_udf_BS_123", "특수계정") is None


def test_lookup_terms():
    out = lookup_terms(["유상증자", "최대주주", "없는용어", "전환사채권 발행결정"])
    assert out["최대주주"] == "Largest shareholder"
    assert out["없는용어"] is None
    assert out["전환사채권 발행결정"] == "Convertible Bond (CB) Issuance Decision"


def test_core_jargon_has_entries():
    out = lookup_terms(["유상증자", "전환사채", "물적분할", "밸류업"])
    assert all(out.values()), out


def test_inner_title_beats_wrapper():
    assert translate_report_name("[기재정정]주요사항보고서(유상증자결정)") == (
        "[Amended] Paid-in Capital Increase (Rights Offering / Placement) Decision"
    )
    assert translate_report_name("주요사항보고서(유형자산양수결정)") == "Acquisition of Tangible Assets"


def test_relation_label():
    from dart_mcp.glossary import relation_label

    assert relation_label("최대주주 본인") == "Largest shareholder (self)"
    assert relation_label("최대주주의 특수관계인") == "Related party of largest shareholder"
    assert relation_label("계열회사 임원") == "Executive of affiliate"
    assert relation_label("") is None
