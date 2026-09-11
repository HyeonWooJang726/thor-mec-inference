import unittest
from event_analysis import occupancy,at_times,temporal_periods
class EventTests(unittest.TestCase):
 def test_clipping_and_overlap(self):
  d,m=occupancy([(-10,20),(10,30),(80,110)],0,100,2)
  self.assertEqual(d,{0:50,1:40,2:10});self.assertAlmostEqual(m,.6)
 def test_touch_and_empty(self):
  self.assertEqual(at_times([(0,10),(10,20)],[0,9,10,20]),[1,1,1,0])
  self.assertEqual(occupancy([],0,100,2),({0:100},0))
 def test_capacity_rejected(self):
  with self.assertRaises(AssertionError):occupancy([(0,10)]*3,0,20,2)
 def test_prior_includes_not_yet_ready(self):
  rs=[dict(frame_id=0,a_ns=0,r_ns=40_000_000,s_ns=50_000_000,c_ns=60_000_000),
      dict(frame_id=1,a_ns=33_333_333,r_ns=35_000_000,s_ns=36_000_000,c_ns=37_000_000)]
  p=temporal_periods(rs,0,2)
  self.assertEqual(p[0]['boundary_prior_pre_ready'],1)
  self.assertEqual(p[0]['next_first_ready_prior_pre_ready'],1)
  self.assertEqual(p[0]['next_first_ready_prior_waiting'],0)
  self.assertEqual(p[1]['boundary_prior_unfinished'],0)
 def test_two_active_carryover(self):
  rs=[dict(frame_id=0,a_ns=0,r_ns=1,s_ns=2,c_ns=50_000_000),dict(frame_id=0,a_ns=0,r_ns=2,s_ns=3,c_ns=40_000_000)]
  p=temporal_periods(rs,0,1)[0]
  self.assertEqual(p['boundary_prior_active'],2);self.assertEqual(p['boundary_prior_waiting'],0)
if __name__=='__main__':unittest.main()
