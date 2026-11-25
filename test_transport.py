"""Transport reliability checks using temporary files and a fake helper only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import bridge


class TransportTests(unittest.TestCase):
    def test_two_callers_cannot_overwrite_an_in_flight_command(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / 'status.json').write_text('{}', encoding='utf-8')
            first_seen = threading.Event()
            permit_response = threading.Event()
            stop = threading.Event()
            results = {}
            errors = []

            def fake_helper():
                last = ''
                while not stop.is_set():
                    try:
                        command = json.loads((runtime / 'command.json').read_text())
                    except (OSError, ValueError):
                        time.sleep(0.005)
                        continue
                    if command['id'] == last:
                        time.sleep(0.005)
                        continue
                    if command['name'] == 'first':
                        first_seen.set()
                        permit_response.wait(2)
                    response = {'id':command['id'],'ok':True,'result':{'name':command['name']}}
                    tmp = runtime / 'fake-response.tmp'
                    tmp.write_text(json.dumps(response), encoding='utf-8')
                    tmp.replace(runtime / 'response.json')
                    last = command['id']

            def caller(name):
                try:
                    results[name] = bridge.call(name, {}, timeout_seconds=2)
                except Exception as error:
                    errors.append(error)

            helper = threading.Thread(target=fake_helper)
            helper.start()
            one = threading.Thread(target=caller, args=('first',))
            two = threading.Thread(target=caller, args=('second',))
            with patch.object(bridge, 'RUNTIME', runtime):
                try:
                    one.start()
                    self.assertTrue(first_seen.wait(1))
                    two.start()
                    time.sleep(0.2)
                    queued = json.loads((runtime / 'command.json').read_text())
                    self.assertEqual(queued['name'], 'first', 'second caller overwrote a request whose response is still pending')
                finally:
                    permit_response.set()
                    one.join(3)
                    two.join(3)
                    stop.set()
                    helper.join(2)
            self.assertEqual(errors, [])
            self.assertEqual(results, {'first':{'name':'first'},'second':{'name':'second'}})

    def test_session_runtime_paths_are_distinct_and_shared_by_modules(self):
        import runtime_context
        import interactive_agent
        import launch_stdio
        root = Path('C:/fake-service')
        self.assertNotEqual(runtime_context.session_runtime(root, 1), runtime_context.session_runtime(root, 2))
        self.assertEqual(bridge.RUNTIME, runtime_context.RUNTIME)
        self.assertEqual(interactive_agent.RUNTIME, runtime_context.RUNTIME)
        self.assertEqual(launch_stdio.RUNTIME, runtime_context.RUNTIME)
        self.assertEqual(runtime_context.RUNTIME.name, f'session-{runtime_context.current_session_id()}')

    def test_request_mutex_timeout_is_bounded(self):
        import runtime_context
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            acquired = threading.Event()
            release = threading.Event()
            def owner():
                with runtime_context.request_lock(runtime, 1):
                    acquired.set()
                    release.wait(2)
            thread = threading.Thread(target=owner)
            thread.start()
            try:
                self.assertTrue(acquired.wait(1))
                start = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with runtime_context.request_lock(runtime, .1):
                        self.fail('lock unexpectedly acquired')
                self.assertLess(time.monotonic()-start, .6)
            finally:
                release.set()
                thread.join(2)
            with runtime_context.request_lock(runtime, .5):
                pass

    def test_abandoned_request_mutex_is_recovered(self):
        import runtime_context
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            source = '''import os,sys
from pathlib import Path
import runtime_context as rc
with rc.request_lock(Path(sys.argv[1]),2):
 print("locked",flush=True)
 sys.stdin.readline()
 os._exit(0)
'''
            child = subprocess.Popen([sys.executable,'-B','-c',source,str(runtime)],cwd=Path(__file__).parent,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            handle = None
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                # Keep the named object alive across the owner's exit.
                handle = runtime_context.open_named_mutex(runtime_context.request_mutex_name(runtime))
                child.stdin.write('exit\n')
                child.stdin.flush()
                self.assertEqual(child.wait(timeout=3),0)
                with runtime_context.request_lock(runtime,.5) as abandoned:
                    self.assertTrue(abandoned)
            finally:
                if handle is not None:
                    runtime_context.close_mutex(handle)
                if child.poll() is None:
                    child.stdin.close()
                    child.wait(timeout=3)
                if not child.stdin.closed:
                    child.stdin.close()
                child.stdout.close()
                child.stderr.close()

    def test_two_processes_share_request_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime/'status.json').write_text('{}', encoding='utf-8')
            stop = threading.Event()

            def fake_helper():
                last = ''
                while not stop.is_set():
                    try:
                        command = json.loads((runtime/'command.json').read_text())
                    except (OSError, ValueError):
                        time.sleep(.005)
                        continue
                    if command['id'] == last:
                        time.sleep(.005)
                        continue
                    time.sleep(.1)
                    result = {'id':command['id'],'ok':True,'result':{'name':command['name']}}
                    temporary = runtime/'fake-response.tmp'
                    temporary.write_text(json.dumps(result), encoding='utf-8')
                    temporary.replace(runtime/'response.json')
                    last = command['id']

            helper = threading.Thread(target=fake_helper)
            helper.start()
            source = '''import json,sys
from pathlib import Path
import bridge
bridge.RUNTIME=Path(sys.argv[1])
print(json.dumps(bridge.call(sys.argv[2],{},timeout_seconds=3)),flush=True)
'''
            children = []
            try:
                for name in ('process-one', 'process-two'):
                    children.append((name, subprocess.Popen([sys.executable,'-B','-c',source,str(runtime),name],cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)))
                for name, child in children:
                    output, error = child.communicate(timeout=5)
                    self.assertEqual(child.returncode,0,error)
                    self.assertEqual(json.loads(output),{'name':name})
            finally:
                stop.set()
                helper.join(2)
                for _, child in children:
                    if child.poll() is None:
                        child.wait(timeout=5)

    def test_bridge_error_releases_request_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime/'status.json').write_text('{}', encoding='utf-8')
            with patch.object(bridge,'RUNTIME',runtime), patch.object(bridge,'read_response',side_effect=RuntimeError('fake helper failure')):
                with self.assertRaisesRegex(RuntimeError,'fake helper failure'):
                    bridge.call('first',{},timeout_seconds=.5)
            result = []
            def next_thread():
                with patch.object(bridge,'RUNTIME',runtime), patch.object(bridge,'read_response',return_value={'ok':True}):
                    result.append(bridge.call('second',{},timeout_seconds=.5))
            thread = threading.Thread(target=next_thread)
            thread.start()
            thread.join(1)
            self.assertEqual(result,[{'ok':True}])


if __name__ == '__main__':
    unittest.main()
