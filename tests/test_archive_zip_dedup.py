import csv, json, tempfile, unittest, zipfile
from pathlib import Path

from orchestrator.archive_zip_dedup import run, sha256


class ArchiveZipDedupTests(unittest.TestCase):
    def _base_package(self, td):
        root=Path(td); package=root/'assembled'; package.mkdir()
        tree=root/'tree'/'테스트_환경자료'; idx=tree/'00_자료목록'; cp=tree/'90_시스템원본'/'control_plane'
        idx.mkdir(parents=True,exist_ok=True); cp.mkdir(parents=True,exist_ok=True)
        (idx/'Archive_Manifest.json').write_text(json.dumps({'archive_root':tree.name}),encoding='utf-8')
        manifest={'human_archive':{'status':'PASS'}}
        (package/'Master_Manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        (cp/'Master_Manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        (package/'Archive_Summary.json').write_text(json.dumps({'archive_root':tree.name}),encoding='utf-8')
        with (package/'Artifact_Index.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['source','path','bytes','sha256']); w.writeheader()
        return root,package,tree

    def _zip_tree(self, package, tree):
        zip_path=package/'Human_Archive.zip'
        with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
            for p in tree.rglob('*'):
                if p.is_file(): z.write(p,arcname=str(Path(tree.name)/p.relative_to(tree)))
        return zip_path

    def test_identical_system_copy_is_replaced_by_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root,package,tree=self._base_package(td)
            user=tree/'01_사용자자료'/'04_지속가능경영보고서'; system=tree/'90_시스템원본'/'ENVINFO'/'raw_attachments'
            user.mkdir(parents=True,exist_ok=True); system.mkdir(parents=True,exist_ok=True)
            payload=b'official-document-binary'*100
            (user/'report.pdf').write_bytes(payload); (system/'same.pdf').write_bytes(payload); (system/'other.txt').write_text('different',encoding='utf-8')
            zip_path=self._zip_tree(package,tree)
            result=run(package)
            self.assertEqual(result['deduplicated_files'],1)
            self.assertEqual(result['deduplicated_bytes'],len(payload))
            self.assertEqual(result['user_deduplicated_files'],0)
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

    def test_exact_user_duplicates_in_same_folder_keep_canonical_name(self):
        with tempfile.TemporaryDirectory() as td:
            root,package,tree=self._base_package(td)
            user=tree/'01_사용자자료'/'04_지속가능경영보고서'; system=tree/'90_시스템원본'
            user.mkdir(parents=True,exist_ok=True); system.mkdir(parents=True,exist_ok=True)
            payload=b'same-2022-report'*200
            canonical=user/'금호석유화학_지속가능경영보고서_2022.pdf'
            promoted1=user/'ENVINFO공개연도_2022_2022_SUSTAINABILITY_REPORT.pdf'
            promoted2=user/'ENVINFO공개연도_2022_첨부 1. 지속가능경영보고서.pdf'
            canonical.write_bytes(payload); promoted1.write_bytes(payload); promoted2.write_bytes(payload)
            different=user/'ENVINFO공개연도_2022_다른버전.pdf'; different.write_bytes(payload+b'-different')
            zip_path=self._zip_tree(package,tree)
            result=run(package)
            self.assertEqual(result['user_deduplicated_files'],2)
            self.assertEqual(result['user_deduplicated_bytes'],len(payload)*2)
            with zipfile.ZipFile(zip_path) as z:
                names=set(z.namelist())
                base=f'{tree.name}/01_사용자자료/04_지속가능경영보고서/'
                self.assertIn(base+canonical.name,names)
                self.assertIn(base+different.name,names)
                self.assertNotIn(base+promoted1.name,names)
                self.assertNotIn(base+promoted2.name,names)
                ref_name=f'{tree.name}/00_자료목록/Deduplicated_User_File_References.csv'
                self.assertIn(ref_name,names)
                ref=z.read(ref_name).decode('utf-8-sig')
                self.assertIn(promoted1.name,ref)
                self.assertIn(promoted2.name,ref)
                self.assertIn(canonical.name,ref)


if __name__=='__main__': unittest.main()
