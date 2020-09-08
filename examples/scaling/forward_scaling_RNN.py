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

import torch
import torch.nn as nn
import torch.nn.functional as F

# import torchbraid
import time

import getopt,sys
import argparse

# only print on rank==0
def root_print(rank,s):
  if rank==0:
    print(s)

class RNN_BasicBlock(nn.Module):
  def __init__(self, input_size, hidden_size, num_layers, timer_manager):
    super(RNN_BasicBlock, self).__init__()
    self.hidden_size = hidden_size
    self.num_layers = num_layers
    self.timer_manager = timer_manager

    torch.manual_seed(20)
    self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)

  def __del__(self):
    pass

  def forward(self, x, h_prev, c_prev):
    with self.timer_manager.timer("forward"): 
      h0 = h_prev
      c0 = c_prev
      _, (hn, cn) = self.lstm(x, (h0, c0))
      return _, (hn, cn)

class ODEBlock(nn.Module):
  def __init__(self,layer,dt):
    super(ODEBlock, self).__init__()

    self.dt = dt
    self.layer = layer

  def forward(self, x):
    return x + self.dt*self.layer(x)


def RNN_build_block_with_dim(input_size, hidden_size, num_layers, timer_manager):
  b = RNN_BasicBlock(input_size, hidden_size, num_layers, timer_manager) # channels = hidden_size
  return b

# def build_block_with_dim(channels,timer_manager):
#   b = BasicBlock(channels,timer_manager)
#   return b

def preprocess_input_data_serial_test(num_blocks, num_batch, batch_size, channels, sequence_length, input_size):
  torch.manual_seed(20)
  x = torch.randn(num_batch,batch_size,channels,sequence_length,input_size)

  data_all = []
  x_block_all = []
  for i in range(len(x)):
    image = x[i].reshape(-1, sequence_length, input_size)
    images_split = torch.chunk(image, num_blocks, dim=1)
    seq_split = []
    for blk in images_split:
      seq_split.append(blk)
    x_block_all.append(seq_split)
    data_all.append(image)

  return data_all, x_block_all

def preprocess_distribute_input_data_parallel(rank,num_procs,num_batch,batch_size,channels,sequence_length,input_size):
  if rank == 0:
    torch.manual_seed(20)
    x = torch.randn(num_batch,batch_size,channels,sequence_length,input_size)

    # x_block_all[total_images][total_blocks]
    x_block_all = []
    for i in range(len(x)):
      image = x[i].reshape(-1,sequence_length,input_size)
      data_split = torch.chunk(image, num_procs, dim=1)
      seq_split = []
      for blk in data_split:
        seq_split.append(blk)
      x_block_all.append(seq_split)

    x_block = []
    for image_id in range(len(x_block_all)):
      x_block.append(x_block_all[image_id][rank])

    for block_id in range(1,num_procs):
      x_block_tmp = []
      for image_id in range(len(x_block_all)):
        x_block_tmp.append(x_block_all[image_id][block_id])
      comm.send(x_block_tmp,dest=block_id,tag=20)

    return x_block
  
  else:
    x_block = comm.recv(source=0,tag=20)

    return x_block

def compute_levels(num_steps,min_coarse_size,cfactor): 
  from math import log, floor 
  
  # we want to find $L$ such that ( max_L min_coarse_size*cfactor**L <= num_steps)
  levels =  floor(log(num_steps/min_coarse_size,cfactor))+1 

  if levels<1:
    levels = 1
  return levels
# end compute levels

# some default input arguments
###########################################

my_rank   = 0
# some default input arguments
###########################################
max_levels      = 3
max_iters       = 1
local_num_steps = 5
# For CNN
###########################################
# channels        = 16
# images          = 10
# image_size      = 256

# For RNN
###########################################
channels        = 1
images          = 10
image_size      = 28

###########################################
Tf              = 2.0
run_serial      = False
print_level     = 0
nrelax          = 1
cfactor         = 2

# parse the input arguments
###########################################

parser = argparse.ArgumentParser()
parser.add_argument("steps",type=int,help="total numbere of steps, must be product of proc count")
parser.add_argument("--levels",    type=int,  default=max_levels,   help="maximum number of Layer-Parallel levels")
parser.add_argument("--iters",     type=int,   default=max_iters,   help="maximum number of Layer-Parallel iterations")
parser.add_argument("--channels",  type=int,   default=channels,    help="number of convolutional channels")
parser.add_argument("--images",    type=int,   default=images,      help="number of images")
parser.add_argument("--pxwidth",   type=int,   default=image_size,  help="Width/height of images in pixels")
parser.add_argument("--verbosity", type=int,   default=print_level, help="The verbosity level, 0 - little, 3 - lots")
parser.add_argument("--cfactor",   type=int,   default=cfactor,     help="The coarsening factor")
parser.add_argument("--nrelax",    type=int,   default=nrelax,      help="The number of relaxation sweeps")
parser.add_argument("--tf",        type=float, default=Tf,          help="final time for ODE")
parser.add_argument("--serial",  default=run_serial, action="store_true", help="Run the serial version (1 processor only)")
parser.add_argument("--optstr",  default=False,      action="store_true", help="Output the options string")
args = parser.parse_args()
   
