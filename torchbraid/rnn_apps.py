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

# cython: profile=True
# cython: linetrace=True

import torch

from braid_vector import BraidVector
from rnn_braid_app import BraidApp

import sys

from mpi4py import MPI

class ForwardBraidApp(BraidApp):

  def __init__(self,comm,RNN_models,local_num_steps,hidden_size,num_layers,Tf,max_levels,max_iters,timer_manager):
    BraidApp.__init__(self,comm,local_num_steps,hidden_size,num_layers,Tf,max_levels,max_iters)

    self.RNN_models = RNN_models

    comm          = self.getMPIComm()
    my_rank       = self.getMPIComm().Get_rank()
    num_ranks     = self.getMPIComm().Get_size()

    # build up the core
    self.py_core = self.initCore()

    # force evaluation of gradients at end of up-cycle
    self.finalRelax()

    self.timer_manager = timer_manager
    self.use_deriv = False
  # end __init__

  def run(self,x):

    # run the braid solver
    with self.timer("runBraid"):
      # RNN_torchbraid_app.pyx -> runBraid()
      y = self.runBraid(x)

    # print("Rank %d ForwardBraidApp -> run() - end" % prefix_rank)

    #print('step bounds = ',self.getStepBounds())

    return y
  # end forward

  def timer(self,name):
    return self.timer_manager.timer("ForWD::"+name)

  def eval(self,g0,tstart,tstop,level,done,force_deriv=False):
    """
    Method called by "my_step" in braid. This is
    required to propagate from tstart to tstop, with the initial
    condition x. The level is defined by braid
    """

    # prefix_rank  = self.comm.Get_rank()
    # print("Rank",prefix_rank,"- ForwardBraidApp->eval() - tstart:",tstart,"tstop:",tstop,"level:",level)

    # there are two paths by which eval is called:
    #  1. x is a BraidVector: my step has called this method
    #  2. x is a torch tensor: called internally (probably at the behest
    #                          of the adjoint)

    t_h,t_c = g0.tensors()
    t_x = self.x # defined in rnn_braid_app.pyx line 69 in runBraid()
        # (1,14,28)

    # print("t_x: ",t_x, " Rank: %d" % prefix_rank)
    # print("t_h: ",t_h, " Rank: %d" % prefix_rank)
    # print("t_c: ",t_c, " Rank: %d" % prefix_rank)

    index = self.getLocalTimeStepIndex(tstart,tstop,level)
    _, (t_yh,t_yc) = self.RNN_models(t_x[:,index,:].unsqueeze(1),t_h,t_c)

       

    g0.replaceTensor(t_yh,0)
    g0.replaceTensor(t_yc,1)
  # end eval

# end ForwardBraidApp

##############################################################

"""
class BackwardBraidApp(BraidApp):

  def __init__(self,fwd_app,timer_manager):
    # call parent constructor
    BraidApp.__init__(self,fwd_app.getMPIData().getComm(),
                           fwd_app.local_num_steps,
                           fwd_app.Tf,
                           fwd_app.max_levels,
                           fwd_app.max_iters)

    self.fwd_app = fwd_app

    # build up the core
    self.py_core = self.initCore()

    # setup adjoint specific stuff
    self.fwd_app.setStorage(0)

    # reverse ordering for adjoint/backprop
    self.setRevertedRanks(1)

    self.timer_manager = timer_manager
  # end __init__

  def timer(self,name):
    return self.timer_manager.timer("BckWD::"+name)

  def run(self,x):

    with self.timer("runBraid"):
      f = self.runBraid(x)

    with self.timer("run::extra"):
      my_params = self.fwd_app.parameters()

      # this code is due to how braid decomposes the backwards problem
      # The ownership of the time steps is shifted to the left (and no longer balanced)
      first = 1
      if self.getMPIData().getRank()==0:
        first = 0

      # preserve the layerwise structure, to ease communication
      self.grads = [ [item.grad.clone() for item in sublist] for sublist in my_params[first:]]
      for m in self.fwd_app.layer_models:
         m.zero_grad()

    return f
  # end forward

  def eval(self,x,tstart,tstop,level,done):
    with self.timer("eval(level=%d)" % level):
      # we need to adjust the time step values to reverse with the adjoint
      # this is so that the renumbering used by the backward problem is properly adjusted
      (t_py,t_px),layer = self.fwd_app.getPrimalWithGrad(self.Tf-tstop,self.Tf-tstart,level)
  
      # t_px should have no gradient
      if not t_px.grad is None:
        t_px.grad.data.zero_()
  
      with self.timer("eval(level=%d):set_grads" % level):
        # play with the layers gradient to make sure they are on apprpriately
        for p in layer.parameters(): 
          if level==0:
            if not p.grad is None:
              p.grad.data.zero_()
          else:
            # if you are not on the fine level, compute n gradients
            p.requires_grad = False
  
      # perform adjoint computation
      t_x = x.tensor()
      t_py.backward(t_x,retain_graph=True)
  
      with self.timer("eval(level=%d):reset_grads" % level):
        for p in layer.parameters():
          p.requires_grad = True

    return BraidVector(t_px.grad,level) 
  # end eval

# end BackwardBraidApp
"""
