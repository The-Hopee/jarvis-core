import unittest
from jarvis.agent_limits import capacity
from jarvis.config import Settings
from jarvis.coding import validate_plan

class AgentLimitsTests(unittest.TestCase):
    def test_hardware_and_manual_cap_bound_running_workers(self):
        settings=Settings()
        self.assertEqual(capacity(settings,cpus=12,available_mb=16000),4)
        self.assertEqual(capacity(settings,cpus=1,available_mb=16000),1)
        self.assertEqual(capacity(settings,cpus=12,available_mb=2500),1)
        self.assertEqual(capacity(Settings(agent_workers=2),cpus=12,available_mb=16000),2)

    def test_plan_can_exceed_four_tasks_but_not_have_only_one_worker(self):
        plan={'summary':'six helpers','tasks':[{'id':'a'+str(i),'goal':'Implement or verify','paths':['a'+str(i)+'.py'],'depends_on':[]} for i in range(6)]}
        self.assertEqual(len(validate_plan(plan)['tasks']),6)
        with self.assertRaises(Exception):validate_plan({**plan,'tasks':plan['tasks'][:1]})
