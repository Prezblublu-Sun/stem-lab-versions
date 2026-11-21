"""让 tests/ 之外的测试也用得上共用的夹具。

固定的验收都在 tests/ 下。自由代码的测试在 tests_free/ 和各插件自己的 tests/ 里，不进 FROZEN；
它们要的 data、lab、real_lab 这些夹具从这里拿到。
"""
from tests.conftest import (_fresh_process_state, data, lab, lab_repo, own_lab,  # noqa: F401
                            real_lab, real_own_lab, real_repo)
