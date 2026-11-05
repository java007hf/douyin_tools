import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.youtube.task_queue import UnderstandingQueue


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('queue did not reach expected state')


class QueueTests(unittest.TestCase):
    def test_serial_fifo_and_recovery_of_pending_tasks(self):
        with tempfile.TemporaryDirectory(dir='cache') as directory:
            path = Path(directory) / 'queue.sqlite3'
            entered, release = threading.Event(), threading.Event()
            order = []
            def execute(identifier, url, progress):
                order.append(identifier)
                entered.set()
                if identifier == 'first':
                    release.wait(5)
                progress('processing')
                return {'title': identifier}
            queue = UnderstandingQueue(path, execute)
            try:
                queue.enqueue('first', 'url1')
                queue.start()
                self.assertTrue(entered.wait(3))
                queue.enqueue('second', 'url2')
                queue.enqueue('third', 'url3')
                self.assertEqual(queue.snapshot()['active'], 1)
                self.assertEqual(queue.snapshot()['pending'], 2)
                self.assertEqual(queue.get('second')['queue_position'], 1)
                self.assertEqual(queue.get('third')['queue_position'], 2)
                queue.close()
                release.set()
                queue.close(wait=True)
                self.assertEqual(order, ['first'])
                recovered = UnderstandingQueue(path, execute)
                try:
                    self.assertEqual(recovered.get('first')['status'], 'done')
                    self.assertEqual(recovered.snapshot()['pending'], 2)
                    recovered.start()
                    wait_for(lambda: recovered.get('third')['status'] == 'done')
                    self.assertEqual(order, ['first', 'second', 'third'])
                    self.assertEqual(recovered.get('second')['result']['title'], 'second')
                finally:
                    recovered.close(wait=True)
            finally:
                release.set()
                queue.close(wait=True)

    def test_failure_does_not_block_next_task_and_interrupted_tasks_are_not_replayed(self):
        with tempfile.TemporaryDirectory(dir='cache') as directory:
            path = Path(directory) / 'queue.sqlite3'
            def execute(identifier, url, progress):
                if identifier == 'bad':
                    raise RuntimeError('provider failed')
                return {'ok': True}
            queue = UnderstandingQueue(path, execute)
            queue.enqueue('interrupted', 'url0')
            queue.update('interrupted', status='running')
            queue.close()
            recovered = UnderstandingQueue(path, execute)
            try:
                self.assertEqual(recovered.get('interrupted')['status'], 'error')
                recovered.enqueue('bad', 'url1')
                recovered.enqueue('good', 'url2')
                recovered.start()
                wait_for(lambda: recovered.get('good')['status'] == 'done')
                self.assertEqual(recovered.get('bad')['error'], 'provider failed')
                self.assertEqual(recovered.snapshot()['active'], 0)
            finally:
                recovered.close(wait=True)
