"""Repair type corrections preserve the actual module interface contract."""
import unittest
from agent.core.interface import check_interface_result
from agent.core.task import TaskSpec
from agent.prompts.builder import assemble_messages
from agent.prompts.context import messages_hash

INTERFACE = 'module Sample(input a, output q);'
TASK = TaskSpec.from_text('test', 'Implement the declared module.', INTERFACE)


class RepairInterfacePromptTests(unittest.TestCase):
    def test_first_prompt_remains_byte_identical_to_before_clarification(self):
        messages, _ = assemble_messages(TASK, style='repair')
        # Captured from 92ed389 before the repair-only clarification.
        self.assertEqual(messages_hash(messages),
                         '73fbf61915b8bbc0bdcfcc986165f4705f1b1502e7d49acd8b0bd0d69bede3fd')

    def test_type_permission_is_only_in_repair_and_keeps_explicit_task_constraints(self):
        initial, _ = assemble_messages(TASK, style='repair')
        repaired, _ = assemble_messages(TASK, style='repair', feedback='compiler failure',
                                        parent_code=INTERFACE+' endmodule')
        self.assertEqual(initial[0], repaired[0])
        self.assertNotIn('允许根据自身编译诊断', initial[-1]['content'])
        self.assertIn('允许根据自身编译诊断', repaired[-1]['content'])
        self.assertIn('遵守题面明确指定的类型约束', repaired[-1]['content'])
        self.assertIn('模块名、端口名、方向、位宽和顺序须保持', repaired[-1]['content'])

    def test_variable_type_fix_passes_interface_but_name_direction_width_still_fail(self):
        for var_type in ('reg', 'logic'):
            code=f'module Sample(input a, output {var_type} q); always @* q=a; endmodule'
            self.assertEqual(check_interface_result(code, INTERFACE).status, 'ok')
        for code in ('module Sample(input a, output reg wrong); endmodule',
                     'module Sample(input a, input q); endmodule',
                     'module Sample(input a, output reg [1:0] q); endmodule'):
            self.assertTrue(check_interface_result(code, INTERFACE).blocking)
