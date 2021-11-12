"""
An implementation of FCN in tensorflow.
------------------------

The MIT License (MIT)

Copyright (c) 2016 Marvin Teichmann

Details: https://github.com/MarvinTeichmann/KittiSeg/blob/master/LICENSE
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import scipy as scp
import random
from seg_utils import seg_utils as seg


import tensorflow as tf


def _add_softmax(hypes, logits):
    num_classes = hypes['arch']['num_classes']
    with tf.name_scope('decoder'):
        logits = tf.reshape(logits, [-1, num_classes])
        epsilon = tf.constant(value=hypes['solver']['epsilon'])
        # logits = logits + epsilon

        softmax = tf.nn.softmax(logits) + epsilon

    return softmax


def _add_sigmoid(hypes, logits):
    num_classes = hypes['arch']['num_classes']
    with tf.name_scope('decoder'):
        logits = tf.reshape(logits, [-1, num_classes])
        # epsilon = tf.constant(value=hypes['solver']['epsilon'])
        # logits = logits + epsilon

        sigmoid = tf.nn.sigmoid(logits)

    return sigmoid


def _add_relu(hypes, logits):
    num_classes = hypes['arch']['num_classes']
    with tf.name_scope('decoder'):
        logits = tf.reshape(logits, [-1, num_classes])
        # epsilon = tf.constant(value=hypes['solver']['epsilon'])
        relu = tf.nn.relu(logits)

    return relu


def _add_dense(hypes, logits):
    with tf.name_scope('decoder'):
        dense = tf.layers.dense(logits, 2, activation=tf.nn.relu, name="output")

    return dense


def decoder(hypes, logits, train):
    """Apply decoder to the logits.

    Args:
      logits: Logits tensor, float - [batch_size, NUM_CLASSES].

    Return:
      logits: the logits are already decoded.
    """
    decoded_logits = {}
    decoded_logits['logits'] = logits['fcn_logits']
    if hypes['arch']['output'] == "softmax":
        decoded_logits['output'] = _add_softmax(hypes, logits['fcn_logits'])
    elif hypes['arch']['output'] == "sigmoid":
        decoded_logits['output'] = _add_sigmoid(hypes, logits['fcn_logits'])
    elif hypes['arch']['output'] == "regress":
        decoded_logits['logits'] = logits['fcn_in']
        decoded_logits['output'] = _add_dense(hypes, logits['fcn_in'])

    return decoded_logits


def loss(hypes, decoded_logits, labels):
    """Calculate the loss from the logits and the labels.

    Args:
      logits: Logits tensor, float - [batch_size, NUM_CLASSES].
      labels: Labels tensor, int32 - [batch_size, NUM_CLASSES].

    Returns:
      loss: Loss tensor of type float.
    """

    logits = decoded_logits['logits']
    output = decoded_logits['output']
    print("=== labels' shape ===")
    print(labels.shape)
    print("=== logits' shape ===")
    print(logits.shape)

    if hypes['arch']['output'] != "regress":
        assert(logits.shape[-1] == labels.shape[-1])
        num_classes = hypes['arch']['num_classes']
    with tf.name_scope('loss'):
        # logits = tf.reshape(logits, [-1, num_classes])
        # shape = [logits.get_shape()[0], 2]
        epsilon = tf.constant(value=hypes['solver']['epsilon'])
        # logits = logits + epsilon
        if hypes['arch']['output'] != "regress":
            labels = tf.to_float(tf.reshape(labels, [-1, num_classes]))

        """
        if hypes['arch']['output'] == "softmax":
            output = tf.nn.softmax(logits) + epsilon
        elif hypes['arch']['output'] == "softmax":
            output = tf.nn.sigmoid(logits) + epsilon
        """

        if hypes['loss'] == 'xentropy':
            loss_output = _compute_cross_entropy_mean(hypes, labels, output)
        elif hypes['loss'] == 'softF1':
            loss_output = _compute_f1(hypes, labels, output, epsilon)
        elif hypes['loss'] == 'softIU':
            loss_output = _compute_soft_ui(hypes, labels, output,
                                                  epsilon)
        elif hypes['loss'] == 'l2':
            loss_output = _compute_l2_loss(labels, output)
        elif hypes['loss'] == 'meanSquared':
            loss_output = _compute_mean_squared_error(labels, output)
        elif hypes['loss'] == 'euclidean':
            loss_output = _compute_euclidean_pixel(labels, output)
        elif hypes['loss'] == 'absDiff':
            loss_output = _compute_absolute_difference(labels, output)
        elif hypes['loss'] == 'gaussian':
            loss_output = _compute_gaussian_loss(labels, output)

        reg_loss_col = tf.GraphKeys.REGULARIZATION_LOSSES

        weight_loss = tf.add_n(tf.get_collection(reg_loss_col),
                               name='reg_loss')

        total_loss = loss_output + weight_loss

        losses = {}
        losses['total_loss'] = total_loss
        losses['loss'] = loss_output
        losses['weight_loss'] = weight_loss

    return losses


def _compute_gaussian_loss(gt, output):
    # assume gt and output are (x, y) pair
    sigma = (32, 32)
    gaussian_loss = 1 - tf.exp(\
        -(tf.square(output[0] - gt[0]) / tf.multiply(2.0, tf.square(sigma[0])) \
        + tf.square(output[1] - gt[1] / tf.multiply(2.0, tf.square(sigma[1])))))
    return gaussian_loss


def _compute_absolute_difference(gt, output):
    abs_diff = tf.losses.absolute_difference(gt, output)
    mean_abs_diff = tf.reduce_mean(abs_diff)
    return mean_abs_diff


def _compute_l2_loss(labels, softmax):
    return tf.nn.l2_loss(labels - softmax)


def _compute_mean_squared_error(labels, softmax):
    return tf.losses.mean_squared_error(labels, softmax)


def _compute_cross_entropy_mean(hypes, labels, softmax):
    head = hypes['arch']['weight']
    cross_entropy = -tf.reduce_sum(tf.multiply(labels * tf.log(softmax), head),
                                   axis=1)
    cross_entropy_mean = tf.reduce_mean(cross_entropy,
                                        name='xentropy_mean')
    return cross_entropy_mean


def _compute_f1(hypes, labels, softmax, epsilon):
    labels = tf.to_float(tf.reshape(labels, (-1, 2)))[:, 1]
    logits = softmax[:, 1]
    true_positive = tf.reduce_sum(labels*logits)
    false_positive = tf.reduce_sum((1-labels)*logits)

    recall = true_positive / tf.reduce_sum(labels)
    precision = true_positive / (true_positive + false_positive + epsilon)

    score = 2*recall * precision / (precision + recall)
    f1_score = 1 - 2*recall * precision / (precision + recall)

    return f1_score


def _compute_soft_ui(hypes, labels, softmax, epsilon):
    intersection = tf.reduce_sum(labels*softmax, reduction_indices=0)
    union = tf.reduce_sum(labels+softmax, reduction_indices=0) \
        - intersection+epsilon

    mean_iou = 1-tf.reduce_mean(intersection/union, name='mean_iou')

    return mean_iou


def _compute_euclidean_pixel(probs, sigmoid):
    euclidean_loss = tf.reduce_sum(tf.squared_difference(probs, sigmoid),
            name='euclidean_loss')
    # euclidean_mean = tf.reduce_mean(euclidean_sum, name="euclidean_mean")

    return euclidean_loss


def evaluation(hypes, images, labels, decoded_logits, losses, global_step):
    """Evaluate the quality of the logits at predicting the label.

    Args:
      logits: Logits tensor, float - [batch_size, NUM_CLASSES].
      labels: Labels tensor, int32 - [batch_size], with values in the
        range [0, NUM_CLASSES). 
            or
              Probs tensor, float - [batch_size], with values in the
        range [0, 1].

    Returns:
      A scalar int32 tensor with the number of examples (out of batch_size)
      that were predicted correctly.
    """
    # For a classifier model, we can use the in_top_k Op.
    # It returns a bool tensor with shape [batch_size] that is true for
    # the examples where the label's is was in the top k (here k=1)
    # of all logits for that example.

    # get the number of classes
    num_classes = hypes['arch']['num_classes']

    eval_list = []
    logits = tf.reshape(decoded_logits['logits'], [-1, num_classes])
    labels = tf.reshape(labels, [-1, num_classes])

    if hypes['arch']['output'] == "softmax":
        pred = tf.argmax(logits, dimension=1)
        negative = tf.to_int32(tf.equal(pred, 0))
        tn = tf.reduce_sum(negative * labels[:, 0])
        fn = tf.reduce_sum(negative * labels[:, 1])
        positive = tf.to_int32(tf.equal(pred, 1))
        tp = tf.reduce_sum(positive * labels[:, 1])
        fp = tf.reduce_sum(positive * labels[:, 0])

        eval_list.append(('Acc. ', (tn+tp)/(tn + fn + tp + fp)))
        eval_list.append(('loss', losses['loss']))
        eval_list.append(('weight_loss', losses['weight_loss']))
    else:
        eval_list.append(('loss', losses['loss']))
        eval_list.append(('weight_loss', losses['weight_loss']))

    # eval_list.append(('Precision', tp/(tp + fp)))
    # eval_list.append(('True BG', tn/(tn + fp)))
    # eval_list.append(('True Street [Recall]', tp/(tp + fn)))

    return eval_list
