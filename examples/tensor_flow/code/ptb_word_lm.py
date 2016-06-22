# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Example / benchmark for building a PTB LSTM model.

Trains the model described in:
(Zaremba, et. al.) Recurrent Neural Network Regularization
http://arxiv.org/abs/1409.2329

There are 3 supported model configurations:
===========================================
| config | epochs | train | valid  | test
===========================================
| small  | 13     | 37.99 | 121.39 | 115.91
| medium | 39     | 48.45 |  86.16 |  82.07
| large  | 55     | 37.87 |  82.62 |  78.29
The exact results may vary depending on the random initialization.

The hyperparameters used in the model:
- init_scale - the initial scale of the weights
- learning_rate - the initial value of the learning rate
- max_grad_norm - the maximum permissible norm of the gradient
- num_layers - the number of LSTM layers
- num_steps - the number of unrolled steps of LSTM
- hidden_size - the number of LSTM units
- max_epoch - the number of epochs trained with the initial learning rate
- max_max_epoch - the total number of epochs for training
- keep_prob - the probability of keeping weights in the dropout layer
- lr_decay - the decay of the learning rate for each epoch after "max_epoch"
- batch_size - the batch size

The data required for this example is in the data/ dir of the
PTB dataset from Tomas Mikolov's webpage:

$ wget http://www.fit.vutbr.cz/~imikolov/rnnlm/simple-examples.tgz
$ tar xvf simple-examples.tgz

To run:

$ python ptb_word_lm.py --data_path=simple-examples/data/

"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time

import numpy as np
import tensorflow as tf

import sys
import os
import json
sys.path.insert(0, os.path.abspath('..'))
from code import reader

flags = tf.flags
logging = tf.logging

flags.DEFINE_string(
    "model", "small",
    "A type of model. Possible options are: small, medium, large.")
flags.DEFINE_string("data_path", None, "data_path")
flags.DEFINE_string("generate", False, "Whether or not to emit new sentence")
flags.DEFINE_string("model_path_prefix", None, "model_path_prefix")
FLAGS = flags.FLAGS


class PTBModel(object):
  """The PTB model."""

  def __init__(self, is_training, config):
    self.batch_size = batch_size = config.batch_size
    self.num_steps = num_steps = config.num_steps
    size = config.hidden_size
    vocab_size = config.vocab_size

    self._input_data = tf.placeholder(tf.int32, [batch_size, num_steps])
    self._targets = tf.placeholder(tf.int32, [batch_size, num_steps])
    self._weights = tf.placeholder(tf.float32, [batch_size * num_steps])

    # Slightly better results can be obtained with forget gate biases
    # initialized to 1 but the hyperparameters of the model would need to be
    # different than reported in the paper.
    lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(size, forget_bias=0.0)
    if is_training and config.keep_prob < 1:
      lstm_cell = tf.nn.rnn_cell.DropoutWrapper(
          lstm_cell, output_keep_prob=config.keep_prob)
    cell = tf.nn.rnn_cell.MultiRNNCell([lstm_cell] * config.num_layers)

    self._initial_state = cell.zero_state(batch_size, tf.float32)

    with tf.device("/cpu:0"):
      embedding = tf.get_variable("embedding", [vocab_size, size])
      inputs = tf.nn.embedding_lookup(embedding, self._input_data)

    if is_training and config.keep_prob < 1:
      inputs = tf.nn.dropout(inputs, config.keep_prob)

    # Simplified version of tensorflow.models.rnn.rnn.py's rnn().
    # This builds an unrolled LSTM for tutorial purposes only.
    # In general, use the rnn() or state_saving_rnn() from rnn.py.
    #
    # The alternative version of the code below is:
    #
    # from tensorflow.models.rnn import rnn
    # inputs = [tf.squeeze(input_, [1])
    #           for input_ in tf.split(1, num_steps, inputs)]
    # outputs, state = rnn.rnn(cell, inputs, initial_state=self._initial_state)
    outputs = []
    state = self._initial_state
    with tf.variable_scope("RNN"):
      for time_step in range(num_steps):
        if time_step > 0: tf.get_variable_scope().reuse_variables()
        (cell_output, state) = cell(inputs[:, time_step, :], state)
        outputs.append(cell_output)

    output = tf.reshape(tf.concat(1, outputs), [-1, size])
    softmax_w = tf.get_variable("softmax_w", [size, vocab_size])
    softmax_b = tf.get_variable("softmax_b", [vocab_size])
    logits = tf.matmul(output, softmax_w) + softmax_b
    loss = tf.nn.seq2seq.sequence_loss_by_example(
        [logits],
        [tf.reshape(self._targets, [-1])],
        [self._weights])
    self._cost = cost = tf.reduce_sum(loss) / batch_size
    self._final_state = state
    self._logits = logits
    self._probs = tf.nn.softmax(logits)
    self.saver = tf.train.Saver(tf.all_variables())

    if not is_training:
      return

    self._lr = tf.Variable(0.0, trainable=False)
    tvars = tf.trainable_variables()
    grads, _ = tf.clip_by_global_norm(tf.gradients(cost, tvars),
                                      config.max_grad_norm)
    optimizer = tf.train.GradientDescentOptimizer(self.lr)
    self._train_op = optimizer.apply_gradients(zip(grads, tvars))

  def assign_lr(self, session, lr_value):
    session.run(tf.assign(self.lr, lr_value))

  @property
  def input_data(self):
    return self._input_data

  @property
  def targets(self):
    return self._targets

  @property
  def probs(self):
    return self._probs

  @property
  def logits(self):
    return self._logits

  @property
  def weights(self):
    return self._weights

  @property
  def initial_state(self):
    return self._initial_state

  @property
  def cost(self):
    return self._cost

  @property
  def final_state(self):
    return self._final_state

  @property
  def lr(self):
    return self._lr

  @property
  def train_op(self):
    return self._train_op


