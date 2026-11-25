"""Lifecycle regression checks; never issue a window-management command."""
import inspect
import tempfile
import unittest
from pathlib import Path

import interactive_agent as agent


class LifecycleTests(unittest.TestCase):
    def test_unverified_pid_is_never_a_process_termination_target(self):
        self.assertNotIn('taskkill', inspect.getsource(agent))

    def test_named_mutex_allows_only_one_helper_for_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            first = agent.acquire_agent_mutex(Path(directory))
            self.assertIsNotNone(first)
            try:
                second = agent.acquire_agent_mutex(Path(directory))
                self.assertIsNone(second)
            finally:
                agent.release_agent_mutex(first)

    def test_mutex_is_released_when_owner_closes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            first = agent.acquire_agent_mutex(Path(directory))
            self.assertIsNotNone(first)
            agent.release_agent_mutex(first)
            second = agent.acquire_agent_mutex(Path(directory))
            self.assertIsNotNone(second)
            agent.release_agent_mutex(second)

    def test_existing_command_id_is_skipped_at_helper_start(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / 'command.json'
            command.write_text('{"id":"stale-request","name":"close_window","arguments":{"handle":123}}', encoding='utf-8')
            self.assertEqual(agent.existing_command_id(command), 'stale-request')
            command.write_text('incomplete', encoding='utf-8')
            self.assertEqual(agent.existing_command_id(command), '')


if __name__ == '__main__':
    unittest.main()
