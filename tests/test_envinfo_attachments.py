import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collectors"))
from envinfo_collect import extract_attachments, classify_attachment


class EnvInfoAttachmentTests(unittest.TestCase):
    def test_extracts_download_file_links_with_section_context(self):
        html = '''
        <html><body>
          <a href="#inquiry04">의무 4. 전담조직·교육훈련·내부심사 등</a>
          <div id="inquiry04" class="inquiry_cont">
            <table><tbody><tr><td>부서명 환경팀 업무내용 환경경영시스템 운영</td></tr>
            <tr><td>첨부파일</td><td><a href="javascript:downloadFile('FILE001','pdf');">녹색경영 전담조직 및 업무·역할·권한.pdf</a></td></tr>
            </tbody></table>
            <table><tbody><tr><td>규격 이행준수 및 효율적 운영여부 점검</td></tr>
            <tr><td>첨부파일</td><td><a href="javascript:downloadFile('FILE002','PPTX');">환경안전보건 경영시스템 내부심사 결과 보고서.PPTX</a></td></tr>
            </tbody></table>
          </div>
        </body></html>
        '''
        rows = extract_attachments(html, 2024, "COMP1", "테스트공장")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["section_id"], "inquiry04")
        self.assertIn("전담조직", rows[0]["section_title"])
        self.assertEqual(rows[0]["document_category"], "ORGANIZATION_ROLE")
        self.assertEqual(rows[0]["importance"], "CORE")
        self.assertEqual(rows[1]["document_category"], "INTERNAL_AUDIT")
        self.assertEqual(rows[1]["file_id"], "FILE002")
        self.assertEqual(rows[1]["file_ext"], "PPTX")

    def test_duplicate_same_file_reference_is_deduped(self):
        html = '''<div id="inquiry04"><table><tbody>
        <tr><td><a href="javascript:downloadFile('F1','PNG');">비상대응 조직도.PNG</a></td></tr>
        <tr><td><a href="javascript:downloadFile('F1','PNG');">비상대응 조직도.PNG</a></td></tr>
        </tbody></table></div>'''
        rows = extract_attachments(html, 2024, "C1", "공장")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["document_category"], "ORGANIZATION_ROLE")
        self.assertEqual(rows[0]["file_ext"], "PNG")

    def test_evidence_only_precedes_generic_chemical_keyword(self):
        category, importance = classify_attachment("유해화학물질 관리자 워크숍 서명지.pdf")
        self.assertEqual(category, "CERTIFICATION_EVIDENCE")
        self.assertEqual(importance, "EVIDENCE_ONLY")

    def test_emergency_response_is_core(self):
        category, importance = classify_attachment("24년 유해화학물질 유누출 비상대응 훈련결과.png")
        self.assertEqual(category, "EMERGENCY_RESPONSE")
        self.assertEqual(importance, "CORE")


if __name__ == "__main__": unittest.main()
