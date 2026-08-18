import unittest

from collectors.prtr_collect import parse_rows


HTML = '''
<table><tbody>
<tr>
<td>1</td>
<td class="left"><a href="#none" onclick="fnEntrpsDetail('312');return false;" class="link_blue2">(주)LG화학 대산공장</a></td>
<td class="left">충청남도 서산시 대산읍 독곶1로 54 (주)LG화학 대산공장</td>
<td class="right">87,252</td><td class="right">0</td><td class="right">20,126</td>
</tr>
<tr>
<td>2</td>
<td class="left"><a href="#none" onclick="fnEntrpsDetail('311');return false;" class="link_blue2">(주)LG화학 익산공장</a></td>
<td class="left">전라북도 익산시 석암로 99 (용제동)</td>
<td class="right">0</td><td class="right">0</td><td class="right">2</td>
</tr>
</tbody></table>
'''


class TestPrtrParser(unittest.TestCase):
    def test_onclick_ids_and_raw_values(self):
        rows = parse_rows(HTML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["entrps_id"], "312")
        self.assertEqual(rows[0]["company_name_raw"], "(주)LG화학 대산공장")
        self.assertEqual(rows[0]["release_total_raw"], "87,252")
        self.assertEqual(rows[1]["entrps_id"], "311")
        self.assertEqual(rows[1]["transfer_total_raw"], "2")


if __name__ == "__main__":
    unittest.main()
