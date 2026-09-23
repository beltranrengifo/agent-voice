"""End-to-end wiring tests.

Each test here corresponds to a bug that actually shipped. They all drive the
real adapters and assert on what the stub Piper received, because every one of
these bugs survived a check that only looked at the code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fake_env import FakeInstall, assistant, user, tool_result  # noqa: E402


class WiringTest(unittest.TestCase):
    def setUp(self):
        self.inst = FakeInstall()

    def tearDown(self):
        self.inst.cleanup()

    # -- Claude Code adapter -------------------------------------------------

    def test_speaks_the_final_answer(self):
        t = self.inst.transcript([user(), assistant("Hola, esto es la respuesta final.")])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertEqual(len(self.inst.utterances), 1, "should speak exactly once")
        self.assertIn("respuesta final", self.inst.utterances[0])
        self.assertTrue(self.inst.playbacks, "synthesis happened but playback never ran")

    def test_speaks_prose_that_preceded_tool_calls(self):
        """A turn often ends on a tool call; the prose before it is the answer."""
        t = self.inst.transcript([
            user(),
            assistant("He terminado de revisarlo todo y funciona."),
            assistant(tools=True),
        ])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertTrue(self.inst.utterances, "prose before a trailing tool call was skipped")
        self.assertIn("funciona", self.inst.utterances[0])

    def test_silent_when_the_turn_has_no_prose(self):
        t = self.inst.transcript([user(), tool_result()])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertEqual(self.inst.utterances, [])

    def test_waits_for_a_transcript_still_being_written(self):
        """The hook can fire before the answer is flushed to disk."""
        import threading
        t = self.inst.transcript([user()])

        def finish_writing():
            import time, json
            time.sleep(0.6)
            with open(t, "a") as fh:
                fh.write(json.dumps(assistant("Respuesta que llega tarde al disco.")) + "\n")

        threading.Thread(target=finish_writing, daemon=True).start()
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertTrue(self.inst.utterances, "gave up before the transcript was written")

    def test_ignores_reentrant_stop_hook(self):
        t = self.inst.transcript([user(), assistant("No debería sonar.")])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": True})
        self.assertEqual(self.inst.utterances, [])

    # -- Codex adapter -------------------------------------------------------

    def test_codex_speaks_its_payload(self):
        self.inst.run_codex({
            "type": "agent-turn-complete",
            "last-assistant-message": "He corregido el error y los tests pasan.",
        })
        self.assertTrue(self.inst.utterances)
        self.assertIn("tests pasan", self.inst.utterances[0])

    def test_codex_ignores_other_events(self):
        self.inst.run_codex({"type": "some-other-event", "last-assistant-message": "No."})
        self.assertEqual(self.inst.utterances, [])

    # -- Shared gate ---------------------------------------------------------

    def test_off_means_silent(self):
        self.inst.run_cli("off")
        t = self.inst.transcript([user(), assistant("Esto no debe sonar.")])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertEqual(self.inst.utterances, [])

    def test_pause_means_silent_then_resume_speaks(self):
        self.inst.run_cli("pause")
        t = self.inst.transcript([user(), assistant("Primera, en pausa.")])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        self.assertEqual(self.inst.utterances, [])

        self.inst.run_cli("resume")
        t2 = self.inst.transcript([user(), assistant("Segunda, ya reanudado.")])
        self.inst.run_hook({"transcript_path": t2, "stop_hook_active": False})
        self.assertTrue(self.inst.utterances)

    def test_the_same_answer_is_not_spoken_twice(self):
        """Hosts can deliver one answer through two loaded copies of the plugin."""
        t = self.inst.transcript([user(), assistant("Una sola vez, por favor.")])
        payload = {"transcript_path": t, "stop_hook_active": False}
        self.inst.run_hook(payload)
        self.inst.run_hook(payload)
        self.assertEqual(len(self.inst.utterances), 1)

    # -- The portable entry point -------------------------------------------

    def test_speak_reads_stdin(self):
        self.inst.run_cli("speak", stdin="Cualquier agente puede usar esta entrada.")
        self.assertTrue(self.inst.utterances)
        self.assertIn("Cualquier agente", self.inst.utterances[0])

    def test_code_is_never_read_aloud(self):
        answer = (
            "He arreglado el bug.\n\n"
            "```python\n"
            "def secreto():\n"
            "    return 42\n"
            "```\n\n"
            "Los tests pasan todos ahora."
        )
        t = self.inst.transcript([user(), assistant(answer)])
        self.inst.run_hook({"transcript_path": t, "stop_hook_active": False})
        spoken = self.inst.utterances[0]
        self.assertIn("arreglado el bug", spoken)
        self.assertIn("tests pasan", spoken)
        self.assertNotIn("def secreto", spoken)
        self.assertNotIn("return 42", spoken)


if __name__ == "__main__":
    unittest.main(verbosity=2)