# determine the number of steps
num_steps       = args.steps

# user wants us to determine how many levels
if args.levels==-1:
  min_coarse_size = 4
  args.levels = compute_levels(num_steps,min_coarse_size,args.cfactor)
# end args.levels

if args.levels:    max_levels  = args.levels
if args.iters:     max_iters   = args.iters
if args.channels:  channels    = args.channels
if args.images:    images      = args.images
if args.pxwidth:   image_size  = args.pxwidth
if args.verbosity: print_level = args.verbosity
if args.cfactor:   cfactor     = args.cfactor
if args.nrelax :   nrelax      = args.nrelax
if args.tf:        Tf          = args.tf
if args.serial:    run_serial  = args.serial


class Options:
  def __init__(self):
    self.num_steps   = args.steps
    self.max_levels  = args.levels
    self.max_iters   = args.iters
    self.channels    = args.channels
    self.images      = args.images
    self.image_size  = args.pxwidth
    self.print_level = args.verbosity
    self.cfactor     = args.cfactor
    self.nrelax      = args.nrelax
    self.Tf          = args.tf
    self.run_serial  = args.serial

  def __str__(self):
    s_net = 'net:ns=%04d_ch=%04d_im=%05d_is=%05d_Tf=%.2e' % (self.num_steps,
                                                             self.channels,
                                                             self.images,
                                                             self.image_size,
                                                             self.Tf)
    s_alg = '__alg:ml=%02d_mi=%02d_cf=%01d_nr=%02d' % (self.max_levels,
                                                       self.max_iters,
                                                       self.cfactor,
                                                       self.nrelax)
    return s_net+s_alg

opts_obj = Options()

if args.optstr==True:
  if my_rank==0:
    print(opts_obj)
  sys.exit(0)

import torchbraid
from mpi4py import MPI

comm = MPI.COMM_WORLD
my_rank   = comm.Get_rank()
last_rank = comm.Get_size()-1

local_num_steps = int(num_steps/comm.Get_size())


# the number of steps is not valid, then return
if not args.steps % comm.Get_size()==0:
  if my_rank==0:
    print('error in <steps> argument, must be a multiple of proc count: %d' % comm.Get_size())
    parser.print_help()
  sys.exit(0)
# end if not args.steps

if args.serial==True and comm.Get_size()!=1:
  if my_rank==0:
    print('The <--serial> optional argument, can only be run in serial (proc count: %d)' % comm.Get_size())
    parser.print_help()
  sys.exit(0)
# end if not args.steps

print(opts_obj)

# build the neural network
###########################################

# define the neural network parameters
timer_manager = torchbraid.utils.ContextTimerManager()
# basic_block = lambda: build_block_with_dim(channels,timer_manager)

# build parallel information
dt        = Tf/num_steps

# set hyper-parameters for RNN
###########################################
sequence_length = 28 # total number of time steps for each sequence
input_size = 28 # input size for each time step in a sequence
hidden_size = 20
num_layers = 2
batch_size = 1

# generate randomly initialized data
###########################################
num_batch = int(images / batch_size)

# In case of MNIST data is used
###########################################
# for i, (images, labels) in enumerate(train_loader):
#   images = images.reshape(-1, sequence_length, input_size)
# train_loader.images: torch.Size([batch_size, channels, sequence_length, input_size])
# train_loader.images.reshape(-1, sequence_length, input_size): torch.Size([batch_size, sequence_length, input_size])

# do forward propagation (in parallel)
# x = torch.randn(images,channels,image_size,image_size)

root_print(my_rank,'Number of steps: %d' % num_steps)

