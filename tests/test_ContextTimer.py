#@HEADER
# ************************************************************************
# 
#                        Torchbraid v. 0.1
# 
# Copyright 2020 National Technology & Engineering Solutions of Sandia, LLC 
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S. 
# Government retains certain rights in this software.
# 
# Torchbraid is licensed under 3-clause BSD terms of use:
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
# 
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
# 
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
# 
# 3. Neither the name National Technology & Engineering Solutions of Sandia, 
# LLC nor the names of the contributors may be used to endorse or promote 
# products derived from this software without specific prior written permission.
# 
# Questions? Contact Eric C. Cyr (eccyr@sandia.gov)
# 
# ************************************************************************
#@HEADER

import unittest
import faulthandler
faulthandler.enable()

import time
import torchbraid.utils as utils

class TestContextTimer(unittest.TestCase):

  def test_ContextTiming_exception(self):
     mgr = utils.ContextTimerManager()
     clock = mgr.timer("hello")
     clock_timing_in_context = None

     caught = False
     try:
       with clock:
         clock_timing_in_context = clock.isTiming() 
         time.sleep(0.10) 
         raise Exception('Test')
       print('exception raised')
     except:
       caught = True

     self.assertTrue(caught)

  def test_ContextTiming(self):

     comm = None
     mgr = utils.ContextTimerManager()
     clock = mgr.timer("hello")

     self.assertTrue(not clock.isTiming())
     self.assertTrue(clock.getName()=="hello")
     self.assertTrue(len(clock.getTimes())==0)

     for i in range(5):
       clock_timing_in_context = None
       with clock:
         clock_timing_in_context = clock.isTiming() 
         time.sleep(0.10) 
       self.assertTrue(clock_timing_in_context)

     self.assertTrue(not clock.isTiming())
     self.assertTrue(clock.getName()=="hello")
     self.assertTrue(len(clock.getTimes())==5)

     self.assertTrue(len(mgr.getTimers())==1)

     for i in range(5):
       clock_timing_in_context = None
       with mgr.timer("cat") as clock_2:
         clock_timing_in_context = clock_2.isTiming() 
         time.sleep(0.10) 
         clock_save = clock_2
       self.assertTrue(clock_timing_in_context)

     self.assertTrue(not clock_save.isTiming())
     self.assertTrue(clock_save.getName()=="cat")
     self.assertTrue(len(clock_save.getTimes())==5)

     self.assertTrue(len(mgr.getTimers())==2)

     print(mgr.getResultString())
  # end test_ContextTiming(self):
# end TestTimerContext

if __name__ == '__main__':
  unittest.main()
