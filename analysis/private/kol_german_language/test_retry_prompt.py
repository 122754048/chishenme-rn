import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run_edit.py")
SPEC = importlib.util.spec_from_file_location("kol_german_run_edit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_minimal_language_prompt_contains_no_competing_instructions():
    prompt = MODULE.compile_prompt()["prompt"]
    assert prompt == "@Video1 将这个视频改为德语。"
