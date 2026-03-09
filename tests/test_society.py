import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_society import GeminiCliInvoker, deterministic_regression_guard


class SocietyTests(unittest.TestCase):
    def test_regression_guard_flags_removed_assertions(self):
        original = """
        @Test
        public void addsValues() {
            assertEquals(2, calculator.add(1, 1));
        }
        """
        candidate = """
        @Test
        public void addsValues() {
            calculator.add(1, 1);
        }
        """
        flags = deterministic_regression_guard(original, candidate, 'add', 'addsValues')
        self.assertIn('assertions_removed', flags)
        self.assertIn('empty_or_missing_assertions', flags)

    @mock.patch('agentic_society._is_windows', return_value=True)
    @mock.patch('agentic_society.shutil.which', return_value=r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
    @mock.patch('agentic_society.subprocess.run')
    def test_invoker_uses_powershell_env_bridge_on_windows(self, run_mock, _, __):
        run_mock.return_value = mock.Mock(returncode=0, stdout='candidate', stderr='')
        invoker = GeminiCliInvoker()

        with tempfile.TemporaryDirectory() as temp_dir:
            response, elapsed = invoker.invoke('generator', 'prompt text', Path(temp_dir), 'gemini')

        self.assertEqual('candidate', response)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', run_mock.call_args.args[0][0])
        self.assertEqual('gemini', json.loads(run_mock.call_args.kwargs['env']['AGONE_AGENT_COMMAND_JSON'])[0])
        self.assertEqual('prompt text', run_mock.call_args.kwargs['env']['AGONE_AGENT_PROMPT'])


if __name__ == '__main__':
    unittest.main()