if run_serial:
  root_print(my_rank,'Running PyTorch: %d' % comm.Get_size())

  # build the neural network
  ###########################################
  basic_block = lambda: RNN_build_block_with_dim(input_size, hidden_size, num_layers, timer_manager)
  serial_rnn = basic_block()
  num_blocks = 2 # equivalent to the num_procs variable used for parallel implementation
  print("num_blocks (num_procs): ",num_blocks)
  image_all, x_block_all = preprocess_input_data_serial_test(num_blocks,num_batch,batch_size,channels,sequence_length,input_size)

  # layers = [basic_block() for i in range(num_steps)]
  # serial_nn = torch.nn.Sequential(*layers)

  with torch.no_grad(): 
    t0_parallel = time.time()
    # y_serial = serial_nn(x)

    # for i in range(len(image_all)):
    for i in range(1):

      # Serial ver. 1
      ###########################################
      y_serial_hn = torch.zeros(num_layers, image_all[i].size(0), hidden_size)
      y_serial_cn = torch.zeros(num_layers, image_all[i].size(0), hidden_size)

      _, (y_serial_hn, y_serial_cn) = serial_rnn(image_all[i],y_serial_hn,y_serial_cn)

      # Serial ver.2
      ###########################################
      for j in range(num_blocks):
        if j == 0:
          y_serial_prev_hn = torch.zeros(num_layers, x_block_all[i][j].size(0), hidden_size)
          y_serial_prev_cn = torch.zeros(num_layers, x_block_all[i][j].size(0), hidden_size)

        _, (y_serial_prev_hn, y_serial_prev_cn) = serial_rnn(x_block_all[i][j],y_serial_prev_hn,y_serial_prev_cn)

      print(" ")
      print(" ")
      print("Serial version 1 - y_serial_hn size: ", y_serial_hn.shape)
      print(y_serial_hn.data[0])
      print(y_serial_hn.data[1])
      print("Serial version 2 - y_serial_prev_hn size: ", y_serial_prev_hn.shape)
      print(y_serial_prev_hn.data[0])
      print(y_serial_prev_hn.data[1])

      print(" ")
      print(" ")
      print("Serial version 1 - y_serial_cn size: ", y_serial_cn.shape)
      print(y_serial_cn.data[0])
      print(y_serial_cn.data[1])
      print("Serial version 2 - y_serial_prev_cn size: ", y_serial_prev_cn.shape)
      print(y_serial_prev_cn.data[0])
      print(y_serial_prev_cn.data[1])

    tf_parallel = time.time()

  timer_str = timer_manager.getResultString()
  print(timer_str)

else:
  root_print(my_rank,'Running TorchBraid: %d' % comm.Get_size())
  # build the parallel neural network
  # parallel_nn   = torchbraid.LayerParallel(comm,basic_block,local_num_steps,Tf,max_levels=max_levels,max_iters=max_iters)
  
  basic_block_parallel = lambda: RNN_build_block_with_dim(input_size, hidden_size, num_layers, timer_manager)
  num_procs = comm.Get_size()
  print("num_procs: ",num_procs)
  # preprocess and distribute input data
  ###########################################
  x_block = preprocess_distribute_input_data_parallel(my_rank,num_procs,num_batch,batch_size,channels,sequence_length,input_size)

  max_levels = 1 # for testing parallel rnn
  max_iters = 1 # for testing parallel rnn
  num_steps = 1
  # RNN_parallel.py -> RNN_Parallel() class
  parallel_nn = torchbraid.RNN_Parallel(comm,basic_block_parallel,num_steps,hidden_size,num_layers,Tf,max_levels=max_levels,max_iters=max_iters)

  parallel_nn.setPrintLevel(print_level)
  parallel_nn.setSkipDowncycle(True)
  parallel_nn.setCFactor(cfactor)
  parallel_nn.setNumRelax(nrelax)
  #parallel_nn.setNumRelax(nrelax,level=0)

  print("x_block len: ",len(x_block))

  t0_parallel = time.time()

  # for i in range(len(x_block)):
  for i in range(1):

    print("Input image %d - parallel version" % i)
    print("Rank", my_rank, "- x_block size:", x_block[i].size())
    print("Rank", my_rank, "- x_block:", x_block[i])
    # print(x_block[i])

    print("Rank %d START forward pass" % my_rank)

    y_parallel = parallel_nn(x_block[i])

    (y_parallel_hn, y_parallel_cn) = y_parallel

    comm.barrier()

    print("Rank %d FINISHED forward pass" % my_rank)
    
    if my_rank == last_rank:
      print(" ")
      print(" ")
      print("Parallel version - y_parallel_hn size: ", y_parallel_hn.shape)
      print(y_parallel_hn.data[0])
      print(y_parallel_hn.data[1])
      print(" ")
      print(" ")
      print("Parallel version - y_parallel_cn size: ", y_parallel_cn.shape)
      print(y_parallel_cn.data[0])
      print(y_parallel_cn.data[1])


  # y_parallel = parallel_nn(x)
  # comm.barrier()
  tf_parallel = time.time()
  comm.barrier()

  timer_str = parallel_nn.getTimersString()
  if my_rank==0:
    print(timer_str)

  timer_str = timer_manager.getResultString()
  if my_rank==0:
    print(timer_str)

  # check serial case
  # serial_nn = parallel_nn.buildSequentialOnRoot()
  # y_parallel = parallel_nn.getFinalOnRoot()
  
  # if my_rank==0:
    # with torch.no_grad():
      # y_serial = serial_nn(x)
    # print('error = ',torch.norm(y_serial-y_parallel)/torch.norm(y_serial))

    # print('RNN hidden layer 1 - error = ',torch.norm(y_serial_prev_hn.data[0]-y_parallel_hn.data[0])/torch.norm(y_serial_prev_hn.data[0]))
    # print('RNN hidden layer 2 - error = ',torch.norm(y_serial_prev_hn.data[1]-y_parallel_hn.data[1])/torch.norm(y_serial_prev_hn.data[1]))
# end if not run_serial


root_print(my_rank,'Run    Time: %.6e' % (tf_parallel-t0_parallel))
