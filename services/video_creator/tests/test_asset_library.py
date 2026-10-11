from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from services.video_creator.asset_library import ReferenceAssetStore


class ReferenceAssetStoreTests(unittest.TestCase):
    def test_deduplicates_by_file_content_and_keeps_description(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/"pig.png"; source.write_bytes(b"same image")
            store=ReferenceAssetStore(root/"library")
            first,duplicate=store.add(source,name="猪八戒",kind="character",description={"appearance":"黑色僧衣"})
            second,is_duplicate=store.add(source,name="另一个名字",kind="character")
            self.assertFalse(duplicate)
            self.assertTrue(is_duplicate)
            self.assertEqual(first["id"],second["id"])
            self.assertEqual(first["description"]["appearance"],"黑色僧衣")
            self.assertEqual(len(store.list()),1)
            self.assertTrue((root/"library"/f"{first['id']}.json").is_file())

    def test_use_counts_and_delete_removes_owned_file(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/"scene.jpg"; source.write_bytes(b"scene")
            store=ReferenceAssetStore(root/"library"); asset,_=store.add(source,name="高老庄",kind="location")
            stored=store.use(asset["id"])
            self.assertTrue(stored.is_file())
            self.assertEqual(store.get(asset["id"])["use_count"],1)
            self.assertTrue(store.delete(asset["id"]))
            self.assertFalse(stored.exists())

    def test_updates_editable_metadata_and_json_sidecar(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/"asset.png"; source.write_bytes(b"asset")
            store=ReferenceAssetStore(root/"library"); asset,_=store.add(source,name="旧名称",kind="reference")
            updated=store.update(asset["id"],name="猪八戒",kind="character",description={"prompt":"只包含猪八戒"})
            self.assertEqual(updated["name"],"猪八戒")
            self.assertEqual(updated["kind"],"character")
            self.assertEqual(store.get(asset["id"])["description"]["prompt"],"只包含猪八戒")


if __name__ == "__main__":
    unittest.main()
