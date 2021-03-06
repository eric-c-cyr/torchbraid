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

import numpy as np
import torch.autograd
import torchbraid.utils as utils
import traceback

from mpi4py import MPI

class BraidFunction(torch.autograd.Function):

  @staticmethod
  def forward(ctx, fwd_app, bwd_app, x, h,c, *params):

    # copy the input to all processors (ensure consistency)
    comm = fwd_app.getMPIComm()
    with fwd_app.timer("func:precomm"):
      shape = comm.bcast((h.size(),c.size()),root=0)

    # setup context
    ctx.fwd_app = fwd_app
    ctx.bwd_app = bwd_app
    ctx.save_for_backward(x, h,c, *params)

    fwd_app.setShape(shape)
    bwd_app.setShape(shape)

    h_c = (h,c)

    result = fwd_app.run(x,h_c)

    return result

  @staticmethod
  def backward(ctx, grad_hn, grad_cn):
    comm          = ctx.bwd_app.getMPIComm()
    my_rank       = ctx.bwd_app.getMPIComm().Get_rank()
    num_ranks     = ctx.bwd_app.getMPIComm().Get_size()

    # copy the input to the final processor (where iter time integration begins)
    with ctx.bwd_app.timer("func:precomm"):
      if num_ranks>1:
        if my_rank==num_ranks-1: 
          hn_cn = torch.stack([grad_hn,grad_cn])
          req = comm.Irecv(hn_cn.numpy(),source=0,tag=22)
          req.Wait()

          grad_hn = hn_cn[0]
          grad_cn = hn_cn[1]

        if my_rank==0:
          hn_cn = torch.stack([grad_hn,grad_cn])
          comm.Isend(hn_cn.numpy(),dest=num_ranks-1,tag=22)
      # end if num_ranks
    # end with

    with ctx.bwd_app.timer("func:run"):
      if my_rank==num_ranks-1:
        result = ctx.bwd_app.run((grad_hn,grad_cn))
      else:
        result = ctx.bwd_app.run(None)

    with ctx.bwd_app.timer("func:postrun"):
      # pack up the buffer, and then send it out
      buf_size = utils.buffer_size(ctx.bwd_app.grads)
      src_buf = utils.pack_buffer(ctx.bwd_app.grads)
      dst_buf = np.zeros(buf_size)

      req = comm.Iallreduce(src_buf,dst_buf,MPI.SUM)

      # grad_input follows the input to forward: fwd_app, bwd_app, x, params
      grad_input = (None,None) 

      if ctx.needs_input_grad[2]: grad_input += (ctx.fwd_app.x.grad,)
      else: grad_input += (None,) # x

      if result is not None:
        if ctx.needs_input_grad[3]: grad_input += (result[0],) # h
        else: grad_input += (None,) # h

        if ctx.needs_input_grad[4]: grad_input += (result[1],) # c
        else: grad_input += (None,) # c
      else: 
        grad_input += (None,) # h
        grad_input += (None,) # c

      # with for communication to complete
      MPI.Request.Wait(req) 
      utils.unpack_buffer(ctx.bwd_app.grads,dst_buf)

      # setup the return value (perversely grad_input)
      for grad_needed,g in zip(ctx.needs_input_grad[5:],ctx.bwd_app.grads):
        if grad_needed:
          grad_input += (g,)
        else:
          grad_input += (None,)
    # end with timer

    return grad_input
