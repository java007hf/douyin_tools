import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.core.understanding_queue import reserve, shared_slot, snapshot

CHILD = '''
import sys,time
from pathlib import Path
from services.core.understanding_queue import shared_slot
root=Path(sys.argv[1]); task=sys.argv[2]
with shared_slot(task, sys.argv[3]):
    (root/(task+'.entered')).touch()
    while not (root/(task+'.release')).exists(): time.sleep(.02)
'''


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError('shared queue did not reach expected state')


class SharedUnderstandingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='cache')
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {'DOUYIN_STORE_DIR': str(self.root)})
        self.env.start()
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
            child.stderr.close()
        self.env.stop()
        self.temp.cleanup()

    def child(self, task, platform):
        child = subprocess.Popen([sys.executable, '-c', CHILD, str(self.root), task, platform],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.children.append(child)
        return child

    def release(self, task):
        (self.root / (task + '.release')).touch()

    def test_douyin_youtube_and_mcp_processes_share_one_fifo(self):
        a = self.child('douyin', '抖音')
        wait_for(lambda: (self.root / 'douyin.entered').exists())
        b = self.child('youtube', 'YouTube')
        wait_for(lambda: snapshot()['pending'] == 1)
        c = self.child('mcp', '抖音 MCP')
        wait_for(lambda: snapshot()['pending'] == 2)
        state = snapshot()
        self.assertEqual(state['active'], 1)
        self.assertEqual([x['task_id'] for x in state['items']], ['douyin','youtube','mcp'])
        self.assertEqual([x['queue_position'] for x in state['items']], [None,1,2])
        self.assertFalse((self.root / 'youtube.entered').exists())
        self.release('douyin')
        wait_for(lambda: (self.root / 'youtube.entered').exists())
        self.assertFalse((self.root / 'mcp.entered').exists())
        self.release('youtube')
        wait_for(lambda: (self.root / 'mcp.entered').exists())
        self.release('mcp')
        for child in (a,b,c):
            self.assertEqual(child.wait(timeout=5), 0, child.stderr.read().decode(errors='replace'))
        self.assertEqual(snapshot()['active'], 0)

    def test_dead_owner_releases_slot_but_live_owner_is_not_timed_out(self):
        a = self.child('old', 'YouTube')
        wait_for(lambda: (self.root / 'old.entered').exists())
        b = self.child('next', '抖音')
        wait_for(lambda: snapshot()['pending'] == 1)
        time.sleep(.6)
        self.assertFalse((self.root / 'next.entered').exists())
        a.terminate()
        a.wait(timeout=5)
        wait_for(lambda: (self.root / 'next.entered').exists())
        self.assertEqual(snapshot()['active'], 1)
        self.release('next')
        self.assertEqual(b.wait(timeout=5), 0)

    def test_reservation_is_fifo_and_nested_model_calls_are_reentrant(self):
        reserve('first', 'YouTube')
        b = self.child('second', '抖音')
        wait_for(lambda: snapshot()['pending'] == 2)
        with shared_slot('first', 'YouTube'):
            with shared_slot(platform='模型卸载'):
                self.assertEqual(snapshot()['active'], 1)
                self.assertFalse((self.root / 'second.entered').exists())
        wait_for(lambda: (self.root / 'second.entered').exists())
        self.release('second')
        self.assertEqual(b.wait(timeout=5), 0)

    def test_exception_releases_model_for_next_task(self):
        with self.assertRaisesRegex(RuntimeError, 'provider'):
            with shared_slot('bad', 'YouTube'):
                raise RuntimeError('provider')
        with shared_slot('next', '抖音'):
            self.assertEqual(snapshot()['active'], 1)

    def test_mcp_keeps_the_shared_store_override_without_copying_credentials(self):
        from services.douyin.mention_agent import mcp_environment
        with patch.dict(os.environ, {'SECRET_API_KEY': 'do-not-copy'}):
            env = mcp_environment()
        self.assertEqual(env['DOUYIN_STORE_DIR'], str(self.root))
        self.assertNotIn('SECRET_API_KEY', env)