class SmallConfig(object):
  """Small config."""
  init_scale = 0.1
  learning_rate = 1.0
  max_grad_norm = 5
  num_layers = 2
  num_steps = 20
  hidden_size = 200
  max_epoch = 4
  max_max_epoch = 13
  keep_prob = 1.0
  lr_decay = 0.5
  batch_size = 20
  vocab_size = 10002


class MediumConfig(object):
  """Medium config."""
  init_scale = 0.05
  learning_rate = 1.0
  max_grad_norm = 5
  num_layers = 2
  num_steps = 35
  hidden_size = 650
  max_epoch = 6
  max_max_epoch = 39
  keep_prob = 0.5
  lr_decay = 0.8
  batch_size = 20
  vocab_size = 10002


class LargeConfig(object):
  """Large config."""
  init_scale = 0.04
  learning_rate = 1.0
  max_grad_norm = 10
  num_layers = 2
  num_steps = 35
  hidden_size = 1500
  max_epoch = 14
  max_max_epoch = 55
  keep_prob = 0.35
  lr_decay = 1 / 1.15
  batch_size = 20
  vocab_size = 10002


class TestConfig(object):
  """Tiny config, for testing."""
  init_scale = 0.1
  learning_rate = 1.0
  max_grad_norm = 1
  num_layers = 1
  num_steps = 2
  hidden_size = 2
  max_epoch = 1
  max_max_epoch = 1
  keep_prob = 1.0
  lr_decay = 0.5
  batch_size = 20
  vocab_size = 10002


