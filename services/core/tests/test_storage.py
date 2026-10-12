import json
from contextlib import closing
import os
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from services.core.storage import migrate_legacy_store, service_store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('cache/storage_tests') / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {'DOUYIN_STORE_DIR': str(self.root / 'store')})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        shutil.rmtree(self.root)

    def test_migration_preserves_history_media_and_updates_absolute_paths(self):
        legacy = self.root / 'cache'
        creator = legacy / 'video_creator'
        creator.mkdir(parents=True)
        (creator / 'provider_configs.json').write_text('[{"api_key":"secret-fixture"}]')
        task = creator / 'generation_jobs/task-id'
        task.mkdir(parents=True)
        (task / 'video.mp4').write_bytes(b'video-fixture')
        payload = {'video': str((task / 'video.mp4').resolve()), 'href': '/artifacts/generation_jobs/task-id/video.mp4'}
        (task / 'task.json').write_text(json.dumps(payload))
        with closing(sqlite3.connect(creator / 'assets.db')) as db, db:
            db.execute('CREATE TABLE assets (id TEXT, data TEXT)')
            db.execute('INSERT INTO assets VALUES (?,?)', ('task-id', json.dumps(payload)))
        diagnostic = creator / 'diagnostics'
        diagnostic.mkdir()
        (diagnostic / 'log.txt').write_text('temporary')
        migrated = migrate_legacy_store(legacy)
        target = service_store('video_creator')
        self.assertIn('video_creator/assets.db', migrated)
        self.assertEqual((target / 'generation_jobs/task-id/video.mp4').read_bytes(), b'video-fixture')
        self.assertEqual(json.loads((target / 'provider_configs.json').read_text())[0]['api_key'], 'secret-fixture')
        with closing(sqlite3.connect(target / 'assets.db')) as db:
            restored = json.loads(db.execute('SELECT data FROM assets').fetchone()[0])
        self.assertEqual(restored['video'], str(target / 'generation_jobs/task-id/video.mp4'))
        self.assertEqual(restored['href'], payload['href'])
        self.assertTrue(diagnostic.exists())
        self.assertEqual(migrate_legacy_store(legacy), [])

    def test_conflicting_destination_never_overwrites_or_partially_moves(self):
        legacy = self.root / 'cache/video_creator'
        legacy.mkdir(parents=True)
        (legacy / 'provider_configs.json').write_text('original')
        target = service_store('video_creator')
        target.mkdir(parents=True)
        (target / 'provider_configs.json').write_text('existing')
        with self.assertRaises(FileExistsError):
            migrate_legacy_store(self.root / 'cache')
        self.assertEqual((legacy / 'provider_configs.json').read_text(), 'original')
        self.assertEqual((target / 'provider_configs.json').read_text(), 'existing')

    def test_locked_directory_rolls_back_previous_moves(self):
        legacy = self.root / 'cache/video_creator'
        legacy.mkdir(parents=True)
        (legacy / 'provider_configs.json').write_text('original')
        (legacy / 'generation_jobs').mkdir()
        original_rename = Path.rename
        def rename(source, target):
            if source.name == 'generation_jobs':
                raise PermissionError('directory temporarily occupied')
            return original_rename(source, target)
        with patch.object(Path, 'rename', rename), patch('services.core.storage.time.sleep'):
            with self.assertRaises(PermissionError):
                migrate_legacy_store(self.root / 'cache')
        self.assertEqual((legacy / 'provider_configs.json').read_text(), 'original')
        self.assertFalse((service_store('video_creator') / 'provider_configs.json').exists())
