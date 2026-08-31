from media_platform.epo.core import EPOCrawler


def test_epo_parser_extracts_potential_customer():
    xml = b'''<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">
      <ops:biblio-search total-result-count="1"><ops:search-result><exchange-documents>
        <exchange-document family-id="42" country="EP" doc-number="123" kind="A1">
          <bibliographic-data>
            <publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>123</doc-number><kind>A1</kind><date>20260101</date></document-id></publication-reference>
            <parties><applicants><applicant><applicant-name><name>ACME MEDICAL LTD</name></applicant-name><residence><country>DE</country></residence></applicant></applicants></parties>
            <invention-title lang="en">PEEK medical implant</invention-title>
            <abstract lang="en"><p>A component made from PEEK.</p></abstract>
          </bibliographic-data>
        </exchange-document>
      </exchange-documents></ops:search-result></ops:biblio-search>
    </ops:world-patent-data>'''
    import xml.etree.ElementTree as ET

    items = EPOCrawler._parse_patents(ET.fromstring(xml), "PEEK")
    assert items[0]["potential_customers"] == "ACME MEDICAL LTD"
    assert items[0]["publication_number"] == "EP123A1"
    assert items[0]["title"] == "PEEK medical implant"