def run_epoch(session, m, data, eval_op, verbose=False):
  """Runs the model on the given data."""
  epoch_size = ((len(data) // m.batch_size) - 1) // m.num_steps
  start_time = time.time()
  costs = 0.0
  iters = 0
  state = m.initial_state.eval()
  final_chosen_word = ""
  print("batch size: %s" % m.batch_size)
  for step, (x, y) in enumerate(reader.ptb_iterator(data, m.batch_size,
                                                    m.num_steps)):
    cost, state, logits, probs, _ = session.run([m.cost, m.final_state, m.logits, m.probs, eval_op],
                                 {m.input_data: x,
                                  m.targets: y,
                                  m.initial_state: state,
                                  m.weights: np.ones(m.batch_size * m.num_steps)})
    costs += cost
    iters += m.num_steps

    if verbose and step % (epoch_size // 10) == 10:
      print("%.3f perplexity: %.3f speed: %.0f wps" %
            (step * 1.0 / epoch_size, np.exp(costs / iters),
             iters * m.batch_size / (time.time() - start_time)))
      chosen_word = np.argmax(probs, 1)
      chosen_word = chosen_word[-1]
      #print("chosen word : %s" %(id_to_word[chosen_word]))

    chosen_word = np.argmax(probs, 1)
    chosen_word = chosen_word[-1]
    final_chosen_word = chosen_word
    break

  return np.exp(costs / iters), final_chosen_word


def get_config():
  if FLAGS.model == "small":
    return SmallConfig()
  elif FLAGS.model == "medium":
    return MediumConfig()
  elif FLAGS.model == "large":
    return LargeConfig()
  elif FLAGS.model == "test":
    return TestConfig()
  else:
    raise ValueError("Invalid model: %s", FLAGS.model)


def main(_):
  if not FLAGS.data_path and not FLAGS.generate:
    raise ValueError("Must set --data_path to PTB data directory")

  if not FLAGS.generate:
    train()
  else:
    word_to_id_f = open(os.path.join(FLAGS.model_path_prefix, "word_to_id.json"), "r")
    id_to_word_f = open(os.path.join(FLAGS.model_path_prefix, "id_to_word.json"), "r")
    word_to_id = json.load(word_to_id_f)
    id_to_word = json.load(id_to_word_f)
    generate(word_to_id, id_to_word)

def train():

  config = get_config()
  eval_config = get_config()
  eval_config.batch_size = 1
  eval_config.num_steps = 1

  raw_data = reader.ptb_raw_data(FLAGS.data_path)
  train_data, valid_data, test_data, vocab, word_to_id, id_to_word = raw_data
  print("Size of vocabulary: %d" % (vocab))
   
  word_to_id_f = open(os.path.join(FLAGS.model_path_prefix, "word_to_id.json"), "w")
  json.dump(word_to_id, word_to_id_f)
  id_to_word_f = open(os.path.join(FLAGS.model_path_prefix, "id_to_word.json"), "w")
  json.dump(id_to_word, id_to_word_f)

  with tf.Graph().as_default(), tf.Session() as session:
    initializer = tf.random_uniform_initializer(-config.init_scale,
                                                config.init_scale)
    with tf.variable_scope("model", reuse=None, initializer=initializer):
      m = PTBModel(is_training=True, config=config)
    with tf.variable_scope("model", reuse=True, initializer=initializer):
      mvalid = PTBModel(is_training=False, config=config)
      mtest = PTBModel(is_training=False, config=eval_config)

    tf.initialize_all_variables().run()

    for i in range(config.max_max_epoch):
      lr_decay = config.lr_decay ** max(i - config.max_epoch, 0.0)
      m.assign_lr(session, config.learning_rate * lr_decay)

      print("Epoch: %d Learning rate: %.3f" % (i + 1, session.run(m.lr)))
      train_perplexity, _ = run_epoch(session, m, train_data, m.train_op,
                                   verbose=True)
      print("Epoch: %d Train Perplexity: %.3f" % (i + 1, train_perplexity))
      valid_perplexity, _ = run_epoch(session, mvalid, valid_data, tf.no_op())
      print("Epoch: %d Valid Perplexity: %.3f" % (i + 1, valid_perplexity))
      m.saver.save(session, os.path.join(FLAGS.model_path_prefix, "ptb.ckpt"))

    print("test model")
    print(mtest)
    test_perplexity, _ = run_epoch(session, mtest, test_data, tf.no_op())
    print("Test Perplexity: %.3f" % test_perplexity)

def generate(word_to_id, id_to_word):

  config = get_config()
  config.num_steps = 1
  config.batch_size = 1
  with tf.Graph().as_default(), tf.Session() as session:

      with tf.variable_scope("model"):
          m = PTBModel(is_training=False, config=config)

      f = open(os.path.join(FLAGS.model_path_prefix, "ptb.ckpt"), "r")
      print("opened checkpoint file")
      m.saver.restore(session, os.path.join(FLAGS.model_path_prefix, "ptb.ckpt"))

      probs, final_state, _ = session.run([m.probs, m.final_state, tf.no_op()],
                                                {m.input_data: np.zeros((1, 1)),
                                                 m.targets: np.zeros((1, 1)),
                                                 m.initial_state: m.initial_state.eval(),
                                                 m.weights: np.ones(1)})
      print("probs shape: ")
      print(probs.shape)
      print("initial state shape:")
      print(final_state.shape)
      # sample from our softmax probs
      #next_letter = np.random.choice(27, p=probs[0])
      next_word = int(word_to_id["<bos>"])
      sentence = []
#      while next_word != word_to_id["<eos>"]:
      for i in range(30):
          print("---")
          print("using input next_word: %d" % next_word)
          print("shapes for: targets / init state / weights:")
          print(np.zeros((1,1)).shape)
          print(final_state.shape)
          print(np.ones(1).shape)
          print("shapes for probs / final_state")
          print(m.probs.get_shape())
          print(m.final_state.get_shape())
          print(tf.no_op())
          probs, final_state, _ = session.run([m.probs, m.final_state, tf.no_op()],
                                                    {m.input_data: [[next_word]],
                                                     m.targets: np.zeros((1, 1)),
                                                     m.initial_state: final_state,
                                                     m.weights: np.ones(1)})
          next_word = np.random.choice(10002, p=probs[0])
          #next_word = np.argmax(probs, 1)
          #next_word = next_word[0]
          print("next_word=%d" % next_word)
          print(type(next_word))
          print("word: %s" % id_to_word[str(next_word)])
          print("next initial state shape:")
          print(final_state.shape)
          print("probs shape: ")
          print(probs.shape)
          sentence += [id_to_word[str(next_word)]]

      print("SENTENCE:")
      
      print(" ".join(sentence))

"""
  next_word = word_to_id["<bos>"]
  cumulative_sentence = []
  for j in range(100):
    # Todo - think I need to adjust the batch size down?
    perplexity, next_word = run_epoch(session, mtest, [[next_word]], tf.no_op())
    print("p (%d), word (%s)" % (perplexity, id_to_word(next_word)))
    cumulative_sentence.append(id_to_word(next_word))
  print("Generated sentence: %s" % (" ".join(cumulative_sentence)))
"""

if __name__ == "__main__":
  tf.app.run()


