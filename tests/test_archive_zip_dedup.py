import csv, json, tempfile, unittest, zipfile
from pathlib import Path

from orchestrator.archive_zip_dedup import run, sha256


class ArchiveZipDedupTests(unittest.TestCase):
    def test_identical_system_copy_is_replaced_by_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); package=root/'assembled'; package.mkdir()
            tree=root/'tree'/'테스트_환경자료'; user=tree/'01_사용자자료'/'04_지속가능경영보고서'; system=tree/'90_시스템원본'/'ENVINFO'/'raw_attachments'; idx=tree/'00_자료목록'; cp=tree/'90_시스템원본'/'control_plane'
            for p in [user,system,idx,cp]: p.mkdir(parents=True,exist_ok=True)
            payload=b'official-document-binary'*100
            (user/'report.pdf').write_bytes(payload); (system/'same.pdf').write_bytes(payload); (system/'other.txt').write_text('different',encoding='utf-8')
            (idx/'Archive_Manifest.json').write_text(json.dumps({'archive_root':tree.name}),encoding='utf-8')
            manifest={'human_archive':{'status':'PASS'}}
            (package/'Master_Manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            (cp/'Master_Manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            (package/'Archive_Summary.json').write_text(json.dumps({'archive_root':tree.name}),encoding='utf-8')
            with (package/'Artifact_Index.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['source','path','bytes','sha256']); w.writeheader()
            zip_path=package/'Human_Archive.zip'
            with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
                for p in tree.rglob('*'):
                    if p.is_file(): z.write(p,arcname=str(Path(tree.name)/p.relative_to(tree)))
            result=run(package)
            self.assertEqual(result['deduplicated_files'],1)
            self.assertEqual(result['deduplicated_bytes'],len(payload))
            with zipfile.ZipFile(zip_path) as z:
                names=set(z.namelist())
                self.assertNotIn(f'{tree.name}/90_시스템원본/ENVINFO/raw_attachments/same.pdf',names)
                self.assertIn(f'{tree.name}/01_사용자자료/04_지속가능경영보고서/report.pdf',names)
                self.assertIn(f'{tree.name}/90_시스템원본/Deduplicated_File_References.csv',names)
                ref=z.read(f'{tree.name}/90_시스템원본/Deduplicated_File_References.csv').decode('utf-8-sig')
                self.assertIn('same.pdf',ref); self.assertIn('report.pdf',ref)
            summary=json.loads((package/'Archive_Summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['deduplicated_files'],1)
            rows=list(csv.DictReader((package/'Artifact_Index.csv').open(encoding='utf-8-sig')))
            human=[r for r in rows if r['path']=='Human_Archive.zip'][0]
            self.assertEqual(human['sha256'],sha256(zip_path))


if __name__=='__main__': unittest.main()
